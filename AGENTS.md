# AGENTS.md — a map for agents (and future maintainers)

lc is a LeetCode client for the terminal: a Typer CLI, a Textual TUI, a Vim
plugin, and a spaced-repetition deck that syncs through a git repo the user
owns. Read this before changing anything — most bugs fixed here were in code
that looked obviously correct from inside one file.

## Hard rules — even if you read nothing else

- `~/.lc/review.json` is **user data**: never regenerate, reset or overwrite
  the deck wholesale. The sync clone (`~/.lc/review-repo/`) and `cache.db`
  are the disposable ones.
- **Every commit bumps the version** in `pyproject.toml` **and**
  `lc/__init__.py`. Never reuse a version number — releases are tags pushed
  from the maintainer's machine and feed a brew tap.
- **Two machines push to this repo** — `git fetch` before pushing.
- Commit with the **repo-local identity**, never the global one (it carries
  a private work email; GitHub also rejects private addresses with GH007):
  `Eliot <105957288+Elliott-byte@users.noreply.github.com>`
- A bug fix ships with a regression test **proven to fail on the old code**.

## Doc rules — every change updates the docs that describe it, same commit

- **Changed a behaviour this file documents** (module map, invariants,
  recipes) → edit that entry here so AGENTS.md never lies.
- **User-visible change** → one prepended line in `docs/CHANGELOG.md`
  (into the current day's section, or start one), and both `README.md` and
  `README.zh-CN.md`.
- **Reversed or reshaped a documented design decision** → update its entry
  in `docs/DECISIONS.md`: mark the old one *superseded* (never delete it)
  and record what replaced it and why.
- **Learned a non-obvious invariant the hard way** (a bug that looked
  correct from inside one file) → add it to the module map here, phrased as
  the failure it prevents.
- **Changed the Vim plugin string** → reinstall with `lc setup vim --force`
  and say so in the commit message; users need the same step.
- **CLAUDE.md stays one line.** It is loaded into context every session;
  anything worth saying belongs here or in `docs/`.

## Working on it

```bash
uv venv && uv pip install -e '.[dev]'     # dev env
.venv/bin/python -m pytest -q             # the whole suite, one file: tests/test_lc.py
uv tool install --force --reinstall .     # install the real `lc` from this checkout
```

`uv` caches wheels by version — after changing code, reinstall picks up stale
builds unless the version was bumped (every commit bumps it, see below) or
`uv cache clean lc-cli` is run first.

## Conventions

- **Commit messages are narrative**: a one-line summary, then a paragraph or
  two explaining the failure mode and why this shape of fix. Look at
  `git log` and match it. Commits end with a `Co-Authored-By:` line when an
  agent wrote them.
- A rejected push usually means the other machine landed commits — rebase on
  top and **renumber your versions** during the conflict resolution (each
  side bumps independently; the pushed/tagged numbers win).
- `README.md` and `README.zh-CN.md` are kept in parity — a user-visible
  change documents itself in both.
- Proving a regression test: revert the fix in the working tree (the fix
  only, not the test), run the test, restore. Each commit passes its own
  suite in isolation, so the history bisects.
- Code style: comments and docstrings explain the *failure mode being
  prevented*, not what the line does; behaviour-shaped test names; plain
  `assert` messages that say what broke. Match the surrounding voice.

## Data files and who owns what

Everything lc owns lives under `$LC_HOME` (default `~/.lc`):

| File | Ownership |
| --- | --- |
| `review.json` | **User data. Never rebuilt, never overwritten wholesale.** The deck of record. |
| `config.json` | User settings. Unknown keys survive a round-trip (`Config.extra`). |
| `cookies.json` | Session cookies, written `0600` from the first byte. |
| `cache.db` | sqlite cache (problem index, statements, meta). Disposable. |
| `review-repo/` | Private clone used by sync. **Disposable** — every sync resets it to the remote. |
| `timer.json` | The one active solve clock. Shared by TUI, CLI and Vim, hence a file. |
| `<workspace>/<dir>/notes.md` | That problem's note cards — one `##` heading per card. User data; synced into the review repo as `notes/<slug>.md`. |

Solutions live in `~/leetcode/<0322-coin-change>/` with `solution.<ext>`,
`README.md` (rendered statement) and `.lc.json` (slug, lang, file). The
recorded file in `.lc.json` wins over a directory scan, so helper files are
never submitted by accident.

## Module map

### `lc/review.py` — the deck
- `ReviewItem`: `level`, `graded` (local date the level last changed), `due`,
  `updated` (UTC microsecond stamp — the merge-ordering key), `removed`
  (tombstone date), `attempted`/`attempt_passed` (today's ✔/✗ mark).
- `merge(local, remote) -> (merged, added, updated, removed)`: union; where
  both know a slug the higher `_edit_key` (mostly `updated`) wins. Removals
  travel as tombstones. **The counts describe the live deck view**: a revival
  counts as added, a tombstone hiding a live item as removed,
  tombstone-on-tombstone as nothing.
- `record_submit(slug, accepted, *, curve=None)`: no curve → mark the row
  only. With curve (autograde): **whoever grades first that day wins** — an
  earlier submit, a hand `+`/`-`/`0`, or `add()` itself (all stamp `graded`),
  so a submit can never stack on any of them, and day zero is
  order-independent. The first submitted verdict behind a visible attempt
  mark wins too: a retry cannot repaint an initial failure green. A hand grade
  clears that mark, so a later submit may begin a new one.
- All mutations go through `@_atomic` (an RLock — judge/sync workers are
  threads) and `save()` writes tmp-then-rename.
- Coercion in `items_from_raw` is deliberate: the file is hand-editable, and
  `attempt_passed` uses `is True` because a hand-typed `"false"` is a truthy
  string.

- Dates are clamped at `date.max`: a deck can hold a far-future `due`
  (hand-edited, or written by a newer lc and synced in), and `postpone`
  used to raise OverflowError straight out of the TUI's `z`.

### `lc/gitsync.py`### `lc/gitsync.py` — deck sync
- The clone is disposable; `~/.lc/review.json` is the deck of record.
  `fetch_remote_deck` hard-resets the clone to `origin/<branch>` first, so a
  divergence is a Python merge, never a git conflict.
- `ensure_clone`: **re-clones when the configured URL changes.** Re-pointing
  origin is not enough — fetch does not prune, so `origin/<branch>` still
  names the old repo's commit and the sync silently publishes nothing.
- `pull`/`_push_once` save when `merged != local`, **not** when the counters
  are non-zero — a tombstone for a never-seen slug counts as nothing but must
  still be written, or `status()` reports a phantom "1 change to push".
- `author(path) -> (name, email, source)`: `lc config author` override →
  git's own identity → `lc <lc@localhost>` as last resort. Commits pass it
  via `git -c`, never editing any git config.
- `_explain`/`_KNOWN` map git stderr to one sentence + hint. **Order
  matters**: GH007 (email privacy) must precede "failed to push some refs" —
  GH007's output *contains* that line, and the race rule's advice ("run it
  again") retries into the same wall.
- `status()` is computed from local files only — the strip redraws on every
  deck refresh and must never touch the network. "synced" means "agreed with
  the clone at last contact".
- A **real level transition** automatically calls the normal sync when a repo
  is configured: TUI `+`/`-`/`0`, CLI `review level`/`add --level`, and
  autograde submits. Compare before/after levels so a curve clamp or repeated
  command does not make a needless network request; sync failure never rolls
  back the already-durable local grade.

### `lc/solvetimer.py` — the clock
- One `Timer` in `timer.json`: `armed` (created, never started), running
  (`started` set), paused (accum banked), `done` (an accepted submit ended
  it). Wall-clock epoch, not monotonic — three processes read the stamps.
- `begin(slug)` **arms**, it does not start — starting is a deliberate act
  (space in Vim → `lc timer start`). Re-opening the problem being solved
  leaves its clock alone; a different or done slug re-arms from zero. A
  clock found *running* at begin() escaped the quit-pause (crash, killed
  terminal, pre-0.7.48 plugin): the phantom run is dropped, the banked
  accum kept — nobody was solving for that stretch.
- `stop_if(slug)` matches **slugs** — anything armed under a non-slug never
  stops, which is why `lc timer start` resolves ids/titles first.

### `lc/tui.py` — the browser
- `action_pick` (enter): **load the existing solution first, whatever its
  language**; only choose a language and `create()` when nothing exists.
  Re-picking would write a second file in the config default and repoint
  `.lc.json`, stranding the real work and aiming `r`/`s` at starter code.
- A due problem opened from Review resets that recorded solution to starter
  code **once per local day**. `.lc.json`'s `review_started` stamp prevents a
  same-day reopen from erasing the new attempt; Problems-tab/CLI opens and
  already-attempted rows remain ordinary reopens.
- Editor-return heuristics in `action_pick`: snapshot **at the door, every
  visit** — both the store's solved flag and the deck's ✔ mark. Both mean
  "today", not "while I was in the editor"; acting on a standing value
  clocks out a re-practice session with a phantom "solved in …".
- `ReviewList._render_rows` restores the cursor **by slug, then old slug,
  then row index** — grading re-sorts the deck. `load_items(focus=…)` is a
  one-shot request consumed by that single render (a resize re-renders too
  and must not yank the cursor back).
- Review's `Diff` column is explicit, not just an id tint. `_CHROME` includes
  all six columns and their padding; at the 40-column pane floor the title
  yields down to nine cells so difficulty never disappears behind scrolling.
- The status bar is per-tab: `_remember_status(pane, …)` stores each tab's
  durable line and only writes the bar when that tab is active;
  `_tab_activated` restores the arriving tab's line. Transient messages
  (judge verdicts, "syncing…") still write directly via `set_status`.
- `load_problem` sets `current = None` until the fetch lands — pick/run/
  submit must not act on the problem shown before. Corollary for tests: a
  row highlight with no cached statement clears `current`.
- `_row_highlighted` ignores events from the hidden table — a background
  rebuild re-highlights its cursor row.
- Workers are `@work(thread=True, exclusive=True)` per group; UI mutations
  from workers go through `call_from_thread`.
- `_day_rollover` (a 60s interval) re-dates everything day-shaped when a
  local or UTC midnight passes — due counts, mark tints, the daily pin.
  Anything new that renders "today" should be refreshed from there too.

### `lc/cli.py`
- `die(msg, hint)` prints and raises `typer.Exit(1)`. `main()` catches
  `AuthError`/`LeetCodeError` at top level so no traceback reaches the user.
- Browser login retains no cookie values in diagnostics: a Safari
  `PermissionError` becomes a Full Disk Access warning, and `p` at the retry
  prompt falls through to manual cookie entry. Do not swallow the error into
  another identical Enter prompt — OS permission cannot change by retrying.
- `_load_for_judging` resolves ref-or-cwd; an explicit `--lang` wins over
  `.lc.json`, and it never falls back to another language's file.
- `submit` mirrors the TUI: status update never downgrades a solve
  (`notac` only when not already `ac`), `record_submit` with curve iff
  autograde, timer `stop_if` on accept. If autograde actually changes the
  level, it synchronises the configured review repo after recording locally.
- `resolve_problem` short-circuits through the statement cache so re-reading
  works offline; `store.find` accepts id (zero-padded too), slug, or title.

### `lc/api.py` — LeetCode client
- Cookie auth; every mutating request echoes `x-csrftoken`.
- `whoami` can pass on `LEETCODE_SESSION` while judge POSTs reject a stale
  CSRF token as HTTP 499 with an HTML 403 page. `_judge_post` then loads the
  problem page once, removes **all** old/domainless `csrftoken` cookies, adopts
  LeetCode's fresh domain cookie for both header and cookie, and retries once.
- `_poll` treats network drops, 429 and 5xx as "keep asking until the
  deadline" — the submission already went in; only 4xx or judge FAILURE are
  terminal. Runs get 90s, submits 180s.
- `_to_result` flattens the judge's per-verdict payload shapes; for runs,
  "accepted" is computed from `correct_answer`/`compare_result`, not the
  status (LeetCode calls any run that executed "Accepted").
- `LC_DEBUG=1` makes the CLI print the raw judge payload.

### `lc/render.py` — statement HTML → terminal / Markdown
- Hand-rolled parser for LeetCode's HTML subset. `<sup>`/`<sub>` map to real
  Unicode; `<pre>` becomes a Panel with inline styling deliberately dropped.
- **Style spans, not base styles, for anything that can wrap**: a folded line
  is padded to the column edge in the Text's base style, which underlines
  (and OSC 8-links) the blank cells after the address.
- The url line is an OSC 8 hyperlink plus a Textual `@click` meta (the TUI
  and Vim's terminal never deliver the escape). Shown scheme-less so most
  slugs fit one line; the column uses `overflow="fold"`, never ellipsis —
  half a URL can't be clicked or copied.
- `to_markdown` re-emits parsed spans as `` ` ``/`**`/`*` for the workspace
  README; emphasis is trimmed at whitespace edges of whole runs because
  Markdown ignores padded delimiters.

### `lc/workspace.py`
- `create` refreshes `README.md` + `.lc.json` every time but never touches an
  existing solution file unless `overwrite`. Python snippets keep their
  trailing indentation (`rstrip("\n")` only) — stripping it breaks compiles.
- `starter_code` is the single constructor for the exact snippet text — new
  solutions have no generated title/URL header. The built-in editor's reset
  and `create(overwrite=True)` must use the same path, or reset can silently
  produce a different file from a fresh pick.
- `restart_review` keeps the existing recorded language/file and stamps the
  local day in `.lc.json`; never infer the reset from the deck alone, or a
  second editor visit that day destroys the attempt in progress.
- `strip_header` removes only a leading comment block that contains the
  problem URL. This is compatibility for files written by older lc versions;
  a user's own comment is never deleted.

- The judge worker's boundary is **guarded twice**: unexpected exceptions
  from the judge, and from the bookkeeping that files a verdict away, are
  reported in full and never allowed to kill the session — the app dying
  mid-solve takes the unsaved buffer with it. `api.py` wraps what it knows
  into `LeetCodeError`; this is for what it does not. `_record_submit` only
  records; `_judge_worker` owns the one result display because its `cases`
  input does not exist at the bookkeeping boundary.

### `lc/notes.py` — note cards
- `open_card` **creates the directory** — it can be gone by the time a note
  is written (a `git clean`, a moved workspace, a problem deleted while the
  editor is open), and in the TUI that exception killed the app with the
  buffer on screen. Callers still guard OSError: a `notes.md` that is a
  *directory* rightly refuses.
- **Read note files through `notes.read`, never `read_text`.** They sit in
  the user's workspace, where a stray binary or a bad encoding is possible;
  one undecodable file used to raise straight out of `_merge_notes` and
  abort the whole deck sync, losing every *other* problem's notes with it.
  `read` returns "" instead, and the unreadable file is left untouched
  rather than overwritten.
- One markdown file per problem (`notes.md`, in the problem's workspace
  directory), one `##` heading per card. `open_card` stamps a heading and
  **reuses a still-blank newest card**, so two submits before one written
  word do not litter the file. Prose above the first heading is not a card.
- Written by `lc note` / Vim's `\n` (split under the solution — the
  submitted code stays visible); read by the TUI's `n` (cards, newest
  first). The workspace's own git versions it, and the deck sync carries
  it too: `notes/<slug>.md` in the review repo, merged as a card **union**
  (`merge_texts` — deterministic, idempotent, **commutative**, which is what
  makes two machines converge; sort on the whole card, never the title
  alone: same-minute cards would otherwise order by argument position and
  the repo would ping-pong a reordering commit at every sync). Nothing is ever deleted by the sync; a card
  for a problem the receiving machine never picked waits in the clone until
  the index can name its directory.

### `lc/editscreen.py` — the built-in edit screen
- Pushed by `action_pick` when the editor is `builtin` (or nothing resolves).
  Statement left, `TextArea.code_editor` right, judge via the app's own
  `_judge` (results are toasts, so they land on any screen), clock on
  `#edit-status` (its own id — `set_status` writes `#status-bar` and must
  no-op here, or the 1s tick would erase judge text). First edit starts an
  armed clock; esc saves and pauses it, like quitting Vim.
- **Saving can fail** (read-only file, full disk): `_save` returns False
  and toasts rather than raising — esc then stays on the screen instead of
  leaving with the buffer unwritten and unrecoverable, and run/submit do
  not judge code the buffer never reached.
- Run/Submit push an opaque `JudgeScreen` before starting the worker, so the
  live controls cannot enqueue duplicate requests. Every worker exit path
  must call `_judge_finished` before its toast/result; `_judge()` returns
  False for preflight failures so `_start_judge` removes the cover instead
  of trapping the user behind a wait that never began.
- `X Reset code` is Normal/Visual-only and confirms before replacing the live
  buffer. It uses one TextArea history batch rather than `load_text`, so `u`
  restores the previous answer; the disk file changes only on a later save.
- A trailing `\n` becomes an extra empty sentinel row in TextArea. Initial and
  reset cursor placement must step over that row without deleting the newline,
  or every edit opens one blank line below the actual starter body.
- Clock keys: ctrl+b pauses *running* clocks behind the cover and starts
  stopped ones (never a no-op key; covering a stopped clock would hide the
  statement with nothing counting), ctrl+g resets. `space` cannot be the
  pause here — it types.
- The footer swaps its honest exit by mode: `esc Back` in plain editing,
  clickable `ZZ Back` with Vim keys. Textual cannot bind a two-key sequence,
  and Footer clicks simulate one key, so ZZ uses a priority synthetic F24
  action with `key_display="ZZ"`; binding a real `Z` would steal the first
  half from `VimTextArea`. `check_action` ensures only one exit is shown.
- Command bindings also swap by mode: Vim Normal/Visual shows and accepts
  `R S N B T X`; Insert/plain shows the ctrl chords. The uppercase keys are
  non-conflicting with the supported Vim subset and are dispatched by
  `VimTextArea` only after its Insert branch and only with no pending Vim
  operator (`rR` must still replace with uppercase R). Textual does not
  reliably route uppercase screen bindings and omits them from Footer, so
  F18-F23 provide clickable display aliases. The physical ctrl bindings stay
  enabled and hidden in every mode, while F13-F17 are their Insert/plain
  display aliases; disabling the ctrl actions to hide them also disables the
  old keys. Mode changes must call `refresh_bindings()` or the footer lies
  until refocus.
- **While it is on top, the app's bindings stand down** via
  `LeetCodeTUI.check_action` — the priority `tab` binding would otherwise
  reach through the editor and flip the hidden Problems/Review tabs when
  the code needed an indent.
- The statement URL uses `screen.open_web()`, not `app.open_web()`: app
  actions are disabled while the editor is on top, so pointing the link at
  the app makes it look clickable but do nothing. Do not re-enable app
  `open_web` here, or the `o` key leaks through into the code area.
- The question pane cannot depend on the mouse wheel: some WSL terminal paths
  do not forward it. With Vim keys on, `ctrl+w h` / `ctrl+w l` move between
  code and question; both panes must own the prefix so keyboard focus can make
  the round trip, and the question's native arrows and Page Up/Down scroll it.
- A newly opened edit screen resets the question to the top both on mount and
  after the first refresh. Focus/layout can settle late on some terminals and
  otherwise override the initial scroll position with the bottom of the pane.

### `lc/vimtext.py` — the built-in editor's Vim layer
- A deliberate subset (docstring lists it), not an emulator; one unnamed
  register, counts on simple motions. `set_vim(False)` is the plain editor:
  permanent insert mode, esc → screen Back (a bare TextArea would eat esc
  as its own focus-next). Vim-inclusive visual ranges: Textual selections
  are end-exclusive, so y/d/c extend the end by one column.
- Textual's code TextArea inserts a bare newline, so `VimTextArea` supplies
  indentation in both Vim insert and plain modes: preserve the current
  leading whitespace, and add one level after a Python line ending in `:`.
  `source_language` is separate from syntax grammar because highlighting may
  fall back to plain text while editing behaviour must remain language-aware.
- Grammar sdists are wheel-first upstreams whose source builds are broken
  (missing scanner objects/headers) — the brew formula ships
  tree-sitter-python as a **platform wheel**; never add a grammar as an
  sdist resource without building it first.
- Syntax needs the grammar *installed*, not just known —
  `available_languages` lists names textual recognises, so the edit screen
  assigns `language` in a try/except and falls back to plain text (found
  when a Go file crashed compose).

### `lc/editors.py` — the Vim plugin (one file, installed by `lc setup vim`)
- Everything is buffer-local, attached by an autocmd when the buffer's
  directory has `.lc.json`. The statement pane is a terminal running
  `lc show` (README fallback), marked by `b:lc_statement_for`.
- The pane's terminal quirks are all commented in place (term_start options,
  QuitPre semantics — `:q` in the pane means "leave Vim", `q` closes it).
  Native `ZZ` cannot own the pane because it tries to write the read-only
  terminal; map `ZZ` in both Normal and Terminal mode to `LcQuitAll`, so the
  same save-and-exit works after the cursor moves left.
- **Reset the statement view only after the terminal job exits.** `lc show`
  writes asynchronously, so an earlier `gg` looks right inside the open
  function but the output cursor subsequently drags a long question back to
  its final page. Vim and Neovim have separate exit callbacks; both wait 50ms
  before the final `gg0zt` because Vim performs one more terminal redraw after
  a zero-delay callback and otherwise drags the view straight back down.
- `LcJudge` snapshots `v:shell_error` immediately after its shell command and
  waits for Enter when `lc test` fails. Without that explicit acknowledgement,
  some terminal/Vim combinations redraw the editor over the case details.
- The clock is drawn on the solution's statusline (the pane shows only
  `q close` — both statuslines share a screen row, so anything else doubles)
  from `timer.json` by a 1s ticker that holds its repaint while a prompt
  owns the screen; space starts/resumes via `lc timer start <slug>` and
  falls through to plain space once running.
