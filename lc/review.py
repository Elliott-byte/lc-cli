"""The local review deck: spaced repetition over problems you want to re-solve.

``$LC_HOME/review.json`` holds one entry per saved problem. It is user data,
not cache — ``cache.db`` can be deleted freely, this file is the deck.

A problem sits at a level from 1 to ``len(curve)``; the curve says how many
days a pass at each level buys before the next review. The default doubles —
2, 4, 8, … days, the forgetting-curve shape — and ``lc config curve``
replaces it. Passing a due review climbs one level, failing any submit drops
back to level 1.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from .config import Config, home

#: Days until the next review, by level: 2^level. `lc config curve` overrides.
DEFAULT_CURVE = tuple(2 ** n for n in range(1, 11))


def review_path() -> Path:
    return home() / "review.json"


#: Ten years. Beyond this a "gap" is not a schedule, and timedelta overflows.
MAX_GAP_DAYS = 3650


def curve_of(config: Config) -> list[int]:
    """The active curve: config's, with nonsense filtered out, else the default."""
    raw = config.review_curve if isinstance(config.review_curve, (list, tuple)) else []
    days: list[int] = []
    for value in raw:
        try:
            n = int(value)
        except (TypeError, ValueError, OverflowError):  # Overflow: int(1e999)
            continue
        if 1 <= n <= MAX_GAP_DAYS:
            days.append(n)
    return days or list(DEFAULT_CURVE)


@dataclass
class ReviewItem:
    slug: str
    #: Denormalized from the index at save time, so the deck renders offline
    #: and survives a deleted cache.
    title: str = ""
    frontend_id: str = ""
    difficulty: str = ""
    level: int = 1
    added: str = ""   # ISO dates throughout
    graded: str = ""  # the day the level last changed (pass, fail or manual)
    due: str = ""     # next review day

    def due_in(self, today: date) -> int:
        """Days until due — 0 means today, negative means overdue."""
        try:
            return (date.fromisoformat(self.due) - today).days
        except ValueError:
            return 0


def load() -> dict[str, ReviewItem]:
    path = review_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return items_from_raw(raw)


def items_from_raw(raw: object) -> dict[str, ReviewItem]:
    """Decode a deck payload — from the local file or a synced repo."""
    if not isinstance(raw, dict):
        return {}
    known = set(ReviewItem.__dataclass_fields__) - {"slug"}
    items: dict[str, ReviewItem] = {}
    for slug, data in raw.items():
        if not isinstance(data, dict):
            continue
        fields = {k: v for k, v in data.items() if k in known}
        # The file is hand-editable JSON — coerce what arithmetic, date
        # parsing and sorting rely on, so one odd value cannot crash the TUI.
        try:
            fields["level"] = max(1, int(fields.get("level", 1)))
        except (TypeError, ValueError, OverflowError):
            fields["level"] = 1
        for key in ("title", "frontend_id", "difficulty", "added", "graded", "due"):
            if not isinstance(fields.get(key, ""), str):
                fields[key] = ""
        items[slug] = ReviewItem(slug=slug, **fields)
    return items


