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
from textual.widgets import Button, Footer, LoadingIndicator, Static, TextArea

from . import notes, solvetimer, store, workspace
from .browser import open_url
from .vimtext import VimTextArea
from .render import problem_header, render_statement

#: TextArea language ids, where its highlighter knows the language.
_TS_LANG = {"python3": "python", "python": "python", "java": "java",
            "cpp": "cpp", "c": "cpp", "golang": "go", "rust": "rust",
            "javascript": "javascript", "typescript": "javascript"}


def _move_to_code_end(area: TextArea) -> None:
    """Place the cursor before TextArea's sentinel row for a final newline."""
    row, column = area.document.end
    if row > 0 and column == 0 and not area.document.get_line(row):
        row -= 1
        column = len(area.document.get_line(row))
    area.move_cursor((row, column))


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


class JudgeScreen(ModalScreen[None]):
    """Opaque in-flight cover: one judge request, no live controls beneath."""

    CSS = """
    JudgeScreen { background: $background; align: center middle; }
    #judge-box {
        width: 34; height: 7; padding: 1 3;
        align: center middle;
        background: $surface; border: round $accent;
    }
    #judge-box > Static { width: 1fr; text-align: center; }
    #judge-box > LoadingIndicator { height: 1; margin-top: 1; }
    """

    def __init__(self, submit: bool) -> None:
        super().__init__()
        self.submit = submit

    def compose(self) -> ComposeResult:
        with Vertical(id="judge-box"):
            yield Static("Submitting…" if self.submit else "Running samples…")
            yield LoadingIndicator()


