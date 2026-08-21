"""Turn LeetCode's statement HTML into something readable in a terminal.

LeetCode statements are a small, predictable subset of HTML: paragraphs, `<pre>`
example blocks, `<code>` spans, lists, and `<sup>`/`<sub>` for the constraints.
A hand-rolled parser handles that subset better than a general converter — it
keeps the example blocks intact and maps exponents onto real Unicode.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

SUPERSCRIPT = str.maketrans(
    "0123456789+-=()n i", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ ⁱ"
)
SUBSCRIPT = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")

DIFFICULTY_STYLE = {"Easy": "green", "Medium": "yellow", "Hard": "red"}

_BLOCK_TAGS = {
    "p", "div", "pre", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "table", "tr",
}


@dataclass
class _Block:
    kind: str               # paragraph | pre | heading | list-item | rule | image
    text: Text = field(default_factory=Text)
    level: int = 0
    bullet: str = ""


class _StatementParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[_Block] = []
        self._current = _Block("paragraph")
        self._styles: list[str] = []
        self._in_pre = False
        self._list_stack: list[dict] = []
        self._pending_image: str | None = None

    # -- block bookkeeping ----------------------------------------------------

    def _flush(self) -> None:
        if self._current.text.plain.strip() or self._current.kind == "rule":
            self.blocks.append(self._current)
        self._current = _Block("paragraph")

    def _start_block(self, kind: str, *, level: int = 0, bullet: str = "") -> None:
        self._flush()
        self._current = _Block(kind, level=level, bullet=bullet)

    @property
    def _style(self) -> str:
        return " ".join(self._styles) if self._styles else ""

    def _append(self, chunk: str, style: str | None = None) -> None:
        self._current.text.append(chunk, style=style if style is not None else self._style)

    # -- HTMLParser hooks -----------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: (v or "") for k, v in attrs}

        if tag == "pre":
            self._start_block("pre")
            self._in_pre = True
        elif tag == "code":
            if self._in_pre:
                return  # <pre><code> — the pre block already owns the styling
            self._styles.append("__code__")
        elif tag in ("strong", "b"):
            self._styles.append("bold")
        elif tag in ("em", "i"):
            self._styles.append("italic")
        elif tag == "u":
            self._styles.append("underline")
        elif tag == "sup":
            self._styles.append("__sup__")
        elif tag == "sub":
            self._styles.append("__sub__")
        elif tag == "br":
            self._append("\n")
        elif tag == "hr":
            self._start_block("rule")
            self._flush()
        elif tag in ("ul", "ol"):
            self._flush()
            self._list_stack.append({"ordered": tag == "ol", "n": 0})
        elif tag == "li":
            depth = max(len(self._list_stack) - 1, 0)
            if self._list_stack:
                ctx = self._list_stack[-1]
                ctx["n"] += 1
                bullet = f"{ctx['n']}. " if ctx["ordered"] else "• "
            else:
                bullet = "• "
            self._start_block("list-item", level=depth, bullet=bullet)
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._start_block("heading", level=int(tag[1]))
        elif tag == "img":
            src = attr.get("src", "")
            if src:
                self._flush()
                self.blocks.append(_Block("image", Text(src)))
        elif tag == "a":
            href = attr.get("href", "")
            if href:
                self._pending_image = href  # reused as "pending href"
        elif tag in ("p", "div", "blockquote", "table", "tr"):
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag == "pre":
            self._in_pre = False
            self._flush()
        elif tag == "code" and not self._in_pre:
            self._pop_style("__code__")
        elif tag in ("strong", "b"):
            self._pop_style("bold")
        elif tag in ("em", "i"):
            self._pop_style("italic")
        elif tag == "u":
            self._pop_style("underline")
        elif tag == "sup":
            self._pop_style("__sup__")
        elif tag == "sub":
            self._pop_style("__sub__")
        elif tag in ("ul", "ol"):
            self._flush()
            if self._list_stack:
                self._list_stack.pop()
        elif tag == "a":
            href, self._pending_image = self._pending_image, None
            if href and href.startswith("http"):
                self._append(f" ({href})", style="dim")
        elif tag in _BLOCK_TAGS:
            self._flush()

    def _pop_style(self, style: str) -> None:
        if style in self._styles:
            # Remove the most recent occurrence so nested tags unwind correctly.
            for i in range(len(self._styles) - 1, -1, -1):
                if self._styles[i] == style:
                    del self._styles[i]
                    return

    def handle_data(self, data: str) -> None:
        if not data:
            return
        if "__sup__" in self._styles:
            self._append(data.translate(SUPERSCRIPT))
            return
        if "__sub__" in self._styles:
            self._append(data.translate(SUBSCRIPT))
            return
        if self._in_pre:
            self._append(data)
            return
        # Outside <pre>, collapse whitespace the way a browser would.
        text = re.sub(r"\s+", " ", data.replace("\xa0", " "))
        if not text.strip() and not self._current.text.plain:
            return
        self._append(text)

    def close(self) -> None:  # type: ignore[override]
        super().close()
        self._flush()


#: Semantic markers the parser leaves behind, mapped to Rich styles.
_MARKER_STYLES = {"__code__": "bold cyan"}


def _clean_style(text: Text) -> Text:
    """Resolve the parser's semantic markers into real Rich styles."""
    out = Text(text.plain)
    for span in text.spans:
        parts = [
            _MARKER_STYLES.get(part, "" if part.startswith("__") else part)
            for part in str(span.style).split()
        ]
        style = " ".join(p for p in parts if p)
        if style:
            out.stylize(style, span.start, span.end)
    return out


