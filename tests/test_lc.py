"""Tests for the parts that are awkward to exercise by hand.

The judge flow in particular needs a real account and burns a submission, so it
is covered here against a mock transport that replays LeetCode's actual payload
shapes.
"""

from __future__ import annotations

import json

import httpx
import pytest

from lc import editors
from lc.api import BASE, LeetCode, LeetCodeError, Problem
from lc.config import Credentials, load_config
from lc.langs import resolve
from lc.render import to_markdown
from lc.workspace import strip_header

CREDS = Credentials(session="sess", csrf="tok", username="tester")

PROBLEM = Problem(
    question_id="322",
    frontend_id="322",
    title="Coin Change",
    slug="coin-change",
    difficulty="Medium",
    content="<p>x</p>",
    paid_only=False,
    likes=1,
    dislikes=0,
    ac_rate=48.9,
    total_accepted="3M",
    total_submission="6M",
    sample_testcase="[1,2,5]\n11",
    example_testcases="[1,2,5]\n11\n[2]\n3",
    hints=[],
    tags=[],
    snippets={"python3": "class Solution:\n    def coinChange(self):\n        "},
    meta={},
)


def judge_client(check_payloads, capture=None):
    """A LeetCode client whose /check/ endpoint replays `check_payloads` in order."""
    remaining = list(check_payloads)

    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        url = str(request.url)
        if url.endswith("/interpret_solution/"):
            return httpx.Response(200, json={"interpret_id": "runcode_1"})
        if url.endswith("/submit/"):
            return httpx.Response(200, json={"submission_id": 4242})
        if "/check/" in url:
            return httpx.Response(200, json=remaining.pop(0))
        raise AssertionError(f"unexpected request: {url}")

    return LeetCode(CREDS, transport=httpx.MockTransport(handler))


# ------------------------------------------------------------------ judge: run

def test_run_reports_pass_when_every_sample_matches():
    lc = judge_client([
        {"state": "PENDING"},
        {
            "state": "SUCCESS",
            "status_msg": "Accepted",
            "run_success": True,
            "correct_answer": True,
            "code_answer": ["3", "-1"],
            "expected_code_answer": ["3", "-1"],
            "status_runtime": "48 ms",
            "status_memory": "16.1 MB",
        },
    ])
    result = lc.run(PROBLEM, "python3", "code", PROBLEM.example_testcases)
    assert result.accepted
    assert result.is_run
    assert result.code_output == ["3", "-1"]
    assert result.runtime == "48 ms"


def test_run_reports_failure_when_a_sample_differs():
    lc = judge_client([
        {
            "state": "SUCCESS",
            "status_msg": "Accepted",  # a run's status_msg is about the process
            "run_success": True,
            "correct_answer": False,   # ...this is the verdict
            "code_answer": ["3", "0"],
            "expected_code_answer": ["3", "-1"],
        },
    ])
    result = lc.run(PROBLEM, "python3", "code", PROBLEM.example_testcases)
    assert not result.accepted


def test_run_posts_the_expected_request():
    capture: list[httpx.Request] = []
    lc = judge_client([{"state": "SUCCESS", "status_msg": "Accepted",
                        "correct_answer": True}], capture)
    lc.run(PROBLEM, "python3", "my code", "[1]\n1")

    post = capture[0]
    assert str(post.url) == f"{BASE}/problems/coin-change/interpret_solution/"
    assert post.headers["x-csrftoken"] == "tok"
    assert post.headers["referer"] == f"{BASE}/problems/coin-change/"
    assert "LEETCODE_SESSION=sess" in post.headers["cookie"]
    assert json.loads(post.content) == {
        "lang": "python3",
        "question_id": "322",
        "typed_code": "my code",
        "data_input": "[1]\n1",
    }


# --------------------------------------------------------------- judge: submit

def test_submit_accepted():
    lc = judge_client([
        {"state": "STARTED"},
        {
            "state": "SUCCESS",
            "status_msg": "Accepted",
            "total_correct": 145,
            "total_testcases": 145,
            "status_runtime": "52 ms",
            "status_memory": "17.2 MB",
            "runtime_percentile": 91.3,
            "memory_percentile": 60.0,
        },
    ])
    result = lc.submit(PROBLEM, "python3", "code")
    assert result.accepted
    assert not result.is_run
    assert (result.total_correct, result.total_testcases) == (145, 145)
    assert result.runtime_percentile == 91.3


def test_submit_wrong_answer_surfaces_the_failing_case():
    lc = judge_client([
        {
            "state": "SUCCESS",
            "status_msg": "Wrong Answer",
            "total_correct": 12,
            "total_testcases": 145,
            "last_testcase": "[1,2,5]\n11",
            "code_output": "4",
            "expected_output": "3",
        },
    ])
    result = lc.submit(PROBLEM, "python3", "code")
    assert not result.accepted
    assert result.status == "Wrong Answer"
    assert result.last_testcase == "[1,2,5]\n11"
    assert result.code_output == ["4"]
    assert result.expected_output == ["3"]


def test_submit_compile_error():
    lc = judge_client([
        {
            "state": "SUCCESS",
            "status_msg": "Compile Error",
            "full_compile_error": "line 3: expected an indented block",
        },
    ])
    result = lc.submit(PROBLEM, "python3", "code")
    assert not result.accepted
    assert "indented block" in result.error


def test_split_testcases_by_parameter_count():
    from dataclasses import replace

    from lc.api import split_testcases

    two_arg = replace(PROBLEM, meta={"params": [{"name": "coins"}, {"name": "amount"}]})
    assert split_testcases(two_arg, "[1,2,5]\n11\n[2]\n3") == ["[1,2,5]\n11", "[2]\n3"]
    # Class-design problems have no "params": two lines per case.
    design = replace(PROBLEM, meta={"classname": "LRUCache"})
    assert split_testcases(design, "ops1\nargs1\nops2\nargs2\n") == [
        "ops1\nargs1", "ops2\nargs2",
    ]


def test_run_status_says_samples_not_accepted():
    from lc.api import JudgeResult

    assert JudgeResult(raw={}, accepted=False, status="Accepted",
                       is_run=True).display_status == "Samples failed"
    assert JudgeResult(raw={}, accepted=True, status="Accepted",
                       is_run=True).display_status == "Samples passed"
    # Real submits and real errors keep LeetCode's own words.
    assert JudgeResult(raw={}, accepted=True, status="Accepted",
                       is_run=False).display_status == "Accepted"
    assert JudgeResult(raw={}, accepted=False, status="Runtime Error",
                       is_run=True).display_status == "Runtime Error"


def test_firework_frames_shape_and_sparks():
    import random

    from lc import fx

    frames = fx.firework_frames(30, 8, 1, 16, rng=random.Random(7))
    assert len(frames) == 16
    for frame in frames:
        lines = frame.plain.splitlines()
        assert len(lines) == 8
        assert all(len(line) == 30 for line in lines)
    assert "✦" in "".join(f.plain for f in frames)  # it does actually explode
    # mid-animation is busier than the launch
    assert frames[8].plain.count(" ") < frames[0].plain.count(" ")


def test_defeat_frames_end_in_orz():
    from lc import fx

    small = fx.defeat_frames()
    assert len(small) == 10
    assert all(len(f.plain.splitlines()) == 5 for f in small)
    assert "orz" in small[-1].plain
    assert "orz" not in small[0].plain

    big = fx.defeat_frames(big=True)
    assert len(big) == 13
    assert all(len(f.plain.splitlines()) == 7 for f in big)
    assert "O r z" in big[-1].plain
    assert "~" in big[-1].plain and "'" in big[-1].plain  # the rain rolled in


def test_animations_stay_out_of_pipes():
    from io import StringIO

    from rich.console import Console

    from lc import fx

    out = StringIO()
    fx.play(Console(file=out), big=True)  # not a terminal — must be a no-op
    fx.defeat(Console(file=out), big=True)
    assert out.getvalue() == ""


def test_judge_requires_login():
    lc = LeetCode(None)
    with pytest.raises(LeetCodeError):
        lc.submit(PROBLEM, "python3", "code")


def test_graphql_errors_become_exceptions():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "boom"}]})

    lc = LeetCode(CREDS, transport=httpx.MockTransport(handler))
    with pytest.raises(LeetCodeError, match="boom"):
        lc.problem("coin-change")


# ------------------------------------------------------------------ formatting

PY = resolve("python3")
GO = resolve("golang")


def test_strip_header_removes_only_our_own_header():
    ours = (
        "# [1] Two Sum\n"
        "# https://leetcode.com/problems/two-sum/\n"
        "\n"
        "class Solution:\n"
    )
    assert strip_header(ours, PY) == "class Solution:\n"

    theirs = "# my notes\n# about the approach\n\nclass Solution:\n"
    assert strip_header(theirs, PY) == theirs


def test_strip_header_handles_slash_comments():
    src = "// [1] Two Sum\n// https://leetcode.com/problems/two-sum/\n\nfunc a() {}\n"
    assert strip_header(src, GO) == "func a() {}\n"


def test_markdown_keeps_code_spans_intact_across_superscripts():
    html = "<ul><li><code>1 &lt;= n &lt;= 2<sup>31</sup> - 1</code></li></ul>"
    assert to_markdown(html).strip() == "- `1 <= n <= 2³¹ - 1`"


def test_markdown_renders_examples_as_fenced_blocks():
    html = "<pre><strong>Input:</strong> n = 1\n<strong>Output:</strong> 2\n</pre>"
    assert to_markdown(html).strip() == "```\nInput: n = 1\nOutput: 2\n```"


def test_markdown_emphasis_is_balanced():
    html = "<p>return <em>the <strong>only</strong> answer</em> now</p>"
    assert to_markdown(html).strip() == "return *the **only** answer* now"


# ------------------------------------------------------------------ lc setup vim

