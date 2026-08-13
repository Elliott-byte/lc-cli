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
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url))

    from typer.testing import CliRunner
    result = CliRunner().invoke(cli.app, ["login"], input="\n")

    assert result.exit_code == 0, result.output
    assert opened == [cli.LOGIN_URL]
    from lc.config import load_credentials
    assert load_credentials().session == "sess"


# ------------------------------------------------------ workspace file choice

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


# ------------------------------------------------------------------ bare `lc`

def test_bare_lc_prints_help_when_not_a_terminal():
    """Piped/scripted `lc` must never launch the full-screen app."""
    from typer.testing import CliRunner
    from lc.cli import app

    result = CliRunner().invoke(app, [])
    assert result.exit_code == 0, result.output
    assert "Usage" in result.output
