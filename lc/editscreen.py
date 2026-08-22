"""The built-in editing screen: solve without leaving the TUI.

`lc config editor builtin` (or no editor at all) makes `enter` push this
screen instead of suspending into an external editor. Statement on the
left, code on the right, judge results as toasts, the solve clock on the
status bar — one look, one process, no terminal hand-offs.

The external-editor path (vim and its plugin) is untouched: this is an
alternative front door to the same files, judge and clock.
"""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.text import Text

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Static, TextArea

from . import notes, solvetimer, store
from .vimtext import VimTextArea
from .render import problem_header, render_statement

#: TextArea language ids, where its highlighter knows the language.
_TS_LANG = {"python3": "python", "python": "python", "java": "java",
            "cpp": "cpp", "c": "cpp", "golang": "go", "rust": "rust",
            "javascript": "javascript", "typescript": "javascript"}


class PauseScreen(ModalScreen[None]):
    """The break cover — opaque, so the statement cannot be read while the
    clock is stopped. Closing it is the resume, exactly like Vim's."""

    CSS = """
    PauseScreen { background: $background; align: center middle; }
    #pause-box {
        width: auto; height: auto; padding: 2 6;
        background: $surface; border: round $accent;
    }
    #pause-box > Static { width: auto; }
    #pause-hint { color: $text-muted; margin-top: 1; }
    """

    BINDINGS = [Binding("space,escape,enter", "resume", "Resume")]

    def __init__(self, elapsed: float) -> None:
        super().__init__()
        self.elapsed = elapsed

    def compose(self) -> ComposeResult:
        with Vertical(id="pause-box"):
            yield Static(Text(f"paused at {solvetimer.clock(self.elapsed)}",
                              style="bold"))
            yield Static(Text("space resumes", style="dim"), id="pause-hint")

    def action_resume(self) -> None:
        self.dismiss(None)


def statement_body(problem) -> RenderableType:
    """Header + statement + hints, the same content the main screen shows."""
    parts: list[RenderableType] = [problem_header(problem), Text("")]
    if problem.paid_only and not problem.content:
        parts.append(Text("Premium problem — your account cannot read it.",
                          style="yellow"))
    else:
        parts.append(render_statement(problem.content))
    if problem.hints:
        parts.append(Text("Hints", style="bold dim"))
        for i, hint in enumerate(problem.hints, 1):
            parts.append(render_statement(f"<p>{i}. {hint}</p>"))
    return Group(*parts)