def statement_blocks(html: str) -> list[tuple[str, RenderableType]]:
    """Render statement HTML into ``(kind, renderable)`` pairs."""
    parser = _StatementParser()
    parser.feed(html)
    parser.close()

    out: list[tuple[str, RenderableType]] = []
    for block in parser.blocks:
        text = _clean_style(block.text)
        if block.kind == "pre":
            # Inline styling inside example blocks is mostly <strong>Input:</strong>
            # noise, so render them plain and let the box provide the structure.
            body = Text(text.plain.strip("\n"))
            out.append(
                ("pre", Panel(body, border_style="dim", padding=(0, 1), expand=False))
            )
        elif block.kind == "rule":
            out.append(("rule", Rule(style="dim")))
        elif block.kind == "heading":
            heading = text.copy()
            heading.stylize("bold")
            out.append(("heading", heading))
        elif block.kind == "list-item":
            item = Text("  " * block.level + block.bullet, style="dim")
            item.append_text(text)
            out.append(("list-item", item))
        elif block.kind == "image":
            out.append(("image", Text(f"🖼  {text.plain}", style="dim blue")))
        else:
            out.append(("paragraph", text))
    return out


def render_statement(html: str) -> RenderableType:
    """Statement HTML as a single renderable, with paragraph spacing applied."""
    blocks = statement_blocks(html)
    spaced: list[RenderableType] = []
    for i, (kind, renderable) in enumerate(blocks):
        spaced.append(renderable)
        # Keep consecutive bullets tight; separate everything else with a blank line.
        next_kind = blocks[i + 1][0] if i + 1 < len(blocks) else None
        if not (kind == "list-item" and next_kind == "list-item"):
            spaced.append(Text(""))
    return Group(*spaced)


# --------------------------------------------------------------------------- markdown

#: Parser style name -> Markdown delimiter.
_MARK_OF = {"__code__": "`", "bold": "**", "italic": "*"}
_ALL_MARKS = tuple(_MARK_OF.values())


def _span_marks(style: str) -> list[str]:
    """The Markdown delimiters a span needs, outermost first.

    The parser pushes styles onto a stack, so the order they appear in the style
    string is the order the tags were opened — which is exactly the nesting order
    Markdown needs.
    """
    marks = [_MARK_OF[part] for part in style.split() if part in _MARK_OF]
    if "`" in marks:
        # Markdown inside a code span is literal, so nothing nested there applies.
        marks = marks[: marks.index("`") + 1]
    return marks


def _inline_markdown(text: Text) -> str:
    """Re-emit a parsed Text as Markdown, restoring `code`/**bold**/*italic*.

    Takes the *unresolved* Text so the parser's ``__code__`` marker is still
    visible — after :func:`_clean_style` it is indistinguishable from bold.
    """
    plain = text.plain
    n = len(plain)
    active: list[list[str]] = [[] for _ in range(n)]

    for span in text.spans:
        marks = _span_marks(str(span.style))
        if not marks:
            continue
        for i in range(max(span.start, 0), min(span.end, n)):
            active[i] = list(marks)

    # Markdown ignores emphasis padded with spaces. Trim at the edges of each
    # whole run rather than per span, or a styled run split across spans
    # (`2<sup>31</sup> - 1`) would fragment at every internal space.
    for mark in _ALL_MARKS:
        i = 0
        while i < n:
            if mark not in active[i]:
                i += 1
                continue
            start = i
            while i < n and mark in active[i]:
                i += 1
            end = i
            # Dropping a mark also drops whatever it contained.
            while start < end and plain[start].isspace():
                active[start] = active[start][: active[start].index(mark)]
                start += 1
            while end > start and plain[end - 1].isspace():
                active[end - 1] = active[end - 1][: active[end - 1].index(mark)]
                end -= 1

    out: list[str] = []
    previous: list[str] = []
    for i in range(n + 1):
        current = active[i] if i < n else []
        if current != previous:
            shared = 0
            while (
                shared < len(previous)
                and shared < len(current)
                and previous[shared] == current[shared]
            ):
                shared += 1
            out += reversed(previous[shared:])
            out += current[shared:]
            previous = current
        if i < n:
            out.append(plain[i])
    return "".join(out)


