# Changelog

The development log, newest first — what changed and, where it matters, what
it *used to do*. Commit messages carry the full reasoning (`git log` is
narrative in this repo); this file is the condensed view an agent or a human
can skim to learn how the current behaviour came to be. In recent history
every commit bumps the version (early tags grouped a few commits); tags
(`vX.Y.Z`) are the releases the brew tap ships.

**Maintenance rule:** prepend a line per shipped user-visible change, into
the top section for the current day — or start a new one. Say what changed
and, when behaviour reversed, what it used to do.

## 0.7.78 — 2026-08-26 · clean recall attempts

- The first time a due problem is opened from Review each day, its previous
  answer is now replaced with starter code in the language already selected.
  Reopening it later that day preserves the new attempt; Problems-tab and
  `lc edit` opens still preserve existing files as before.

## 0.7.77 — 2026-08-25 · Vim questions begin at the beginning

- A newly opened Vim or Neovim statement pane now starts at the question
  heading. Its terminal previously followed `lc show`'s output cursor and
  settled on the final page; lc now resets the view after that job exits.

## 0.7.76 — 2026-08-25 · the first attempt stands

- The Review mark now keeps the day's first submitted verdict. A failed first
  attempt remains red after a successful retry instead of being repainted
  green; grading still clears the mark, and a new day starts fresh.

## 0.7.75 — 2026-08-25 · visible beginnings and failures

- The built-in editor now explicitly resets the question pane to the top when
  it opens. Some terminal/layout paths could previously settle with a long
  statement already scrolled to its bottom.
- A failed Vim `\t` test now leaves its case details visible until Enter is
  pressed instead of immediately redrawing the edit page over the result.

## 0.7.74 — 2026-08-25 · solutions start with the solution

- New solution files and the built-in editor's explicit Reset now contain
  only LeetCode's starter code, without a generated title/URL comment above
  it. Existing solution files remain untouched, and legacy headers still
  strip safely before judging.

## 0.7.73 — 2026-08-25 · the question scrolls without a mouse

- With Vim keys on, `ctrl+w h` now moves from code to the built-in editor's
  question pane, where arrows and Page Up/Down scroll even when a terminal
  does not forward mouse-wheel events (as can happen under WSL). `ctrl+w l`
  returns to the code.

## 0.7.72 — 2026-08-23 · ZZ leaves from either Vim pane

- `ZZ` in the Vim statement pane now saves the real solution and exits just
  as it does from the solution pane. The read-only terminal previously tried
  to handle native `ZZ` itself, so moving left to read made the exit fail.

## 0.7.71 — 2026-08-23 · the cursor starts on the code

- Opening or resetting a solution in the built-in editor now puts the cursor
  at the end of the last real line. TextArea used to expose the file's normal
  final newline as one extra blank row and place the cursor there.

## 0.7.70 — 2026-08-22 · new lines keep their indentation

- Vim Normal/Visual mode now has a clickable `X Reset code` command. It asks
  for confirmation, restores the current language's LeetCode starter code as
  one buffer edit, and remains recoverable with `u` before saving.
- The built-in editor now carries the current indentation onto a new line
  and adds one level after a Python block header ending in `:`. Previously
  Enter always returned to column zero, leaving every line to be tabbed by
  hand in both Vim insert mode and the plain editor.
- Vim Normal/Visual mode now exposes `R S N B T` for Run, Submit, Note,
  Pause and Reset, with the same clickable labels in the footer. Insert and
  plain modes retain the ctrl chords so uppercase code cannot fire commands.
- Run and Submit now cover the built-in editor with an in-flight screen until
  the verdict or error returns. The live footer used to remain underneath,
  making impatient clicks or keypresses start the judge repeatedly.

## 0.7.69 — 2026-08-22 · ZZ joins the editor footer

- With Vim keys on, the built-in editor now shows a clickable `ZZ Back`
  beside Run and the other footer commands. It used to leave the way out in
  the status line because ZZ is a two-key Vim command; the footer now has a
  separate mouse-safe action that does not turn one keyboard Z into Back.

## 0.7.68 — 2026-08-22 · the editor URL opens

- The built-in editor's statement URL opens in the browser again. Its click
  action was aimed at the main app, whose bindings intentionally stand down
  while the editor is on top, so the link looked live but did nothing.

## 0.7.67 — 2026-08-22 · the footer stops promising a dead esc

- With Vim keys on, the editor's footer advertised `esc Back` while the
  Vim layer owned esc — pressing the key a UI promises and getting nothing
  read as "the shortcuts are broken". The footer drops the row (the status
  line already names `ZZ back`); with Vim keys off, `esc Back` stays and
  works. Also fixed the flaky notes test: it raced the startup index sync.

