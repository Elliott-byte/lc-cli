"""The local review deck: spaced repetition over problems you want to re-solve.

``$LC_HOME/review.json`` holds one entry per saved problem. It is user data,
not cache — ``cache.db`` can be deleted freely, this file is the deck.

A problem sits at a level from 1 to ``len(curve)``; the curve says how many
days a pass at each level buys before the next review. The default is
Ebbinghaus's — 1, 2, 4, 7, 15 days, then out to a year — and ``lc config
curve`` replaces it. By default levels move only when you say so: submitting
a deck problem marks it as attempted today, and you grade it with + or - — or
with 0, for a problem you did not remember at all. ``lc config autograde on``
hands that to the judge instead — accepted climbs a level, a failure drops
one, once per problem per day and never over a hand grade.
"""

from __future__ import annotations

import functools
import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .config import Config, home

#: Ebbinghaus's forgetting curve: the classic 1/2/4/7/15-day review ladder,
#: continued out to a year for material you have clearly kept.
#: `lc config curve` overrides it.
DEFAULT_CURVE = (1, 2, 4, 7, 15, 30, 60, 90, 180, 365)


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


def _stamp() -> str:
    """Now, in UTC — the ordering key for syncing.

    Microseconds, not seconds: remove-then-re-add, or two grades in quick
    succession, land inside the same second, and a merge that cannot order
    them keeps the wrong one. Fixed width, so plain string comparison sorts
    it correctly.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


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
    #: UTC timestamp of the last edit of any kind. Syncing merges on this:
    #: `graded` is a local date, so two machines editing on the same day tie,
    #: and postponing does not touch it at all.
    updated: str = ""
    #: Set when the problem was taken off the deck. The entry stays behind as
    #: a tombstone so the removal can reach the other machine instead of the
    #: other machine handing the problem straight back.
    removed: str = ""
    #: The day of the last submit lc saw for this problem, and how it went.
    #: Levels are yours to set; this only marks the row, so you can see which
    #: problems you have already re-solved today and are ready to grade.
    attempted: str = ""
    attempt_passed: bool = False

    def due_in(self, today: date) -> int:
        """Days until due — 0 means today, negative means overdue."""
        try:
            return (date.fromisoformat(self.due) - today).days
        except ValueError:
            return 0

    def attempt_today(self, today: date) -> str:
        """'passed' / 'failed' if it was submitted today, '' otherwise."""
        if not self.attempted or self.attempted != today.isoformat():
            return ""
        return "passed" if self.attempt_passed else "failed"


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
        for key in ("title", "frontend_id", "difficulty", "added", "graded",
                    "due", "updated", "removed", "attempted"):
            if not isinstance(fields.get(key, ""), str):
                fields[key] = ""
        # `is True`, not bool(): a hand-edited "false" is a truthy *string*,
        # and claiming a problem passed when it did not is the worse mistake.
        fields["attempt_passed"] = fields.get("attempt_passed") is True
        items[slug] = ReviewItem(slug=slug, **fields)
    return items


def dumps(items: dict[str, ReviewItem]) -> str:
    """The deck as JSON: sorted and indented, so git diffs read cleanly."""
    payload = {
        slug: {k: v for k, v in asdict(item).items() if k != "slug"}
        for slug, item in sorted(items.items())
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


#: Serialises read-modify-write on the deck. The judge and git-sync workers
#: are threads, and the UI grades problems on the main one — without this two
#: of them interleave and the second save silently drops the first's change.
#: Across processes there is no lock; the atomic rename below still leaves a
#: whole file, and last writer wins.
_LOCK = threading.RLock()


def _atomic(fn):
    """Run a read-modify-write of the deck without another thread interleaving."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _LOCK:
            return fn(*args, **kwargs)

    return wrapper