- Quitting Vim pauses this session's running clock — but **commands run
  inside an autocmd fire no further autocmds**, so the `VimLeavePre` hook
  never sees an exit performed by the plugin's own `qall!` (QuitPre's
  pane logic, `\q`, the last-window close). Every self-initiated exit must
  call `s:LcTimerAutoPause()` by hand; it is idempotent, so firing it twice
  on a plain `:q` costs nothing.
- After changing the plugin string, `lc setup vim --force` must be re-run —
  the installed copy is compared byte-for-byte and refuses to overwrite what
  differs.

### `lc/store.py`, `lc/config.py`, `lc/browser.py`, `lc/langs.py`, `lc/fx.py`
- `store`: sqlite; LIKE needles escaped (`_escape_like` + `ESCAPE '\'`);
  statements expire after 7 days; `meta` holds sync stamps and the daily.
  `replace_index` keeps an existing ✔/✗ status wherever the fresh index has
  none — an unauthenticated fetch (expired session) knows nothing about
  what you solved, and LeetCode has no "unsolve".
- `config`: dataclass; unknown json keys preserved through `extra`; the
  boolean properties (`autograde`, `timer_on`) deliberately use `is True` /
  `is not False` so hand-edited strings fail safe in each field's direction.
- `browser`: WSL-aware URL opening (`wslview`/`explorer.exe`) and Windows
  Firefox cookie reading (snapshot db + WAL sidecars before sqlite-reading).
