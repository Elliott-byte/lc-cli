"""Regenerate the README screenshots in docs/*.svg.

    .venv/bin/python docs/screenshots.py

Everything renders through lc's real code paths — the data is canned so the
output is reproducible and needs no network or account.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SHOT_HOME = Path(tempfile.mkdtemp(prefix="lc-shots-"))
os.environ["LC_HOME"] = str(SHOT_HOME)
os.environ["LC_NO_FX"] = "1"
(SHOT_HOME / "config.json").write_text(json.dumps({
    "workspace": str(SHOT_HOME / "workspace"),
    "editor": "builtin",
}) + "\n")

from rich.console import Console  # noqa: E402
from rich.text import Text  # noqa: E402

from lc import notes, store  # noqa: E402
from lc.api import JudgeResult, Problem, ProblemSummary  # noqa: E402
from lc.cli import print_result, problems_table  # noqa: E402

DOCS = Path(__file__).resolve().parent

DAILY_SLUG = "longest-substring-of-one-repeating-character"

STATEMENT_HTML = """
<p>You are given a <strong>0-indexed</strong> string <code>s</code>. You are
also given a 0-indexed string <code>queryCharacters</code> of length
<code>k</code> and a 0-indexed array of integer indices
<code>queryIndices</code> of length <code>k</code>, both of which are used to
describe <code>k</code> queries.</p>
<p>The <code>i<sup>th</sup></code> query updates the character in
<code>s</code> at index <code>queryIndices[i]</code> to the character
<code>queryCharacters[i]</code>.</p>
<p>Return an array <code>lengths</code> of length <code>k</code>, where
<code>lengths[i]</code> is the length of the <strong>longest substring</strong>
of <code>s</code> consisting of <strong>only one repeating character</strong>
after the <code>i<sup>th</sup></code> query is performed.</p>
<pre><strong>Input:</strong> s = "babacc", queryCharacters = "bcb", queryIndices = [1,3,3]
<strong>Output:</strong> [3,3,4]
<strong>Explanation:</strong> after the third query s = "bccbb": the longest run is "bb", &hellip;
</pre>
<p><strong>Constraints:</strong></p>
<ul>
<li><code>1 &lt;= s.length &lt;= 10<sup>5</sup></code></li>
<li><code>k == queryCharacters.length == queryIndices.length</code></li>
</ul>
"""

#: The problem the editor screenshot solves — its statement must match the
#: code in the pane beside it, or the shot documents a bug that is not there.
TRAP_PROBLEM = Problem(
    question_id="42",
    frontend_id="42",
    title="Trapping Rain Water",
    slug="trapping-rain-water",
    difficulty="Hard",
    content=(
        "<p>Given <code>n</code> non-negative integers representing an "
        "elevation map where the width of each bar is <code>1</code>, "
        "compute how much water it can trap after raining.</p>"
        "<p><strong>Example 1:</strong></p>"
        "<pre>Input: height = [0,1,0,2,1,0,1,3,2,1,2,1]\nOutput: 6</pre>"
        "<p><strong>Constraints:</strong></p><ul>"
        "<li><code>n == height.length</code></li>"
        "<li><code>1 &lt;= n &lt;= 2 * 10<sup>4</sup></code></li>"
        "<li><code>0 &lt;= height[i] &lt;= 10<sup>5</sup></code></li></ul>"
    ),
    paid_only=False,
    likes=31000,
    dislikes=380,
    ac_rate=65.3,
    total_accepted="2.1M",
    total_submission="3.2M",
    sample_testcase="[0,1,0,2,1,0,1,3,2,1,2,1]",
    example_testcases="[0,1,0,2,1,0,1,3,2,1,2,1]",
    hints=[],
    tags=["Array", "Two Pointers", "Dynamic Programming", "Stack"],
    snippets={"python3": "class Solution:\n    def trap(self, height: List[int]) -> int:\n        "},
    meta={},
)

DAILY_PROBLEM = Problem(
    question_id="2213",
    frontend_id="2213",
    title="Longest Substring of One Repeating Character",
    slug=DAILY_SLUG,
    difficulty="Hard",
    content=STATEMENT_HTML,
    paid_only=False,
    likes=455,
    dislikes=87,
    ac_rate=56.5,
    total_accepted="31K",
    total_submission="54.9K",
    sample_testcase="",
    example_testcases="",
    hints=[],
    tags=["Array", "String", "Segment Tree", "Ordered Set"],
    snippets={"python3": "class Solution: ..."},
    meta={"params": [{"name": "s"}, {"name": "queryCharacters"},
                     {"name": "queryIndices"}]},
)


def _s(fid, title, slug, diff, rate, status, paid=False):
    return ProblemSummary(fid, title, slug, diff, rate, paid, status)


INDEX = [
    _s("1", "Two Sum", "two-sum", "Easy", 56.4, "ac"),
    _s("2", "Add Two Numbers", "add-two-numbers", "Medium", 46.5, "ac"),
    _s("3", "Longest Substring Without Repeating Characters",
       "longest-substring-without-repeating-characters", "Medium", 37.2, "notac"),
    _s("4", "Median of Two Sorted Arrays", "median-of-two-sorted-arrays",
       "Hard", 44.3, None),
    _s("11", "Container With Most Water", "container-with-most-water",
       "Medium", 58.1, "ac"),
    _s("15", "3Sum", "3sum", "Medium", 37.6, "notac"),
    _s("23", "Merge k Sorted Lists", "merge-k-sorted-lists", "Hard", 56.9, None),
    _s("42", "Trapping Rain Water", "trapping-rain-water", "Hard", 65.3, "ac"),
    _s("146", "LRU Cache", "lru-cache", "Medium", 45.4, None),
    _s("200", "Number of Islands", "number-of-islands", "Medium", 62.4, "ac"),
    _s("322", "Coin Change", "coin-change", "Medium", 48.9, "ac"),
    _s("2213", "Longest Substring of One Repeating Character", DAILY_SLUG,
       "Hard", 56.5, None),
]


def shot_list() -> None:
    mediums = [p for p in INDEX if p.difficulty == "Medium"][:8]
    console = Console(record=True, width=88)
    console.print(problems_table(mediums))
    console.print()
    console.print(Text("8 of 641 — more with --offset 8", style="dim"))
    console.save_svg(str(DOCS / "list.svg"), title="lc list -d medium -n 8")


def shot_test() -> None:
    result = JudgeResult(
        raw={},
        accepted=False,
        status="Accepted",  # LeetCode's word for "it ran"; lc says Samples failed
        is_run=True,
        total_correct=1,
        total_testcases=2,
        runtime="0 ms",
        memory="19.4 MB",
        code_output=["[3,3,4]", "[2,2]"],
        expected_output=["[3,3,4]", "[2,3]"],
    )
    data_input = 'babacc\nbcb\n[1,3,3]\nabyzz\naa\n[2,1]'
    console = Console(record=True, width=88)
    # print_result writes to lc's module-level console; point it at the recorder.
    from lc import cli
    cli.console = console
    print_result(result, DAILY_PROBLEM, data_input)
    console.save_svg(str(DOCS / "test.svg"),
                     title="lc test  ·  in ~/leetcode/2213-longest-substring…")


#: A solve in progress — enough real code that the syntax colours show.
SOLUTION_IN_PROGRESS = """\
class Solution:
    def trap(self, height: List[int]) -> int:
        left, right = 0, len(height) - 1
        best = water = 0
        while left < right:
            low = height[left] if height[left] < height[right] else height[right]
            best = low if low > best else best
            water += best - low