## 0.7.66 — 2026-08-22 · the READMEs catch up

- Both READMEs gained **Solving** and **Notes** sections, each with a new
  screenshot: the built-in editor mid-solve (statement, code, Vim status,
  running clock) and the note cards. Solving had been a paragraph inside
  "The browser" despite being the biggest recent feature, and the tail
  section named "Notes" collided with it — it is "Odds and ends" now.

## 0.7.65 — 2026-08-22 · the judge cannot take the session

- An unexpected error inside a judge run — or inside the bookkeeping that
  records its verdict — is now reported and survived instead of killing
  the app mid-solve (which took the unsaved buffer with it). Known
  network, HTTP and JSON failures were already handled; this covers what
  is not.

## 0.7.64 — 2026-08-22 · a date at the end of time

- `z` (postpone) no longer crashes on a problem whose next review is a
  far-future date — one hand-edited into `review.json`, or written by a
  newer lc and synced in. Dates are clamped at 9999-12-31 throughout the
  deck's write path.

## 0.7.63 — 2026-08-22 · notes that survive a moved workspace

- Writing a note no longer crashes when the problem's directory has since
  been removed (a `git clean`, a moved workspace, a directory deleted while
  the editor is open) — it is recreated. In the built-in editor that
  exception took the app down with the unsaved buffer on screen.
- `lc note` explains a notes file it cannot write instead of showing a
  traceback.

## 0.7.62 — 2026-08-22 · notes that actually converge

- Two machines that both wrote a note in the same minute never agreed on
  the merged file: cards sharing a heading were ordered by which side
  merged first, so each machine rewrote the other's order and every sync
  committed a reordering diff, forever. The merge sorts on the whole card
  now — verified commutative and idempotent over randomised card sets.

## 0.7.61 — 2026-08-22 · an audit's findings

- One unreadable `notes.md` anywhere in the workspace no longer aborts the
  whole deck sync (it raised out of the notes merge, taking every other
  problem's notes and the deck push with it). Such a file is skipped and
  left untouched.
- The built-in editor no longer crashes when it cannot save — a read-only
  file used to raise out of `esc`, taking the unsaved buffer with it. It
  now reports and stays put, and run/submit refuse to judge code that
  never reached disk.

## 0.7.60 — 2026-08-22 · the built-in editor's clock keys

- `ctrl+b` on a clock that is merely stopped now starts it again (it did
  nothing, so a pause taken any way but the cover was a dead end), and
  `ctrl+g` resets the clock to 00:00 — the built-in answer to Vim's `\Z`,
  which had no equivalent here at all. The status line names `^b resumes`
  while paused.

## 0.7.58 — 2026-08-22 · the built-in editor grows up

- Syntax highlighting: Python in the code pane (the tree-sitter grammar
  ships as a dependency; other languages fall back to plain text instead
  of crashing — a Go file found that out). The markdown grammar was cut
  in 0.7.59: the notes split never set a language, and its sdist does not
  build from source.
- A Vim subset, on by default: modes, hjkl/w/b/e/0/^/$/gg/G with counts,
  i a I A o O s x r, dd yy cc dw cw D C p P, visual, u undo, U redo
  (ctrl+r runs the samples), ZZ leaves. esc never exits the screen in vim
  mode; `lc config vimkeys off` restores the plain editor.

## 0.7.57 — 2026-08-22 · say builtin when it is

- `lc config show` names the builtin editor instead of showing the editor
  as unset (its display went through resolve_editor, which rightly refuses
  to treat "builtin" as a command).

## 0.7.56 — 2026-08-22 · the built-in edit screen

- `lc config editor builtin` (or no editor at all): `enter` now opens an
  edit screen inside the TUI — statement left, code right, `ctrl+r` run,
  `ctrl+s` submit, `ctrl+n` note split, `ctrl+b` pause cover, `esc` saves
  and returns (pausing the clock, like quitting Vim). Typing the first
  character starts an armed clock. The external-editor flow is unchanged.

## 0.7.55 — 2026-08-22 · notes travel

- `lc review sync` now carries note cards between machines, next to the
  deck (`notes/<slug>.md` in the review repo). Card union: both sides'
  cards survive, in timestamp order; the sync never deletes one. A card
  for a problem the other machine never picked waits in the clone until
  the index can name its directory.
- The deck merge inside pull/push now runs under the deck lock, so a grade
  pressed in the TUI at the exact moment a sync lands can no longer be
  lost between the merge's read and its write.

## 0.7.53 — 2026-08-22 · \n toggles

- `\n` is a toggle like `\p`: pressed again it saves the card and closes
  the split (it used to stack a new split on every press).

## 0.7.52 — 2026-08-22 · note cards

- Every attempt can leave a note: `lc note` (or `\n` in Vim, which opens
  `notes.md` in a split under the solution so the submitted code stays on
  screen) stamps a card heading — date · verdict · language — and you write
  under it. `n` in the TUI's list shows that problem's cards, newest first.
  Plain markdown in the problem's directory; your workspace git owns it.

## 0.7.49–0.7.50 — 2026-08-22 · stale clocks, deduped chrome

- `\z` pauses, full stop — as a toggle it silently *started* a stopped
  clock, which read as "pause is broken". A stopped clock now answers
  "space starts it"; declining `\Z`'s confirm (Enter = No) says "not
  reset" instead of nothing.
- The clock and the key hints show once, on the solution's statusline — the
  statement pane's carries only `q close` (both statuslines share a screen
  row, so everything on both was everything twice).