def test_setup_vim_installs_the_plugin(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    path, status = editors.install_vim_plugin()
    assert status == "installed"
    assert path == tmp_path / ".vim" / "plugin" / "lc.vim"
    text = path.read_text()
    assert "lc test" in text and "lc submit" in text and ".lc.json" in text
    assert "LcToggleStatement" in text and "README.md" in text
    assert "lc review add" in text  # \m saves the problem mid-solve


def test_vim_quit_never_fights_the_statement_terminal():
    """The pane runs `lc show` in a terminal; its job blocks :quit and :xall."""
    text = editors.VIM_PLUGIN

    # \q must not map straight to :xall — that tries to write the terminal
    # buffer (E382) and dies without quitting.
    assert "<leader>q :xall" not in text
    assert "<leader>q :call <SID>LcQuitAll()" in text

    # The pane carries the action keys too: landing in it and pressing \t
    # used to do nothing at all.
    pane = text.split("function! s:LcOpenStatement")[1].split("endfunction")[0]
    for key in ("<leader>t", "<leader>s", "<leader>m", "<leader>q"):
        assert key in pane, key

    # The keys are on the status line — Vim has no footer to put them on.
    assert "LcKeyHints" in text and "statusline" in text
    assert "lc_statusline" in text          # ...and you can turn it off
    # They shrink to fit rather than losing their right-hand end silently.
    assert "winwidth(0)" in text and "call remove(l:parts, -1)" in text
    # The cursor lands in the solution, found by name rather than by
    # "previous window".
    assert "LcSolutionWin(l:dir)" in text
    assert "LcFocusSolution(l:dir)" in text
    # A terminal opened with ++curwin seizes the cursor in Terminal-Job mode
    # once Vim reaches its main loop, undoing the jump above: start the job
    # hidden and show the buffer afterwards instead.
    assert "terminal ++curwin" not in text
    assert "'hidden': 1" in text
    # term_start() splits a string command itself and never runs a shell, so
    # the slug must go in as a list element: shellescape()'d, `lc show` got
    # the quotes as part of the slug and the pane read "no problem matching".
    assert "let l:cmd = ['lc', 'show', l:slug]" in text
    assert "term_start(l:cmd" in text
    assert "term_start('lc show" not in text
    # Vim re-enters the first window when startup finishes, which is the
    # pane — the jump has to be repeated after that.
    assert "v:vim_did_enter" in text
    # The README fallback is a real file in the problem directory too, so
    # the solution lookup must not mistake the pane for the solution and
    # write the statement instead.
    assert "getbufvar(l:b, 'lc_statement_for', '') ==# ''" in text

    # The solve clock is drawn where the solving happens: Vim's statusline
    # reads the shared timer file and a ticker keeps it moving.
    assert "LcClockText" in text and "timer.json" in text
    assert "timer_start(1000" in text and "redrawstatus" in text
    # ...but never while a prompt, the cmdline or a shell command owns the
    # screen — that repaint splattered clock digits over `lc test`'s report.
    assert "mode(1) !~# '^[rc!]'" in text
    # Text only on the statusline: ⏱ is a double-width emoji to the terminal
    # and single-width to Vim, and the disagreement tears the highlight.
    for emoji in ("⏱", "⏸", "✔"):
        assert emoji not in text, emoji
    # ...and paused there too: \z covers code and statement with a fresh tab
    # page, and closing the cover is the resume.
    assert "<leader>z :call <SID>LcTimerToggle()" in text
    assert "lc timer pause" in text and "lc timer resume" in text
    # \z pauses, full stop — as a toggle it silently *started* a stopped
    # clock, which read as "pause is broken". Declining \Z's confirm says
    # so too, since Enter takes the default (No).
    assert "clock is not running — space starts it" in text
    assert "echo 'lc: not reset'" in text
    assert "tab new" in text and "tabclose" in text
    # \Z resets — one shifted slip from \z, so it must confirm first.
    assert "<leader>Z :call <SID>LcTimerReset()" in text
    assert "confirm('Reset the solve clock" in text and "lc timer reset" in text
    # Opening a problem only arms the clock; space is the deliberate start —
    # and once it runs, space must fall through to plain vim space.
    assert "<expr> <Space> <SID>LcSpaceKey()" in text
    assert "space starts the clock" in text
    # ...and space can conjure the clock from nothing, so a bare
    # `vim solution.py` session gets one without going through lc.
    assert "lc timer start" in text
    # \Z earns a hint slot; last, so narrow windows drop it first.
    assert "['Z', 'reset']" in text
    # Quitting Vim pauses this session's running clock — and because
    # commands inside an autocmd fire no further autocmds, the VimLeavePre
    # hook alone cannot cover the plugin's own qall! exits: each calls the
    # pause by hand. (Proven to fail on 0.7.47, which had none of these.)
    assert "autocmd VimLeavePre * call s:LcTimerAutoPause()" in text
    assert text.count("call s:LcTimerAutoPause()") >= 5
    assert "has_key(s:lc_slugs" in text     # unrelated Vims touch nothing
    # One clock, one hint list: both statuslines share a screen row in a
    # vertical split, so the pane carries only its own `q close` and the
    # clock skips it entirely.
    assert "call s:LcKeyHints([['', 'q close']])" in text
    # \n writes a note card with the submitted code still on screen: the
    # split opens under the solution, and `lc note` stamps the heading.
    assert "<leader>n :call <SID>LcNote()" in text
    assert "lc note --no-edit" in text and "belowright split" in text
    # ...and \n is a toggle like \p: again saves the card and closes the
    # split, instead of stacking window upon window.
    assert "s:LcNoteWin(l:dir)" in text
    assert text.count("LcClockText") >= 2 and "if exists('b:lc_statement_for')" in text
    assert "return \' \'" in text          # the fall-through: plain space

    # Vim owns the mouse in the pane, and its terminal drops the hyperlink
    # escape, so the URL can only be opened by something Vim itself binds.
    assert "<2-LeftMouse>" in pane and "LcClickOpen" in text
    assert "leetcode\\.com/problems/" in text

    # :q means "leave" from either window, not "close one of the two".
    assert "QuitPre" in text and "LcPaneQuit" in text
    # The terminal job must not veto :q / :qa with E948.
    assert "'term_kill': 'term'" in text
    # ...nor :wall / :wqa fail on E382 trying to write it.
    assert "BufWriteCmd" in text

    # Closing the pane forces past the running job, in both window layouts.
    assert "close!" in text and "quit!" in text
    # ...but never at the cost of a real unsaved file.
    assert "LcUnsaved" in text
    assert 'getbufvar(v:val.bufnr, "&buftype") ==# ""' in text


def test_setup_vim_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    editors.install_vim_plugin()
    _, status = editors.install_vim_plugin()
    assert status == "unchanged"


def test_setup_vim_refuses_to_clobber_local_edits(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    path, _ = editors.install_vim_plugin()
    path.write_text("my own mappings\n")
    with pytest.raises(FileExistsError):
        editors.install_vim_plugin()
    _, status = editors.install_vim_plugin(force=True)
    assert status == "updated"
    assert path.read_text() == editors.VIM_PLUGIN


def test_setup_vim_command_sets_editor_when_none_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LC_HOME", str(tmp_path / ".lc"))
    for var in ("EDITOR", "VISUAL", "LC_EDITOR"):
        monkeypatch.delenv(var, raising=False)

    from typer.testing import CliRunner
    from lc.cli import app

    result = CliRunner().invoke(app, ["setup", "vim"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".vim" / "plugin" / "lc.vim").exists()
    assert load_config().editor == "vim"


# ------------------------------------------------------------------ lc login

class _FakeLeetCode:
    """Stands in for cli.LeetCode: any cookies count as signed in."""

    def __init__(self, creds):
        self.creds = creds

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def user_status(self):
        return {"isSignedIn": True, "username": "tester", "isPremium": False}


def _login_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LC_HOME", str(tmp_path / ".lc"))
    monkeypatch.delenv("LEETCODE_SESSION", raising=False)
    monkeypatch.delenv("LEETCODE_CSRF", raising=False)
    import lc.cli as cli
    monkeypatch.setattr(cli, "LeetCode", _FakeLeetCode)
    return cli


def test_login_reads_cookies_from_the_browser(tmp_path, monkeypatch):
    cli = _login_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        cli, "_read_browser_cookies",
        lambda: [{"LEETCODE_SESSION": "sess", "csrftoken": "tok"}],
    )

    from typer.testing import CliRunner
    result = CliRunner().invoke(cli.app, ["login"])

    assert result.exit_code == 0, result.output
    from lc.config import load_credentials
    creds = load_credentials()
    assert creds is not None
    assert creds.session == "sess" and creds.csrf == "tok"
    assert creds.username == "tester"


def test_login_opens_the_browser_and_waits_when_signed_out(tmp_path, monkeypatch):
    cli = _login_env(tmp_path, monkeypatch)
    reads = iter([[], [{"LEETCODE_SESSION": "sess", "csrftoken": "tok"}]])
    monkeypatch.setattr(cli, "_read_browser_cookies", lambda: next(reads))
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)
    opened = []
    monkeypatch.setattr(cli.browser, "open_url", lambda url: opened.append(url) or True)

    from typer.testing import CliRunner
    result = CliRunner().invoke(cli.app, ["login"], input="\n")

    assert result.exit_code == 0, result.output
    assert opened == [cli.LOGIN_URL]
    from lc.config import load_credentials
    assert load_credentials().session == "sess"


# ------------------------------------------------------------------ WSL

def test_is_wsl_reads_the_kernel_banner(tmp_path, monkeypatch):
    from lc import browser

    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    proc = tmp_path / "version"
    monkeypatch.setattr(browser, "_PROC_VERSION", proc)
    assert not browser.is_wsl()  # no such file
    proc.write_text("Linux version 6.6.36-microsoft-standard-WSL2 (root@1) ...")
    assert browser.is_wsl()
    proc.write_text("Linux version 6.9.0-generic (buildd@lcy02) ...")
    assert not browser.is_wsl()
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    assert browser.is_wsl()


def test_open_url_uses_the_windows_opener_under_wsl(monkeypatch):
    from lc import browser

    monkeypatch.setattr(browser, "is_wsl", lambda: True)
    monkeypatch.delenv("BROWSER", raising=False)
    monkeypatch.setattr(
        browser.shutil, "which",
        lambda exe: "/mnt/c/Windows/explorer.exe" if exe == "explorer.exe" else None,
    )
    runs = []
    monkeypatch.setattr(browser.subprocess, "run", lambda argv, **kw: runs.append(argv))

    assert browser.open_url("https://example.com") is True
    assert runs == [["/mnt/c/Windows/explorer.exe", "https://example.com"]]


def test_open_url_respects_an_explicit_browser_env(monkeypatch):
    from lc import browser

    monkeypatch.setattr(browser, "is_wsl", lambda: True)
    monkeypatch.setenv("BROWSER", "firefox")
    opened = []
    monkeypatch.setattr(browser.webbrowser, "open", lambda url: opened.append(url) or True)

    assert browser.open_url("https://example.com") is True
    assert opened == ["https://example.com"]


def test_open_url_is_plain_webbrowser_off_wsl(monkeypatch):
    from lc import browser

    monkeypatch.setattr(browser, "is_wsl", lambda: False)
    opened = []
    monkeypatch.setattr(browser.webbrowser, "open", lambda url: opened.append(url) or True)

    assert browser.open_url("https://example.com") is True
    assert opened == ["https://example.com"]


def _firefox_db(profile_dir, cookies):
    """A Firefox cookie database inside *profile_dir* with the given cookies."""
    import sqlite3

    profile_dir.mkdir(parents=True)
    conn = sqlite3.connect(profile_dir / "cookies.sqlite")
    conn.execute("CREATE TABLE moz_cookies (host TEXT, name TEXT, value TEXT)")
    conn.executemany("INSERT INTO moz_cookies VALUES (?, ?, ?)", cookies)
    conn.commit()
    conn.close()


LEETCODE_JAR = [
    (".leetcode.com", "LEETCODE_SESSION", "sess"),
    ("leetcode.com", "csrftoken", "tok"),
    (".example.com", "LEETCODE_SESSION", "someone-elses"),
]


def test_windows_firefox_cookies_reads_the_profile(tmp_path, monkeypatch):
    from lc import browser

    _firefox_db(
        tmp_path / "AppData/Roaming/Mozilla/Firefox/Profiles/ab12cd.default-release",
        LEETCODE_JAR,
    )
    monkeypatch.setattr(browser, "_windows_profile_roots", lambda: [tmp_path])

    assert browser.windows_firefox_cookies() == [
        {"LEETCODE_SESSION": "sess", "csrftoken": "tok"}
    ]


def test_windows_firefox_cookies_reads_microsoft_store_installs(tmp_path, monkeypatch):
    from lc import browser

    _firefox_db(
        tmp_path / "AppData/Local/Packages/Mozilla.Firefox_8wekyb3d8bbwe"
                   "/LocalCache/Roaming/Mozilla/Firefox/Profiles/xy99.default",
        LEETCODE_JAR,
    )
    monkeypatch.setattr(browser, "_windows_profile_roots", lambda: [tmp_path])

    assert browser.windows_firefox_cookies() == [
        {"LEETCODE_SESSION": "sess", "csrftoken": "tok"}
    ]


def test_windows_firefox_cookies_none_without_a_profile(tmp_path, monkeypatch):
    from lc import browser

    monkeypatch.setattr(browser, "_windows_profile_roots", lambda: [tmp_path])
    assert browser.windows_firefox_cookies() is None


def test_read_browser_cookies_includes_windows_firefox_under_wsl(monkeypatch):
    import sys
    import types

    import lc.cli as cli

    # No Linux-side browsers, a Windows Firefox with one complete session.
    monkeypatch.setitem(sys.modules, "browser_cookie3",
                        types.SimpleNamespace(all_browsers=[]))
    monkeypatch.setattr(cli.browser, "is_wsl", lambda: True)
    monkeypatch.setattr(
        cli.browser, "windows_firefox_cookies",
        lambda: [{"LEETCODE_SESSION": "sess", "csrftoken": "tok"},
                 {"csrftoken": "incomplete"}],
    )

    assert cli._read_browser_cookies() == [
        {"LEETCODE_SESSION": "sess", "csrftoken": "tok"}
    ]


# ------------------------------------------------------ workspace file choice

def test_find_by_path_walks_up_from_a_subdirectory(tmp_path):
    from lc import workspace
    from lc.config import Config

    config = Config(workspace=str(tmp_path))
    created = workspace.create(config, PROBLEM, resolve("python3"))
    scratch = created.directory / "scratch"
    scratch.mkdir()

    found = workspace.find_by_path(config, scratch)
    assert found is not None
    assert found[0] == "coin-change"
    assert found[2] == created.file


def test_load_prefers_the_recorded_solution_file(tmp_path):
    from lc import workspace
    from lc.config import Config

    config = Config(workspace=str(tmp_path))
    created = workspace.create(config, PROBLEM, resolve("python3"))
    # Sorts before solution.py — a scan would pick it, the metadata must not.
    (created.directory / "aaa_scratch.py").write_text("print('scratch')\n")

    loaded = workspace.load(config, PROBLEM)
    assert loaded is not None
    assert loaded.file == created.file


def test_load_falls_back_to_scanning_for_another_language(tmp_path):
    from lc import workspace
    from lc.config import Config

    config = Config(workspace=str(tmp_path))
    created = workspace.create(config, PROBLEM, resolve("python3"))
    go_file = created.directory / "solution.go"
    go_file.write_text("func x() {}\n")

    loaded = workspace.load(config, PROBLEM, resolve("golang"))
    assert loaded is not None
    assert loaded.file == go_file


# ----------------------------------------------------------------- judge: poll

def test_poll_survives_a_dropped_connection():
    calls = {"n": 0}
    verdict = {"state": "SUCCESS", "status_msg": "Accepted", "correct_answer": True}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/interpret_solution/"):
            return httpx.Response(200, json={"interpret_id": "runcode_1"})
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("network blip")
        return httpx.Response(200, json=verdict)

    lc = LeetCode(CREDS, transport=httpx.MockTransport(handler))
    result = lc.run(PROBLEM, "python3", "code", "[1]\n1")
    assert result.accepted
    assert calls["n"] == 2


def test_poll_retries_a_throttled_check(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/interpret_solution/"):
            return httpx.Response(200, json={"interpret_id": "runcode_1"})
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429)
        return httpx.Response(
            200, json={"state": "SUCCESS", "status_msg": "Accepted", "correct_answer": True}
        )

    lc = LeetCode(CREDS, transport=httpx.MockTransport(handler))
    result = lc.run(PROBLEM, "python3", "code", "[1]\n1")
    assert result.accepted
    assert calls["n"] == 2


def test_poll_stops_on_a_terminal_judge_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/interpret_solution/"):
            return httpx.Response(200, json={"interpret_id": "runcode_1"})
        return httpx.Response(200, json={"state": "FAILURE"})

    lc = LeetCode(CREDS, transport=httpx.MockTransport(handler))
    with pytest.raises(LeetCodeError, match="judge failed"):
        lc.run(PROBLEM, "python3", "code", "[1]\n1")


# ---------------------------------------------------------------------- config

def test_config_preserves_unknown_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from lc.config import config_path, save_config

    config_path().write_text(json.dumps({"lang": "golang", "from_the_future": 42}))
    cfg = load_config()
    assert cfg.lang == "golang"
    save_config(cfg)
    raw = json.loads(config_path().read_text())
    assert raw["from_the_future"] == 42
    assert raw["lang"] == "golang"


# ----------------------------------------------------------------------- store

def test_search_treats_like_wildcards_literally(tmp_path, monkeypatch):
    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from lc import store
    from lc.api import ProblemSummary

    store.replace_index([
        ProblemSummary("1", "Two Sum", "two-sum", "Easy", 50.0, False, None),
        ProblemSummary("2", "Get 100% Coverage", "coverage", "Easy", 50.0, False, None),
    ])
    assert [p.slug for p in store.search(keyword="100%")] == ["coverage"]
    # Unescaped, `_` matches any character and "T_o" would find "Two".
    assert store.search(keyword="T_o") == []


def test_find_accepts_zero_padded_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from lc import store
    from lc.api import ProblemSummary

    store.replace_index([
        ProblemSummary("322", "Coin Change", "coin-change", "Medium", 45.0, False, None),
    ])
    found = store.find("0322")
    assert found is not None and found.slug == "coin-change"


def test_count_applies_the_same_filters_as_search(tmp_path, monkeypatch):
    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from lc import store
    from lc.api import ProblemSummary

    store.replace_index([
        ProblemSummary("1", "Two Sum", "two-sum", "Easy", 50.0, False, "ac"),
        ProblemSummary("2", "Add Two Numbers", "add-two-numbers", "Medium", 40.0, False, None),
        ProblemSummary("3", "Secret", "secret", "Easy", 30.0, True, None),
    ])
    assert store.count() == 3
    assert store.count(difficulty="easy") == 2
    assert store.count(difficulty="easy", include_paid=False) == 1
    assert store.count(status="solved") == 1
    assert store.count(keyword="two") == 2


def test_store_meta_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from lc import store

    assert store.get_meta("daily_slug") is None
    store.set_meta("daily_slug", "coin-change")
    store.set_meta("daily_slug", "two-sum")  # overwrite, not accumulate
    assert store.get_meta("daily_slug") == "two-sum"


# ---------------------------------------------------------------- review deck

def _review_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from lc import review
    return review


def test_review_add_schedules_the_first_review(tmp_path, monkeypatch):
    from datetime import date

    review = _review_env(tmp_path, monkeypatch)
    d = date(2026, 8, 15)
    item = review.add("coin-change", title="Coin Change", frontend_id="322",
                      difficulty="Medium", curve=[2, 4, 8], today=d)
    assert (item.level, item.due) == (1, "2026-08-17")

    stored = review.load()["coin-change"]
    assert stored.title == "Coin Change"
    assert stored.added == "2026-08-15"
    # Re-adding freshens metadata but must not reset the schedule.
    review.shift_level("coin-change", +1, [2, 4, 8], today=d)
    again = review.add("coin-change", title="Coin Change!", frontend_id="322",
                       difficulty="Medium", curve=[2, 4, 8], today=d)
    assert again.level == 2 and again.title == "Coin Change!"


def test_a_submit_marks_the_problem_without_grading_it(tmp_path, monkeypatch):
    """Levels are the user's to set — lc only records that they re-solved it."""
    from datetime import date

    review = _review_env(tmp_path, monkeypatch)
    curve = [1, 2, 4, 7]
    d = date(2026, 8, 15)
    review.add("s", curve=curve, today=d)
    review.shift_level("s", +2, curve, today=d)      # level 3
    before = review.load()["s"]

    note = review.record_submit("s", True, today=d)
    after = review.load()["s"]
    assert (after.level, after.due) == (before.level, before.due), "must not reschedule"
    assert after.attempt_today(d) == "passed"
    assert note is not None and "solved" in note and "level 3" in note

    # A failed submit marks it the other way, still without touching the level.
    review.record_submit("s", False, today=d)
    after = review.load()["s"]
    assert (after.level, after.due) == (before.level, before.due)
    assert after.attempt_today(d) == "failed"

    # Grading by hand moves it and clears the mark.
    graded = review.shift_level("s", +1, curve, today=d)
    assert graded.level == 4
    assert graded.attempt_today(d) == ""
    assert review.load()["s"].attempt_today(d) == ""

    # Yesterday's mark does not colour today's row.
    review.record_submit("s", True, today=d)
    assert review.load()["s"].attempt_today(date(2026, 8, 16)) == ""

    # A problem that is not on the deck is simply ignored.
    assert review.record_submit("ghost", True, today=d) is None


def test_autograde_moves_the_level_with_the_verdict(tmp_path, monkeypatch):
    """`lc config autograde on`: accepted climbs a level, a failure drops one."""
    from datetime import date

    review = _review_env(tmp_path, monkeypatch)
    curve = [1, 2, 4, 7]
    past, d = date(2026, 8, 10), date(2026, 8, 15)
    review.add("s", curve=curve, today=past)
    review.shift_level("s", +1, curve, today=past)   # level 2, graded days ago

    note = review.record_submit("s", True, today=d, curve=curve)
    item = review.load()["s"]
    assert item.level == 3
    assert item.due == "2026-08-19", "rescheduled from today at the new level"
    assert item.graded == d.isoformat()
    assert "level 2 → 3" in note
    # The mark records what this submit did, and tints the row.
    assert item.attempt_today(d) == "passed"

    # The next day, a failure takes it back down.
    d2 = date(2026, 8, 16)
    note = review.record_submit("s", False, today=d2, curve=curve)
    item = review.load()["s"]
    assert item.level == 2
    assert item.due == "2026-08-18"
    assert "level 3 → 2" in note


def test_autograde_grades_only_once_a_day(tmp_path, monkeypatch):
    """Re-submitting a passing solution is one recall, not five."""
    from datetime import date

    review = _review_env(tmp_path, monkeypatch)
    curve = [1, 2, 4, 7]
    past, d = date(2026, 8, 10), date(2026, 8, 15)
    review.add("s", curve=curve, today=past)

    review.record_submit("s", True, today=d, curve=curve)
    assert review.load()["s"].level == 2
    for _ in range(4):
        note = review.record_submit("s", True, today=d, curve=curve)
        assert "already graded today" in note
    assert review.load()["s"].level == 2, "must not ratchet up"


def test_autograde_never_overrides_a_hand_grade(tmp_path, monkeypatch):
    """+ / - / 0 are the override; a later submit must not undo them.

    The guard used to ask "has a *submit* graded this today?", which a hand
    grade slipped straight past: submit (level up), press - twice ("I
    peeked"), submit an optimised version — and the demotion was quietly
    re-promoted. Whoever grades first that day wins, and a hand grade is a
    grade.
    """
    from datetime import date

    review = _review_env(tmp_path, monkeypatch)
    curve = [1, 2, 4, 7]
    past, d = date(2026, 8, 10), date(2026, 8, 15)
    review.add("s", curve=curve, today=past)
    review.shift_level("s", +2, curve, today=past)   # level 3, graded days ago

    assert "level 3 → 4" in review.record_submit("s", True, today=d, curve=curve)
    review.shift_level("s", -1, curve, today=d)
    review.shift_level("s", -1, curve, today=d)      # the user knows better
    note = review.record_submit("s", True, today=d, curve=curve)
    assert "level 2 stands" in note
    item = review.load()["s"]
    assert item.level == 2
    # The attempt is still recorded — the row shows what today's code did.
    assert item.attempt_today(d) == "passed"

    # A hand grade with no earlier submit stands the same way.
    d2 = date(2026, 8, 16)
    review.shift_level("s", +1, curve, today=d2)     # level 3, by hand
    assert "level 3 stands" in review.record_submit("s", False, today=d2, curve=curve)
    item = review.load()["s"]
    assert item.level == 3
    assert item.attempt_today(d2) == "failed"


def test_the_day_a_problem_is_added_is_not_a_review(tmp_path, monkeypatch):
    """Solving a problem the day it joined the deck must not skip level 1.

    add() schedules the first review for tomorrow; an accepted submit hours
    later is the *initial* solve, not recall, and bumping it would skip the
    one-day review the curve deliberately starts with. It also makes day
    zero order-independent: m-then-solve and solve-then-m both end at
    level 1, due tomorrow.
    """
    from datetime import date

    review = _review_env(tmp_path, monkeypatch)
    curve = [1, 2, 4, 7]
    d = date(2026, 8, 15)
    review.add("s", curve=curve, today=d)

    note = review.record_submit("s", True, today=d, curve=curve)
    item = review.load()["s"]
    assert "added today" in note
    assert item.level == 1
    assert item.due == "2026-08-16"
    assert item.attempt_today(d) == "passed"

    # Tomorrow it is due, and the first real review grades as usual.
    d2 = date(2026, 8, 16)
    assert "level 1 → 2" in review.record_submit("s", True, today=d2, curve=curve)


def test_autograde_clamps_at_both_ends_of_the_curve(tmp_path, monkeypatch):
    """A fail at level 1 has nowhere to fall, a pass at the top nowhere to climb."""
    from datetime import date

    review = _review_env(tmp_path, monkeypatch)
    curve = [1, 2]
    past, d = date(2026, 8, 10), date(2026, 8, 15)
    review.add("floor", curve=curve, today=past)
    note = review.record_submit("floor", False, today=d, curve=curve)
    assert review.load()["floor"].level == 1
    assert "still at level 1" in note

    review.add("roof", curve=curve, today=past)
    review.shift_level("roof", +1, curve, today=past)  # level 2, the top
    note = review.record_submit("roof", True, today=d, curve=curve)
    assert review.load()["roof"].level == 2
    assert "still at level 2" in note


def test_autograde_is_off_unless_asked_for(tmp_path, monkeypatch):
    """Off by default, and a hand-edited "false" is not a yes."""
    from lc.config import Config

    assert Config().autograde is False
    assert Config(review_autograde=True).autograde is True
    # config.json is hand-editable — a truthy *string* must not reschedule a deck.
    assert Config(review_autograde="false").autograde is False
    assert Config(review_autograde="true").autograde is False


def test_a_malformed_attempt_flag_never_claims_a_pass(tmp_path, monkeypatch):
    """"false" is a truthy string — reading it as a pass is the worse mistake."""
    from datetime import date

    review = _review_env(tmp_path, monkeypatch)
    today = date(2026, 8, 15)
    for raw, expected in ((True, True), (False, False), ("false", False),
                          ("true", False), (1, False), (None, False)):
        items = review.items_from_raw(
            {"s": {"attempted": today.isoformat(), "attempt_passed": raw}}
        )
        assert items["s"].attempt_passed is expected, raw
    # And the mark only describes today.
    items = review.items_from_raw(
        {"s": {"attempted": "2026-08-14", "attempt_passed": True}}
    )
    assert items["s"].attempt_today(today) == ""
    assert items["s"].attempt_today(date(2026, 8, 14)) == "passed"


def test_grading_holds_its_invariants_over_a_long_run(tmp_path, monkeypatch):
    """Submit on the due date, over and over, and the schedule stays sane."""
    import random
    from datetime import date

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from lc import review

    curve = list(review.DEFAULT_CURVE)
    rng = random.Random(7)
    review.add("p", frontend_id="1", curve=curve, today=date(2026, 1, 1))

    for _ in range(80):
        item = review.load()["p"]
        day = date.fromisoformat(item.due)      # jump to when it comes due
        before = item.level
        passed = rng.random() < 0.7
        review.record_submit("p", passed, today=day)          # marks it
        review.shift_level("p", 1 if passed else -99, curve, today=day)  # you grade it
        item = review.load()["p"]

        assert 1 <= item.level <= len(curve)
        # the schedule is always exactly one curve gap past the grading day
        gap = (date.fromisoformat(item.due) - date.fromisoformat(item.graded)).days
        assert gap == curve[item.level - 1]
        assert date.fromisoformat(item.due) > day, "a review must land in the future"
        if passed:
            assert item.level == min(before + 1, len(curve))
        else:
            assert item.level == 1


def test_refreshing_metadata_stamps_the_edit(tmp_path, monkeypatch):
    """Otherwise the other machine's emptier copy wins the next merge."""
    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from lc import review

    curve = [1, 2, 4]
    review.add("two-sum", curve=curve)
    first = review.load()["two-sum"].updated

    review.add("two-sum", title="Two Sum", frontend_id="1", difficulty="Easy",
               curve=curve)
    filled = review.load()["two-sum"]
    assert filled.title == "Two Sum"
    assert filled.updated > first, "a metadata change must be stamped"

    # A no-op re-add changes nothing, so it must not churn the timestamp.
    review.add("two-sum", title="Two Sum", frontend_id="1", difficulty="Easy",
               curve=curve)
    assert review.load()["two-sum"].updated == filled.updated


def test_scheduling_survives_a_curve_that_lost_levels():
    from lc import review

    # A level past the end of the curve gets its top gap, never an IndexError.
    assert review._interval([1, 2, 4], 9) == 4
    assert review._interval([1, 2, 4], 0) == 1
    assert review._interval([], 3) == review.DEFAULT_CURVE[2]


def test_review_level_is_clamped_to_the_curve(tmp_path, monkeypatch):
    from datetime import date

    review = _review_env(tmp_path, monkeypatch)
    curve = [2, 4]
    d = date(2026, 8, 15)
    review.add("s", curve=curve, today=d)
    assert review.shift_level("s", +7, curve, today=d).level == 2  # top of a 2-level curve
    assert review.load()["s"].due == "2026-08-19"
    assert review.shift_level("s", -7, curve, today=d).level == 1
    # Climbing while already at the top stays at the top.
    review.shift_level("s", +1, curve, today=d)
    assert review.shift_level("s", +1, curve, today=d).level == 2


def test_review_forget_drops_straight_to_level_one(tmp_path, monkeypatch):
    """A lapse is not one level down: it comes back tomorrow, from any level."""
    from datetime import date

    review = _review_env(tmp_path, monkeypatch)
    curve = list(review.DEFAULT_CURVE)
    d = date(2026, 8, 15)
    review.add("s", curve=curve, today=d)
    review.shift_level("s", +8, curve, today=d)          # up to level 9
    assert review.load()["s"].due == "2027-02-11"        # 180 days away

    item = review.forget("s", curve, today=d)
    assert (item.level, item.due) == (1, "2026-08-16")   # tomorrow
    assert item.graded == "2026-08-15"
    # Grading answers the "you solved this today" prompt either way.
    assert item.attempted == "" and item.attempt_passed is False
    assert review.load()["s"].level == 1                 # and it is on disk

    # Already at the bottom: still a grade, still back tomorrow.
    assert review.forget("s", curve, today=d).due == "2026-08-16"
    # Unknown and removed problems are a no-op, not a crash.
    assert review.forget("nope", curve, today=d) is None
    review.remove("s")
    assert review.forget("s", curve, today=d) is None


def test_review_postpone_single_and_all_due(tmp_path, monkeypatch):
    from datetime import date

    review = _review_env(tmp_path, monkeypatch)
    d = date(2026, 8, 15)
    review.add("overdue", curve=[1], today=date(2026, 8, 10))
    review.add("later", curve=[30], today=d)

    assert review.postpone_due(today=d) == 1  # only the overdue one moves
    assert review.load()["overdue"].due == "2026-08-16"
    assert review.load()["later"].due == "2026-09-14"

    # Postponing one problem pushes past today for due items, past its own
    # date for future ones.
    assert review.postpone("overdue", today=d).due == "2026-08-17"
    assert review.postpone("later", today=d).due == "2026-09-15"


def test_review_handles_unknown_slugs_and_corrupt_files(tmp_path, monkeypatch):
    review = _review_env(tmp_path, monkeypatch)
    assert review.load() == {}
    assert review.record_submit("ghost", True) is None
    assert review.shift_level("ghost", 1, [2]) is None
    assert review.postpone("ghost") is None
    assert review.remove("ghost") is False

    review.review_path().write_text("{not json")
    assert review.load() == {}
    review.add("s", curve=[2])  # writable again after the corruption
    assert "s" in review.load()


def test_default_curve_is_ebbinghaus():
    """The out-of-the-box schedule is the classic 1/2/4/7/15-day ladder."""
    from lc import review

    assert review.DEFAULT_CURVE[:5] == (1, 2, 4, 7, 15)
    assert review.DEFAULT_CURVE == (1, 2, 4, 7, 15, 30, 60, 90, 180, 365)
    # Strictly increasing, and every gap is a schedulable number of days.
    gaps = list(review.DEFAULT_CURVE)
    assert gaps == sorted(set(gaps))
    assert all(1 <= g <= review.MAX_GAP_DAYS for g in gaps)


def test_review_curve_of_sanitizes_config():
    from lc.config import Config
    from lc import review

    assert review.curve_of(Config()) == list(review.DEFAULT_CURVE)
    assert review.curve_of(Config(review_curve=[2, 4, 8])) == [2, 4, 8]
    assert review.curve_of(Config(review_curve=[3, "6"])) == [3, 6]
    # Nothing usable — nonsense entries and a non-list — falls back whole.
    assert review.curve_of(Config(review_curve=[0, -3, "x"])) == list(review.DEFAULT_CURVE)
    assert review.curve_of(Config(review_curve="oops")) == list(review.DEFAULT_CURVE)
    # A gap timedelta would choke on (int(1e999) raises OverflowError) or one
    # past the cap must not survive into scheduling.
    assert review.curve_of(Config(review_curve=[1e999, 2])) == [2]
    assert review.curve_of(Config(review_curve=[999_999, 5])) == [5]


def test_review_load_coerces_a_hand_edited_file(tmp_path, monkeypatch):
    review = _review_env(tmp_path, monkeypatch)
    review.review_path().write_text(json.dumps({
        "ok": {"level": "3", "due": "2026-08-20", "title": "Fine"},
        "odd": {"level": None, "due": 42, "title": 7},
        "not-a-dict": [1, 2, 3],
    }))
    items = review.load()
    assert "not-a-dict" not in items
    assert items["ok"].level == 3 and items["ok"].due == "2026-08-20"
    assert items["odd"].level == 1 and items["odd"].due == "" and items["odd"].title == ""
    # ...and the coerced values survive every operation without crashing.
    from datetime import date
    d = date(2026, 8, 15)
    assert items["odd"].due_in(d) == 0
    assert review.shift_level("odd", +1, [2, 4], today=d).level == 2
    assert review.postpone("ok", today=d).due == "2026-08-21"
    assert review.record_submit("ok", False, today=d) is not None


def test_cli_review_add_list_and_remove(tmp_path, monkeypatch):
    from datetime import date

    review = _review_env(tmp_path, monkeypatch)
    from lc import store
    from lc.api import ProblemSummary
    from typer.testing import CliRunner
    from lc.cli import app

    store.replace_index([
        ProblemSummary("322", "Coin Change", "coin-change", "Medium", 45.0, False, None),
    ])
    runner = CliRunner()

    result = runner.invoke(app, ["review", "add", "322", "-l", "3"])
    assert result.exit_code == 0, result.output
    item = review.load()["coin-change"]
    assert item.level == 3
    assert item.title == "Coin Change"

    result = runner.invoke(app, ["review"])
    assert result.exit_code == 0, result.output
    assert "Coin Change" in result.output

    # A plain re-add freshens the entry but must not reset the level.
    result = runner.invoke(app, ["review", "add", "322"])
    assert result.exit_code == 0, result.output
    assert review.load()["coin-change"].level == 3

    # Postpone: nothing due yet, then one due after we pull the date back.
    result = runner.invoke(app, ["review", "postpone"])
    assert "nothing due" in result.output
    items = review.load()
    items["coin-change"].due = date.today().isoformat()
    review.save(items)
    result = runner.invoke(app, ["review", "postpone"])
    assert "postponed 1" in result.output

    # `lc review level` sets the level by hand.
    result = runner.invoke(app, ["review", "level", "322", "2"])
    assert result.exit_code == 0, result.output
    assert review.load()["coin-change"].level == 2

    result = runner.invoke(app, ["review", "rm", "coin change"])
    assert result.exit_code == 0, result.output
    # Off the deck, but a tombstone stays behind so the removal can sync.
    assert review.live(review.load()) == {}
    assert review.load()["coin-change"].removed

    result = runner.invoke(app, ["review", "rm", "322"])
    assert result.exit_code == 1  # already gone


def test_cli_config_curve_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from typer.testing import CliRunner
    from lc import review
    from lc.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["config", "curve", "3, 6, 12"])
    assert result.exit_code == 0, result.output
    assert load_config().review_curve == [3, 6, 12]
    assert review.curve_of(load_config()) == [3, 6, 12]

    result = runner.invoke(app, ["config", "curve", "reset"])
    assert result.exit_code == 0, result.output
    assert load_config().review_curve == []
    assert review.curve_of(load_config()) == list(review.DEFAULT_CURVE)

    assert runner.invoke(app, ["config", "curve", "0"]).exit_code == 1
    assert runner.invoke(app, ["config", "curve", "banana"]).exit_code == 1
    assert runner.invoke(app, ["config", "curve", "2,999999"]).exit_code == 1