class EditScreen(Screen):
    """Statement · code · judge · clock · notes, in one screen."""

    CSS = """
    EditScreen #edit-left {
        width: 44%; min-width: 30; padding: 1 2;
        border-right: solid $panel;
    }
    EditScreen #edit-code { width: 1fr; }
    EditScreen #edit-notes { height: 30%; border-top: solid $accent; }
    EditScreen #edit-status {
        height: 1; background: $boost; color: $text-muted; padding: 0 1;
    }
    """

    BINDINGS = [
        # priority: a TextArea eats plain keys, and must not eat these.
        Binding("ctrl+r", "run", "Run", priority=True),
        Binding("ctrl+s", "submit", "Submit", priority=True),
        Binding("ctrl+n", "notes", "Note", priority=True),
        Binding("ctrl+b", "pause", "Pause", priority=True),
        Binding("ctrl+g", "reset_clock", "Reset clock", priority=True),
        # escape is NOT priority: the vim layer needs it first (insert ->
        # normal), and in vim mode ZZ is the way out. With vim keys off, or
        # focus outside the code, escape still backs out.
        Binding("escape", "back", "Back"),
    ]

    def __init__(self, problem, solution) -> None:
        super().__init__()
        self.problem = problem
        self.solution = solution
        self._notes_open = False

    # ------------------------------------------------------------- layout

    def compose(self) -> ComposeResult:
        with Horizontal(id="edit-body"):
            with VerticalScroll(id="edit-left"):
                yield Static(statement_body(self.problem), id="edit-statement")
            with Vertical(id="edit-right"):
                lang = _TS_LANG.get(self.solution.language.slug)
                area = VimTextArea.code_editor(
                    self.solution.code, id="edit-code",
                ).set_vim(self.app.config.vim_keys_on)
                if lang:
                    # available_languages lists names textual KNOWS, not
                    # grammars actually installed — only assignment tells.
                    try:
                        area.language = lang
                    except Exception:
                        area.language = None  # no grammar: plain, not broken
                yield area
        yield Static("", id="edit-status")
        yield Footer()

    def on_mount(self) -> None:
        code = self.query_one("#edit-code", TextArea)
        code.focus()
        # Below the header comment, at the function body — where typing starts.
        code.move_cursor(code.document.end)
        if self.app.config.timer_on:
            solvetimer.begin(self.problem.slug)
        self.set_interval(1.0, self._tick)
        self._tick()

    # -------------------------------------------------------------- clock

    def _tick(self) -> None:
        try:
            bar = self.query_one("#edit-status", Static)
        except NoMatches:
            return
        left = f"[{self.problem.frontend_id}] {self.problem.title}"
        right = ""
        if self.app.config.timer_on:
            timer = solvetimer.load()
            if timer and timer.slug == self.problem.slug:
                if timer.done:
                    right = f"done {solvetimer.clock(timer.elapsed())}"
                elif timer.running:
                    right = solvetimer.clock(timer.elapsed())
                elif timer.armed:
                    right = "typing starts the clock"
                else:
                    right = (f"paused {solvetimer.clock(timer.elapsed())}"
                             " · ^b resumes")
        text = Text(left, style="dim")
        try:
            area = self.query_one("#edit-code", TextArea)
        except NoMatches:
            area = None
        vim = getattr(area, "vim_status", "")
        if vim:
            text.append("  ·  ", style="dim")
            text.append(vim, style="bold yellow" if "INSERT" in vim
                        or "VISUAL" in vim else "dim")
        if right:
            text.append("  ·  ", style="dim")
            text.append(right, style="bold" if right[0].isdigit() else "dim")
        bar.update(text)

    @on(TextArea.Changed, "#edit-code")
    def _typing_starts_the_clock(self) -> None:
        if not self.app.config.timer_on:
            return
        timer = solvetimer.load()
        # The deliberate start, translated: in Vim it is space, here it is
        # the first edit — reading the statement is still free.
        if timer and timer.slug == self.problem.slug and timer.armed:
            solvetimer.resume()
            self._tick()

    def action_pause(self) -> None:
        """ctrl+b — pause behind the cover, or start a clock standing still.

        A stopped clock has no pause to give: the same key starts it again,
        so ctrl+b is never a key that does nothing. (Only a *running* clock
        gets the cover — covering a stopped one would hide the statement
        with nothing counting.)
        """
        timer = solvetimer.load()
        if not (timer and timer.slug == self.problem.slug) or timer.done:
            return
        if not timer.running:
            solvetimer.resume()
            self._tick()
            return
        timer = solvetimer.pause()
        self._tick()

        def resumed(_: None) -> None:
            solvetimer.resume()
            self._tick()

        self.app.push_screen(PauseScreen(timer.accum), resumed)

    def _save_notes(self) -> None:
        try:
            notes.path_in(self.solution.directory).write_text(
                self.query_one("#edit-notes", TextArea).text)
        except OSError as exc:
            self.notify(f"could not save the note: {exc.strerror or exc}",
                        severity="error", timeout=10)

    def action_reset_clock(self) -> None:
        """ctrl+g — back to 00:00 and running, a fresh attempt at this
        problem. Vim has \\Z; the built-in editor had nothing."""
        timer = solvetimer.load()
        if not (timer and timer.slug == self.problem.slug):
            return
        fresh = solvetimer.reset()
        self._tick()
        self.notify(f"clock reset — {solvetimer.clock(fresh.accum)}")

    # -------------------------------------------------------------- judge

    def _save(self) -> bool:
        """Write the code back. False (with a toast) when the disk says no —
        a read-only file, a full disk, a deleted directory. Crashing here
        would take the unsaved buffer down with it."""
        try:
            self.solution.file.write_text(
                self.query_one("#edit-code", TextArea).text)
            return True
        except OSError as exc:
            self.notify(f"could not save {self.solution.file.name}: "
                        f"{exc.strerror or exc}", severity="error", timeout=10)
            return False

    def action_run(self) -> None:
        # Judging what is on disk when the buffer could not get there would
        # report on code the user is not looking at.
        if self._save():
            self.app._judge(submit=False)

    def action_submit(self) -> None:
        if self._save():
            self.app._judge(submit=True)

    # -------------------------------------------------------------- notes

    def action_notes(self) -> None:
        """ctrl+n — the note split under the code, toggled; closing saves."""
        if self._notes_open:
            area = self.query_one("#edit-notes", TextArea)
            self._save_notes()
            area.remove()
            self._notes_open = False
            self.query_one("#edit-code", TextArea).focus()
            return
        known = store.find(self.problem.slug)
        verdict = {"ac": "Accepted", "notac": "Not accepted"}.get(
            known.status if known else None, "")
        path = notes.open_card(self.solution.directory, verdict,
                               self.solution.language.slug)
        area = TextArea(notes.read(path), id="edit-notes")
        self.query_one("#edit-right", Vertical).mount(area)
        area.focus()
        area.move_cursor(area.document.end)
        self._notes_open = True

    # --------------------------------------------------------------- exit

    def action_back(self) -> None:
        if not self._save():
            # Stay put: leaving would strand the edit with nowhere to go.
            return
        if self._notes_open:
            self._save_notes()
        # Leaving the editor is leaving the solve, exactly like quitting Vim.
        if self.app.config.timer_on:
            timer = solvetimer.load()
            if timer and timer.slug == self.problem.slug and timer.running:
                solvetimer.pause()
        self.dismiss(True)