- `langs`: registry + aliases; `choose()` walks default → favourites →
  whatever the problem offers.

## Where to look when…

| Symptom | Start at |
| --- | --- |
| sync error message wrong or unhelpful | `gitsync._KNOWN` / `_explain` — ordering is by specificity |
| "N changes to push" that pushing never clears | the save guards in `gitsync.pull`/`_push_once` (`merged != local`) and `status()` |
| deck cursor lands on the wrong problem | `ReviewList._render_rows` restore chain; `load_items(focus=…)` is one-shot |
| wrong file or language opened / judged | `workspace.load` + `.lc.json`; the TUI's reopen-first `action_pick` |
| a level moved when it should not have (or refused to) | `review.record_submit` — the graded-today guard and its docstring |
| clock stops, starts or re-arms by itself | `solvetimer.begin`/`stop_if` + the door snapshots in `tui.action_pick` |
| statement renders oddly / styling bleeds into padding | `render._StatementParser`; use spans, never base styles, where text wraps |
| status bar shows the wrong tab's line | the `_remember_status` / `set_status` split in `lc/tui.py` |
| judge verdict displayed wrongly | `api._to_result`; rerun with `LC_DEBUG=1` to see the raw payload |
| Vim keys do nothing | mappings are buffer-local and need `.lc.json` in the dir; a changed plugin needs `lc setup vim --force` |