def save(items: dict[str, ReviewItem]) -> None:
    path = review_path()
    # Write-then-rename: the deck is user data, a torn write must not eat it.
    # The temp name carries pid and thread so two concurrent saves cannot
    # rename each other's file out from under them.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(dumps(items))
        tmp.replace(path)
    finally:
        # A failed write must not leave a stray temp file behind.
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def merge(
    local: dict[str, ReviewItem], remote: dict[str, ReviewItem]
) -> tuple[dict[str, ReviewItem], int, int]:
    """Combine two decks. Returns (merged, added, updated).

    The union of both sides, so nothing is lost by syncing. Where both know a
    problem, the copy edited most recently wins — that is the machine you
    were actually working on. Removals travel too: `remove` leaves a tombstone
    behind, and a tombstone is just another edit, so it beats an older copy on
    the other machine instead of that machine handing the problem back.
    """
    merged = dict(local)
    added = updated = 0
    for slug, incoming in remote.items():
        current = merged.get(slug)
        if current is None:
            merged[slug] = incoming
            if not incoming.removed:
                added += 1
        elif _edit_key(incoming) > _edit_key(current):
            merged[slug] = incoming
            updated += 1
    return merged, added, updated


def _edit_key(item: ReviewItem) -> tuple[str, str, int, str]:
    """How recent this copy is.

    `updated` is the real answer. Decks written before lc recorded it fall
    back to the old key, and sort below any stamped entry — which is right:
    a machine that has since edited the problem knows more about it.
    """
    return (item.updated, item.graded, item.level, item.due)


def live(items: dict[str, ReviewItem]) -> dict[str, ReviewItem]:
    """The deck without its tombstones — what the user thinks of as the deck."""
    return {slug: item for slug, item in items.items() if not item.removed}


def order(items: dict[str, ReviewItem]) -> list[ReviewItem]:
    """Soonest due first; ties in problem-number order. Tombstones are out."""
    def key(item: ReviewItem) -> tuple[str, int]:
        try:
            fid = int(item.frontend_id)
        except ValueError:
            fid = 0
        return (item.due, fid)

    return sorted(live(items).values(), key=key)


def due_count(items: dict[str, ReviewItem], today: date | None = None) -> int:
    today = today or date.today()
    return sum(1 for item in live(items).values() if item.due_in(today) <= 0)


# ---------------------------------------------------------------- operations

def _interval(curve: list[int], level: int) -> int:
    """Days a pass at *level* buys. Levels past the end of the curve get its
    top gap, so shortening the curve reschedules rather than crashing."""
    if not curve:  # no caller does this, but scheduling must never divide by zero
        curve = list(DEFAULT_CURVE)
    return curve[min(max(level, 1), len(curve)) - 1]


def _schedule(item: ReviewItem, level: int, curve: list[int], today: date) -> None:
    item.level = max(1, min(level, len(curve)))
    item.graded = today.isoformat()
    item.due = (today + timedelta(days=_interval(curve, item.level))).isoformat()
    item.updated = _stamp()
    # Grading answers the "you solved this today" prompt, so the mark clears.
    item.attempted = ""
    item.attempt_passed = False


@_atomic
def add(
    slug: str,
    *,
    title: str = "",
    frontend_id: str = "",
    difficulty: str = "",
    curve: list[int],
    today: date | None = None,
) -> ReviewItem:
    """Put a problem on the deck at level 1. Re-adding only freshens metadata.

    A problem that was removed comes back at level 1: the tombstone is lifted
    and the schedule starts over, which is what asking for it again means.
    """
    today = today or date.today()
    items = load()
    item = items.get(slug)
    if item is None or item.removed:
        item = ReviewItem(slug=slug, added=today.isoformat())
        _schedule(item, 1, curve, today)
        items[slug] = item
    # Freshening the metadata is an edit like any other: without a stamp the
    # other machine's older, emptier copy would win the next merge.
    before = (item.title, item.frontend_id, item.difficulty)
    item.title = title or item.title
    item.frontend_id = frontend_id or item.frontend_id
    item.difficulty = difficulty or item.difficulty
    if (item.title, item.frontend_id, item.difficulty) != before:
        item.updated = _stamp()
    save(items)
    return item


@_atomic
def remove(slug: str) -> bool:
    """Take a problem off the deck, leaving a tombstone so the removal syncs."""
    items = load()
    item = items.get(slug)
    if item is None or item.removed:
        return False
    item.removed = date.today().isoformat()
    item.updated = _stamp()
    save(items)
    return True


@_atomic
def shift_level(
    slug: str, delta: int, curve: list[int], today: date | None = None
) -> ReviewItem | None:
    """Manual grade: move the level and schedule the next review from today."""
    items = load()
    item = items.get(slug)
    if item is None or item.removed:
        return None
    _schedule(item, item.level + delta, curve, today or date.today())
    save(items)
    return item