# ----------------------------------------------------------------- git sync

def _bare_repo(tmp_path):
    import subprocess

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(remote)],
                   check=True)
    return str(remote)


def test_two_machines_converge_over_repeated_syncs(tmp_path, monkeypatch):
    """The mac + WSL workflow: removals, same-day conflicts and postpones."""
    import sys

    remote = _bare_repo(tmp_path)
    curve = [1, 2, 4, 7]

    def on(machine: str):
        monkeypatch.setenv("LC_HOME", str(tmp_path / machine))
        for mod in [m for m in sys.modules if m.startswith("lc.")]:
            del sys.modules[mod]
        from lc import gitsync, review
        return gitsync, review

    def deck(review_mod):
        return sorted(review_mod.live(review_mod.load()))

    g, r = on("mac")
    for slug, fid in (("two-sum", "1"), ("coin-change", "322")):
        r.add(slug, title=slug, frontend_id=fid, curve=curve)
    g.push(remote)
    g, r = on("wsl")
    g.pull(remote)
    assert deck(r) == ["coin-change", "two-sum"]

    # A removal sticks locally and reaches the other machine.
    g, r = on("mac")
    r.remove("two-sum")
    g.sync(remote)
    assert deck(r) == ["coin-change"], "a sync must not undo your own removal"
    g, r = on("wsl")
    assert g.sync(remote)[:3] == (0, 0, 1), "the report must say a removal landed"
    assert deck(r) == ["coin-change"], "the removal must propagate"

    # Re-adding revives it everywhere — and the other machine's report calls
    # a problem re-appearing in its deck what it is: added, not "updated".
    r.add("two-sum", title="Two Sum", frontend_id="1", curve=curve)
    g.sync(remote)
    g, r = on("mac")
    assert g.sync(remote)[:3] == (1, 0, 0)
    assert "two-sum" in deck(r)

    # Same-day edits: the later one wins, whichever level it happens to be.
    r.shift_level("coin-change", +3, curve)
    g.sync(remote)
    g, r = on("wsl")
    g.pull(remote)
    r.shift_level("coin-change", -2, curve)
    expected = r.load()["coin-change"].level
    g.sync(remote)
    g, r = on("mac")
    g.sync(remote)
    assert r.load()["coin-change"].level == expected

    # A postpone is an edit too, and survives the round trip.
    r.postpone("coin-change")
    postponed = r.load()["coin-change"].due
    g.sync(remote)
    g, r = on("wsl")
    g.sync(remote)
    assert r.load()["coin-change"].due == postponed

    # Repeated syncing converges instead of oscillating, and stops committing.
    for i in range(6):
        g, _ = on("mac" if i % 2 == 0 else "wsl")
        g.sync(remote)
    mac_dump = on("mac")[1].dumps(on("mac")[1].load())
    wsl_dump = on("wsl")[1].dumps(on("wsl")[1].load())
    assert mac_dump == wsl_dump