## Common tasks — the full checklist each one implies

**Add a config setting** — field on `Config` (lc/config.py; hand-edited-json
tolerance goes in a property, `is True` / `is not False` chosen per the safe
direction), row in `lc config show`, a `lc config <name>` command, and — if a
user would toggle it mid-session — `FIELDS`/`TOGGLES` on the TUI's
`ConfigScreen`. Unknown json keys already survive via `Config.extra`.

**Add a TUI key** — widget-level `BINDINGS` when it must only fire (and show
in the footer) while that pane has focus; app-level otherwise. The footer
carries only the solving loop; everything else is `show=False` and lives in
`?`. Bind both halves of a shifted pair (`plus,equals_sign`) or the shifted
press silently does nothing.

**Change the Vim plugin** — it is one string in `lc/editors.py`; after
installing, `lc setup vim --force` (the installed copy is compared
byte-for-byte and refuses to overwrite what differs). Terminal-pane quirks
are commented in place — read them before touching pane logic.

**Touch sync** — test against local bare repos (`_bare_repo`), one `LC_HOME`
per simulated machine, purging `lc.*` from `sys.modules` between switches.
Remember `status()` must stay network-free.

**Add a language** — one `Language(...)` row in `lc/langs.py`, plus an alias
if people type something shorter. Everything else follows from the registry.