- A clock still running when a problem is opened is treated as escaped (a
  crash or killed terminal skipped the quit-pause): the phantom stretch is
  dropped, the banked time kept. Found as a 13-hour overnight "solve" that
  also left space inert.
- New solution files get a one-line header (`# [322] Coin Change ·
  leetcode.com/problems/coin-change/`) instead of three — the statement
  pane already shows the difficulty and acceptance right beside it.
  Existing files keep their old headers; both kinds strip before submit.

## 0.7.48 — 2026-08-21 · the clock stays in the editor

- Quitting Vim pauses a running solve clock (it used to keep counting while
  you browsed the TUI or the shell); space resumes it on the next visit.
  Quitting a Vim session that never edited that problem touches nothing.

## 0.7.38–0.7.47 — 2026-08-21 · counting, polish, docs

- **0.7.47** A TUI left open overnight rolls the day over by itself: due
  counts, yesterday's ✔/✗ tints and the daily pin refresh on a one-minute
  check instead of waiting for the next keypress.
- **0.7.46** An index refresh with an expired session keeps the ✔/✗ marks
  it cannot see. An unauthenticated fetch returns no statuses, and
  replacing the index with it used to blank every mark until the next
  signed-in sync — LeetCode has no "unsolve", so the old mark stands
  wherever the fresh index says nothing.
- **0.7.45** The docs became rules: AGENTS.md gained "Doc rules" (every
  change names the docs it must update, same commit), a symptom→file
  routing table, and self-maintenance hooks in the shipping checklist.
- **0.7.44** docs/: this changelog and DECISIONS.md.
- **0.7.43** CLAUDE.md reduced to one redirect line (it loads into agent
  context every session); AGENTS.md gained the hard rules and task recipes.
- **0.7.42** AGENTS.md: the module map and invariants written down.
- **0.7.41** Timer fixes: the editor-return check now snapshots the deck's
  ✔ mark at the door (a morning's solve no longer clocks out evening
  practice with a phantom "solved in …"), and `lc timer start` resolves
  ids/titles like every other command (a literal "322" armed a clock no
  submit's slug could ever stop).
- **0.7.40** A folded statement URL no longer underlines (or OSC 8-links)
  the padding after it — style moved from the Text's base style to a span.
- **0.7.39** The bottom status bar describes the tab on screen: the Review
  tab counts its deck (`69 on the deck · 3 due`, narrowing under `/`), each
  tab's line is restored on switch, and a background refresh of the hidden
  tab can no longer steal the bar.
- **0.7.38** GH007 (GitHub email-privacy rejection) is recognised for what
  it is. Its output ends with the same "failed to push some refs" line as a
  lost push race, so the classifier used to advise "run the sync again" —
  a retry into the same wall. Non-retryable, with a noreply-address hint.

## 0.7.28–0.7.37 — 2026-08-20 · the solve clock

- **0.7.37** Space starts the clock from anywhere (`lc timer start <slug>`
  can conjure one, so a bare `vim solution.py` session counts); the
  became-solved snapshot is taken at the door on *every* visit.
- **0.7.36** Opening a problem **arms** the clock at 00:00; starting it is
  deliberate (space). Walking in is not a start.
- **0.7.33–0.7.35** `\Z` resets for a fresh attempt (asks first); the clock
  is drawn in text, not emoji (width disagreements tear the statusline);
  repaint held while a prompt owns the screen.
- **0.7.30–0.7.32** The clock moved to where the solving happens: Vim's
  statusline shows it, `\z` pauses behind a cover tab, the TUI keeps only
  the bookkeeping (arm on open, stop on accepted submit). `lc timer`
  (`start`/`pause`/`resume`/`reset`) is the shared control surface.
- **0.7.29** Settings screen gained the autograde and timer toggles.
- **0.7.28** First version of the clock, TUI-side (superseded within the
  day by 0.7.30–0.7.32).

## 0.7.20–0.7.27 — 2026-08-20 · sync correctness, autograde, identity

- **0.7.27** Deck commits default to **your own git identity**, no
  configuration needed; `lc config author` still overrides; lc's own name
  (`lc <lc@localhost>`) remains the fallback where git has none.
- **0.7.26** `enter` on a started problem reopens the existing file in the
  language it was started in. It used to re-pick in the config default:
  a Go workspace grew a `solution.py`, `.lc.json` was repointed, and
  `r`/`s` judged fresh starter code while the real work sat stranded.
- **0.7.25** A pull that removes problems says so (`… 2 removed`).
  merge() counts what the live deck view did: revival = added, tombstone
  hiding a live problem = removed, tombstone-on-tombstone = nothing.
- **0.7.24** **A hand grade stands against later submits.** The autograde
  guard now keys on `graded` alone: whoever grades first that day wins —
  an earlier submit, a hand `+`/`-`/`0`, or the add itself. This reversed
  0.7.22's guard, which a hand grade slipped past (submit, demote by hand,
  re-submit → demotion silently re-promoted), and made day zero
  order-independent (an added problem stays level 1 until tomorrow).