def test_a_push_race_with_the_other_machine_is_retried(tmp_path, monkeypatch):
    import subprocess

    monkeypatch.setenv("LC_HOME", str(tmp_path / "home"))
    from lc import gitsync, review

    remote = _bare_repo(tmp_path)
    review.add("two-sum", frontend_id="1", curve=[1, 2])
    gitsync.push(remote)

    # The remote moves once, inside our fetch-to-push window.
    real = gitsync._commit_and_push
    fired: list[int] = []

    def racing(path, message):
        """The other machine lands a push between our fetch and our push."""
        if not fired:
            fired.append(1)
            other = tmp_path / "other-machine"
            subprocess.run(["git", "clone", "--quiet", remote, str(other)], check=True)
            (other / "note.txt").write_text("from the other machine\n")
            subprocess.run(["git", "-C", str(other), "add", "note.txt"], check=True)
            subprocess.run(
                ["git", "-C", str(other), "-c", "user.name=o", "-c", "user.email=o@x",
                 "commit", "--quiet", "-m", "other machine"], check=True)
            subprocess.run(["git", "-C", str(other), "push", "--quiet", "origin", "HEAD"],
                           check=True)
        return real(path, message)

    monkeypatch.setattr(gitsync, "_commit_and_push", racing)
    review.shift_level("two-sum", +1, [1, 2])
    count, changed = gitsync.push(remote)  # must not raise
    assert fired and changed and count == 1


def test_merge_prefers_the_most_recently_graded_side():
    from lc import review

    def it(slug, level, graded):
        return review.ReviewItem(slug=slug, level=level, graded=graded, due=graded)

    local = {"a": it("a", 2, "2026-08-01"), "b": it("b", 1, "2026-08-10")}
    remote = {"a": it("a", 5, "2026-08-09"), "c": it("c", 3, "2026-08-05")}
    merged, added, updated, removed = review.merge(local, remote)

    assert (added, updated, removed) == (1, 1, 0)
    assert merged["a"].level == 5      # remote graded later
    assert merged["b"].level == 1      # local only, untouched
    assert merged["c"].level == 3      # arrived from the remote
    # A stale remote entry must not win.
    back, added, updated, removed = review.merge(merged, {"b": it("b", 9, "2026-07-01")})
    assert (added, updated, removed) == (0, 0, 0) and back["b"].level == 1


def test_merge_counts_what_the_deck_view_actually_did():
    """A problem vanishing from the deck must not be reported as "updated".

    The counts feed the sync report, which is the only warning the user gets
    that a removal made on another machine just landed here. A tombstone
    hiding a live problem is removed, a live copy beating a tombstone is
    added (the deck grew), and tombstone-on-tombstone traffic counts as
    nothing, because nothing visible moved.
    """
    from lc import review

    def it(slug, graded, dead=""):
        return review.ReviewItem(slug=slug, level=1, graded=graded, due=graded,
                                 removed=dead)

    local = {"gone": it("gone", "2026-08-01"),
             "back": it("back", "2026-08-01", dead="2026-08-01"),
             "quiet": it("quiet", "2026-08-01", dead="2026-08-01")}
    remote = {"gone": it("gone", "2026-08-09", dead="2026-08-09"),
              "back": it("back", "2026-08-09"),
              "quiet": it("quiet", "2026-08-09", dead="2026-08-09"),
              "ghost": it("ghost", "2026-08-09", dead="2026-08-09")}
    merged, added, updated, removed = review.merge(local, remote)
    assert (added, updated, removed) == (1, 0, 1)
    assert sorted(review.live(merged)) == ["back"]
    # The invisible traffic still merged — only the counting ignored it.
    assert merged["quiet"].removed == "2026-08-09"
    assert "ghost" in merged


def test_git_sync_roundtrips_a_deck_between_two_homes(tmp_path, monkeypatch):
    from datetime import date

    remote = _bare_repo(tmp_path)

    monkeypatch.setenv("LC_HOME", str(tmp_path / "a"))
    from lc import gitsync, review

    review.add("coin-change", title="Coin Change", frontend_id="322",
               difficulty="Medium", curve=[2, 4], today=date(2026, 8, 15))
    total, changed = gitsync.push(remote)
    assert (total, changed) == (1, True)
    assert gitsync.push(remote)[1] is False  # nothing new to commit

    # A second machine starts empty and pulls the deck down.
    monkeypatch.setenv("LC_HOME", str(tmp_path / "b"))
    assert review.load() == {}
    assert gitsync.pull(remote) == (1, 0, 0)
    assert review.load()["coin-change"].title == "Coin Change"

    # It grades the problem and syncs; the first machine picks that up.
    review.shift_level("coin-change", +1, [2, 4], today=date(2026, 8, 17))
    gitsync.sync(remote)
    monkeypatch.setenv("LC_HOME", str(tmp_path / "a"))
    assert gitsync.pull(remote) == (0, 1, 0)
    assert review.load()["coin-change"].level == 2


def test_git_sync_writes_a_readable_table(tmp_path, monkeypatch):
    monkeypatch.setenv("LC_HOME", str(tmp_path / "home"))
    from lc import gitsync, review

    remote = _bare_repo(tmp_path)
    review.add("coin-change", title="Coin Change", frontend_id="322",
               difficulty="Medium", curve=[2])
    gitsync.push(remote)

    table = (gitsync.repo_dir() / gitsync.TABLE_FILE).read_text()
    assert "| 322 | [Coin Change](https://leetcode.com/problems/coin-change/)" in table
    assert (gitsync.repo_dir() / gitsync.DECK_FILE).exists()
    # README.md is the user's to own — lc must never write one.
    assert not (gitsync.repo_dir() / "README.md").exists()


def test_sync_status_walks_its_states(tmp_path, monkeypatch):
    monkeypatch.setenv("LC_HOME", str(tmp_path / "home"))
    from lc import gitsync, review
    from lc.config import load_config, save_config

    # No repo configured: nothing to say, and the TUI strip stays hidden.
    assert gitsync.status(load_config()).state == "off"
    assert gitsync.summary(load_config()) == ""

    remote = _bare_repo(tmp_path)
    cfg = load_config()
    cfg.review_repo = remote
    save_config(cfg)
    review.add("coin-change", title="Coin Change", frontend_id="322",
               difficulty="Medium", curve=[2, 4])
    assert gitsync.status(load_config()).state == "never"

    gitsync.sync(remote)
    state = gitsync.status(load_config())
    assert state.state == "clean" and state.synced_at is not None
    assert gitsync.summary(load_config()).startswith("✔ synced")

    # A local edit is something to push.
    review.postpone("coin-change")
    state = gitsync.status(load_config())
    assert (state.state, state.pending) == ("pending", 1)
    assert "1 change to push" in gitsync.summary(load_config())

    # A failure is remembered, then cleared by the next success.
    cfg.review_repo = str(tmp_path / "gone.git")
    save_config(cfg)
    with pytest.raises(gitsync.SyncError):
        gitsync.pull(cfg.review_repo)
    assert gitsync.status(load_config()).state == "failed"
    cfg.review_repo = remote
    save_config(cfg)
    gitsync.sync(remote)
    assert gitsync.status(load_config()).state == "clean"


def test_sync_status_never_touches_the_network(tmp_path, monkeypatch):
    """It is recomputed on every deck refresh — it must stay local."""
    monkeypatch.setenv("LC_HOME", str(tmp_path / "home"))
    from lc import gitsync, review
    from lc.config import load_config, save_config

    remote = _bare_repo(tmp_path)
    cfg = load_config()
    cfg.review_repo = remote
    save_config(cfg)
    review.add("coin-change", curve=[2])
    gitsync.sync(remote)

    def no_git(*a, **kw):
        raise AssertionError("status() ran a git command")

    monkeypatch.setattr(gitsync.subprocess, "run", no_git)
    assert gitsync.status(load_config()).state == "clean"


def test_ago_reads_as_a_relative_clock():
    from lc import gitsync

    now = 1_000_000.0
    assert gitsync.ago(None) == "never"
    assert gitsync.ago(now - 5, now=now) == "just now"
    assert gitsync.ago(now - 600, now=now) == "10m ago"
    assert gitsync.ago(now - 7200, now=now) == "2h ago"
    assert gitsync.ago(now - 3 * 86400, now=now) == "3d ago"
    # A clock that jumped backwards must not print a negative age.
    assert gitsync.ago(now + 60, now=now) == "just now"