@_atomic
def forget(
    slug: str, curve: list[int], today: date | None = None
) -> ReviewItem | None:
    """"I had no idea": straight back to level 1, so it returns tomorrow.

    A lapse is not one level down. Stepping a level-9 problem to 8 still buys
    it three months, which is no way to treat something you just failed — and
    pressing `-` eight times to say so is not a grade, it is a chore.
    """
    items = load()
    item = items.get(slug)
    if item is None or item.removed:
        return None
    _schedule(item, 1, curve, today or date.today())
    save(items)
    return item


@_atomic
def postpone(slug: str, today: date | None = None) -> ReviewItem | None:
    """Push one problem's review a day past today (or past its future date)."""
    today = today or date.today()
    items = load()
    item = items.get(slug)
    if item is None or item.removed:
        return None
    try:
        base = max(date.fromisoformat(item.due), today)
    except ValueError:
        base = today
    item.due = (base + timedelta(days=1)).isoformat()
    item.updated = _stamp()   # postponing is an edit too, and syncing sorts on it
    save(items)
    return item


@_atomic
def postpone_due(today: date | None = None) -> int:
    """The "not today" button: everything due today moves to tomorrow."""
    today = today or date.today()
    items = load()
    moved = 0
    for item in live(items).values():
        if item.due_in(today) <= 0:
            item.due = (today + timedelta(days=1)).isoformat()
            item.updated = _stamp()
            moved += 1
    if moved:
        save(items)
    return moved


@_atomic
def record_submit(
    slug: str,
    accepted: bool,
    today: date | None = None,
    *,
    curve: list[int] | None = None,
) -> str | None:
    """Note that a deck problem was submitted today.

    Without *curve* lc only marks the problem as re-solved and the Review tab
    colours the row, which is the cue to press + (or -). Levels stay the
    user's to set, because the judge cannot tell recall from a solution that
    was looked up — which is why grading yourself is still the default.

    Pass *curve* — `lc config autograde on` — and the verdict grades it:
    accepted moves the problem a level up, a failure a level down, with the
    next review scheduled from today. Whoever grades first that day wins:
    re-submitting cannot ratchet the level (five green submits are one
    recall), a + / - / 0 pressed by hand stands against any later submit,
    and on the day a problem is added its schedule stays at level 1 no
    matter how the solve went. The attempt is marked either way.

    Returns a short human-readable line, or None when the problem is not on
    the deck. Only real submits belong here — passing the samples proves
    nothing about recall.
    """
    today = today or date.today()
    items = load()
    item = items.get(slug)
    if item is None or item.removed:
        return None

    verdict = "solved" if accepted else "not solved"

    if not curve:
        # Just the fact — the TUI can say "press +", a shell cannot.
        note = f"review: {verdict} — still at level {item.level}"
    elif item.graded == today.isoformat():
        # One grade a day, from whoever grades first. `graded` is stamped by
        # every way that happens — an earlier submit, a manual + / - / 0, and
        # add(), which schedules the problem at level 1 — so a submit can
        # never stack a second move on any of them. The hand grade above all
        # must stand: + / - / 0 are the documented override for the judge,
        # and an override the next submit undoes is no override at all.
        if item.added == today.isoformat():
            note = (f"review: {verdict} — added today, "
                    f"first review in {item.due_in(today)}d")
        elif item.attempt_today(today):
            note = f"review: {verdict} — already graded today, level {item.level}"
        else:
            note = (f"review: {verdict} — graded by hand today, "
                    f"level {item.level} stands")
    else:
        before = item.level
        _schedule(item, before + (1 if accepted else -1), curve, today)
        # Clamped at both ends: a failure at level 1 has nowhere to fall, and a
        # pass at the top of the curve nowhere to climb.
        moved = (f"level {before} → {item.level}" if item.level != before
                 else f"still at level {item.level}")
        note = f"review: {verdict} — {moved}, next in {item.due_in(today)}d"

    # Whatever the level did, the attempt itself is recorded: the mark tints
    # the row — the cue to grade by hand when nothing has graded yet, and the
    # record of what today's code actually did when something already has.
    item.attempted = today.isoformat()
    item.attempt_passed = accepted
    item.updated = _stamp()
    save(items)
    return note
