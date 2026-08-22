"""A Vim layer for the built-in editor's TextArea.

A deliberate subset, not an emulator: modes, the movements and edits a
LeetCode solve leans on, undo/redo, one unnamed register. `lc config editor
vim` remains the door to the real thing; this keeps the muscle memory that
matters working *inside* the TUI.

Normal mode:  h j k l  w b e  0 ^ $  gg G  (counts on h j k l w b x, and NG)
              i a I A o O s  x  r<ch>  dd yy cc  dw de db  cw ce cb  D C
              p P  u (undo)  U (redo — ctrl+r runs the samples)  v  ZZ ZQ
Insert/visual behave as expected; esc never leaves the screen — ZZ does.
"""

from __future__ import annotations

from textual import events
from textual.widgets import TextArea

_WORD_MOTIONS = {"w": "action_cursor_word_right", "b": "action_cursor_word_left",
                 "e": "action_cursor_word_right"}
_GLOBAL_COMMANDS = {"R": "run", "S": "submit", "N": "notes",
                    "B": "pause", "T": "reset_clock", "X": "reset_code"}


class VimTextArea(TextArea):
    """TextArea with a Vim subset. `vim_status` feeds the status bar."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # code_editor() cannot forward extra kwargs — set_vim() after building.
        self.vim_enabled = True
        self.mode = "normal"          # normal | insert | visual
        self._pending = ""            # d y c g r Z awaiting their second key
        self._count = ""
        self._register: tuple[str, bool] = ("", False)   # text, linewise
        self.source_language = ""

    def set_vim(self, enabled: bool) -> "VimTextArea":
        self.vim_enabled = enabled
        self.mode = "normal" if enabled else "insert"
        return self

    def set_source_language(self, language: str) -> "VimTextArea":
        """Remember the solution language even when no syntax grammar loads."""
        self.source_language = language
        return self

    # ---------------------------------------------------------------- status

    @property
    def vim_status(self) -> str:
        if not self.vim_enabled:
            return ""
        if self.mode == "insert":
            return "-- INSERT -- · esc for normal"
        if self.mode == "visual":
            return "-- VISUAL --"
        # The clickable footer carries ZZ; this line stays about Vim state.
        # A pending operator still replaces the idle insert hint.
        return (self._count + self._pending) or "i insert"

    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        self._pending = ""
        self._count = ""
        screen = getattr(self, "screen", None)
        tick = getattr(screen, "_tick", None)
        if callable(tick):
            tick()
        refresh_bindings = getattr(screen, "refresh_bindings", None)
        if callable(refresh_bindings):
            refresh_bindings()

    # ------------------------------------------------------------------ keys

    async def _on_key(self, event: events.Key) -> None:
        if self.mode == "insert":
            if event.key == "enter":
                event.stop()
                event.prevent_default()
                start, end = self.selection
                self._replace_via_keyboard(self._indented_newline(), start, end)
                return
            if event.key == "escape":
                if not self.vim_enabled:
                    # plain editor: esc belongs to the screen ("Back") — and
                    # must not become TextArea's own focus-next.
                    event.prevent_default()
                    screen = getattr(self, "screen", None)
                    if screen is not None and hasattr(screen, "action_back"):
                        event.stop()
                        screen.action_back()
                    return
                event.stop()
                event.prevent_default()
                # vim steps the cursor back one column on leaving insert
                row, col = self.cursor_location
                if col > 0:
                    self.move_cursor((row, col - 1))
                self._set_mode("normal")
                return
            await super()._on_key(event)
            return

        # Normal/Visual is also the editor's global command layer. Route
        # these before Vim parsing; Insert returned above and types them.
        key = event.key
        char = event.character or ""
        event.stop()
        event.prevent_default()
        command = _GLOBAL_COMMANDS.get(char)
        screen = getattr(self, "screen", None)
        dispatch = getattr(screen, "action_global_command", None)
        if not self._pending and command is not None and callable(dispatch):
            dispatch(command)
            return

        if self._pending == "r":
            self._pending = ""
            if len(char) == 1 and char.isprintable():
                row, col = self.cursor_location
                line = self.document.get_line(row)
                if col < len(line):
                    self.replace(char, (row, col), (row, col + 1))
                    self.move_cursor((row, col))
            self._touch()
            return

        if self._pending == "Z":
            self._pending = ""
            if char in ("Z", "Q"):
                screen = getattr(self, "screen", None)
                if screen is not None and hasattr(screen, "action_back"):
                    screen.action_back()
                return
            self._touch()
            return

        if char.isdigit() and not (char == "0" and not self._count):
            self._count += char
            self._touch()
            return

        count = max(1, int(self._count or "1"))
        self._count = ""

        if self._pending in ("d", "y", "c"):
            op, self._pending = self._pending, ""
            self._operate(op, char, count)
            self._touch()
            return
        if self._pending == "g":
            self._pending = ""
            if char == "g":
                self.move_cursor((0, 0), select=self.mode == "visual")
            self._touch()
            return

        self._normal_key(key, char, count)
        self._touch()

    def _indented_newline(self) -> str:
        """Carry indentation forward; Python block headers add one level."""
        row, column = self.cursor_location
        prefix = self.document.get_line(row)[:column]
        indent = prefix[:len(prefix) - len(prefix.lstrip(" \t"))]
        if self.source_language in ("python", "python3") \
                and prefix.rstrip().endswith(":"):
            indent += ("\t" if self.indent_type == "tabs"
                       else " " * self.indent_width)
        return "\n" + indent

    def _touch(self) -> None:
        screen = getattr(self, "screen", None)
        tick = getattr(screen, "_tick", None)
        if callable(tick):
            tick()

    # ----------------------------------------------------------- normal keys

    def _normal_key(self, key: str, char: str, count: int) -> None:
        sel = self.mode == "visual"
        move = {"h": "action_cursor_left", "left": "action_cursor_left",
                "l": "action_cursor_right", "right": "action_cursor_right",
                "j": "action_cursor_down", "down": "action_cursor_down",
                "k": "action_cursor_up", "up": "action_cursor_up"}
        if key in move or char in move:
            name = move.get(key) or move.get(char)
            for _ in range(count):
                getattr(self, name)(sel)
            return
        if char in _WORD_MOTIONS:
            for _ in range(count):
                getattr(self, _WORD_MOTIONS[char])(sel)
            return
        if char == "0":
            self.action_cursor_line_start(sel)
            return
        if char in ("^", "_"):
            self.action_cursor_line_start(sel)
            row, _ = self.cursor_location
            line = self.document.get_line(row)
            self.move_cursor((row, len(line) - len(line.lstrip())), select=sel)
            return
        if char == "$":
            self.action_cursor_line_end(sel)
            return
        if char == "g":
            self._pending = "g"
            return
        if char == "G":
            if self._count_was(count):
                target = min(count, self.document.line_count) - 1
                self.move_cursor((target, 0), select=sel)
            else:
                self.move_cursor(self.document.end, select=sel)
            return

        if self.mode == "visual":
            if char in ("y", "d", "x", "c"):
                start, end = self._selection_range()
                self._register = (self.get_text_range(start, end), False)
                if char in ("d", "x", "c"):
                    self.delete(start, end)
                else:
                    self.move_cursor(start)
                self._set_mode("insert" if char == "c" else "normal")
            elif char == "v" or key == "escape":
                self._set_mode("normal")
            return

        if char == "i":
            self._set_mode("insert")
        elif char == "a":
            self.action_cursor_right(False)
            self._set_mode("insert")
        elif char == "I":
            self._normal_key("", "^", 1)
            self._set_mode("insert")
        elif char == "A":
            self.action_cursor_line_end(False)
            self._set_mode("insert")
        elif char == "o":
            self.action_cursor_line_end(False)
            self.insert("\n")
            self._set_mode("insert")
        elif char == "O":
            self.action_cursor_line_start(False)
            self.insert("\n")
            self.action_cursor_up(False)
            self._set_mode("insert")
        elif char == "s":
            self._delete_at_cursor(1)
            self._set_mode("insert")
        elif char == "x":
            self._delete_at_cursor(count)
        elif char in ("d", "y", "c"):
            self._pending = char
        elif char == "r":
            self._pending = "r"
        elif char == "Z":
            self._pending = "Z"
        elif char == "D":
            self._operate("d", "$", 1)
        elif char == "C":
            self._operate("c", "$", 1)
        elif char == "p":
            self._paste(after=True)
        elif char == "P":
            self._paste(after=False)
        elif char == "u":
            self.undo()
        elif char == "U":
            self.redo()
        elif char == "v":
            self._set_mode("visual")
        # anything else in normal mode: swallowed, like vim's bell

    @staticmethod
    def _count_was(count: int) -> bool:
        return count > 1

    # ------------------------------------------------------------- operators

    def _operate(self, op: str, motion: str, count: int) -> None:
        row, col = self.cursor_location
        if motion == op:                      # dd yy cc: whole lines
            last = min(row + count - 1, self.document.line_count - 1)
            text = "\n".join(self.document.get_line(r)
                             for r in range(row, last + 1))
            self._register = (text, True)
            if op != "y":
                end = ((last + 1, 0) if last + 1 < self.document.line_count
                       else (last, len(self.document.get_line(last))))
                start = (row, 0) if last + 1 < self.document.line_count else \
                    ((row - 1, len(self.document.get_line(row - 1)))
                     if row else (row, 0))
                self.delete(start, end)
                self.move_cursor((min(row, self.document.line_count - 1), 0))
            if op == "c":
                # cc leaves one fresh empty line where the lines were
                row = self.cursor_location[0]
                self.insert("\n", (row, 0))
                self.move_cursor((row, 0))
                self._set_mode("insert")
            return
        targets = {"w": _WORD_MOTIONS["w"], "e": _WORD_MOTIONS["e"],
                   "b": _WORD_MOTIONS["b"]}
        if motion == "$":
            line = self.document.get_line(row)
            start, end = (row, col), (row, len(line))
        elif motion in targets:
            before = self.cursor_location
            for _ in range(count):
                getattr(self, targets[motion])(False)
            end = self.cursor_location
            self.move_cursor(before)
            start = before
            if end < start:
                start, end = end, start
        else:
            return
        self._register = (self.get_text_range(start, end), False)
        if op != "y":
            self.delete(start, end)
        if op == "c":
            self._set_mode("insert")

    def _delete_at_cursor(self, count: int) -> None:
        row, col = self.cursor_location
        line = self.document.get_line(row)
        end = min(col + count, len(line))
        if end > col:
            self._register = (line[col:end], False)
            self.delete((row, col), (row, end))

    def _paste(self, after: bool) -> None:
        text, linewise = self._register
        if not text:
            return
        row, col = self.cursor_location
        if linewise:
            if after:
                line = self.document.get_line(row)
                self.insert("\n" + text, (row, len(line)))
                self.move_cursor((row + 1, 0))
            else:
                self.insert(text + "\n", (row, 0))
                self.move_cursor((row, 0))
        else:
            target = (row, col + 1) if after and col < len(
                self.document.get_line(row)) else (row, col)
            self.insert(text, target)

    def _selection_range(self):
        """The visual range, vim-style inclusive of the character under the
        cursor — Textual selections are exclusive at the end."""
        sel = self.selection
        start, end = sel.start, sel.end
        if start > end:
            start, end = end, start
        row, col = end
        if col < len(self.document.get_line(row)):
            end = (row, col + 1)
        return start, end
