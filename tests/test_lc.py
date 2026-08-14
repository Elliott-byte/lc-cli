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