def test_pushing_an_unchanged_deck_is_a_no_op_on_a_later_day(tmp_path, monkeypatch):
    """REVIEW.md must be a function of the deck, not of what day it is.

    Anything relative in it — "3d overdue", "2 due", "synced <today>" — would
    diff overnight and commit every morning for a deck that never moved.
    """
    import datetime

    monkeypatch.setenv("LC_HOME", str(tmp_path / "home"))
    from lc import gitsync, review

    remote = _bare_repo(tmp_path)
    review.add("coin-change", title="Coin Change", frontend_id="322",
               difficulty="Medium", curve=[2, 4])
    assert gitsync.push(remote) == (1, True)

    real = datetime.date

    class Tomorrow(real):
        @classmethod
        def today(cls):
            return real.today() + datetime.timedelta(days=400)

    # raising=False: gitsync imports no date today — the patch is a tripwire
    # for the future one that would make the table day-dependent again.
    monkeypatch.setattr(gitsync, "date", Tomorrow, raising=False)
    assert gitsync.push(remote)[1] is False
    # ...and the rendered table still carries the facts, just absolute ones.
    table = (gitsync.repo_dir() / gitsync.TABLE_FILE).read_text()
    assert review.load()["coin-change"].due in table
    assert "overdue" not in table


def test_concurrent_deck_writes_neither_crash_nor_lose_entries(tmp_path, monkeypatch):
    """The judge and sync workers are threads; the UI grades on the main one."""
    import threading

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from lc import review

    curve = [2, 4, 8]
    for i in range(10):
        review.add(f"p{i}", title=f"P{i}", frontend_id=str(i), curve=curve)

    errors: list[str] = []

    def grade(lo: int, hi: int) -> None:
        try:
            for _ in range(20):
                for i in range(lo, hi):
                    review.shift_level(f"p{i}", +1, curve)
                    review.shift_level(f"p{i}", -1, curve)
        except Exception as exc:  # a crash in a worker is the bug
            errors.append(repr(exc))

    threads = [threading.Thread(target=grade, args=(0, 5)),
               threading.Thread(target=grade, args=(5, 10))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(review.load()) == 10
    # Every save cleans up after itself, whichever thread wrote it.
    assert list(tmp_path.glob("review.json.*")) == []


def test_blank_workspace_falls_back_instead_of_meaning_here():
    from lc.config import DEFAULT_WORKSPACE, Config

    assert Config(workspace="").workspace_path == DEFAULT_WORKSPACE
    assert Config(workspace="~/code/lc").workspace_path.name == "lc"


def test_git_errors_name_the_real_problem_not_the_last_line():
    """Git's complaint is multi-line; its last line is often a sentence fragment."""
    from lc import gitsync

    ssh = (
        "git@github.com: Permission denied (publickey).\n"
        "fatal: Could not read from remote repository.\n"
        "\n"
        "Please make sure you have the correct access rights\n"
        "and the repository exists.\n"
    )
    exc = gitsync._explain("clone", ssh)
    assert "SSH key" in str(exc)
    assert "and the repository exists" not in str(exc)  # the useless fragment
    assert "https://" in exc.hint

    creds = "fatal: could not read Username for 'https://github.com': terminal prompts disabled"
    assert "credentials" in str(gitsync._explain("push", creds))
    assert "gh auth setup-git" in gitsync._explain("push", creds).hint

    missing = "remote: Repository not found.\nfatal: repository not found\n"
    assert "does not exist" in str(gitsync._explain("clone", missing))

    # Unrecognised: prefer git's own diagnosis line over whatever printed last.
    other = ("Cloning into 'x'...\n"
             "fatal: the disk is on fire\n"
             "and the repository exists.\n")
    assert str(gitsync._explain("clone", other)) == "git clone: fatal: the disk is on fire"
    # And never crash on empty output.
    assert "failed" in str(gitsync._explain("push", "  \n \n"))

    # GH007's output ends with the push-race rule's needle, and calling it the
    # race told the user to retry — into the same wall, as many times as they
    # obeyed. The email-privacy rule has to win, and has to not be retryable.
    gh007 = (
        "remote: error: GH007: Your push would publish a private email address.\n"
        "remote: You can make your email public or disable this protection by visiting:\n"
        "remote: https://github.com/settings/emails\n"
        "To github.com:you/lc-review.git\n"
        " ! [remote rejected] HEAD -> main (push declined due to email privacy restrictions)\n"
        "error: failed to push some refs to 'github.com:you/lc-review.git'\n"
    )
    exc = gitsync._explain("push", gh007)
    assert "private email" in str(exc)
    assert "noreply" in exc.hint
    assert exc.retryable is False, "retrying cannot fix an identity"
    # A plain rejection with no GH007 in sight is still read as the race.
    race = (
        "To github.com:you/lc-review.git\n"
        " ! [rejected]        main -> main (fetch first)\n"
        "error: failed to push some refs to 'github.com:you/lc-review.git'\n"
    )
    assert gitsync._explain("push", race).retryable is True

    # `git -c user.name=lc commit` must be reported as "commit", not "-c".
    assert gitsync._command_name(("-c", "user.name=lc", "commit", "-m", "x")) == "commit"
    assert gitsync._command_name(("--quiet", "push")) == "push"
    assert gitsync._command_name(("-c", "a=b")) == "git"


def test_git_sync_reports_a_bad_remote_cleanly(tmp_path, monkeypatch):
    monkeypatch.setenv("LC_HOME", str(tmp_path / "home"))
    from lc import gitsync

    with pytest.raises(gitsync.SyncError):
        gitsync.pull(str(tmp_path / "nope.git"))


def test_cli_review_sync_without_a_repo_explains_itself(tmp_path, monkeypatch):
    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from typer.testing import CliRunner
    from lc.cli import app

    result = CliRunner().invoke(app, ["review", "sync"])
    assert result.exit_code == 1
    assert "lc config repo" in result.output


def test_cli_config_repo_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from typer.testing import CliRunner
    from lc.cli import app

    runner = CliRunner()
    assert runner.invoke(app, ["config", "repo", "git@github.com:me/d.git"]).exit_code == 0
    assert load_config().review_repo == "git@github.com:me/d.git"
    assert runner.invoke(app, ["config", "repo", "none"]).exit_code == 0
    assert load_config().review_repo == ""


def test_cli_review_add_uses_the_current_problem_directory(tmp_path, monkeypatch):
    """What Vim's \\m and a bare `lc review add` rely on."""
    monkeypatch.setenv("LC_HOME", str(tmp_path / ".lc"))
    from lc import review, store, workspace
    from lc.api import ProblemSummary
    from lc.config import Config
    from typer.testing import CliRunner
    from lc.cli import app

    store.replace_index([
        ProblemSummary("322", "Coin Change", "coin-change", "Medium", 45.0, False, None),
    ])
    created = workspace.create(Config(workspace=str(tmp_path / "ws")), PROBLEM,
                               resolve("python3"))
    monkeypatch.chdir(created.directory)

    result = CliRunner().invoke(app, ["review", "add"])
    assert result.exit_code == 0, result.output
    assert "coin-change" in review.load()

    # Outside a problem directory it says so instead of guessing.
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["review", "add"])
    assert result.exit_code == 1
    assert "not a problem directory" in result.output


# ------------------------------------------------------------------ bare `lc`

def test_bare_lc_prints_help_when_not_a_terminal():
    """Piped/scripted `lc` must never launch the full-screen app."""
    from typer.testing import CliRunner
    from lc.cli import app

    result = CliRunner().invoke(app, [])
    assert result.exit_code == 0, result.output
    assert "Usage" in result.output


# ------------------------------------------------------------- error handling

def test_main_prints_clean_errors_without_a_traceback(monkeypatch, capsys):
    """A network failure escaping a command must not dump a traceback."""
    import lc.cli as cli

    def raising_app():
        raise cli.LeetCodeError("network error talking to LeetCode: boom")

    monkeypatch.setattr(cli, "app", raising_app)
    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    stderr = capsys.readouterr().err
    assert "boom" in stderr
    assert "Traceback" not in stderr


def test_main_expired_session_suggests_logging_in(monkeypatch, capsys):
    import lc.cli as cli

    def raising_app():
        raise cli.AuthError("LeetCode rejected the session")

    monkeypatch.setattr(cli, "app", raising_app)
    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    stderr = capsys.readouterr().err
    assert "lc login" in stderr
    assert "Traceback" not in stderr


# ----------------------------------------------------------------- languages

def test_choose_resolves_aliases_and_falls_back():
    from lc.langs import choose

    # An alias in the favourites must match the real snippet slug.
    assert choose("python3", ["go"], {"golang": "..."}).slug == "golang"
    # The default wins when the problem offers it.
    assert choose("python3", ["go"], {"python3": "...", "golang": "..."}).slug == "python3"
    # Nothing configured matches — fall back to anything lc understands.
    assert choose("python3", ["javascript"], {"mysql": "..."}).slug == "mysql"
    assert choose("python3", [], {}) is None


# ----------------------------------------------------------------------- tui

def test_the_footer_carries_the_loop_and_hides_the_rest():
    """A footer of fifteen keys is a wall; the rest live behind `?`."""
    from lc.tui import LeetCodeTUI, ReviewList

    app_shown = {b.key for b in LeetCodeTUI.BINDINGS if b.show}
    app_hidden = {b.key for b in LeetCodeTUI.BINDINGS if not b.show}
    assert app_shown == {"slash", "p", "r", "s", "m", "n", "tab",
                         "question_mark", "q"}
    # Everything taken off the footer must still be bound, not deleted.
    for key in ("c", "d", "t", "o", "D", "ctrl+r", "R"):
        assert key in app_hidden, key

    review_shown = {b.key for b in ReviewList.BINDINGS if b.show}
    assert review_shown == {"plus,equals_sign", "g"}
    review_hidden = {b.key for b in ReviewList.BINDINGS if not b.show}
    assert {"minus,underscore", "z", "Z", "x"} <= review_hidden

    # Every binding still names an action, shown or not.
    for binding in LeetCodeTUI.BINDINGS + ReviewList.BINDINGS:
        assert binding.action, binding.key
    # ...and `?` reaches the panel that lists them all.
    assert hasattr(LeetCodeTUI, "action_toggle_keys")


def test_daily_note_says_which_day_and_when_it_turns_over():
    """East of Greenwich the local date runs ahead of LeetCode's UTC daily."""
    import time

    from lc.tui import daily_note

    def at(hour, minute):
        return time.struct_time((2026, 8, 15, hour, minute, 0, 0, 227, 0))

    # 23:17 UTC is already the 16th in Adelaide — the date is what explains it.
    assert daily_note("2026-08-15", at(23, 17)) == "★ daily 08-15, next in 43m"
    assert daily_note("2026-08-15", at(23, 59)) == "★ daily 08-15, next in 1m"
    assert daily_note("2026-08-15", at(12, 0)) == "★ daily 08-15, next in 12h"
    assert daily_note("2026-08-15", at(0, 5)) == "★ daily 08-15, next in 23h55m"
    # Never "next in 0m": there is always some of the day left.
    assert daily_note("2026-08-15", at(23, 59, )) .endswith("1m")
    # An unknown date still gives the countdown rather than a stray separator.
    assert daily_note("", at(23, 17)) == "★ daily, next in 43m"


def test_pin_daily_moves_the_daily_to_the_front():
    from lc.api import ProblemSummary
    from lc.tui import pin_daily

    rows = [
        ProblemSummary("1", "Two Sum", "two-sum", "Easy", 50.0, False, None),
        ProblemSummary("322", "Coin Change", "coin-change", "Medium", 45.0, False, None),
    ]
    assert pin_daily(rows, "coin-change") is True
    assert [p.slug for p in rows] == ["coin-change", "two-sum"]
    # Not in the filtered list (or unknown) — leave the order alone.
    assert pin_daily(rows, "word-ladder") is False
    assert pin_daily(rows, None) is False
    assert [p.slug for p in rows] == ["coin-change", "two-sum"]


def test_grading_keeps_the_cursor_on_the_problem(tmp_path, monkeypatch):
    """A grade re-sorts the deck; the cursor has to follow the problem.

    Restoring it by row number instead left it on whatever slid into that
    slot, so a second + or - graded a problem the user never looked at — and
    the one they were aiming at looked like it had not moved.
    """
    import asyncio
    from datetime import date

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from lc import review, tui

    today = date.today().isoformat()

    def item(slug, fid, level):
        return {"title": slug, "frontend_id": fid, "difficulty": "Easy",
                "level": level, "added": today, "graded": today,
                "due": today, "updated": "2026-01-01T00:00:00.000000Z"}

    # Same due date today, so the order is by problem number: two-sum first.
    (tmp_path / "review.json").write_text(json.dumps({
        "two-sum": item("two-sum", "1", 6),
        "move-zeroes": item("move-zeroes", "283", 1),
    }))

    async def grade():
        app = tui.LeetCodeTUI()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("tab")        # to the Review tab
            await pilot.pause()
            seen = []
            # underscore too: it is shift-minus, and binding only half of a
            # shifted pair means holding shift silently does nothing.
            for key in ("minus", "plus", "plus", "underscore", "0"):
                await pilot.press(key)
                await pilot.pause()
                deck = review.load()
                seen.append((deck["two-sum"].level, deck["move-zeroes"].level))
            return seen

    # Every keystroke lands on the row the cursor started on, even though
    # demoting it (6 -> 5, due in 15 days) moves it below move-zeroes.
    # ...and 0 says "no idea at all", from wherever it was.
    assert asyncio.run(grade()) == [(5, 1), (6, 1), (7, 1), (6, 1), (1, 1)]


def test_problem_header_url_is_a_real_hyperlink():
    """It was styled to look like a link but was not one — clicks did nothing."""
    import io

    from rich.console import Console

    from lc.render import problem_header

    out = io.StringIO()
    Console(file=out, force_terminal=True, width=80).print(problem_header(PROBLEM))
    line = next(l for l in out.getvalue().splitlines() if "leetcode.com" in l)
    # OSC 8, the terminal hyperlink escape — not just blue and underlined.
    assert "\x1b]8;" in line
    assert PROBLEM.url in line          # ...and still readable where OSC 8 is not


