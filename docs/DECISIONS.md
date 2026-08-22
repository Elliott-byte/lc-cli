# Design decisions

The *why* behind the shapes in this codebase, with the alternatives that were
considered and rejected — so a future session (human or model) doesn't
relitigate them without new evidence. Statuses: **standing** (in force),
**amended** (still true, with a documented exception), **superseded**
(replaced — kept because the reasoning explains the current shape).

**Maintenance rule:** never delete a decision. When one changes, mark it
superseded (or amended) in place and say what replaced it and why — the
graveyard is half of this file's value.

## Deck & grading

**You grade, lc remembers.** — *standing, amended by opt-in autograde.*
Submits mark the row (✔/✗) and never touch the level, because the judge
knows whether the code passed, not whether you *recalled* it — a solve by
luck or after peeking must not quietly buy itself a month. Autograde
(`lc config autograde on`) hands the decision to the verdict for users who
want it, and stays off by default. Rejected: grading automatically for
everyone (silently corrupts the schedule's meaning).

**Whoever grades first that day wins.** — *standing (replaced an earlier
guard).* Under autograde, one level move a day, and the guard keys on
`graded` alone — stamped by an earlier submit, a hand `+`/`-`/`0`, and
`add()` alike. Consequences that are features: a hand grade stands against
any later submit (the override is real), re-submits can't ratchet, and day
zero is order-independent — the day you add a problem it stays at level 1,
because that solve is initial learning, not recall, and bumping it would
skip the one-day review the curve deliberately starts with. The first
guard ("has a *submit* graded this today?") let hand grades be silently
re-promoted; the second (attempt mark) blocked the day's first real grade
after a mid-day toggle. Both are in the tests as regressions.

**A lapse is not one level down.** — *standing.* `0` resets to level 1;
`-` steps down one. A level-9 problem stepped to 8 still buys three months,
which is no way to treat something you just blanked on — and pressing `-`
eight times is a chore, not a grade.

**The curve is data, not code.** — *standing.* `review_curve` in config;
levels past the end clamp to the top gap so shortening the curve
reschedules rather than crashes. Default is Ebbinghaus's ladder.

## Sync

**Merge in Python, never in git.** — *standing.* The clone is disposable
and hard-reset to the remote before every merge; the deck of record is
`~/.lc/review.json`. Divergence becomes a union merge lc controls —
last-edit-wins on a fixed-width UTC microsecond stamp (`updated`) — and the
user is never shown a git conflict. Removals travel as tombstones (a
tombstone is just another edit, so it beats the other machine's older live
copy instead of being handed the problem back). Rejected: git-level
merging (conflicts surface to the user), CRDTs (overkill for one person's
deck), and matching on `graded` (a local date — same-day edits on two
machines would tie).

**Counts describe the live deck view.** — *standing.* The sync report is
the only warning that another machine's removal landed here, so a
tombstone hiding a live problem is *removed* — never "updated" — a revival
is *added*, and tombstone-on-tombstone traffic is nothing.

**Save when the merge changed anything, not when the counters say so.** —
*standing.* A tombstone for a never-seen slug counts as nothing but must
still reach disk, or status() counts it as pending forever.

**The status strip never touches the network.** — *standing.* It redraws
with every deck refresh; "synced" means "agreed with the clone at last
contact", not "checked GitHub just now".

**Errors say the real problem and the next step.** — *standing.* The
`_KNOWN` classifier maps git's multi-line stderr to one sentence + hint;
**ordering is by specificity** (GH007's output *contains* the push-race
line, and the race rule's "run it again" advice retries into the same
wall). Only the genuine push race is retryable.

**A changed repo URL means a fresh clone.** — *standing.* `git fetch` does
not prune, so re-pointing origin leaves `origin/<branch>` naming the old
repo's commit — the sync resets onto it, finds nothing to commit, and
reports success while the new repo stays empty. Re-cloning is cheap; the
clone holds nothing of record.

## Identity

**Deck commits are yours by default, lc's as last resort.** — *standing
(third iteration).* v1: hardcoded `lc <lc@localhost>` so lc never depends
on (or edits) the user's git config — but GitHub credited the deck to
nobody. v2: `lc config author` override — worked, but had to be configured
on every machine. v3 (current): override → the identity git already has →
lc's own name, passed via `git -c` on every commit, never written into any
config. GH007 (email privacy) gets a specific hint pointing at the
GitHub noreply address.

## Notes

**A note is a markdown card in the problem's own directory.** — *standing.*
Not a database: you write notes in your editor with the submitted code on
screen (Vim opens `notes.md` in a split under the solution), the workspace
git versions them with the code, and `cat` reads them anywhere. The TUI
renders the `##` sections as cards, newest first. lc stamps the heading
(date · verdict · language) so the card is tied to the attempt without the
user typing bookkeeping. The deck sync carries the cards as a **union**
(`notes/<slug>.md` in the review repo): deterministic and idempotent, so
two machines converge — at the price that the sync never deletes a card;
removing one locally resurrects it from the other side.

## Solve clock

**The clock's state is a file.** — *standing.* Three processes read it —
the TUI arms it, Vim's statusline draws it, the CLI's submit stops it — so
`timer.json` (wall-clock epochs, not monotonic) is the only shape that
works. One active clock at a time.

**Opening arms; starting is yours.** — *standing (replaced start-on-open).*
Walking into a problem must not start the count — reading the statement is
not solving. Space (in Vim; `lc timer start` underneath) is the deliberate
go; it can conjure a clock from nothing so a bare `vim solution.py`
session counts too.

**Leaving Vim pauses the clock.** — *standing.* Editor time is the solve
time: quitting back to the TUI or the shell must not keep the meter
running while you browse. Space (or `\z`) picks it back up on the next
visit — deliberately, like the start. Only a session that actually edited
that problem pauses it, so quitting an unrelated Vim touches nothing.
Corollary: a clock still *running* when a session begins escaped through a
crash or a killed terminal — `begin()` drops the phantom run and keeps the
banked time, because nobody was solving for that stretch.

**Only an accepted submit stops it — and only a *fresh* one.** — *standing.*
A failed submit keeps the clock running (the problem is not done). The
editor-return inference in the TUI snapshots both the store's solved flag
and the deck's ✔ mark **at the door, every visit**: both mean "today", not
"while I was in the editor", and acting on a standing value clocked out
re-practice sessions with phantom results. Twice, in two forms — both are
regression-tested.

**The clock lives where the solving happens.** — *standing.* Vim's
statusline, drawn in plain text (emoji are double-width to the terminal
and single-width to Vim; the disagreement tears the highlight), repainted
by a 1s ticker that holds while a prompt owns the screen. The TUI shows no
clock chrome.

## TUI

**`enter` reopens; `pick` creates.** — *standing.* A problem you already
started reopens as-is, whatever language it was picked in — re-picking
would write a second file in the config default and repoint `.lc.json`,
stranding the half-written one and aiming `r`/`s` at fresh starter code.
The CLI's `lc pick` keeps create semantics (with `--lang`/`--overwrite`);
`lc edit` and the TUI's enter are the reopen paths.

**Cursor follows the problem, not the row number.** — *standing.* Grading
moves a due date, which re-sorts the deck; restore by slug (with a one-shot
`focus` request after a submit so tabbing over lands on what you just
solved — consumed by that single render, because a resize re-renders too).

**The status bar describes the tab on screen.** — *standing.* Each tab's
durable line is remembered and restored on switch; a background refresh of
the hidden tab may not steal the bar; the `d`/`t` filter prefix belongs to
the Problems line only. Transient messages (judge verdicts, "syncing…")
write directly and are overwritten by the next refresh, as before.

**`current` is nothing while a statement is loading.** — *standing.*
Pick/run/submit must not act on the problem shown before; a highlight with
no cached statement clears `current` until the fetch lands. (Tests that
drive picks must `store.put_statement(...)` first.)

## Rendering

**Parse LeetCode's HTML by hand.** — *standing.* The statements use a
small, predictable subset; a hand parser keeps example blocks intact and
maps `<sup>`/`<sub>` to real Unicode where a general converter mangles
them. The same parse re-emits Markdown for the workspace README.

**URLs fold; they are never ellipsized.** — *standing.* Half a URL cannot
be clicked, copied or read. Shown scheme-less (nine columns buys most
problems one line); the link still carries the full URL, via OSC 8 *and*
Textual `@click` meta, because the TUI captures the mouse and Vim's
terminal swallows the escape — each channel drops one mechanism.

**Styles are spans wherever text can wrap.** — *standing.* A folded line
is padded to the column edge in the Text's *base* style; a base-style
underline (or link) paints across the blank cells after the text.

## Workspace & judging

**The recorded file wins.** — *standing.* `.lc.json` names the solution
file; a helper file the user drops alongside is never submitted by
accident, and lc never falls back to another language's file (submitting
Python as Go wastes a real submission).

**The whole file is submitted; only lc's header comes off.** — *standing.*
`strip_header` removes a leading comment block only when it contains the
problem URL — a comment the user wrote is never deleted.

**Judge polling survives drops.** — *standing.* The submission already
went in, so network errors, 429 and 5xx during `/check/` polling mean
"keep asking until the deadline"; only 4xx and the judge's own FAILURE are
terminal.

## Process

**Every commit bumps the version; tags are releases.** — *standing.* The
maintainer tags from their machine (brew tap). Two machines develop and
push; version numbers collide across them and the pushed/tagged numbers
win — renumber local commits during the rebase.

**Bug fixes ship with regressions proven against the old code.** —
*standing.* Revert the fix (only the fix), watch the test fail, restore.
Each commit passes its own suite so history bisects.
