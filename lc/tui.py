"""Full-screen problem browser.

Two panes: the problem list on the left, the statement on the right. Everything
that touches the network runs on a thread worker so the UI never blocks.
"""

from __future__ import annotations

import os
import time
from datetime import date
from typing import Iterable

from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable,
    Footer,
    Input,
    Label,
    Static,
    TabbedContent,
    TabPane,
)
from textual.widgets.data_table import RowDoesNotExist
from textual.strip import Strip

from rich.console import Group, RenderableType
from rich.segment import Segment
from rich.markup import escape
from rich.text import Text

from . import fx, gitsync, review, store, workspace
from .api import (
    JudgeResult,
    LeetCode,
    LeetCodeError,
    Problem,
    ProblemSummary,
    split_testcases,
)
from .browser import open_url
from .config import load_config, load_credentials, save_config
from .langs import choose
from .render import (
    DIFFICULTY_STYLE,
    difficulty_text,
    problem_header,
    render_statement,
    status_mark,
)

DIFFICULTIES = ("", "Easy", "Medium", "Hard")
STATUSES = ("", "todo", "attempted", "solved")


def daily_note(daily_date: str, now: time.struct_time | None = None) -> str:
    """Label for the pinned daily: which day it is, and when it turns over.

    LeetCode rotates at UTC midnight, so anywhere east of Greenwich the local
    date is a day ahead of the daily on screen for part of the morning —
    without the date it reads as "refresh isn't working".
    """
    now = now or time.gmtime()
    left = 86400 - (now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec)
    if left >= 3600:
        hours, minutes = divmod(left // 60, 60)
        when = f"{hours}h" if minutes == 0 else f"{hours}h{minutes:02d}m"
    else:
        when = f"{max(1, left // 60)}m"
    day = daily_date[5:] if len(daily_date) == 10 else daily_date  # MM-DD
    return f"★ daily {day}, next in {when}" if day else f"★ daily, next in {when}"


def pin_daily(rows: list[ProblemSummary], slug: str | None) -> bool:
    """Move today's daily challenge to the front. True when it is in the list."""
    if not slug:
        return False
    for i, p in enumerate(rows):
        if p.slug == slug:
            rows.insert(0, rows.pop(i))
            return True
    return False


class ProblemList(DataTable):
    """The left pane. Row keys are problem slugs."""

    #: Columns other than the title, plus DataTable's per-cell padding.
    _CHROME = 1 + 4 + 6 + 8

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._rows_data: list[ProblemSummary] = []
        self._daily: str | None = None
        self._title_width = 0

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.zebra_stripes = True
        self.add_column("", width=1, key="mark")
        self.add_column("#", width=4, key="id")
        # Difficulty sits before the title so it stays visible in a narrow pane.
        self.add_column("Diff", width=6, key="difficulty")
        self.add_column("Title", key="title")

    def _available(self) -> int:
        return max((self.size.width or 46) - self._CHROME, 14)

    def load(self, rows: Iterable[ProblemSummary], daily: str | None = None) -> None:
        self._rows_data = list(rows)
        self._daily = daily
        self._render_rows()

    def _render_rows(self) -> None:
        width = self._available()
        self._title_width = width
        self.clear()
        for p in self._rows_data:
            is_daily = p.slug == self._daily
            label = p.title
            budget = width - (2 if p.paid_only else 0) - (2 if is_daily else 0)
            if len(label) > budget:
                label = label[: budget - 1] + "…"
            title = Text()
            if is_daily:
                title.append("★ ", style="bold yellow")
            title.append(label, style="bold yellow" if is_daily else "")
            if p.paid_only:
                title.append(" 🔒", style="yellow")
            self.add_row(
                status_mark(p.status),
                Text(p.frontend_id, style="dim"),
                difficulty_text(p.difficulty[:6]),
                title,
                key=p.slug,
            )

    def on_resize(self) -> None:
        # Re-truncate only when the usable width actually changed.
        if self._rows_data and self._available() != self._title_width:
            selected = self.cursor_row
            self._render_rows()
            if 0 <= selected < self.row_count:
                self.move_cursor(row=selected)


class ReviewList(DataTable):
    """The Review tab: the spaced-repetition deck. Row keys are problem slugs."""

    #: Columns other than the title, plus DataTable's per-cell padding.
    _CHROME = 1 + 4 + 2 + 6 + 10

    BINDINGS = [
        # These live on the widget so they only fire — and only show in the
        # footer — while the Review tab has focus. One footer slot documents
        # the pair; the rest are in `?`.
        Binding("plus,equals_sign", "app.review_level_up", "Grade +/-"),
        Binding("g", "app.review_sync", "Sync"),

        # Both halves of each key: + is shift-=, and _ is shift--. Binding
        # only one of a pair means holding shift silently does nothing, which
        # reads as "grading is broken" rather than "wrong key".
        Binding("minus,underscore", "app.review_level_down", "Grade down",
                show=False),
        Binding("0", "app.review_forget", "Forgot it — back to level 1",
                show=False),
        Binding("z", "app.review_snooze", "Postpone this one", show=False),
        Binding("Z", "app.review_snooze_due", "Postpone everything due",
                show=False),
        Binding("x", "app.review_remove", "Take off the deck", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._items: list[review.ReviewItem] = []
        self._today = date.today()
        self._title_width = 0

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.zebra_stripes = True
        self.add_column("", width=1, key="due-mark")
        self.add_column("#", width=4, key="id")
        self.add_column("Lv", width=2, key="level")
        self.add_column("Due", width=6, key="due")
        self.add_column("Title", key="title")

    def _available(self) -> int:
        return max((self.size.width or 46) - self._CHROME, 14)

    def load_items(self, items: Iterable[review.ReviewItem], today: date) -> None:
        self._items = list(items)
        self._today = today
        self._render_rows()

    #: Row background for a problem submitted today — the cue that it is
    #: waiting for you to grade it with + or -.
    ATTEMPT_BG = {"passed": "on #14532d", "failed": "on #4c1d24"}

    def _render_rows(self) -> None:
        width = self._available()
        self._title_width = width
        selected = self.cursor_row
        here = self._cursor_slug()
        self.clear()
        for item in self._items:
            days = item.due_in(self._today)
            attempt = item.attempt_today(self._today)
            # A row you solved today is tinted whole, so it reads as one block
            # rather than a stray coloured cell.
            bg = self.ATTEMPT_BG.get(attempt, "")

            def paint(text: str, style: str = "") -> Text:
                return Text(text, style=f"{style} {bg}".strip())

            if attempt:
                mark = paint("✔" if attempt == "passed" else "✗",
                             "bold green" if attempt == "passed" else "bold red")
            elif days < 0:
                mark = paint("●", "bold red")
            elif days == 0:
                mark = paint("●", "bold yellow")
            else:
                mark = paint("○", "dim")

            if days < 0:
                due = paint(f"{days}d", "bold red")
            elif days == 0:
                due = paint("today", "bold yellow")
            else:
                due = paint(f"{days}d", "dim")

            label = item.title or item.slug
            if len(label) > width:
                label = label[: width - 1] + "…"
            self.add_row(
                mark,
                paint(item.frontend_id,
                      DIFFICULTY_STYLE.get(item.difficulty, "dim")),
                paint(str(item.level), "bold" if days <= 0 else ""),
                due,
                paint(label),
                key=item.slug,
            )
        # Stay on the problem, not on the row number. Grading changes a due
        # date, which re-sorts the deck — restoring the old index would leave
        # the cursor on whatever slid into that slot, so the next + or - would
        # grade a problem the user never looked at.
        if here is not None:
            try:
                self.move_cursor(row=self.get_row_index(here))
                return
            except RowDoesNotExist:
                pass    # taken off the deck: fall back to where it used to be
        if 0 <= selected < self.row_count:
            self.move_cursor(row=selected)

    def _cursor_slug(self) -> str | None:
        if not self.row_count or not 0 <= self.cursor_row < self.row_count:
            return None
        key = self.coordinate_to_cell_key(self.cursor_coordinate).row_key
        return str(key.value) if key is not None and key.value else None

    def on_resize(self) -> None:
        if self._items and self._available() != self._title_width:
            self._render_rows()


class Splitter(Static):
    """The bar between the panes — drag it to hand width to either side.

    A widget rather than the left pane's `border-right`, because a border is
    paint: there is nothing there for the mouse to take hold of.
    """

    DEFAULT_CSS = """
    Splitter { width: 1; height: 1fr; color: $panel; }
    Splitter:hover, Splitter.-dragging { color: $accent; }
    """

    #: Neither side may be squeezed below this, however far you drag.
    MIN_PANE = 24

    def render_line(self, y: int) -> Strip:
        # The same rule the left pane's border used to draw, so nothing about
        # the layout looks different until you reach for it.
        return Strip([Segment("│", self.rich_style)])

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self.capture_mouse()
        self.add_class("-dragging")

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self.release_mouse()
        self.remove_class("-dragging")

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self.has_class("-dragging"):
            return
        left = self.screen.query_one("#left")
        # -1 for the bar itself, or the right pane ends up a cell short.
        room = self.screen.size.width - self.MIN_PANE - 1
        width = max(self.MIN_PANE, min(event.screen_x - left.region.x, room))
        # The CSS bounds size the opening layout. Once you have taken hold of
        # the bar, the width you drag to is the width you meant — so widen them
        # to the drag limits rather than clearing them, which only falls back
        # to the stylesheet.
        left.styles.min_width = self.MIN_PANE
        left.styles.max_width = room
        left.styles.width = width


class ConfigScreen(ModalScreen[bool]):
    """Settings, edited in place. Returns True when something was saved."""

    CSS = """
    ConfigScreen { align: center middle; }
    #config-box {
        width: 78; max-width: 96%; height: auto; max-height: 90%;
        background: $surface; border: round $accent; padding: 1 2;
    }
    /* Single-line fields: the whole form, including the live curve preview,
       has to fit without scrolling on a short terminal. */
    #config-box > Label { color: $text-muted; margin-top: 1; }
    #config-box > Input {
        height: 1; border: none; padding: 0 1; background: $panel;
    }
    #config-box > Input:focus { background: $boost; color: $text; }
    #curve-preview { color: $accent; height: auto; }
    #config-error { color: $error; height: auto; }
    #config-hint { color: $text-muted; margin-top: 1; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    #: (config attribute, label, placeholder)
    FIELDS = (
        ("workspace", "Workspace — where solution files are written", "~/leetcode"),
        ("lang", "Default language for new problems", "python3"),
        ("editor", "Editor command (blank uses $EDITOR)", "vim"),
        ("review_repo", "Review repo — git remote the deck syncs with",
         "git@github.com:you/lc-review.git"),
    )

    def __init__(self, config, curve: list[int]) -> None:
        super().__init__()
        self.config = config
        self.curve = curve

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="config-box"):
            yield Static(Text("lc settings", style="bold"))
            for name, label, placeholder in self.FIELDS:
                yield Label(label)
                yield Input(
                    value=str(getattr(self.config, name, "") or ""),
                    placeholder=placeholder,
                    id=f"cfg-{name}",
                )
            yield Label("Memory curve — days between reviews, one per level")
            yield Input(
                value=", ".join(str(d) for d in self.curve),
                placeholder="1, 2, 4, 7, 15",
                id="cfg-curve",
            )
            yield Static("", id="curve-preview")
            yield Static("", id="config-error")
            yield Static(
                Text("ctrl+s save · esc cancel · blank curve restores the default",
                     style="dim"),
                id="config-hint",
            )

    def on_mount(self) -> None:
        self._preview()
        self.query_one("#cfg-workspace", Input).focus()

    @on(Input.Changed, "#cfg-curve")
    def _curve_changed(self) -> None:
        self._preview()

    @on(Input.Submitted)
    def _submitted(self) -> None:
        # Enter anywhere in the form saves, like a dialog's default button.
        self.action_save()

    def _parse_curve(self) -> list[int] | None:
        """The typed curve, or None when it cannot be read (error shown)."""
        raw = self.query_one("#cfg-curve", Input).value.strip()
        error = self.query_one("#config-error", Static)
        if not raw:
            error.update("")
            return []  # empty means "lc's default"
        try:
            days = [int(part) for part in raw.replace(" ", "").split(",") if part]
        except ValueError:
            error.update(Text("curve: days must be whole numbers, e.g. 1, 2, 4, 7"))
            return None
        if not days or any(not 1 <= d <= review.MAX_GAP_DAYS for d in days):
            error.update(
                Text(f"curve: each level needs 1 to {review.MAX_GAP_DAYS} days")
            )
            return None
        error.update("")
        return days

    def _preview(self) -> None:
        days = self._parse_curve()
        preview = self.query_one("#curve-preview", Static)
        if days is None:
            preview.update("")
            return
        effective = days or list(review.DEFAULT_CURVE)
        shown = " · ".join(
            f"lv{i}→{d}d" for i, d in enumerate(effective[:8], 1)
        )
        if len(effective) > 8:
            shown += " · …"
        suffix = " (lc default)" if not days else ""
        preview.update(
            Text(f"{len(effective)} levels: {shown}{suffix}", style="dim")
        )

    def action_save(self) -> None:
        days = self._parse_curve()
        if days is None:
            self.query_one("#cfg-curve", Input).focus()
            return
        # Everything else may be blank and mean something; a blank workspace
        # would just be "wherever lc was started", which is never intended.
        if not self.query_one("#cfg-workspace", Input).value.strip():
            self.query_one("#config-error", Static).update(
                Text("workspace: give a directory for solution files")
            )
            self.query_one("#cfg-workspace", Input).focus()
            return
        for name, _label, _placeholder in self.FIELDS:
            setattr(self.config, name, self.query_one(f"#cfg-{name}", Input).value.strip())
        self.config.review_curve = days
        save_config(self.config)
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class LeetCodeTUI(App):
    CSS = """
    Screen { layers: base fx; }
    #fx { layer: fx; width: 100%; height: 100%; align: center middle; }
    #fx-frame { width: auto; height: auto; }
    #body { height: 1fr; }
    #left { width: 40%; min-width: 40; max-width: 64; }
    #filter { border: none; height: 3; background: $boost; }
    #tabs { height: 1fr; }
    TabPane { padding: 0; }
    #right { width: 1fr; padding: 1 2; }
    #status-bar { height: 1; background: $boost; color: $text-muted; padding: 0 1; }
    ProblemList { height: 1fr; }
    ReviewList { height: 1fr; }
    /* Hidden until a review repo is configured — an empty strip would just
       cost the deck a row. */
    #sync-bar { height: 1; padding: 0 1; background: $boost; }
    #sync-bar.-off { display: none; }
    """

    # Only the solving loop is on the footer. The rest still works and is one
    # `?` away — a footer listing fifteen keys is a wall, not a reminder.
    BINDINGS = [
        Binding("slash", "focus_filter", "Filter"),
        # `enter` is handled via DataTable.RowSelected rather than a priority
        # binding, so that enter in the filter box just returns focus to the list.
        Binding("p", "pick", "Edit"),
        Binding("r", "run", "Run"),
        Binding("s", "submit", "Submit"),
        Binding("m", "save_review", "Save"),
        # Priority: the Screen's own tab binding (focus-next) would win otherwise.
        Binding("tab", "switch_pane", "Review", priority=True),
        Binding("question_mark", "toggle_keys", "Keys"),
        Binding("q", "quit", "Quit"),

        Binding("c", "settings", "Settings", show=False),
        Binding("d", "cycle_difficulty", "Difficulty filter", show=False),
        Binding("t", "cycle_status", "Status filter", show=False),
        Binding("o", "open_web", "Open on leetcode.com", show=False),
        Binding("D", "daily", "Jump to today's daily", show=False),
        Binding("ctrl+r", "refresh", "Refresh from the local index", show=False),
        Binding("R", "sync", "Re-download the problem index", show=False),
        Binding("escape", "focus_list", "", show=False),
    ]

    def __init__(self, initial: str | None = None) -> None:
        super().__init__()
        self.initial = initial
        self.config = load_config()
        self.curve = review.curve_of(self.config)
        self.client = LeetCode(load_credentials())
        self.difficulty = ""
        self.status_filter = ""
        self.keyword = ""
        self.current: Problem | None = None
        self.current_slug: str = ""
        self.daily_slug: str | None = None
        self._filter_timer = None

    # ----------------------------------------------------------------- layout

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield Input(placeholder="filter…", id="filter")
                with TabbedContent(id="tabs"):
                    with TabPane("Problems", id="pane-problems"):
                        yield ProblemList(id="list")
                    with TabPane("Review", id="pane-review"):
                        yield ReviewList(id="review")
                        yield Static("", id="sync-bar")
            yield Splitter(id="splitter")
            with VerticalScroll(id="right"):
                yield Static("", id="statement")
        yield Static("", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "LeetCode"
        self.refresh_list()
        self.refresh_review()
        if store.index_size() == 0:
            self.action_sync()
        self._daily_worker()
        table = self.query_one("#list", ProblemList)
        if self.initial:
            summary = store.find(self.initial)
            if summary:
                self.select_slug(summary.slug)
        table.focus()

    def select_slug(self, slug: str) -> bool:
        """Move the cursor onto a problem. Highlighting it loads the statement."""
        table = self.query_one("#list", ProblemList)
        try:
            index = table.get_row_index(slug)
        except RowDoesNotExist:
            return False
        table.move_cursor(row=index)
        return True

    # ----------------------------------------------------------------- state

    def set_status(self, message: str, style: str = "") -> None:
        bar = self.query_one("#status-bar", Static)
        filters = []
        if self.difficulty:
            filters.append(self.difficulty)
        if self.status_filter:
            filters.append(self.status_filter)
        prefix = f"[{' · '.join(filters)}] " if filters else ""
        bar.update(Text(prefix + message, style=style or "dim"))

    def refresh_list(self) -> None:
        selected = self.current_slug
        rows = store.search(
            keyword=self.keyword,
            difficulty=self.difficulty,
            status=self.status_filter,
            limit=1_000_000,  # the whole problem set; the table scrolls fine
        )
        pinned = pin_daily(rows, self.daily_slug)
        self.query_one("#list", ProblemList).load(
            rows, daily=self.daily_slug if pinned else None
        )
        # Rebuilding rows resets the cursor to the top — put it back on the
        # problem the user was on whenever it is still in the list.
        if selected:
            self.select_slug(selected)
        if not rows and store.index_size() == 0:
            self.set_status("no local index yet — press R to sync", "yellow")
        else:
            message = f"{len(rows)} problems"
            if pinned:
                # Recomputed on every refresh — which is exactly when someone
                # is wondering why the daily has not changed.
                message += "  ·  " + daily_note(store.get_meta("daily_date") or "")
            self.set_status(message)

    def refresh_review(self) -> None:
        today = date.today()
        items = review.load()
        rows = review.order(items)
        if self.keyword:
            needle = self.keyword.lower()
            rows = [
                item for item in rows
                if needle in (item.title or "").lower()
                or needle in item.slug
                or item.frontend_id == self.keyword
            ]
        self.query_one("#review", ReviewList).load_items(rows, today)
        # The tab itself carries the day's workload, visible from either pane.
        due = review.due_count(items, today)
        self.query_one(TabbedContent).get_tab("pane-review").label = (
            f"Review ({due})" if due else "Review"
        )
        self.refresh_sync_bar()

    #: Style per sync state, so the strip reads at a glance.
    SYNC_STYLES = {
        "clean": "green", "pending": "yellow", "failed": "red",
        "never": "dim", "syncing": "yellow",
    }

    def refresh_sync_bar(self, message: str = "", state: str = "") -> None:
        """The git line under the deck. `message` overrides it while syncing."""
        bar = self.query_one("#sync-bar", Static)
        if message:
            bar.set_class(False, "-off")
            bar.update(Text(message, style=self.SYNC_STYLES.get(state, "dim")))
            return
        status = gitsync.status(self.config)
        bar.set_class(status.state == "off", "-off")
        if status.state == "off":
            bar.update("")
            return
        bar.update(
            Text(gitsync.summary(self.config), style=self.SYNC_STYLES[status.state])
        )

    def _active_table(self) -> DataTable:
        if self.query_one(TabbedContent).active == "pane-review":
            return self.query_one("#review", ReviewList)
        return self.query_one("#list", ProblemList)

    # ----------------------------------------------------------------- events

    @on(Input.Changed, "#filter")
    def _filter_changed(self, event: Input.Changed) -> None:
        self.keyword = event.value.strip()
        # Rebuilding a few thousand DataTable rows per keystroke lags — wait
        # for a pause in typing instead.
        if self._filter_timer is not None:
            self._filter_timer.stop()
        self._filter_timer = self.set_timer(0.15, self._apply_filter)

    def _apply_filter(self) -> None:
        self.refresh_list()
        self.refresh_review()

    @on(Input.Submitted, "#filter")
    def _filter_submitted(self) -> None:
        self._active_table().focus()

    @on(DataTable.RowHighlighted, "#list")
    @on(DataTable.RowHighlighted, "#review")
    def _row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        # A hidden pane rebuilding its rows re-highlights its cursor row too.
        # Only the visible table may drive the statement pane — current_slug
        # is what r/s/enter act on, so a stray event here would point them
        # at a problem the user cannot even see.
        if event.data_table is not self._active_table():
            return
        if event.row_key is not None and event.row_key.value:
            self.load_problem(str(event.row_key.value))

    @on(DataTable.RowSelected, "#list")
    @on(DataTable.RowSelected, "#review")
    def _row_selected(self) -> None:
        self.action_pick()

    # ----------------------------------------------------------------- actions

    def action_focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_focus_list(self) -> None:
        # esc closes the key list first — the list even names esc among the
        # keys, so pressing it and having nothing happen is a trap.
        if self._keys_open():
            self.action_hide_help_panel()
            return
        self._active_table().focus()

    def action_switch_pane(self) -> None:
        tabs = self.query_one(TabbedContent)
        tabs.active = (
            "pane-problems" if tabs.active == "pane-review" else "pane-review"
        )

    @on(TabbedContent.TabActivated)
    def _tab_activated(self) -> None:
        # Key and mouse land here alike: focus the now-visible table and point
        # the statement pane at whatever its cursor is on.
        table = self._active_table()
        table.focus()
        if table.row_count:
            key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            if key is not None and key.value:
                self.load_problem(str(key.value))

    # ------------------------------------------------------------ review deck

    def action_save_review(self) -> None:
        slug = self.current_slug
        if not slug:
            return
        deck = review.live(review.load())
        if slug in deck:
            item = deck[slug]
            self.notify(
                f"already on the review deck (level {item.level}) — "
                "x in the Review tab removes it",
                severity="warning",
            )
            return
        summary = store.find(slug)
        problem = self.current if self.current and self.current.slug == slug else None
        source = summary or problem
        item = review.add(
            slug,
            title=source.title if source else slug,
            frontend_id=source.frontend_id if source else "",
            difficulty=source.difficulty if source else "",
            curve=self.curve,
        )
        self.notify(
            f"saved for review — level 1, first review in {item.due_in(date.today())}d"
        )
        self.refresh_review()

    def _review_slug(self) -> str | None:
        table = self.query_one("#review", ReviewList)
        if not table.row_count:
            return None
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        return str(key.value) if key is not None and key.value else None

    def _review_shift(self, delta: int) -> None:
        slug = self._review_slug()
        if not slug:
            return
        item = review.shift_level(slug, delta, self.curve)
        if item:
            self.notify(
                f"level {item.level} — next review in {item.due_in(date.today())}d"
            )
            self.refresh_review()

    def action_review_level_up(self) -> None:
        self._review_shift(+1)

    def action_review_level_down(self) -> None:
        self._review_shift(-1)

    def action_review_forget(self) -> None:
        slug = self._review_slug()
        if not slug:
            return
        item = review.forget(slug, self.curve)
        if item:
            self.notify(
                f"forgotten — back to level 1, next review in "
                f"{item.due_in(date.today())}d"
            )
            self.refresh_review()

    def action_review_snooze(self) -> None:
        slug = self._review_slug()
        if not slug:
            return
        item = review.postpone(slug)
        if item:
            self.notify(f"postponed — due in {item.due_in(date.today())}d")
            self.refresh_review()

    def action_review_snooze_due(self) -> None:
        moved = review.postpone_due()
        if moved:
            self.notify(f"postponed {moved} problem(s) to tomorrow")
            self.refresh_review()
        else:
            self.notify("nothing due today")

    def action_review_sync(self) -> None:
        url = self.config.review_repo.strip()
        if not url:
            self.notify(
                "no review repo yet — press c and fill in 'Review repo'",
                severity="warning",
            )
            return
        # The sync strip owns this story from here: the status bar keeps
        # reporting the problem list, and the notification says what the sync
        # actually did. Three channels repeating "syncing…" is noise.
        self.refresh_sync_bar("⟳ syncing…", "syncing")
        self._review_sync_worker(url)

    @work(thread=True, exclusive=True, group="review-sync")
    def _review_sync_worker(self, url: str) -> None:
        try:
            added, updated, changed = gitsync.sync(url)
        except gitsync.SyncError as exc:
            message = str(exc) + (f"\n{exc.hint}" if exc.hint else "")
            self.call_from_thread(self.notify, escape(message), severity="error",
                                  timeout=12)
            self.call_from_thread(self.refresh_sync_bar)
            return
        parts = []
        if added or updated:
            parts.append(f"pulled {added} new, {updated} updated")
        parts.append("pushed" if changed else "repo already matched")
        # The strip says *where you stand*; this says *what just happened*.
        self.call_from_thread(self.refresh_review)
        self.call_from_thread(self.notify, "review sync: " + ", ".join(parts))

    # ---------------------------------------------------------------- settings

    def _keys_open(self) -> bool:
        return bool(self.screen.query("HelpPanel"))

    def action_toggle_keys(self) -> None:
        """`?` — the full key list, including everything kept off the footer."""
        if self._keys_open():
            self.action_hide_help_panel()
        else:
            self.action_show_help_panel()

    async def action_quit(self) -> None:
        """`q` — but the key list is an overlay, and backing out of it is what
        `q` means there. It used to quit the app instead: you opened the list
        to find your way around and lost the session for it."""
        if self._keys_open():
            self.action_hide_help_panel()
            return
        self.exit()

    def action_settings(self) -> None:
        def saved(changed: bool | None) -> None:
            if not changed:
                return
            # Re-read from disk so the app and config.json cannot drift, and
            # pick up a curve change everywhere at once.
            self.config = load_config()
            self.curve = review.curve_of(self.config)
            self.refresh_review()
            self.notify("settings saved")

        self.push_screen(ConfigScreen(load_config(), self.curve), saved)

    def action_review_remove(self) -> None:
        slug = self._review_slug()
        if not slug:
            return
        item = review.live(review.load()).get(slug)
        review.remove(slug)
        self.notify(f"removed {item.title if item and item.title else slug} "
                    "from the review deck")
        self.refresh_review()

    def action_cycle_difficulty(self) -> None:
        i = DIFFICULTIES.index(self.difficulty)
        self.difficulty = DIFFICULTIES[(i + 1) % len(DIFFICULTIES)]
        self.refresh_list()

    def action_cycle_status(self) -> None:
        i = STATUSES.index(self.status_filter)
        self.status_filter = STATUSES[(i + 1) % len(STATUSES)]
        self.refresh_list()

    def action_open_web(self) -> None:
        if self.current and not open_url(self.current.url):
            self.notify(f"could not open a browser — {self.current.url}",
                        severity="warning")

    def action_pick(self) -> None:
        if not self.current:
            return
        problem = self.current
        if problem.paid_only and not problem.snippets:
            self.notify("premium problem — your account cannot open it",
                        severity="error")
            return
        lang = choose(self.config.lang, self.config.favorite_langs, problem.snippets)
        if lang is None:
            self.notify("this problem has no starter code lc understands",
                        severity="error")
            return
        try:
            solution = workspace.create(self.config, problem, lang)
        except (ValueError, OSError) as exc:
            self.notify(escape(str(exc)), severity="error")
            return

        editor = self.config.resolve_editor()
        if editor:
            with self.suspend():
                workspace.open_in_editor(self.config, solution.file)
            # A `\t`/`\s` inside the editor may have judged this problem — the
            # store already knows, so the ✔/✗ marks must not wait for a sync,
            # and a submit may also have moved it on the review deck.
            self.refresh_list()
            self.refresh_review()
            self.refresh()
        else:
            self.notify(f"created {solution.file} (set $EDITOR to auto-open)")

    def action_run(self) -> None:
        self._judge(submit=False)

    def action_submit(self) -> None:
        self._judge(submit=True)

    def action_sync(self) -> None:
        self.set_status("syncing problem index…", "yellow")
        self._sync_worker()

    def action_refresh(self) -> None:
        """Instant, local: re-read the index (a Vim `\\s` may have landed) and
        re-check the daily in case the UTC day rolled over."""
        self._daily_worker()
        self.refresh_list()
        self.refresh_review()

    def action_daily(self) -> None:
        if not self.daily_slug:
            self.notify("today's daily is not known yet — check your connection",
                        severity="warning")
            return
        # The daily lives in the problem list — make sure that pane is showing.
        self.query_one(TabbedContent).active = "pane-problems"
        if not self.select_slug(self.daily_slug):
            self.notify("today's daily is hidden by the current filters",
                        severity="warning")

    # ----------------------------------------------------------------- workers

    @work(thread=True, exclusive=True, group="daily")
    def _daily_worker(self) -> None:
        """Resolve today's daily challenge, hitting the network once per day."""
        today = time.strftime("%Y-%m-%d", time.gmtime())  # dailies rotate at midnight UTC
        slug = store.get_meta("daily_slug")
        if store.get_meta("daily_date") != today or not slug:
            try:
                date, summary = self.client.daily()
            except LeetCodeError:
                return  # offline — the list just stays unpinned
            slug = summary.slug
            store.set_meta("daily_date", date or today)
            store.set_meta("daily_slug", slug)
        self.daily_slug = slug
        self.call_from_thread(self.refresh_list)

    def load_problem(self, slug: str) -> None:
        self.current_slug = slug
        cached = store.get_statement(slug)
        if cached:
            self._show(cached)
            return
        # Until the fetch lands there is no current problem — pick/run/submit
        # must not quietly act on the one shown before.
        self.current = None
        self.query_one("#statement", Static).update(Text("loading…", style="dim"))
        self._fetch_worker(slug)

    @work(thread=True, exclusive=True, group="fetch")
    def _fetch_worker(self, slug: str) -> None:
        try:
            problem = self.client.problem(slug)
        except LeetCodeError as exc:
            if slug == self.current_slug:  # a stale error must not cover a newer pick
                self.call_from_thread(
                    self.query_one("#statement", Static).update,
                    Text(str(exc), style="red"),
                )
            return
        store.put_statement(problem)
        if slug == self.current_slug:
            self.call_from_thread(self._show, problem)

    def _show(self, problem: Problem) -> None:
        self.current = problem
        body: list[RenderableType] = [problem_header(problem), Text("")]
        if problem.paid_only and not problem.content:
            body.append(Text("Premium problem — your account cannot read it.",
                             style="yellow"))
        else:
            body.append(render_statement(problem.content))
        if problem.hints:
            body.append(Text("Hints", style="bold dim"))
            for i, hint in enumerate(problem.hints, 1):
                body.append(render_statement(f"<p>{i}. {hint}</p>"))
        self.query_one("#statement", Static).update(Group(*body))
        self.query_one("#right", VerticalScroll).scroll_home(animate=False)
        self.sub_title = f"{problem.frontend_id}. {problem.title}"

    def _judge(self, submit: bool) -> None:
        if not self.current:
            return
        if not self.client.authenticated:
            self.notify("not logged in — run `lc login` first", severity="error")
            return
        solution = workspace.load(self.config, self.current)
        if solution is None:
            self.notify("no solution file yet — press enter to create one",
                        severity="warning")
            return
        self.set_status("submitting…" if submit else "running samples…", "yellow")
        self._judge_worker(self.current, solution, submit)

    @work(thread=True, exclusive=True, group="judge")
    def _judge_worker(
        self, problem: Problem, solution: workspace.Solution, submit: bool
    ) -> None:
        code = workspace.strip_header(solution.code, solution.language)
        cases: list[str] = []
        try:
            if submit:
                result = self.client.submit(problem, solution.language.slug, code)
            else:
                data_input = problem.example_testcases or problem.sample_testcase
                cases = split_testcases(problem, data_input)
                result = self.client.run(
                    problem, solution.language.slug, code, data_input
                )
        except LeetCodeError as exc:
            self.call_from_thread(self.notify, escape(str(exc)), severity="error")
            self.call_from_thread(self.set_status, "judge failed", "red")
            return

        if submit:
            # Mirror the CLI: record the attempt, but never downgrade a solve.
            if result.accepted:
                store.update_status(problem.slug, "ac")
            else:
                known = store.find(problem.slug)
                if known is not None and not known.solved:
                    store.update_status(problem.slug, "notac")
            note = review.record_submit(problem.slug, result.accepted)
            self.call_from_thread(self.refresh_list)
            self.call_from_thread(self.refresh_review)
            if note:
                key = "+" if result.accepted else "-"
                self.call_from_thread(
                    self.notify, f"{note} · press {key} in the Review tab",
                    timeout=8,
                )

        self.call_from_thread(self._show_result, result, cases)

    def _show_result(self, result: JudgeResult, cases: list[str] | None = None) -> None:
        lines: list[RenderableType] = [
            Text(result.display_status,
                 style="bold green" if result.accepted else "bold red")
        ]
        if result.error:
            lines.append(Text(result.error.strip()[:2000], style="red"))
        if result.total_testcases:
            lines.append(
                Text(f"{result.total_correct or 0}/{result.total_testcases} passed",
                     style="dim")
            )
        if result.is_run and result.code_output:
            for i, got in enumerate(result.code_output):
                want = (
                    result.expected_output[i]
                    if i < len(result.expected_output)
                    else ""
                )
                if not got and not want:
                    continue  # the judge pads its answer arrays with a trailing ""
                ok = got == want
                line = Text(f"{i + 1}. {got}", style="green" if ok else "red")
                if not ok:
                    line.append(f"   expected {want}", style="dim")
                lines.append(line)
                if not ok and cases and i < len(cases):
                    one = cases[i].replace("\n", " · ")
                    lines.append(Text(f"   input: {one[:100]}", style="dim"))
        if not result.is_run and not result.accepted and result.last_testcase:
            label = "failing input"
            if result.total_testcases:
                label = f"failing case {(result.total_correct or 0) + 1}/{result.total_testcases}"
            lines.append(Text(f"{label}: {result.last_testcase[:200]}", style="dim"))
        if result.runtime:
            lines.append(Text(f"{result.runtime}   {result.memory}", style="dim"))

        self.set_status(
            result.display_status, "green" if result.accepted else "red"
        )
        # notify() treats its message as markup — judge output like `[true,false]`
        # would otherwise be eaten as a style tag.
        self.notify(
            escape(
                "\n".join(
                    line.plain if isinstance(line, Text) else str(line)
                    for line in lines
                )
            ),
            title=result.display_status,
            severity="information" if result.accepted else "error",
            timeout=12,
        )
        if result.accepted:
            self._celebrate(big=not result.is_run)
        else:
            self._mourn(big=not result.is_run)

    def _celebrate(self, big: bool) -> None:
        """Fireworks in a transparent overlay — small for runs, big for submits."""
        width = self.size.width
        if big:
            frames = fx.firework_frames(min(width - 4, 74), 15, 4, 40)
        else:
            frames = fx.firework_frames(min(width - 4, 46), 10, 2, 20)
        self._play_overlay(frames, interval=0.05)

    def _mourn(self, big: bool) -> None:
        self._play_overlay(fx.defeat_frames(big), interval=0.09)

    def _play_overlay(self, frames: list, interval: float) -> None:
        if os.environ.get("LC_NO_FX"):
            return
        for old in self.query("#fx"):
            old.remove()
        inner = Static(frames[0], id="fx-frame")
        overlay = Vertical(inner, id="fx")
        self.mount(overlay)
        state = {"i": 0}

        def tick() -> None:
            state["i"] += 1
            if state["i"] >= len(frames):
                timer.stop()
                overlay.remove()
                return
            inner.update(frames[state["i"]])

        timer = self.set_interval(interval, tick)

    @work(thread=True, exclusive=True, group="sync")
    def _sync_worker(self) -> None:
        try:
            problems = list(self.client.iter_all_problems())
        except LeetCodeError as exc:
            self.call_from_thread(self.set_status, str(exc), "red")
            return
        count = store.replace_index(problems)
        self.call_from_thread(self.refresh_list)
        self.call_from_thread(self.set_status, f"synced {count} problems", "green")

    def on_unmount(self) -> None:
        self.client.close()


def run_tui(initial: str | None = None) -> None:
    LeetCodeTUI(initial).run()