def test_clicking_the_url_in_the_tui_opens_the_browser(tmp_path, monkeypatch):
    """OSC 8 is not enough: the TUI captures the mouse, so the terminal never
    sees the click. Textual dispatches its own clicks through style meta."""
    import asyncio

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from lc import tui

    opened: list[str] = []
    monkeypatch.setattr(tui, "open_url", lambda url: opened.append(url) or True)

    async def click_it():
        app = tui.LeetCodeTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            app._show(PROBLEM)          # no network: render this problem directly
            await pilot.pause()
            cells = [
                (x, y)
                for y in range(40)
                for x in range(120)
                if app.screen.get_style_at(x, y).meta.get("@click")
            ]
            if not cells:
                return None
            await pilot.click(offset=cells[len(cells) // 2])
            await pilot.pause()
            return len(cells)

    cells = asyncio.run(click_it())
    shown = PROBLEM.url.removeprefix("https://").rstrip("/")
    assert cells and cells >= len(shown) - 2     # the url itself is the target
    # ...and the click still opens the full address, scheme and all.
    assert opened == [PROBLEM.url]


def test_the_key_list_can_be_closed_without_quitting(tmp_path, monkeypatch):
    """`?` opens an overlay with no obvious way out, and `q` sat right there
    in the footer — pressing it to dismiss the list quit the whole app."""
    import asyncio

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from lc import tui

    async def keys():
        app = tui.LeetCodeTUI()
        seen = []
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            for key in ("question_mark", "escape", "question_mark", "q", "q"):
                await pilot.press(key)
                await pilot.pause()
                seen.append((bool(app.screen.query("HelpPanel")), not app._exit))
        return seen

    # open, esc closes it, open again, q closes it — and only then does q quit.
    assert asyncio.run(keys()) == [
        (True, True), (False, True), (True, True), (False, True), (False, False)
    ]


def test_the_splitter_hands_width_to_either_pane(tmp_path, monkeypatch):
    """The divider used to be the left pane's border — paint, with nothing
    there for the mouse to grab."""
    import asyncio

    from textual import events

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from lc import tui

    async def drag():
        app = tui.LeetCodeTUI()
        shapes = []
        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.pause()
            left = app.query_one("#left")
            right = app.query_one("#right")
            bar = app.query_one("#splitter", tui.Splitter)
            shapes.append((left.region.width, right.region.width))
            for target in (100, 30, 2, 400):
                await pilot.mouse_down(tui.Splitter, offset=(0, 5))
                await pilot.pause()
                bar.post_message(events.MouseMove(
                    widget=bar, x=0, y=5, delta_x=1, delta_y=0, button=1,
                    shift=False, meta=False, ctrl=False,
                    screen_x=target, screen_y=5,
                ))
                await pilot.pause()
                await pilot.mouse_up(tui.Splitter, offset=(0, 5))
                await pilot.pause()
                shapes.append((left.region.width, right.region.width))
        return shapes

    floor = tui.Splitter.MIN_PANE
    shapes = asyncio.run(drag())
    assert shapes[1][0] == 100 and shapes[2][0] == 30   # the pane follows the mouse
    assert shapes[3][0] == floor                        # dragged off the left edge
    assert shapes[4][1] == floor                        # ...and off the right
    # Neither side is ever squeezed away, and the two always fill the row.
    assert all(l >= floor and r >= floor for l, r in shapes)
    assert all(l + 1 + r == 160 for l, r in shapes)


def test_a_narrow_pane_shows_the_whole_url():
    """Vim's statement split is ~60 columns, and a URL is one long word: it
    was truncated mid-slug, which cannot be clicked, copied or even read.
    Folding it instead was honest but ugly — a lone "/" on its own line — so
    the scheme and trailing slash go, which fits most problems on one line."""
    import io
    from dataclasses import replace

    from rich.console import Console

    from lc.render import problem_header

    def url_lines(problem, width=60):
        out = io.StringIO()
        Console(file=out, width=width, no_color=True).print(problem_header(problem))
        lines = out.getvalue().splitlines()
        i = next(n for n, l in enumerate(lines) if l.startswith("url"))
        rest = [l for l in lines[i + 1:] if l.strip()]
        return [lines[i]] + rest[:1]

    shown = PROBLEM.url.removeprefix("https://").rstrip("/")
    lines = url_lines(PROBLEM)
    assert "…" not in "".join(lines)
    assert shown in lines[0]              # one line, whole address

    # A slug long enough to fold still breaks inside itself, never onto a
    # line holding nothing but the trailing slash.
    long_lines = url_lines(replace(PROBLEM, slug="a" * 60))
    assert len(long_lines) == 2 and len(long_lines[1].strip()) > 1


def test_a_submit_aims_the_deck_cursor_at_the_problem(tmp_path, monkeypatch):
    """Tabbing to the deck after a submit must land on what you just solved.

    Otherwise the cursor is still parked wherever it was left, and the + or -
    pressed next grades an unrelated problem.
    """
    import asyncio
    from datetime import date

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from lc import review, tui

    today = date.today().isoformat()

    def item(slug, fid, level):
        return {"title": slug, "frontend_id": fid, "difficulty": "Easy",
                "level": level, "added": today, "graded": today,
                "due": today, "updated": "2026-01-01T00:00:00.000000Z"}

    # Both due today, so the order is by problem number: two-sum first.
    (tmp_path / "review.json").write_text(json.dumps({
        "two-sum": item("two-sum", "1", 3),
        "move-zeroes": item("move-zeroes", "283", 3),
    }))

    async def run():
        app = tui.LeetCodeTUI()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("tab")            # to the Review tab
            await pilot.pause()
            start = app._review_slug()          # the top row, two-sum

            # What a submit of move-zeroes now does to the deck pane.
            app.refresh_review("move-zeroes")
            await pilot.pause()
            aimed = app._review_slug()

            # So + grades the problem submitted, not the one under the old cursor.
            await pilot.press("plus")
            await pilot.pause()
            deck = review.load()

            # The request is honoured once. Moving away by hand and refreshing
            # again must not drag the cursor back — a resize re-renders too.
            await pilot.press("up")
            await pilot.pause()
            app.refresh_review()
            await pilot.pause()
            return start, aimed, deck, app._review_slug()

    start, aimed, deck, after = asyncio.run(run())
    assert start == "two-sum"
    assert aimed == "move-zeroes", "the submit must aim the cursor"
    assert (deck["move-zeroes"].level, deck["two-sum"].level) == (4, 3)
    assert after == "two-sum", "focus is one-shot, not sticky"


def test_autograde_turned_on_mid_day_still_grades(tmp_path, monkeypatch):
    """A submit made while autograde was off must not eat the day's first grade.

    The once-a-day guard keys on `graded`, which a non-grading submit never
    stamps — so flipping autograde on mid-day still grades, while anything
    that did grade today (a submit, a hand + / - / 0, the add itself) blocks
    a second move.
    """
    from datetime import date

    review = _review_env(tmp_path, monkeypatch)
    curve = [1, 2, 4, 7]
    past, today = date(2026, 8, 15), date(2026, 8, 20)
    review.add("s", curve=curve, today=past)
    review.shift_level("s", +2, curve, today=past)     # graded days ago, level 3

    # Morning: autograde off, so the submit only marks the row.
    assert "still at level 3" in review.record_submit("s", True, today=today)
    assert review.load()["s"].level == 3

    # Switched on later the same day: this is still the first grade of the day.
    assert "level 3 → 4" in review.record_submit("s", True, today=today, curve=curve)
    assert review.load()["s"].level == 4

    # And only the first.
    note = review.record_submit("s", True, today=today, curve=curve)
    assert "already graded today" in note
    assert review.load()["s"].level == 4


def test_switching_repos_publishes_to_the_new_one(tmp_path, monkeypatch):
    """Re-pointing `lc config repo` has to actually publish to the new repo.

    Re-using the old clone did not. A fetch does not prune, so origin/<branch>
    still named the *previous* repo's commit: the sync reset onto it, found the
    deck already identical, committed nothing and recorded success — leaving
    the newly configured repo empty while lc reported "✔ synced just now".
    """
    import subprocess
    import sys

    def bare(name: str) -> str:
        path = tmp_path / name
        subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(path)],
                       check=True)
        return str(path)

    def commits(repo: str) -> list[str]:
        out = subprocess.run(["git", "--git-dir", repo, "log", "--oneline"],
                             capture_output=True, text=True).stdout.strip()
        return out.splitlines()

    old, new = bare("old.git"), bare("new.git")
    monkeypatch.setenv("LC_HOME", str(tmp_path / "machine"))
    for mod in [m for m in sys.modules if m.startswith("lc.")]:
        del sys.modules[mod]
    from lc import gitsync, review

    curve = [1, 2, 4, 7]
    review.add("two-sum", title="Two Sum", frontend_id="1", curve=curve)
    gitsync.sync(old)
    review.add("coin-change", title="Coin Change", frontend_id="322", curve=curve)
    gitsync.sync(old)
    assert len(commits(old)) == 2

    # Same machine, same clone on disk, now pointed somewhere else.
    gitsync.sync(new)
    published = subprocess.run(["git", "--git-dir", new, "show", "main:review.json"],
                               capture_output=True, text=True).stdout
    assert "coin-change" in published and "two-sum" in published
    # Started over rather than dragging the old repo's history across with it.
    assert len(commits(new)) == 1


def test_a_tombstone_for_an_unknown_problem_still_settles(tmp_path, monkeypatch):
    """A removal for a problem this machine never had must not sit unpushable.

    merge() counts such a tombstone as neither added nor updated, so guarding
    the save on those counters dropped it from review.json — while status()
    went on counting it, reporting a change to push that pushing never cleared.
    """
    import sys

    remote = _bare_repo(tmp_path)
    curve = [1, 2, 4, 7]

    def on(machine: str):
        monkeypatch.setenv("LC_HOME", str(tmp_path / machine))
        for mod in [m for m in sys.modules if m.startswith("lc.")]:
            del sys.modules[mod]
        from lc import gitsync, review
        from lc.config import Config
        return gitsync, review, Config(review_repo=remote)

    g, r, cfg = on("mac")
    r.add("two-sum", title="Two Sum", frontend_id="1", curve=curve)
    g.sync(remote)

    g, r, cfg = on("wsl")
    g.sync(remote)
    assert g.status(cfg).state == "clean"

    # mac puts a problem on the deck and takes it straight off again, so the
    # repo's only new entry is a tombstone for a slug wsl has never seen.
    g, r, cfg = on("mac")
    r.add("scratch", title="Scratch", frontend_id="999", curve=curve)
    r.remove("scratch")
    g.sync(remote)

    g, r, cfg = on("wsl")
    g.sync(remote)
    assert "scratch" in r.load(), "the tombstone has to reach review.json"
    assert g.status(cfg).state == "clean", "and must not linger as a pending change"


def test_deck_commits_are_authored_by_you(tmp_path, monkeypatch):
    """The deck repo holds one person's records, so its commits should be that
    person's without being configured again on every machine: git's own
    identity is the default. lc's name is only the fallback for a machine
    where git has none, which would otherwise fail to commit at all.
    """
    import json as _json
    import os
    import subprocess
    import sys

    remote = _bare_repo(tmp_path)
    gitconfig = tmp_path / "gitconfig"
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    monkeypatch.setenv("LC_HOME", str(tmp_path / "machine"))
    for mod in [m for m in sys.modules if m.startswith("lc.")]:
        del sys.modules[mod]
    from lc import gitsync, review

    def author() -> str:
        return subprocess.run(
            ["git", "--git-dir", remote, "log", "-1", "--format=%an <%ae>"],
            capture_output=True, text=True,
        ).stdout.strip()

    curve = [1, 2, 4, 7]
    # 1. Nothing set anywhere: lc's own, so a bare machine can still sync.
    review.add("two-sum", title="Two Sum", frontend_id="1", curve=curve)
    gitsync.push(remote)
    assert author() == "lc <lc@localhost>"
    assert gitsync.author()[2] == "lc's own"

    # 2. The machine's git identity — no lc setting involved.
    gitconfig.write_text("[user]\n\tname = Eliot\n\temail = e@example.com\n")
    assert gitsync.author() == ("Eliot", "e@example.com", "from git")
    review.add("coin-change", title="Coin Change", frontend_id="322", curve=curve)
    gitsync.push(remote)
    assert author() == "Eliot <e@example.com>"

    # 3. `lc config author` still overrides it.
    (tmp_path / "machine" / "config.json").write_text(_json.dumps(
        {"review_author_name": "Ada", "review_author_email": "ada@example.com"}
    ))
    assert gitsync.author()[2] == "configured"
    review.add("two-sum-ii", title="Two Sum II", frontend_id="167", curve=curve)
    gitsync.push(remote)
    assert author() == "Ada <ada@example.com>"


def test_enter_reopens_the_language_you_started_in(tmp_path, monkeypatch):
    """`enter` on a started problem must reopen that file, not pick again.

    Re-picking chose the config-default language: a problem started in Go
    grew a solution.py beside the half-written solution.go, .lc.json was
    repointed at the new file, and r / s then judged fresh starter code
    while the real work sat stranded. The README's contract is "reopens
    your existing file".
    """
    import asyncio
    import sys

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    for var in ("LC_EDITOR", "VISUAL", "EDITOR"):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / "config.json").write_text(json.dumps(
        {"workspace": str(tmp_path / "ws"), "lang": "python3"}))
    for mod in [m for m in sys.modules if m.startswith("lc.")]:
        del sys.modules[mod]
    from lc import tui, workspace
    from lc.api import Problem
    from lc.config import load_config
    from lc.langs import resolve

    problem = Problem(
        question_id="322", frontend_id="322", title="Coin Change",
        slug="coin-change", difficulty="Medium", content="", paid_only=False,
        likes=0, dislikes=0, ac_rate=40.0, total_accepted="",
        total_submission="", sample_testcase="", example_testcases="",
        hints=[], tags=[],
        snippets={"python3": "class Solution: ...", "golang": "func stub() {}"},
        meta={},
    )
    started = workspace.create(load_config(), problem, resolve("golang"))
    started.file.write_text("// half-finished\n")

    async def press_enter():
        app = tui.LeetCodeTUI()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.current, app.current_slug = problem, problem.slug
            app.action_pick()
            await pilot.pause()

    asyncio.run(press_enter())
    meta = json.loads((started.directory / ".lc.json").read_text())
    assert (meta["lang"], meta["file"]) == ("golang", "solution.go")
    assert not (started.directory / "solution.py").exists(), "no second pick"
    judged = workspace.load(load_config(), problem)
    assert judged.file.name == "solution.go"
    assert judged.code == "// half-finished\n", "r/s must judge the real work"


