"""Per-problem notes: what you learned from each attempt.

``notes.md`` lives in the problem's workspace directory, next to the
solution — a plain markdown file, one ``##`` heading per card, newest last
on disk (the TUI shows them newest first). A file, not a database: you
write it in your own editor with the submitted code in the next window,
`git` in the workspace versions it like everything else there, and `cat`
reads it anywhere.

A card's heading is stamped by `lc note` (and Vim's \n, which runs it):

    ## 2026-08-22 14:03 · Accepted · python3

Everything until the next ``##`` heading is the card's body.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

FILENAME = "notes.md"


@dataclass
class Card:
    title: str      # the heading line, without the leading ##
    body: str       # everything under it, stripped


def path_in(directory: Path) -> Path:
    return directory / FILENAME


def stamp_header(
    verdict: str = "", lang: str = "", now: time.struct_time | None = None
) -> str:
    """The heading for a fresh card: local time, then whatever is known."""
    when = time.strftime("%Y-%m-%d %H:%M", now or time.localtime())
    parts = [when] + [p for p in (verdict, lang) if p]
    return "## " + " · ".join(parts)


def open_card(directory: Path, verdict: str = "", lang: str = "") -> Path:
    """Append a fresh card heading to the notes file, ready to write under.

    A second call while the newest card is still blank reuses it rather
    than stacking empty headings — submitting twice before writing once
    should not litter the file.
    """
    path = path_in(directory)
    text = path.read_text() if path.exists() else ""
    cards = parse(text)
    if cards and not cards[-1].body:
        return path
    header = stamp_header(verdict, lang)
    lead = "" if not text else ("\n" if text.endswith("\n") else "\n\n")
    with path.open("a") as fh:
        fh.write(f"{lead}{header}\n\n")
    return path


def parse(text: str) -> list[Card]:
    """Split the file into cards. Text before the first heading is ignored
    prose (a title line, say) — only ``##`` sections are cards."""
    cards: list[Card] = []
    title: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if title is not None:
                cards.append(Card(title, "\n".join(body).strip()))
            title = line[3:].strip()
            body = []
        elif title is not None:
            body.append(line)
    if title is not None:
        cards.append(Card(title, "\n".join(body).strip()))
    return cards


def load(directory: Path) -> list[Card]:
    path = path_in(directory)
    if not path.exists():
        return []
    try:
        return parse(path.read_text())
    except OSError:
        return []


def render(cards: list[Card]) -> str:
    """Cards back to markdown — the inverse of parse, normalised."""
    blocks = [f"## {c.title}\n\n{c.body}".rstrip() for c in cards]
    return "\n\n".join(blocks) + "\n"


def merge_texts(ours: str, theirs: str) -> str:
    """Two machines' versions of one problem's notes, combined.

    Cards are near-append-only, so the merge is a union: every distinct
    (title, body) survives, ordered by title — headings start with the
    timestamp, so that is chronological. Deterministic and idempotent, which
    is what makes two machines converge instead of ping-ponging. The cost:
    deleting a card on one machine resurrects it from the other — notes are
    a record, and the sync treats them as one.
    """
    seen = []
    for card in parse(ours) + parse(theirs):
        key = (card.title, card.body)
        if key not in seen:
            seen.append(key)
    ordered = sorted(seen, key=lambda k: k[0])
    return render([Card(t, b) for t, b in ordered])
