# lc — LeetCode in your terminal

**English** · [简体中文](README.zh-CN.md)

Browse problems, read statements, write solutions in your own editor, and run
them against LeetCode's real judge — without leaving the shell.

```
lc                              # the full-screen browser: pick, edit, test, submit
lc list --difficulty medium --status todo
lc pick 322 --lang python3      # writes ~/leetcode/0322-coin-change/solution.py and opens it
lc test                         # run the samples on LeetCode's judge
lc submit                       # submit for real
```

![the full-screen browser](docs/tui.svg)

![lc test against the real judge](docs/test.svg)

## Install

```bash
brew install elliott-byte/tap/lc-cli
# or, with uv:
uv tool install git+https://github.com/Elliott-byte/lc-cli
```

From a checkout of this repo:

```bash
uv tool install .
```

Re-run it after changing the source (or use `uv tool install -e .` if `.pth`
files work in your shell — some sandboxed environments ignore them).

To work on it instead, use a local venv:

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
may ask once for keychain access to the browser's cookie store; reading
Safari's cookies needs Full Disk Access for your terminal.

If no browser store is readable (remote box, exotic browser):

```bash
lc login --paste                 # copy LEETCODE_SESSION + csrftoken from
                                 # DevTools → Application → Cookies
lc login --session … --csrf …    # scripted
```

Cookies are written to `~/.lc/cookies.json` with `0600` permissions. They are
also read from `$LEETCODE_SESSION` / `$LEETCODE_CSRF` if you'd rather not store
them on disk.

The session expires every couple of weeks — just run `lc login` again.

## WSL

Everything above works inside the distro unchanged — install with the same
`uv tool install` line, and the TUI, judge runs and vim plugin behave as on
any Linux. The Windows boundary is handled where it shows: pages open through
the Windows browser (`explorer.exe`, or wslu's `wslview` when you have it),
and `lc login` reads Windows Firefox profiles straight through `/mnt/c`, so
Firefox users log in automatically. Windows Chrome and Edge encrypt their
cookie stores with keys only the browser itself can use — nothing outside the
browser can read those — so sign in with `lc login --paste` there; the login
flow reminds you.

## Commands

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
| `lc stat` | Your solve counts by difficulty |
| `lc history 322` | Your recent submissions for a problem |
| `lc code` | Print the current solution, highlighted |
| `lc tags` | Topic tags, ranked by problem count |
| `lc sync` | Refresh the local problem index |
| `lc setup vim` | Install the Vim keybindings (`\t` test, `\s` submit) |
| `lc tui` | Full-screen browser (also just bare `lc`) |

`lc test`, `lc submit`, `lc code`, `lc edit` and `lc history` take no argument
when you run them from inside a problem directory — they pick it up from
`.lc.json`.

Both exit non-zero on a failed verdict, so they compose with shell scripting:

```bash
lc test && lc submit -y
```

## Workspace layout

```
~/leetcode/
  0322-coin-change/
    README.md      the statement, as Markdown
    solution.py    starter code + your work
    .lc.json       which problem and language this is
```

The whole solution file is submitted. The header `lc` writes is a comment in
the target language, so the judge ignores it.

## Config

```bash
lc config show
lc config lang go                  # default language for `lc pick`
lc config workspace ~/code/leetcode
lc config editor "code -w"         # otherwise $EDITOR / $VISUAL is used
```

Settings live in `~/.lc/config.json`; set `$LC_HOME` to move that whole
directory. The problem index and cached statements go in `~/.lc/cache.db` —
delete it any time, `lc` rebuilds it.

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

Opening a solution file also opens the statement beside it automatically —
hide it with `\p` (or `q` inside the pane), bring it back with `\p`. Put
`let g:lc_auto_statement = 0` in your vimrc if you'd rather open it manually.

The pane shows the statement fully rendered — `lc show` running in a small
terminal split, with the same colors, example boxes and superscripts as the
CLI — whenever your Vim has `+terminal` (or on Neovim). Editors without it
fall back to the directory's raw `README.md`; `let g:lc_statement_render = 0`
forces the plain file everywhere.

Python solution buffers are kept space-indented: the Tab key inserts spaces,
and real tabs that arrive via paste are converted when the file is saved.
LeetCode's starters use spaces, and the judge answers a single stray tab with
a `TabError` — `let g:lc_python_indent = 0` disables this if you must.

The keys run from the file's own directory, so it doesn't matter where you
launched Vim. They use `<leader>`, which is backslash unless you've remapped
it. After upgrading `lc`, re-run `lc setup vim --force` to refresh the plugin;
for Neovim, copy the same file to `~/.config/nvim/plugin/`.

## TUI

Bare `lc` (or `lc tui`) opens a two-pane browser: problem list on the left,
statement on the right. On a fresh machine it downloads the problem index by
itself. The loop is: move to a problem, `enter` to open it in your editor,
write, quit the editor back to the list, `r` to run the samples, `s` to
submit — repeat. `enter` on a problem you already started reopens your
existing file.

Today's daily challenge is pinned to the top of the list with a yellow `★`
(and selected when the app opens), so the day's problem is always one
keypress away; `D` jumps back to it from anywhere.

The ✔/✗ marks keep themselves fresh: coming back from the editor re-reads
the local index, so a `\s` submit made inside Vim shows up immediately, and
`ctrl+r` refreshes on demand (instant and local, unlike `R` which re-downloads
the index). Refreshes keep your cursor on the problem it was on.

| Key | Action |
| --- | --- |
| `↑` `↓` | Move through the list |
| `/` | Filter (`esc` or `enter` returns to the list) |
| `enter` / `p` | Set up the solution file and open your editor |
| `r` | Run the samples |
| `s` | Submit |
| `d` | Cycle the difficulty filter |
| `t` | Cycle the status filter |
| `o` | Open the problem on leetcode.com |
| `D` | Jump to today's daily challenge |
| `ctrl+r` | Refresh the list from the local index |
| `R` | Re-sync the problem index |
| `q` | Quit |

## Notes

- Accepted verdicts end in fireworks — a burst for `lc test`, a four-shot
  volley for `lc submit` — and a failed one in a little figure sinking to
  its knees (orz); when it was a submit, a rain cloud rolls in over it.
  Both skip pipes and scripts automatically, and `LC_NO_FX=1` turns them
  off everywhere.
- Premium problems need a premium account; `lc` reports that clearly rather
  than failing oddly.
- `lc test` and `lc submit` run on LeetCode's judge, not locally, so the verdict
  and the runtime percentiles are the real ones.
- Requests go to leetcode.com at a human pace. If you script a loop over many
  problems you will get rate-limited; `lc` surfaces that as a plain error.