class ResetCodeScreen(ModalScreen[bool]):
    """Confirm the destructive-looking edit before making it undoable."""

    CSS = """
    ResetCodeScreen { background: $background 70%; align: center middle; }
    #reset-code-box {
        width: 48; height: auto; padding: 1 2;
        background: $surface; border: round $warning;
    }
    #reset-code-title { width: 1fr; text-style: bold; }
    #reset-code-detail { width: 1fr; color: $text-muted; margin: 1 0; }
    #reset-code-actions { width: 1fr; height: 3; align-horizontal: right; }
    #reset-code-actions Button { margin-left: 1; }
    """

    BINDINGS = [
        Binding("y,enter", "confirm", "Reset"),
        Binding("n,escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="reset-code-box"):
            yield Static("Reset this solution?", id="reset-code-title")
            yield Static("Restore LeetCode's starter code. Undo still restores "
                         "your current buffer.", id="reset-code-detail")
            with Horizontal(id="reset-code-actions"):
                yield Button("Cancel", id="reset-code-cancel")
                yield Button("Reset", id="reset-code-confirm", variant="warning")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#reset-code-confirm")
    def _confirm_button(self) -> None:
        self.action_confirm()

    @on(Button.Pressed, "#reset-code-cancel")
    def _cancel_button(self) -> None:
        self.action_cancel()


def statement_body(problem) -> RenderableType:
    """Header + statement + hints, the same content the main screen shows."""
    parts: list[RenderableType] = [
        problem_header(problem, click_action="screen.open_web()"), Text("")
    ]
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
        # Ctrl chords remain compatible in every mode but stay out of the
        # dynamic footer; F13-F17 are their clickable Insert/plain labels.
        Binding("ctrl+r", "editor_command('run')", show=False, priority=True),
        Binding("ctrl+s", "editor_command('submit')", show=False, priority=True),
        Binding("ctrl+n", "editor_command('notes')", show=False, priority=True),
        Binding("ctrl+b", "editor_command('pause')", show=False, priority=True),
        Binding("ctrl+g", "editor_command('reset_clock')", show=False,
                priority=True),
        Binding("f13", "insert_command('run')", "Run",
                key_display="^r", priority=True),
        Binding("f14", "insert_command('submit')", "Submit",
                key_display="^s", priority=True),
        Binding("f15", "insert_command('notes')", "Note",
                key_display="^n", priority=True),
        Binding("f16", "insert_command('pause')", "Pause",
                key_display="^b", priority=True),
        Binding("f17", "insert_command('reset_clock')", "Reset clock",
                key_display="^g", priority=True),
        # VimTextArea routes Normal/Visual R/S/N/B/T/X itself. Textual omits
        # uppercase bindings from Footer, so synthetic function keys provide
        # the matching clickable display entries.
        Binding("f19", "global_command('run')", "Run",
                key_display="R", priority=True),
        Binding("f20", "global_command('submit')", "Submit",
                key_display="S", priority=True),
        Binding("f21", "global_command('notes')", "Note",
                key_display="N", priority=True),
        Binding("f22", "global_command('pause')", "Pause",
                key_display="B", priority=True),
        Binding("f23", "global_command('reset_clock')", "Reset clock",
                key_display="T", priority=True),
        Binding("f18", "global_command('reset_code')", "Reset code",
                key_display="X", priority=True),
        # FooterKey clicks simulate their binding's key. F24 is an internal,
        # priority-only handle so the button can invoke Back without making
        # one real Z steal the first half of Vim's ZZ command.
        Binding("f24", "vim_back", "Back", key_display="ZZ", priority=True),
        # escape is NOT priority: the vim layer needs it first (insert ->
        # normal), and in vim mode ZZ is the way out. With vim keys off, or
        # focus outside the code (the note split), escape still backs out.
        Binding("escape", "back", "Back"),
    ]

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        # Vim and plain editing have different honest ways out. Keep escape
        # out of Vim's footer because the code area owns it, and keep the
        # synthetic ZZ footer action out of plain mode where escape is real.
        if action == "back":
            return not self.app.config.vim_keys_on
        if action == "vim_back":
            return self.app.config.vim_keys_on
        global_mode = self._global_mode()
        if action == "global_command":
            return global_mode
        if action == "insert_command":
            return not global_mode
        return True

    def _global_mode(self) -> bool:
        if not self.app.config.vim_keys_on:
            return False
        try:
            area = self.query_one("#edit-code", VimTextArea)
        except NoMatches:
            return False
        return area.mode != "insert"

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
                ).set_source_language(
                    self.solution.language.slug
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
        _move_to_code_end(code)
        if self.app.config.timer_on:
            solvetimer.begin(self.problem.slug)
        self.set_interval(1.0, self._tick)
        self._tick()
        self.refresh_bindings()

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

    def action_reset_code(self) -> None:
        """Restore starter code in one undoable edit after confirmation."""
        def reset(confirmed: bool | None) -> None:
            if not confirmed:
                return
            area = self.query_one("#edit-code", VimTextArea)
            try:
                code = workspace.starter_code(
                    self.problem, self.solution.language)
            except ValueError as exc:
                self.notify(str(exc), severity="warning")
                return
            # Bracket the whole replacement as one history batch. load_text()
            # would clear history and make the answer impossible to recover.
            area.history.checkpoint()
            area.replace(code, (0, 0), area.document.end,
                         maintain_selection_offset=False)
            area.history.checkpoint()
            _move_to_code_end(area)
            area.focus()

        self.app.push_screen(ResetCodeScreen(), reset)

    def action_open_web(self) -> None:
        if not open_url(self.problem.url):
            self.notify(f"could not open a browser — {self.problem.url}",
                        severity="warning")

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
        self._start_judge(submit=False)

    def action_submit(self) -> None:
        self._start_judge(submit=True)

    def _start_judge(self, submit: bool) -> None:
        if not self._save():
            return
        self.app.push_screen(JudgeScreen(submit))
        if not self.app._judge(submit):
            # Authentication and missing-solution checks happen in the app.
            # They report their own warning; uncover the editor immediately.
            self.app.screen.dismiss(None)

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
        try:
            path = notes.open_card(self.solution.directory, verdict,
                                   self.solution.language.slug)
        except OSError as exc:
            self.notify(f"could not open the notes: {exc.strerror or exc}",
                        severity="error", timeout=10)
            return
        area = TextArea(notes.read(path), id="edit-notes")
        self.query_one("#edit-right", Vertical).mount(area)
        area.focus()
        area.move_cursor(area.document.end)
        self._notes_open = True

    # --------------------------------------------------------------- exit

    def action_back(self) -> None:
        # From the note split, backing out closes the note rather than the
        # problem — dropping the whole screen from a half-written card is a
        # surprise. (Reached in plain-editor mode; under Vim keys the note
        # split is closed with ctrl+n, as the footer says.)
        if self._notes_open and self.focused is not None \
                and self.focused.id == "edit-notes":
            self.action_notes()
            return
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

    def action_vim_back(self) -> None:
        """The clickable footer entry for Vim's two-keystroke ZZ command."""
        self.action_back()

    def action_global_command(self, command: str) -> None:
        """Dispatch a Normal/Visual shortcut to the existing editor action."""
        getattr(self, f"action_{command}")()

    def action_insert_command(self, command: str) -> None:
        """Dispatch a clickable Insert/plain footer command."""
        getattr(self, f"action_{command}")()

    def action_editor_command(self, command: str) -> None:
        """Keep the original ctrl chords working in every editor mode."""
        getattr(self, f"action_{command}")()