"""

#: Two cards, as `lc note` stamps them.
NOTE_CARDS = """\
## 2026-08-21 21:10 · Not accepted · python3

Two passes over prefix maxima works but allocates twice. The two-pointer
form keeps the same invariant with O(1) space.

## 2026-08-22 09:05 · Accepted · python3

The pointer on the *lower* side is the one that can move: whatever is
behind it already bounds the water there.
"""


def seed_review() -> None:
    """A little review deck: one overdue, one due today, one scheduled out.

    Dues are set relative to today, so the rendered "-3d / today / 11d" —
    and with it the SVG — is the same whichever day this runs.
    """
    from datetime import date, timedelta

    from lc import review

    curve = [2, 4, 8, 16]
    review.add("trapping-rain-water", title="Trapping Rain Water",
               frontend_id="42", difficulty="Hard", curve=curve)
    review.add("coin-change", title="Coin Change", frontend_id="322",
               difficulty="Medium", curve=curve)
    review.add("lru-cache", title="LRU Cache", frontend_id="146",
               difficulty="Medium", curve=curve)
    items = review.load()
    today = date.today()
    items["trapping-rain-water"].due = (today - timedelta(days=3)).isoformat()
    items["coin-change"].due = today.isoformat()
    items["lru-cache"].due = (today + timedelta(days=11)).isoformat()
    items["lru-cache"].level = 4
    review.save(items)


async def shot_tui() -> None:
    from lc import tui as tuimod

    store.replace_index(INDEX)
    store.put_statement(DAILY_PROBLEM)
    store.set_meta("daily_date", time.strftime("%Y-%m-%d", time.gmtime()))
    store.set_meta("daily_slug", DAILY_SLUG)
    seed_review()

    class FakeClient:
        authenticated = True

        def daily(self):
            return "", INDEX[-1]

        def problem(self, slug):
            return DAILY_PROBLEM

        def iter_all_problems(self, progress=None):
            return iter(())

        def close(self):
            pass

    app = tuimod.LeetCodeTUI()
    app.client = FakeClient()
    async with app.run_test(size=(96, 36)) as pilot:
        for _ in range(40):
            await pilot.pause(0.1)
            if app.daily_slug:
                break
        await pilot.pause(0.5)
        (DOCS / "tui.svg").write_text(app.export_screenshot(title="lc"))
        # The same app, flipped to the Review tab.
        await pilot.press("tab")
        await pilot.pause(0.5)
        (DOCS / "review.svg").write_text(app.export_screenshot(title="lc — review"))
        # ...and its settings screen, showing a curve mid-edit.
        await pilot.press("c")
        await pilot.pause(0.5)
        from textual.widgets import Input

        app.screen.query_one("#cfg-curve", Input).value = "1, 2, 4, 7, 15, 30"
        app.screen.query_one("#cfg-review_repo", Input).value = (
            "git@github.com:you/lc-review.git"
        )
        await pilot.pause(0.5)
        (DOCS / "config.svg").write_text(app.export_screenshot(title="lc — settings"))
        await pilot.press("escape")
        await pilot.pause(0.3)

        # The built-in editor, mid-solve: statement beside the code, the vim
        # layer in normal mode, the clock counting on the status line.
        await pilot.press("tab")           # back to the problem list
        await pilot.pause(0.3)
        store.put_statement(TRAP_PROBLEM)
        app.select_slug("trapping-rain-water")
        await pilot.pause(0.4)
        app._show(TRAP_PROBLEM)
        app.current_slug = TRAP_PROBLEM.slug
        app.action_pick()
        await pilot.pause(0.5)
        from lc import solvetimer
        from lc.vimtext import VimTextArea

        code = app.screen.query_one("#edit-code", VimTextArea)
        code.load_text(SOLUTION_IN_PROGRESS)
        code.move_cursor((5, 8))
        # A clock that has been running a few minutes reads better than 00:00.
        timer = solvetimer.load()
        if timer is not None:
            timer.started = time.time() - 227
            solvetimer.save(timer)
        app.screen._tick()
        await pilot.pause(0.4)
        (DOCS / "edit.svg").write_text(
            app.export_screenshot(title="lc — solving"))

        # ...and the note cards that an attempt leaves behind.
        notes.path_in(app.screen.solution.directory).write_text(NOTE_CARDS)
        # ZZ, not escape: with the vim layer on, escape is the editor's own
        # (insert -> normal) and leaving is ZZ. Pressing escape here left the
        # shot on the edit screen — two identical SVGs.
        await pilot.press("Z", "Z")
        await pilot.pause(0.5)
        app.action_view_notes()
        await pilot.pause(0.4)
        (DOCS / "notes.svg").write_text(app.export_screenshot(title="lc — notes"))


if __name__ == "__main__":
    shot_list()
    shot_test()
    asyncio.run(shot_tui())
    print("wrote", ", ".join(str(DOCS / f) for f in
                             ("list.svg", "test.svg", "tui.svg", "review.svg",
                              "config.svg", "edit.svg", "notes.svg")))
