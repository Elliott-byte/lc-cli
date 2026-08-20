# lc — LeetCode in your terminal

**English** · [简体中文](README.zh-CN.md)

Browse problems, read statements, write solutions in your own editor, and run
them against LeetCode's real judge — without leaving the shell. Problems worth
a second look go on a spaced-repetition deck that remembers what you have
re-solved today and follows you between machines.

```bash
lc                              # the full-screen browser: pick, edit, test, submit
lc pick 322 --lang python3      # writes ~/leetcode/0322-coin-change/solution.py and opens it
lc test                         # run the samples on LeetCode's judge
lc submit                       # submit for real
```

![the full-screen browser](docs/tui.svg)

![lc test against the real judge](docs/test.svg)

**Contents** · [Install](#install) · [Log in](#log-in) · [The browser](#the-browser)
· [Review deck](#review-deck) · [Syncing between machines](#syncing-between-machines)
· [Vim](#vim) · [Settings](#settings) · [All commands](#all-commands)
· [Where files live](#where-files-live) · [WSL](#wsl)

## Install

```bash
brew install elliott-byte/tap/lc-cli
# or, with uv:
uv tool install git+https://github.com/Elliott-byte/lc-cli
```

From a checkout of this repo, `uv tool install .` — re-run it after changing
the source. To work on lc instead, use a local venv:

```bash
uv venv && uv pip install -e '.[dev]' && .venv/bin/python -m pytest
```

## Log in

`lc` talks to leetcode.com as you, using your browser's session cookies.

```bash
lc login
```

reads them straight from a local browser (Chrome, Firefox, Safari, Edge, …)
and verifies them. Not signed in yet? It opens the LeetCode login page — sign
in there, press Enter, and `lc` picks up the fresh cookies. On macOS the OS
may ask once for keychain access; reading Safari's cookies needs Full Disk
Access for your terminal.

If no browser store is readable (remote box, exotic browser):

```bash
lc login --paste                 # copy LEETCODE_SESSION + csrftoken from
                                 # DevTools → Application → Cookies
lc login --session … --csrf …    # scripted
```

Cookies are written to `~/.lc/cookies.json` with `0600` permissions, or read
from `$LEETCODE_SESSION` / `$LEETCODE_CSRF` if you'd rather not store them on
disk. The session expires every couple of weeks — just run `lc login` again.

## The browser

Bare `lc` (or `lc tui`) opens two panes: problems on the left, the statement
on the right. On a fresh machine it downloads the problem index by itself.

The loop is: move to a problem, `enter` to open it in your editor, write, quit
the editor back to the list, `r` to run the samples, `s` to submit — repeat.
`enter` on a problem you already started reopens your existing file.

Today's daily challenge is pinned to the top with a yellow `★` and selected
when the app opens, so it is always one keypress away; `D` jumps back to it.
The status bar names the day it belongs to and when the next one lands —
`★ daily 08-15, next in 43m` — because LeetCode rotates at UTC midnight, so
east of Greenwich your local date runs ahead of the daily on screen for part
of the morning.

The ✔/✗ marks stay fresh by themselves: coming back from the editor re-reads
the local index, so a `\s` submit made inside Vim shows up immediately.
`ctrl+r` refreshes on demand — instant and local, unlike `R`, which
re-downloads the whole index.

| Key | Action |
| --- | --- |
| `↑` `↓` | Move through the list |
| `/` | Filter (`esc` or `enter` returns to the list) |
| `enter` / `p` | Set up the solution file and open your editor |
| `r` | Run the samples |
| `s` | Submit |
| `tab` | Switch between the **Problems** and **Review** tabs |
| `m` | Save this problem to the review deck |
| `c` | Settings |
| `d` / `t` | Cycle the difficulty / status filter |
| `o` | Open the problem on leetcode.com |
| `D` | Jump to today's daily challenge |
| `?` | Every key, including the ones kept off the footer |
| `q` | Quit |

Drag the divider between the two panes to give either side more room; it
stops when one of them is down to 24 columns.

Click the statement's `url` line to open the problem in your browser — or
press `o`, which does the same from either tab. In Vim's statement pane the
same line takes a double-click (`\o` works from either window): Vim owns the
mouse there, so a single click never reaches the terminal, and Vim's terminal
drops the escape that would make the URL a link.

The footer shows the solving loop only. `c` (settings), `d`/`t` (filters),
`o` (open on leetcode.com), `D` (jump to the daily), `ctrl+r` (refresh from
the local index) and `R` (re-download it) all still work — press `?` for the
full list, and `?`, `esc` or `q` to put it away again.

## Review deck

Some problems deserve a second — and a fifth — meeting. Press `m` and the
problem joins the **Review** tab, where it climbs Ebbinghaus's forgetting
curve: level 1 comes back after 1 day, then 2, 4, 7, 15, out to a year at
level 10.
Due problems sort to the top and the tab title counts them: `Review (3)`.

![the review deck](docs/review.svg)

**You grade, lc remembers.** Re-solve a due problem and submit: lc marks the
row — green with a `✔` when it passed, red with a `✗` when it did not — and
leaves the level alone. Press `+` to move it up (or `-` to drop it) and the
mark clears. Levels stay yours: a problem solved by luck, or after peeking,
should not quietly buy itself another month.

For the ones you drew a blank on, `0` goes straight back to level 1 and the
problem returns tomorrow. One step down is not enough for a lapse — a level-9
problem stepped to 8 still buys itself three months.

**Or let the judge grade.** If you would rather the verdict decide:

```bash
lc config autograde on
```

A submit then moves the problem by itself — accepted climbs a level, a
failure drops one, and the next review is scheduled from today. Only the
first submit of a day counts, so re-submitting a passing solution cannot
ratchet a problem up to level 10, and `+` / `-` / `0` still override by hand.
It is off by default: the judge knows whether the code passed, not whether
you remembered how.

Submits count from anywhere — the TUI, `lc submit` in a shell, `\s` in Vim —
so a problem you solved in Vim is already green when you get back to the
list. The mark describes today: it clears when you grade the problem, and
otherwise fades overnight.

Nothing is ever added behind your back. Only `m`, Vim's `\m`, and
`lc review add` put a problem on the deck.

On the Review tab:

| Key | Action |
| --- | --- |
| `+` `=` / `-` `_` | Set the level by hand (rescheduled from today) |
| `0` | Forgot it completely — straight back to level 1 |
| `z` | Postpone this problem to tomorrow |
| `Z` | Postpone everything due — the "not today" button |
| `x` | Take it off the deck |
| `g` | Sync with your git repo |
| `enter` | Open it in your editor, as usual |

The same deck from the shell:

```bash
lc review                  # the deck, soonest due first
lc review add 322 -l 3     # save by hand, starting at level 3
lc review add              # ...or the problem directory you are standing in
lc review level 322 5      # set a level
lc review postpone         # everything due moves to tomorrow
lc review rm 322
```

The curve is yours to shape — one gap per level, in days, and the number of
entries is the number of levels:

```bash
lc config curve 1,2,4,7,15,30    # six levels
lc config curve reset            # back to the Ebbinghaus default
```

## Syncing between machines

Point lc at a git repo you own and the deck follows you around — a laptop and
a WSL box stay in step.

```bash
lc config repo https://github.com/you/lc-review.git
lc review sync             # pull, merge, push  (or press g in the Review tab)
lc review pull             # bring the repo's deck down only
lc review push             # publish this machine's deck only
```

Use the `https://` URL unless you have an SSH key GitHub accepts — with `gh`
logged in, https just works. A failed sync says what went wrong and what to
try next.

The Review tab carries a status strip once a repo is configured:

| | Meaning |
| --- | --- |
| `✔ synced 2h ago` | the deck matches the repo as of the last sync |
| `↑ 3 changes to push · synced 2h ago` | you have graded things since |
| `○ not synced yet — press g` | configured, never synced |
| `✗ last sync failed: …` | the reason is shown, with a hint |

The strip is worked out from local files only — redrawing the deck never
reaches for the network — so "synced" means "agreed with the repo when we
last talked to it", not "checked GitHub just now". With no repo configured it
is hidden entirely.

**How merging works.** lc merges in Python, not in git, so you are never asked
to resolve a conflict. Both sides are unioned, and where both machines know a
problem the copy edited most recently wins: every change stamps a UTC
timestamp, so same-day edits on two machines still order correctly. Removals
travel too — taking a problem off the deck leaves a tombstone, which is just
another edit, so the other machine drops it instead of handing the problem
back. Re-adding a removed problem revives it at level 1. If both machines
push at the same moment, lc redoes the sync and you never see it.

lc keeps a private clone in `~/.lc/review-repo` and writes two files there:
`review.json`, the deck it reads back, and `REVIEW.md`, the same deck as a
linked table so the repo page is readable on GitHub. It never writes a
`README.md`, so pointing lc at a repo that has one is safe.

Commits are made as `lc <lc@localhost>` — lc never depends on, or edits, your
global git identity, so a machine that has none still syncs. To have GitHub
credit the deck to your account instead, give it an address that account owns:

```bash
lc config author you@example.com     # --name sets the committer name
lc config author none                # back to lc's own identity
```

## Vim

```bash
lc setup vim
```

Drops a small plugin into `~/.vim/plugin/lc.vim` — no `.vimrc` edits, delete
the file to uninstall. If no editor is configured yet, it also sets
`lc config editor vim`, so `lc pick` drops you straight into Vim.

In a solution buffer (any file next to a `.lc.json`), normal mode:

| Key | Action |
| --- | --- |
| `\t` | save, then `lc test` |
| `\s` | save, then `lc submit` |
| `\p` | show/hide the problem statement in a left split |
| `\o` | open the problem page in your browser (figures render there) |
| `\m` | save this problem to the review deck |
| `\q` | save everything, then quit — back to the TUI/shell |

Opening a solution file opens the statement beside it automatically — hide it
with `\p` (or `q` inside the pane), bring it back with `\p`, or set
`let g:lc_auto_statement = 0` to open it manually. `:q` means "leave" from
either window — the pane is an accessory, not a second document to close
separately — and so do `:qa`, `:x`, `ZZ` and `\q`. Anything unsaved still
vetoes it, exactly as in plain Vim.

The pane shows the statement fully rendered — `lc show` in a small terminal
split, same colors and example boxes as the CLI — whenever your Vim has
`+terminal` (or on Neovim). Without it, the directory's raw `README.md` is
used; `let g:lc_statement_render = 0` forces the plain file everywhere.

Python buffers are kept space-indented: Tab inserts spaces, and pasted tabs
are converted on save. LeetCode's starters use spaces and the judge answers a
single stray tab with a `TabError` — `let g:lc_python_indent = 0` disables it.

The keys are listed on each window's status line, shortened to fit a narrow
split (`let g:lc_statusline = 0` leaves your own status line alone). The
cursor starts in the solution, and the pane is read-only: the statement is
there to read, not to type in. `ctrl+w h` goes over to it and `ctrl+w l`
comes back. The keys work from the pane as well, so it does not matter which
window has the cursor — `\t` saves the solution and runs from the problem's
directory either way, whatever directory you launched Vim in. `<leader>` is backslash unless you remapped it. After upgrading
lc, re-run `lc setup vim --force`; for Neovim, copy the file to
`~/.config/nvim/plugin/`.

## Settings

Press `c` in the TUI for the settings screen: workspace, default language,
editor, review repo and the memory curve — with a live preview of what the
curve you are typing means. `ctrl+s` saves, `esc` cancels.

![the settings screen](docs/config.svg)

The same settings from the shell:

```bash
lc config show
lc config lang go                  # default language for `lc pick`
lc config workspace ~/code/leetcode
lc config editor "code -w"         # otherwise $EDITOR / $VISUAL is used
lc config curve 1,2,4,7,15,30      # days per review level
lc config repo https://github.com/you/lc-review.git
lc config author you@example.com   # who deck commits are authored by
lc config autograde on             # let a submit verdict move the level
```

## All commands

![lc list](docs/list.svg)

| Command | What it does |
| --- | --- |
| `lc list [keyword]` | Browse the problem set. `-d easy`, `-t "Two Pointers"`, `-s todo`, `--free` |
| `lc show 322` | Print the statement, formatted for a terminal |
| `lc pick 322 -l go` | Create a solution file from the starter code and open `$EDITOR` |
| `lc edit 322` | Reopen an existing solution |
| `lc test` | Run the sample cases on LeetCode's judge |
| `lc submit` | Submit; prints verdict, runtime and percentiles |
| `lc daily` | Today's daily challenge (`--pick` to start it immediately) |
| `lc random -d medium` | A random unsolved problem |
| `lc review` | The review deck (`add` / `rm` / `level` / `postpone`) |
| `lc review sync` | Sync the deck with your git repo (`pull` / `push` too) |
| `lc stat` | Your solve counts by difficulty |
| `lc history 322` | Your recent submissions for a problem |
| `lc code` | Print the current solution, highlighted |
| `lc tags` | Topic tags, ranked by problem count |
| `lc sync` | Refresh the local problem index |
| `lc setup vim` | Install the Vim keybindings |
| `lc tui` | Full-screen browser (also just bare `lc`) |

`lc test`, `lc submit`, `lc code`, `lc edit`, `lc history` and `lc review add`
take no argument inside a problem directory — they read it from `.lc.json`.

`lc test` and `lc submit` exit non-zero on a failed verdict, so they compose:

```bash
lc test && lc submit -y
```

## Where files live

Solutions live in a plain, user-visible workspace, easy to keep under version
control:

```
~/leetcode/
  0322-coin-change/
    README.md      the statement, as Markdown
    solution.py    starter code + your work
    .lc.json       which problem and language this is
```

The whole solution file is submitted; the header lc writes is a comment in the
target language, so the judge ignores it.

Everything lc owns is under `~/.lc` (set `$LC_HOME` to move it):

| File | What it is |
| --- | --- |
| `config.json` | your settings |
| `review.json` | the review deck — **user data**, never rebuilt |
| `cookies.json` | session cookies, `0600` |
| `cache.db` | problem index + cached statements — delete any time, lc rebuilds it |
| `review-repo/` | the private clone used for syncing |

## WSL

Everything above works inside the distro unchanged — install with the same
`uv tool install` line, and the TUI, judge runs and vim plugin behave as on
any Linux. The Windows boundary is handled where it shows: pages open through
the Windows browser (`explorer.exe`, or wslu's `wslview`), and `lc login`
reads Windows Firefox profiles through `/mnt/c`, so Firefox users log in
automatically. Windows Chrome and Edge seal their cookie stores with keys only
the browser itself can open — sign in with `lc login --paste` there; the login
flow reminds you.

## Notes

- Accepted verdicts end in fireworks — a burst for `lc test`, a four-shot
  volley for `lc submit` — and a failed one in a little figure sinking to its
  knees (orz); after a failed submit, a rain cloud rolls in over it. Both skip
  pipes and scripts automatically, and `LC_NO_FX=1` turns them off everywhere.
- Premium problems need a premium account; lc says so rather than failing
  oddly.
- `lc test` and `lc submit` run on LeetCode's judge, not locally, so the
  verdict and the runtime percentiles are the real ones.
- Requests go to leetcode.com at a human pace. Scripting a loop over many
  problems will get you rate-limited; lc surfaces that as a plain error.