def to_markdown(html: str) -> str:
    """Statement HTML as Markdown — for the README in each problem directory."""
    parser = _StatementParser()
    parser.feed(html)
    parser.close()

    lines: list[str] = []
    prev_kind = ""
    for block in parser.blocks:
        text = block.text  # keep the markers — _inline_markdown needs them
        if block.kind == "pre":
            lines += ["", "```", *text.plain.strip("\n").splitlines(), "```"]
        elif block.kind == "rule":
            lines += ["", "---"]
        elif block.kind == "heading":
            lines += ["", "#" * max(block.level, 2) + " " + text.plain.strip()]
        elif block.kind == "list-item":
            if prev_kind != "list-item":
                lines.append("")
            bullet = "1." if block.bullet[0].isdigit() else "-"
            lines.append("  " * block.level + f"{bullet} {_inline_markdown(text)}")
        elif block.kind == "image":
            lines += ["", f"![]({text.plain})"]
        else:
            lines += ["", _inline_markdown(text).strip()]
        prev_kind = block.kind

    # Collapse the runs of blank lines the loop above can produce.
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip() + "\n"


# --------------------------------------------------------------------------- misc

def difficulty_text(difficulty: str) -> Text:
    return Text(difficulty, style=DIFFICULTY_STYLE.get(difficulty, "white"))


def status_mark(status: str | None) -> Text:
    if status == "ac":
        return Text("✔", style="green")
    if status == "notac":
        return Text("✗", style="yellow")
    return Text(" ")


def problem_header(problem) -> RenderableType:
    """Title line + metadata table for a fetched Problem."""
    title = Text(f"[{problem.frontend_id}] {problem.title}", style="bold")
    if problem.paid_only:
        title.append("  premium", style="bold yellow")

    meta = Table.grid(padding=(0, 2))
    meta.add_column(style="dim")
    # fold, not ellipsis: a URL is one long word, so a narrow pane — Vim's
    # statement split especially — cut it off mid-slug. Half a URL cannot be
    # clicked, copied or read.
    meta.add_column(overflow="fold")
    meta.add_row("difficulty", difficulty_text(problem.difficulty))
    if problem.ac_rate:
        meta.add_row("acceptance", Text(f"{problem.ac_rate:.1f}%"))
    if problem.total_accepted:
        meta.add_row(
            "solved", Text(f"{problem.total_accepted} / {problem.total_submission}")
        )
    meta.add_row("likes", Text(f"{problem.likes} 👍  {problem.dislikes} 👎"))
    if problem.tags:
        meta.add_row("tags", Text(", ".join(problem.tags), style="cyan"))
    # A real terminal hyperlink (OSC 8), not just blue-and-underlined text:
    # it looked clickable and was not. Terminals that cannot do OSC 8 still
    # show the address itself, so nothing is lost.
    # Shown without the scheme or the trailing slash — nine columns that buy
    # most problems a single line in a narrow pane. Folding is honest but
    # ugly, and its worst case is a lone "/" on a line of its own. The link
    # still points at the full URL.
    shown = problem.url.removeprefix("https://").rstrip("/")
    # Styled as a span over the characters, never as the Text's base style: a
    # folded line is padded out to the column edge, and padding inherits the
    # base style — underlining (and OSC 8-linking) a stretch of blank cells
    # after the address.
    url = Text(shown)
    url.stylize(f"blue underline link {problem.url}")
    # OSC 8 only helps where the terminal sees the click. It does not inside
    # the TUI, which captures the mouse, nor inside Vim's terminal, which
    # swallows the escape entirely. So hand Textual its own handle on the
    # same text: plain Rich printing ignores meta, leaving `lc show` as is.
    url.apply_meta({"@click": "app.open_web()"})
    meta.add_row("url", url)
    return Group(title, Text(""), meta)