def test_opening_a_problem_clocks_it_and_an_accept_stops_it(tmp_path, monkeypatch):
    """The clock is an editing-session thing — the TUI only starts it when a
    problem is opened and stops it when a submit comes back accepted. The
    display and the pause live in Vim, where the solving happens."""
    import asyncio
    import json as _json

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    (tmp_path / "config.json").write_text(_json.dumps(
        {"workspace": str(tmp_path / "ws"), "editor": ""}
    ))
    from lc import solvetimer, tui

    async def solve():
        app = tui.LeetCodeTUI()
        seen = {}
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            app._show(PROBLEM)
            await pilot.pause()

            app.action_pick()
            await pilot.pause()
            timer = solvetimer.load()
            # Armed, not running: the start is space in Vim, not walking in.
            seen["armed"] = timer is not None and timer.armed
            seen["slug"] = timer.slug if timer else ""
            # No timer chrome in the TUI: the clock belongs to the editor.
            seen["no_bar_clock"] = "⏱" not in str(app.query_one("#status-bar").render())

            solvetimer.resume()          # what space in Vim runs
            app._timer_submit(PROBLEM.slug, accepted=False)
            seen["failure_keeps_going"] = solvetimer.load().running
            app._timer_submit(PROBLEM.slug, accepted=True)
            await pilot.pause()
            done = solvetimer.load()
            seen["accept_stops"] = done.done and not done.running
        return seen

    assert asyncio.run(solve()) == {
        "armed": True, "slug": PROBLEM.slug, "no_bar_clock": True,
        "failure_keeps_going": True, "accept_stops": True,
    }


def test_the_solve_timer_can_be_switched_off(tmp_path, monkeypatch):
    import asyncio
    import json as _json

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    (tmp_path / "config.json").write_text(_json.dumps(
        {"workspace": str(tmp_path / "ws"), "editor": "", "solve_timer": False}
    ))
    from lc import tui

    async def solve():
        app = tui.LeetCodeTUI()
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            app._show(PROBLEM)
            await pilot.pause()
            app.action_pick()
            await pilot.pause()
            from lc import solvetimer
            return solvetimer.load() is None

    assert asyncio.run(solve()) is True


def test_settings_screen_edits_the_toggles_too(tmp_path, monkeypatch):
    """Autograde and the solve timer were CLI-only switches; the settings
    screen is where a person expects to flip them."""
    import asyncio
    import json as _json

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    (tmp_path / "config.json").write_text(_json.dumps(
        {"workspace": str(tmp_path / "ws"), "editor": ""}
    ))
    from textual.widgets import Checkbox

    from lc import tui

    async def flip():
        app = tui.LeetCodeTUI()
        async with app.run_test(size=(120, 45)) as pilot:
            await pilot.pause()
            app.action_settings()
            await pilot.pause()
            before = {c.id: c.value for c in app.screen.query(Checkbox)}
            for box in app.screen.query(Checkbox):
                box.toggle()
            app.screen.action_save()
            await pilot.pause()
            saved = _json.loads((tmp_path / "config.json").read_text())
            # Turning the timer off mid-session also takes the clock down.
            from lc import solvetimer
            timer = solvetimer.load()
            live = (app.config.autograde, app.config.timer_on,
                    timer.slug if timer else "")
            # Reopening shows what was saved, not what the screen started with.
            app.action_settings()
            await pilot.pause()
            after = {c.id: c.value for c in app.screen.query(Checkbox)}
            return before, saved, live, after

    before, saved, live, after = asyncio.run(flip())
    assert before == {"cfg-review_autograde": False, "cfg-solve_timer": True}
    assert saved["review_autograde"] is True and saved["solve_timer"] is False
    assert live == (True, False, "")
    assert after == {"cfg-review_autograde": True, "cfg-solve_timer": False}


def test_the_clock_is_shared_and_stopped_by_a_cli_submit(tmp_path, monkeypatch):
    """The clock lives in a file precisely because the solve happens outside
    the TUI: `lc pick` starts it, Vim reads it, an accepted `lc submit`
    (a `\\s` included) stops it."""
    import time as _time

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from lc import solvetimer

    # Opening a problem arms the clock; starting it is a deliberate act
    # (space in Vim, `lc timer resume` anywhere else).
    timer = solvetimer.begin("two-sum")
    assert timer.armed and not timer.running
    assert (tmp_path / "timer.json").exists()
    solvetimer.resume()
    assert solvetimer.load().running

    # pause banks the elapsed time; resume picks it back up
    solvetimer.pause()
    banked = solvetimer.load()
    assert not banked.running and banked.accum > 0 or banked.accum >= 0
    _time.sleep(0.05)
    frozen = solvetimer.load().elapsed()
    assert solvetimer.load().elapsed() == frozen
    solvetimer.resume()
    assert solvetimer.load().running

    # a submit of some other problem is not ours to stop
    assert solvetimer.stop_if("coin-change") is None
    assert not solvetimer.load().done
    # ...but of this one is final
    stopped = solvetimer.stop_if("two-sum")
    assert stopped is not None and solvetimer.load().done
    assert solvetimer.stop_if("two-sum") is None   # already done: no double stop

    # reopening the solved problem re-arms a fresh clock
    fresh = solvetimer.begin("two-sum")
    assert fresh.armed and not fresh.done and fresh.accum == 0.0
    # ...and one still running at a fresh open escaped the quit-pause
    # (crash, killed terminal): the phantom run drops, the bank stays.
    solvetimer.resume()
    demoted = solvetimer.begin("two-sum")
    assert not demoted.running and not demoted.done

    # reset: back to zero and running, whatever state it was in
    solvetimer.pause()
    again = solvetimer.reset()
    assert again.running and again.accum == 0.0 and again.slug == "two-sum"
    solvetimer.stop_if("two-sum")
    assert solvetimer.reset().running        # "go again" works on a done clock

    # a torn or hand-mangled file is "no clock", never a crash
    (tmp_path / "timer.json").write_text("{not json")
    assert solvetimer.load() is None
    (tmp_path / "timer.json").write_text('{"slug": 3}')
    assert solvetimer.load() is None


def test_cli_timer_pause_and_resume(tmp_path, monkeypatch):
    """`lc timer pause|resume` — what Vim's \\z runs under the hood."""
    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from typer.testing import CliRunner

    from lc import solvetimer
    from lc.cli import app

    runner = CliRunner()
    # With no clock: an explanation, not a stack trace — and pause says no.
    assert "no clock" in runner.invoke(app, ["timer"]).output
    assert runner.invoke(app, ["timer", "pause"]).exit_code != 0

    # `start <slug>` conjures a clock from nothing — what Vim's space runs.
    assert "running" in runner.invoke(app, ["timer", "start", "move-zeroes"]).output
    solvetimer.clear()

    solvetimer.begin("two-sum")
    assert "ready" in runner.invoke(app, ["timer"]).output
    runner.invoke(app, ["timer", "resume"])
    assert "running" in runner.invoke(app, ["timer"]).output
    runner.invoke(app, ["timer", "pause"])
    assert not solvetimer.load().running
    runner.invoke(app, ["timer", "resume"])
    assert solvetimer.load().running
    # reset drops the elapsed time and keeps it ticking — Vim's \Z.
    assert "00:00" in runner.invoke(app, ["timer", "reset"]).output


def test_the_review_tab_counts_its_deck_on_the_status_bar(tmp_path, monkeypatch):
    """The bottom bar must describe the tab on screen, deck included.

    It only ever said "N problems" — the Problems tab's line — so on the
    Review tab the bar talked about a list you could not see.
    """
    import asyncio
    import sys
    from datetime import date, timedelta

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    for mod in [m for m in sys.modules if m.startswith("lc.")]:
        del sys.modules[mod]
    from lc import store, tui
    from lc.api import ProblemSummary

    # A non-empty index, so on_mount does not kick off a network sync whose
    # failure would race this test for the status bar.
    store.replace_index([ProblemSummary(
        frontend_id="1", title="Two Sum", slug="two-sum", difficulty="Easy",
        ac_rate=50.0, paid_only=False, status=None, tags=[])])

    today = date.today()
    def item(slug, fid, due):
        return {"title": slug, "frontend_id": fid, "difficulty": "Easy",
                "level": 1, "added": "2026-01-01", "graded": "2026-01-01",
                "due": due, "updated": "2026-01-01T00:00:00.000000Z"}
    (tmp_path / "review.json").write_text(json.dumps({
        "two-sum": item("two-sum", "1", (today - timedelta(days=1)).isoformat()),
        "coin-change": item("coin-change", "322", (today + timedelta(days=3)).isoformat()),
        "move-zeroes": item("move-zeroes", "283", (today + timedelta(days=5)).isoformat()),
    }))

    async def run():
        app = tui.LeetCodeTUI()
        seen = []
        async with app.run_test() as pilot:
            from textual.widgets import Static

            def bar() -> str:
                return str(app.query_one("#status-bar", Static).render())

            await pilot.pause()
            seen.append(bar())               # problems tab
            await pilot.press("tab")
            await pilot.pause()
            seen.append(bar())               # review tab
            app.keyword = "coin"
            app.refresh_review()
            await pilot.pause()
            seen.append(bar())               # review tab, filtered
            app.keyword = ""
            app.refresh_list()               # a background list refresh...
            await pilot.pause()
            seen.append(bar())               # ...must not steal the review bar
            await pilot.press("tab")
            await pilot.pause()
            seen.append(bar())               # back on problems
        return seen

    problems, deck, filtered, stolen, back = asyncio.run(run())
    assert "1 problems" in problems
    assert "3 on the deck" in deck and "1 due" in deck
    assert "1 of 3 on the deck" in filtered
    assert "on the deck" in stolen, "a list refresh must not steal the review bar"
    assert "1 problems" in back


def test_a_folded_url_underlines_its_text_and_not_the_padding():
    """The underline must stop where the address does.

    The style sat on the Text as its base style, and a folded line is padded
    out to the column edge with that style — so the wrapped remainder carried
    an underline (and the OSC 8 link) across a stretch of blank cells.
    """
    from dataclasses import replace

    from rich.console import Console

    from lc.render import problem_header

    console = Console(width=60, force_terminal=True)
    header = problem_header(replace(PROBLEM, slug="determine-if-two-strings-are-close"))
    for line in console.render_lines(header, console.options, pad=True):
        for seg in line:
            if seg.text.strip() == "" and seg.style is not None:
                assert not seg.style.underline, f"underlined padding: {seg!r}"
                assert not seg.style.link, f"linked padding: {seg!r}"


def test_a_mornings_solve_does_not_clock_out_evening_practice(tmp_path, monkeypatch):
    """The deck's ✔ mark says "passed today", not "passed while I was in there".

    Reopening a problem already solved and submitted earlier today re-arms its
    clock for practice — but stepping out of the editor read the standing mark
    as a fresh solve and clocked the practice session out: silently on the
    armed clock (space then refused to start it), with a phantom "solved in …"
    once it was running. Snapshot the mark at the door, like solved-ness.
    """
    import asyncio
    import contextlib
    from datetime import date as _date

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    (tmp_path / "config.json").write_text(json.dumps(
        {"workspace": str(tmp_path / "ws"), "editor": "true"}))
    import sys
    for mod in [m for m in sys.modules if m.startswith("lc.")]:
        del sys.modules[mod]
    from lc import review, solvetimer, store, tui
    from lc.api import ProblemSummary

    today = _date.today().isoformat()
    # Solved and submitted this morning: store says ac, the deck row is green.
    store.replace_index([ProblemSummary(
        frontend_id="322", title="Coin Change", slug="coin-change",
        difficulty="Medium", ac_rate=48.9, paid_only=False, status="ac", tags=[])])
    (tmp_path / "review.json").write_text(json.dumps({"coin-change": {
        "title": "Coin Change", "frontend_id": "322", "difficulty": "Medium",
        "level": 2, "added": "2026-01-01", "graded": "2026-01-01",
        "due": today, "updated": "2026-01-01T00:00:00.000000Z",
        "attempted": today, "attempt_passed": True}}))
    # Cached, as a viewed problem's statement always is — without it the row
    # highlight that follows each pick clears app.current while the fetch
    # worker fails offline, and the later picks would silently no-op.
    store.put_statement(PROBLEM)

    editor_calls = []
    monkeypatch.setattr(tui.workspace, "open_in_editor",
                        lambda config, target: editor_calls.append(target) or True)
    monkeypatch.setattr(tui.LeetCodeTUI, "suspend",
                        lambda self: contextlib.nullcontext())

    async def practice():
        app = tui.LeetCodeTUI()
        seen = {}
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            app._show(PROBLEM)
            await pilot.pause()

            app.action_pick()            # reopen, read, quit — no submit
            await pilot.pause()
            timer = solvetimer.load()
            seen["armed_survives"] = timer is not None and timer.armed

            solvetimer.resume()          # space in Vim: practice for real
            app.current = app.current or PROBLEM
            app.action_pick()            # another visit, still no submit
            await pilot.pause()
            timer = solvetimer.load()
            # A clock still running at a fresh open escaped the quit-pause
            # (0.7.48+): the visit demotes it to paused, never to done —
            # the practice session is interrupted, not clocked out.
            seen["demoted_not_done"] = (timer is not None
                                        and not timer.running and not timer.done)

            # A solve that actually lands inside the editor still stops it:
            # grading cleared the mark, and the editor's submit re-marks it.
            review.shift_level("coin-change", +1, [1, 2, 4, 7])
            def editor_submits(config, target):
                review.record_submit("coin-change", True)
                return True
            monkeypatch.setattr(tui.workspace, "open_in_editor", editor_submits)
            app.current = app.current or PROBLEM
            app.action_pick()
            await pilot.pause()
            timer = solvetimer.load()
            seen["real_solve_stops"] = timer is not None and timer.done
        return seen

    assert asyncio.run(practice()) == {
        "armed_survives": True, "demoted_not_done": True, "real_solve_stops": True,
    }
    assert editor_calls, "the fake editor must actually have been entered"


def test_timer_start_resolves_ids_like_every_other_command(tmp_path, monkeypatch):
    """`lc timer start 322` must clock coin-change, not a problem called "322".

    A literal id armed a clock no submit's slug ever matched — it ticked
    forever and never showed in Vim, whose statusline compares slugs.
    """
    import sys

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    for mod in [m for m in sys.modules if m.startswith("lc.")]:
        del sys.modules[mod]
    from typer.testing import CliRunner
    from lc import solvetimer, store
    from lc.api import ProblemSummary
    from lc.cli import app

    store.replace_index([ProblemSummary(
        frontend_id="322", title="Coin Change", slug="coin-change",
        difficulty="Medium", ac_rate=48.9, paid_only=False, status=None, tags=[])])

    runner = CliRunner()
    assert "running" in runner.invoke(app, ["timer", "start", "322"]).output
    assert solvetimer.load().slug == "coin-change"

    # An unknown ref still passes through literally — a bare `vim` session's
    # slug has to work with no index at all.
    runner.invoke(app, ["timer", "start", "not-indexed-anywhere"])
    assert solvetimer.load().slug == "not-indexed-anywhere"