- **0.7.23** After a submit, the Review tab's cursor sits on the problem
  just submitted, so `+`/`-` grade what was actually re-solved.
- **0.7.22** Autograde, opt-in (`lc config autograde on`): accepted climbs
  a level, a failure drops one, once a day. Off by default — the judge
  knows whether the code passed, not whether you remembered how.
- **0.7.21** `lc config author`: deck commits attributable to you
  (previously hardcoded `lc <lc@localhost>`; superseded as the *default*
  by 0.7.27, kept as the override).
- **0.7.20** Two silent sync bugs: re-pointing `lc config repo` at a new
  repository published nothing (fetch does not prune, so the sync reset
  onto the *old* repo's ref and reported success — now re-clones), and a
  tombstone for a never-seen slug was dropped by the save guard while
  status() counted it forever ("1 change to push" that pushing never
  cleared — now saves whenever the merge changed anything).

## 0.7.11–0.7.19 — 2026-08-17→19 · review keys, URL, panes

- **0.7.16–0.7.19** `esc`/`q` close the `?` key list instead of quitting;
  the pane divider is draggable (24-column floor per side); the statement
  URL opens on double-click in Vim and is shown scheme-less so it fits.
- **0.7.14–0.7.15** The statement URL became a real hyperlink (OSC 8) and
  clickable in the TUI (Textual `@click` meta — each channel drops one of
  the two mechanisms, so both are attached).
- **0.7.11–0.7.13** Grading keys rounded out: cursor follows the problem
  you graded (restore by slug — grading re-sorts the deck), `_` grades
  down like `+` grades up, `0` = "drew a blank" → straight back to level 1
  (one step down is not a lapse's worth).

## 0.7.0–0.7.10 — 2026-08-15→16 · grading model, Vim pane, daily

- **0.7.5–0.7.10** Vim statement pane hardening: keys on the statusline,
  cursor starts in the code, pane read-only, `:q` from either window means
  leave, slug passed as an argument. Daily challenge names its day and
  when the next lands (UTC rollover).
- **0.7.0–0.7.1** The grading contract: **you set the level, lc marks what
  you re-solved.** Submits tint the row (✔/✗) without touching the level;
  `+`/`-` grade and clear the mark. (Amended, opt-in, by 0.7.22/0.7.24.)

## 0.5.x–0.6.x — 2026-08-15 · the deck and its sync

- **0.6.0–0.6.1** Two machines actually converge: union merge with
  last-edit-wins (`updated` UTC stamp), tombstones for removals, metadata
  refreshes stamped.
- **0.5.0–0.5.5** The review deck (spaced repetition, Ebbinghaus curve by
  default), settings screen, git-synced deck, sync status strip
  (computed network-free), sync errors that say what failed and what to
  try next.

## 0.1.0–0.4.0 — 2026-08-13→14 · foundations

- CLI + TUI browser, judge integration (`test`/`submit` against the real
  judge), workspace layout (`~/leetcode/NNNN-slug/`), Vim plugin
  (`\t`/`\s`/`\p`/`\o`), WSL support (explorer.exe URLs, Windows Firefox
  cookies), fireworks on accept / orz on failure, reproducible SVG
  screenshots, Chinese README.