def dumps(items: dict[str, ReviewItem]) -> str:
    """The deck as JSON: sorted and indented, so git diffs read cleanly."""
    payload = {
        slug: {k: v for k, v in asdict(item).items() if k != "slug"}
        for slug, item in sorted(items.items())
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def save(items: dict[str, ReviewItem]) -> None:
    path = review_path()
    # Write-then-rename: the deck is user data, a torn write must not eat it.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(dumps(items))
    tmp.replace(path)


def merge(
    local: dict[str, ReviewItem], remote: dict[str, ReviewItem]
) -> tuple[dict[str, ReviewItem], int, int]:
    """Combine two decks. Returns (merged, added, updated).

    The union of both sides, so nothing is lost by syncing. Where both know a
    problem, the most recently graded copy wins — that is the machine you
    actually reviewed on. Removals do not travel: a problem taken off one
    machine's deck comes back on the next sync, and has to be removed on the
    machine holding it too.
    """
    merged = dict(local)
    added = updated = 0
    for slug, incoming in remote.items():
        current = merged.get(slug)
        if current is None:
            merged[slug] = incoming
            added += 1
        elif _grade_key(incoming) > _grade_key(current):
            merged[slug] = incoming
            updated += 1
    return merged, added, updated


def _grade_key(item: ReviewItem) -> tuple[str, int, str]:
    """Recency of a graded entry: when it was graded, then how far it got."""
    return (item.graded, item.level, item.due)


def order(items: dict[str, ReviewItem]) -> list[ReviewItem]:
    """Soonest due first; ties in problem-number order."""
    def key(item: ReviewItem) -> tuple[str, int]:
        try:
            fid = int(item.frontend_id)
        except ValueError:
            fid = 0
        return (item.due, fid)

    return sorted(items.values(), key=key)


def due_count(items: dict[str, ReviewItem], today: date | None = None) -> int:
    today = today or date.today()
    return sum(1 for item in items.values() if item.due_in(today) <= 0)


# ---------------------------------------------------------------- operations

def _interval(curve: list[int], level: int) -> int:
    return curve[min(level, len(curve)) - 1]


def _schedule(item: ReviewItem, level: int, curve: list[int], today: date) -> None:
    item.level = max(1, min(level, len(curve)))
    item.graded = today.isoformat()
    item.due = (today + timedelta(days=_interval(curve, item.level))).isoformat()


def add(
    slug: str,
    *,
    title: str = "",
    frontend_id: str = "",
    difficulty: str = "",
    curve: list[int],
    today: date | None = None,
) -> ReviewItem:
    """Put a problem on the deck at level 1. Re-adding only freshens metadata."""
    today = today or date.today()
    items = load()
    item = items.get(slug)
    if item is None:
        item = ReviewItem(slug=slug, added=today.isoformat())
        _schedule(item, 1, curve, today)
        items[slug] = item
    item.title = title or item.title
    item.frontend_id = frontend_id or item.frontend_id
    item.difficulty = difficulty or item.difficulty
    save(items)
    return item


def remove(slug: str) -> bool:
    items = load()
    if slug not in items:
        return False
    del items[slug]
    save(items)
    return True


def shift_level(
    slug: str, delta: int, curve: list[int], today: date | None = None
) -> ReviewItem | None:
    """Manual grade: move the level and schedule the next review from today."""
    items = load()
    item = items.get(slug)
    if item is None:
        return None
    _schedule(item, item.level + delta, curve, today or date.today())
    save(items)
    return item


def postpone(slug: str, today: date | None = None) -> ReviewItem | None:
    """Push one problem's review a day past today (or past its future date)."""
    today = today or date.today()
    items = load()
    item = items.get(slug)
    if item is None:
        return None
    try:
        base = max(date.fromisoformat(item.due), today)
    except ValueError:
        base = today
    item.due = (base + timedelta(days=1)).isoformat()
    save(items)
    return item


def postpone_due(today: date | None = None) -> int:
    """The "not today" button: everything due today moves to tomorrow."""
    today = today or date.today()
    items = load()
    moved = 0
    for item in items.values():
        if item.due_in(today) <= 0:
            item.due = (today + timedelta(days=1)).isoformat()
            moved += 1
    if moved:
        save(items)
    return moved


def record_submit(
    slug: str, accepted: bool, curve: list[int], today: date | None = None
) -> str | None:
    """Let judge verdicts drive the deck: a due pass climbs, any fail restarts.

    Returns a short human-readable line when the schedule changed, else None.
    Only real submits belong here — passing the samples proves nothing about
    recall.
    """
    today = today or date.today()
    items = load()
    item = items.get(slug)
    if item is None:
        return None

    if accepted:
        # Early practice doesn't climb, and one day climbs at most once.
        if item.due_in(today) > 0 or item.graded == today.isoformat():
            return None
        before = item.level
        _schedule(item, item.level + 1, curve, today)
        save(items)
        gap = _interval(curve, item.level)
        if item.level == before:  # already at the top of the curve
            return f"review: level {item.level} (top), next in {gap}d"
        return f"review: level {before} → {item.level}, next in {gap}d"

    before_state = (item.level, item.due)
    _schedule(item, 1, curve, today)
    if (item.level, item.due) == before_state:
        return None
    save(items)
    return f"review: back to level 1, next in {_interval(curve, 1)}d"