def test_an_expired_session_refresh_keeps_the_solved_marks(tmp_path, monkeypatch):
    """One R with stale cookies must not blank every ✔/✗.

    The session dies every couple of weeks; an unauthenticated problemset
    fetch returns no statuses at all, and replacing the index with it erased
    what you had solved until the next signed-in sync. A status can only be
    wrong the other way — LeetCode has no "unsolve" — so where the fresh
    index says nothing, the old mark stands.
    """
    import sys

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    for mod in [m for m in sys.modules if m.startswith("lc.")]:
        del sys.modules[mod]
    from lc import store
    from lc.api import ProblemSummary

    def entry(slug, status):
        return ProblemSummary(frontend_id="1", title=slug, slug=slug,
                              difficulty="Easy", ac_rate=50.0, paid_only=False,
                              status=status, tags=[])

    store.replace_index([entry("two-sum", "ac"), entry("coin-change", "notac")])

    # Session expired: the same problems come back with no status at all.
    store.replace_index([entry("two-sum", None), entry("coin-change", None),
                         entry("brand-new", None)])
    assert store.find("two-sum").status == "ac"
    assert store.find("coin-change").status == "notac"
    assert store.find("brand-new").status is None

    # A signed-in refresh still updates marks — fresh data always wins.
    store.replace_index([entry("two-sum", "ac"), entry("coin-change", "ac")])
    assert store.find("coin-change").status == "ac"


def test_the_tui_rolls_the_day_over_without_a_keypress(tmp_path, monkeypatch):
    """A TUI left open overnight must not keep describing yesterday.

    Due counts and the ✔/✗ tints follow the local date, the daily pin the
    UTC one — and all of them only moved when the user next pressed
    something, though the README promises the marks fade overnight.
    """
    import asyncio
    import sys
    from datetime import date as _date, timedelta

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    for mod in [m for m in sys.modules if m.startswith("lc.")]:
        del sys.modules[mod]
    from lc import store, tui
    from lc.api import ProblemSummary

    store.replace_index([ProblemSummary(
        frontend_id="1", title="Two Sum", slug="two-sum", difficulty="Easy",
        ac_rate=50.0, paid_only=False, status=None, tags=[])])
    today = _date.today()
    (tmp_path / "review.json").write_text(json.dumps({"two-sum": {
        "title": "Two Sum", "frontend_id": "1", "difficulty": "Easy",
        "level": 1, "added": "2026-01-01", "graded": "2026-01-01",
        "due": today.isoformat(), "updated": "2026-01-01T00:00:00.000000Z"}}))

    async def overnight():
        app = tui.LeetCodeTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            table = app.query_one("#review")
            # Pretend the app has sat here since yesterday.
            app._seen_day = (today - timedelta(days=1), "2000-01-01")
            table._today = today - timedelta(days=1)
            app._day_rollover()
            await pilot.pause()
            rolled = (table._today, app._seen_day[0])

            # Same day again: the check is a no-op and must not churn.
            table._today = _date(2000, 1, 1)      # sentinel a refresh would fix
            app._day_rollover()
            await pilot.pause()
            return rolled, table._today

    (rolled_today, seen), untouched = asyncio.run(overnight())
    assert rolled_today == today, "the deck must be re-dated after midnight"
    assert seen == today
    assert untouched == _date(2000, 1, 1), "no rollover, no refresh"


def test_begin_demotes_a_clock_that_escaped_the_quit_pause(tmp_path, monkeypatch):
    """Quitting Vim pauses the clock, so one still running when a session
    *begins* escaped through a crash, a killed terminal or an old plugin.
    Found as a 13-hour overnight "solve": the stale run made the statusline
    absurd and space inert (a running clock is not space's to touch).
    Proven to fail on 0.7.48, whose begin() left the run counting."""
    import json as _json
    import time as _time

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from lc import solvetimer

    (tmp_path / "timer.json").write_text(_json.dumps(
        {"slug": "x", "accum": 120.0,
         "started": _time.time() - 13 * 3600, "done": False}))
    timer = solvetimer.begin("x")
    assert not timer.running          # the phantom stretch is dropped...
    assert timer.accum == 120.0       # ...what was honestly banked survives
    assert not timer.done             # and space can start it again


def test_solution_header_is_one_line(tmp_path, monkeypatch):
    """The statement pane sits beside the file showing the same title,
    difficulty and url — a three-line echo of it read as a bug."""
    import json as _json

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from lc import workspace
    from lc.config import Config

    cfg = Config()
    cfg.workspace = str(tmp_path / "ws")
    sol = workspace.create(cfg, PROBLEM, resolve("python3"))
    head, blank, body = sol.code.split("\n", 2)
    assert head == "# [322] Coin Change · leetcode.com/problems/coin-change/"
    assert blank == ""
    # ...and it still carries strip_header's marker, so it never reaches
    # the judge. Old three-line headers in existing files strip too.
    assert workspace.strip_header(sol.code, resolve("python3")) == body
    old = ("# [1] Two Sum\n# Easy  ·  50.0% acceptance\n"
           "# https://leetcode.com/problems/two-sum/\n\nx = 1\n")
    assert workspace.strip_header(old, resolve("python3")) == "x = 1\n"


def test_notes_cards_append_parse_and_reuse_blank(tmp_path):
    """notes.md: one ## heading per card; a blank newest card is reused so
    two submits before one written word do not litter the file."""
    import time as _time

    from lc import notes

    header = notes.stamp_header("Accepted", "python3",
                                _time.localtime(1787600000))
    assert header.startswith("## 2026-08-2") and header.endswith(
        "· Accepted · python3")

    p = notes.open_card(tmp_path, "Accepted", "python3")
    assert notes.open_card(tmp_path) == p          # blank card: reused
    assert len(notes.load(tmp_path)) == 1
    p.write_text(p.read_text() + "dp over amounts\n")
    notes.open_card(tmp_path, "Not accepted", "python3")
    cards = notes.load(tmp_path)
    assert [c.body for c in cards] == ["dp over amounts", ""]
    # prose above the first heading is not a card
    assert notes.parse("# Notes\n\nintro\n\n## one\nbody\n")[0].body == "body"


def test_cli_note_stamps_a_card_in_the_problem_dir(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    from typer.testing import CliRunner

    from lc.cli import app

    ws = tmp_path / "ws" / "0322-coin-change"
    ws.mkdir(parents=True)
    (tmp_path / "config.json").write_text(_json.dumps(
        {"workspace": str(tmp_path / "ws"), "editor": ""}))
    (ws / ".lc.json").write_text(_json.dumps(
        {"slug": "coin-change", "question_id": "322", "frontend_id": "322",
         "lang": "python3", "file": "solution.py"}))
    (ws / "solution.py").write_text("pass\n")

    monkeypatch.chdir(ws)
    result = CliRunner().invoke(app, ["note", "--no-edit"])
    assert result.exit_code == 0
    text = (ws / "notes.md").read_text()
    assert text.startswith("## ") and "python3" in text
    # outside a problem directory, an explanation — not a stack trace
    monkeypatch.chdir(tmp_path)
    assert CliRunner().invoke(app, ["note", "--no-edit"]).exit_code != 0


def test_tui_n_shows_this_problems_cards(tmp_path, monkeypatch):
    """`n` on a problem renders its notes.md as cards, newest first; n again
    restores the statement; a problem without notes just says so."""
    import asyncio
    import json as _json

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    ws = tmp_path / "ws"
    (ws / "0322-coin-change").mkdir(parents=True)
    (tmp_path / "config.json").write_text(_json.dumps(
        {"workspace": str(ws), "editor": ""}))
    (ws / "0322-coin-change" / "notes.md").write_text(
        "## 2026-08-21 21:10 · Not accepted · python3\n\n"
        "greedy fails on [1,3,4] amount 6.\n\n"
        "## 2026-08-22 09:05 · Accepted · python3\n\nbottom-up dp.\n")
    from textual.geometry import Region

    from lc import store, tui
    from lc.api import ProblemSummary

    async def view():
        app = tui.LeetCodeTUI()
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            store.replace_index([ProblemSummary(
                "322", "Coin Change", "coin-change", "Medium",
                48.9, False, "ac", [])])
            app.current_slug = "coin-change"
            await pilot.press("n")
            await pilot.pause()
            st = app.query_one("#statement")
            strips = st.render_lines(Region(0, 0, st.size.width or 120, 50))
            text = "\n".join("".join(seg.text for seg in strip)
                             for strip in strips)
            shown = ("[322] Coin Change — notes" in text
                     and text.find("09:05") < text.find("21:10")
                     and "greedy fails" in text and "bottom-up dp" in text)
            await pilot.press("n")
            await pilot.pause()
            toggled = app._notes_for == ""
            app.current_slug = "two-sum"   # nothing on disk for this one
            await pilot.press("n")
            await pilot.pause()
            return shown, toggled, app._notes_for == ""

    assert asyncio.run(view()) == (True, True, True)


def test_notes_travel_with_the_deck_between_two_homes(tmp_path, monkeypatch):
    """Note cards written on either machine reach the other through the deck
    repo — a union, so unrelated cards from both sides all survive. A note
    for a problem the receiving machine never picked waits in the clone and
    is delivered once the index can name its directory."""
    import json as _json
    import subprocess
    import sys

    remote = _bare_repo(tmp_path)

    def machine(name):
        home = tmp_path / name
        ws = home / "ws"
        ws.mkdir(parents=True)
        (home / "config.json").write_text(_json.dumps({"workspace": str(ws)}))
        return home, ws

    def use(home):
        monkeypatch.setenv("LC_HOME", str(home))
        for mod in [m for m in sys.modules if m.startswith("lc.")]:
            del sys.modules[mod]
        from lc import gitsync, notes, review, store  # noqa: F401
        return gitsync, notes, review, store

    def problem_dir(ws, name, slug, fid):
        d = ws / name
        d.mkdir(parents=True, exist_ok=True)
        (d / ".lc.json").write_text(_json.dumps({"slug": slug,
                                                 "frontend_id": fid}))
        return d

    home_a, ws_a = machine("a")
    home_b, ws_b = machine("b")

    # Machine A: a deck problem and a card about it.
    gitsync, notes, review, store = use(home_a)
    review.add("coin-change", title="Coin Change", frontend_id="322",
               curve=[1, 2, 4])
    d = problem_dir(ws_a, "0322-coin-change", "coin-change", "322")
    (d / "notes.md").write_text("## 2026-08-21 21:10 · python3\n\ngreedy fails.\n")
    gitsync.push(remote)
    assert subprocess.run(
        ["git", "--git-dir", remote, "cat-file", "-e", "HEAD:notes/coin-change.md"],
    ).returncode == 0

    # Machine B: has the problem directory, writes its own card, syncs.
    gitsync, notes, review, store = use(home_b)
    d = problem_dir(ws_b, "0322-coin-change", "coin-change", "322")
    (d / "notes.md").write_text("## 2026-08-22 08:00 · python3\n\noffice idea.\n")
    gitsync.sync(remote)
    text = (d / "notes.md").read_text()
    assert "greedy fails." in text and "office idea." in text
    assert text.find("21:10") < text.find("08:00")   # chronological order

    # ...and A picks B's card up on its next pull.
    gitsync, notes, review, store = use(home_a)
    gitsync.pull(remote)
    text = (ws_a / "0322-coin-change" / "notes.md").read_text()
    assert "office idea." in text and "greedy fails." in text

    # A problem B never picked: the card waits in the clone (no directory
    # invented), then lands once the index knows the problem.
    d2 = problem_dir(ws_a, "0001-two-sum", "two-sum", "1")
    (d2 / "notes.md").write_text("## 2026-08-22 10:00 · python3\n\nhash map.\n")
    gitsync.push(remote)

    gitsync, notes, review, store = use(home_b)
    gitsync.pull(remote)
    assert not (ws_b / "0001-two-sum").exists()      # index empty: parked
    from lc.api import ProblemSummary
    store.replace_index([ProblemSummary("1", "Two Sum", "two-sum", "Easy",
                                        50.0, False, None, [])])
    gitsync.pull(remote)
    assert (ws_b / "0001-two-sum" / "notes.md").read_text().count("hash map.") == 1


def test_builtin_editor_solves_inside_the_tui(tmp_path, monkeypatch):
    """`lc config editor builtin`: enter pushes the edit screen — statement,
    code, judge and clock in one look, no suspend. Typing starts the armed
    clock, ctrl+b pauses behind a cover, ctrl+n writes a note card, an
    accepted ctrl+s stops the clock, tab indents (the hidden main screen's
    tab binding must not reach through), and esc saves and returns."""
    import asyncio
    import json as _json
    import types

    monkeypatch.setenv("LC_HOME", str(tmp_path))
    ws = tmp_path / "ws"
    ws.mkdir()
    (tmp_path / "config.json").write_text(_json.dumps(
        {"workspace": str(ws), "editor": "builtin"}))
    from textual.widgets import TabbedContent, TextArea

    from lc import solvetimer, tui
    from lc.api import JudgeResult

    async def solve():
        app = tui.LeetCodeTUI()
        seen = {}
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause()
            app._show(PROBLEM)
            app.current_slug = PROBLEM.slug
            await pilot.pause()
            app.action_pick()
            await pilot.pause()
            seen["screen"] = app.screen.__class__.__name__
            code = app.screen.query_one("#edit-code", TextArea)
            seen["loaded"] = "coinChange" in code.text and app.focused is code
            seen["armed"] = solvetimer.load().armed

            code.insert("x")
            await pilot.pause()
            seen["typing_starts"] = solvetimer.load().running

            await pilot.press("ctrl+b")
            await pilot.pause()
            seen["cover"] = (app.screen.__class__.__name__ == "PauseScreen"
                             and not solvetimer.load().running)
            await pilot.press("space")
            await pilot.pause()
            seen["resume"] = solvetimer.load().running

            await pilot.press("ctrl+n")
            await pilot.pause()
            app.screen.query_one("#edit-notes", TextArea).insert("two sum idea")
            await pilot.press("ctrl+n")
            await pilot.pause()
            note = ws / "0322-coin-change" / "notes.md"
            seen["note"] = note.exists() and "two sum idea" in note.read_text()

            before_tab = app.screen_stack[0].query_one(TabbedContent).active
            where = code.cursor_location
            code.focus()
            await pilot.press("tab")
            await pilot.pause()
            seen["tab_indents"] = (
                code.cursor_location != where
                and app.screen_stack[0].query_one(TabbedContent).active == before_tab)

            app.client = types.SimpleNamespace(
                authenticated=True, close=lambda: None,
                submit=lambda *a, **k: JudgeResult(
                    raw={}, accepted=True, status="Accepted", is_run=False))
            await pilot.press("ctrl+s")
            for _ in range(30):
                await pilot.pause(0.1)
                if solvetimer.load().done:
                    break
            seen["accept_stops"] = solvetimer.load().done

            await pilot.press("escape")
            await pilot.pause()
            seen["back"] = app.screen.__class__.__name__ == "Screen"
            seen["saved"] = "x" in (ws / "0322-coin-change" /
                                    "solution.py").read_text()
        return seen

    assert asyncio.run(solve()) == {
        "screen": "EditScreen", "loaded": True, "armed": True,
        "typing_starts": True, "cover": True, "resume": True, "note": True,
        "tab_indents": True, "accept_stops": True, "back": True, "saved": True,
    }
