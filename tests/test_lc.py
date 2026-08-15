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
    g.sync(remote)
    assert deck(r) == ["coin-change"], "the removal must propagate"

    # Re-adding revives it everywhere.
    r.add("two-sum", title="Two Sum", frontend_id="1", curve=curve)
    g.sync(remote)
    g, r = on("mac")
    g.sync(remote)
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
    merged, added, updated = review.merge(local, remote)

    assert (added, updated) == (1, 1)
    assert merged["a"].level == 5      # remote graded later
    assert merged["b"].level == 1      # local only, untouched
    assert merged["c"].level == 3      # arrived from the remote
    # A stale remote entry must not win.
    back, added, updated = review.merge(merged, {"b": it("b", 9, "2026-07-01")})
    assert (added, updated) == (0, 0) and back["b"].level == 1


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
    assert gitsync.pull(remote) == (1, 0)
    assert review.load()["coin-change"].title == "Coin Change"

    # It grades the problem and syncs; the first machine picks that up.
    review.shift_level("coin-change", +1, [2, 4], today=date(2026, 8, 17))
    gitsync.sync(remote)
    monkeypatch.setenv("LC_HOME", str(tmp_path / "a"))
    assert gitsync.pull(remote) == (0, 1)
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

    monkeypatch.setattr(gitsync, "date", Tomorrow)
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
