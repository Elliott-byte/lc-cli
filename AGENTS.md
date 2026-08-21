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
  order-independent. The attempt mark is recorded in every branch.
- All mutations go through `@_atomic` (an RLock — judge/sync workers are
  threads) and `save()` writes tmp-then-rename.
- Coercion in `items_from_raw` is deliberate: the file is hand-editable, and
  `attempt_passed` uses `is True` because a hand-typed `"false"` is a truthy
  string.

### `lc/gitsync.py` — deck sync
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

### `lc/solvetimer.py` — the clock
- One `Timer` in `timer.json`: `armed` (created, never started), running
  (`started` set), paused (accum banked), `done` (an accepted submit ended
  it). Wall-clock epoch, not monotonic — three processes read the stamps.
- `begin(slug)` **arms**, it does not start — starting is a deliberate act
  (space in Vim → `lc timer start`). Re-opening the problem being solved
  leaves its clock alone; a different or done slug re-arms from zero.
- `stop_if(slug)` matches **slugs** — anything armed under a non-slug never
  stops, which is why `lc timer start` resolves ids/titles first.

### `lc/tui.py` — the browser
- `action_pick` (enter): **load the existing solution first, whatever its
  language**; only choose a language and `create()` when nothing exists.
  Re-picking would write a second file in the config default and repoint
  `.lc.json`, stranding the real work and aiming `r`/`s` at starter code.
- Editor-return heuristics in `action_pick`: snapshot **at the door, every
  visit** — both the store's solved flag and the deck's ✔ mark. Both mean
  "today", not "while I was in the editor"; acting on a standing value
  clocks out a re-practice session with a phantom "solved in …".
- `ReviewList._render_rows` restores the cursor **by slug, then old slug,
  then row index** — grading re-sorts the deck. `load_items(focus=…)` is a
  one-shot request consumed by that single render (a resize re-renders too
  and must not yank the cursor back).
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

### `lc/cli.py`
- `die(msg, hint)` prints and raises `typer.Exit(1)`. `main()` catches
  `AuthError`/`LeetCodeError` at top level so no traceback reaches the user.
- `_load_for_judging` resolves ref-or-cwd; an explicit `--lang` wins over
  `.lc.json`, and it never falls back to another language's file.
- `submit` mirrors the TUI: status update never downgrades a solve
  (`notac` only when not already `ac`), `record_submit` with curve iff
  autograde, timer `stop_if` on accept.
- `resolve_problem` short-circuits through the statement cache so re-reading
  works offline; `store.find` accepts id (zero-padded too), slug, or title.

### `lc/api.py` — LeetCode client
- Cookie auth; every mutating request echoes `x-csrftoken`.
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
- `strip_header` removes only a leading comment block that contains the
  problem URL — a user's own comment is never deleted.

### `lc/editors.py` — the Vim plugin (one file, installed by `lc setup vim`)
- Everything is buffer-local, attached by an autocmd when the buffer's
  directory has `.lc.json`. The statement pane is a terminal running
  `lc show` (README fallback), marked by `b:lc_statement_for`.
- The pane's terminal quirks are all commented in place (term_start options,
  QuitPre semantics — `:q` in the pane means "leave Vim", `q` closes it).
- The clock is drawn on the statusline from `timer.json` by a 1s ticker that
  holds its repaint while a prompt owns the screen; space starts/resumes via
  `lc timer start <slug>` and falls through to plain space once running.
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
- `docs/screenshots.py` regenerates the READMEs' SVG screenshots.

## Shipping a change

1. Code + regression test; prove the test fails on the old code.
2. Full suite green. If user-visible: update both READMEs and prepend a line
   to `docs/CHANGELOG.md`. If a documented decision changed shape: update
   its status in `docs/DECISIONS.md` (mark it superseded — never delete).
3. Bump the version in `pyproject.toml` **and** `lc/__init__.py`.
4. Narrative commit message; push (fetch first — the other machine also
   pushes); `uv tool install --force --reinstall .` to use it locally.