## Testing

- One file: `tests/test_lc.py`. `conftest.py` only puts the repo on
  `sys.path`. One test: `.venv/bin/python -m pytest -q -k "<part of name>"`.
- House patterns: `monkeypatch.setenv("LC_HOME", tmp_path)` **then purge**
  `sys.modules` of `lc.*` and re-import; bare git remotes via `_bare_repo`;
  the network mocked with `httpx.MockTransport` (`judge_client`); TUI tests
  drive the real app with `app.run_test()` + `pilot`.
- TUI tests that reach `action_pick`'s editor branch: set `"editor": "true"`
  in config.json, monkeypatch `tui.workspace.open_in_editor` and
  `LeetCodeTUI.suspend` (nullcontext), and `store.put_statement(...)` the
  problem so row-highlight refreshes don't clear `app.current` mid-test.
- Test names are sentences about behaviour, docstrings explain the failure
  mode being pinned. No classes, no fixtures beyond tmp_path/monkeypatch.

## Further reading

- `docs/DECISIONS.md` — the *why* behind these shapes, with the alternatives
  rejected and which decisions superseded which. Read it before proposing to
  change a behaviour this file states as an invariant; when a decision does
  change, mark it superseded there rather than deleting it.
- `docs/CHANGELOG.md` — the development log: what changed per version and
  what it used to do. Prepend a line per shipped change; `git log` carries
  the full narrative per commit.
- `docs/screenshots.py` regenerates the READMEs' seven SVG screenshots,
  including the built-in editor (`edit.svg`) and the note cards
  (`notes.svg`). Two traps in there: the code shown must belong to the
  problem whose statement is beside it (a mismatch documents a bug that
  does not exist), and leaving the edit screen needs `ZZ` — `esc` belongs
  to the Vim layer, and pressing it wrote the same shot twice.
  Its workspace and editor must stay pinned inside the temporary `LC_HOME`;
  ambient `~/leetcode` or `$EDITOR` would touch user data or hang generation.

## Shipping a change

1. Code + regression test; prove the test fails on the old code.
2. Full suite green. If user-visible: update both READMEs and prepend a line
   to `docs/CHANGELOG.md`. If a documented decision changed shape: update
   its status in `docs/DECISIONS.md` (mark it superseded — never delete).
3. Bump the version in `pyproject.toml` **and** `lc/__init__.py`.
4. Narrative commit message; push (fetch first — the other machine also
   pushes); `uv tool install --force --reinstall .` to use it locally.
