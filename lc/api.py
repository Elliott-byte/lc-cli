"""Thin client over the leetcode.com GraphQL and judge endpoints.

Auth is cookie-based: LeetCode issues ``LEETCODE_SESSION`` and ``csrftoken``,
and every mutating request must echo the csrf token back in the ``x-csrftoken``
header. See ``lc login`` for how those get here.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

import httpx

from .config import Credentials

BASE = "https://leetcode.com"
GRAPHQL = f"{BASE}/graphql"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


class LeetCodeError(RuntimeError):
    """Any failure talking to LeetCode that the user needs to see."""


class AuthError(LeetCodeError):
    """Session is missing, expired or rejected."""


# --------------------------------------------------------------------------- models

@dataclass
class ProblemSummary:
    frontend_id: str
    title: str
    slug: str
    difficulty: str
    ac_rate: float
    paid_only: bool
    status: str | None  # "ac" | "notac" | None
    tags: list[str] = field(default_factory=list)

    @property
    def solved(self) -> bool:
        return self.status == "ac"

    @property
    def attempted(self) -> bool:
        return self.status == "notac"


@dataclass
class Problem:
    question_id: str
    frontend_id: str
    title: str
    slug: str
    difficulty: str
    content: str
    paid_only: bool
    likes: int
    dislikes: int
    ac_rate: float
    total_accepted: str
    total_submission: str
    sample_testcase: str
    example_testcases: str
    hints: list[str]
    tags: list[str]
    #: langSlug -> starter code
    snippets: dict[str, str]
    meta: dict[str, Any]

    @property
    def url(self) -> str:
        return f"{BASE}/problems/{self.slug}/"


@dataclass
class JudgeResult:
    """Normalised view of the judge's ``/check/`` payload.

    LeetCode returns a different shape for compile errors, runtime errors,
    wrong answers and accepted runs; this flattens all of them.
    """

    raw: dict[str, Any]
    accepted: bool
    status: str
    is_run: bool
    total_correct: int | None = None
    total_testcases: int | None = None
    runtime: str = ""
    memory: str = ""
    runtime_percentile: float | None = None
    memory_percentile: float | None = None
    error: str = ""
    last_testcase: str = ""
    code_output: list[str] = field(default_factory=list)
    expected_output: list[str] = field(default_factory=list)
    std_output: str = ""

    @property
    def display_status(self) -> str:
        """status_msg, except runs say what actually happened — LeetCode
        reports any run that merely executed as "Accepted", outputs aside."""
        if self.is_run and self.status == "Accepted":
            return "Samples passed" if self.accepted else "Samples failed"
        return self.status


# --------------------------------------------------------------------------- queries

_Q_USER_STATUS = """
query globalData {
  userStatus { userId username isSignedIn isPremium }
}
"""

_Q_PROBLEM_LIST = """
query problemsetQuestionList(
  $categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput
) {
  problemsetQuestionList: questionList(
    categorySlug: $categorySlug, limit: $limit, skip: $skip, filters: $filters
  ) {
    total: totalNum
    questions: data {
      frontendQuestionId: questionFrontendId
      title
      titleSlug
      difficulty
      acRate
      paidOnly: isPaidOnly
      status
      topicTags { name slug }
    }
  }
}
"""

_Q_QUESTION = """
query questionData($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    questionId
    questionFrontendId
    title
    titleSlug
    difficulty
    content
    isPaidOnly
    likes
    dislikes
    stats
    hints
    sampleTestCase
    exampleTestcases
    metaData
    topicTags { name slug }
    codeSnippets { lang langSlug code }
  }
}
"""

_Q_DAILY = """
query questionOfToday {
  activeDailyCodingChallengeQuestion {
    date
    userStatus
    link
    question {
      frontendQuestionId: questionFrontendId
      title
      titleSlug
      difficulty
      acRate
      paidOnly: isPaidOnly
      status
      topicTags { name slug }
    }
  }
}
"""

_Q_PROFILE = """
query userProblemsSolved($username: String!) {
  allQuestionsCount { difficulty count }
  matchedUser(username: $username) {
    username
    profile { ranking reputation }
    submitStatsGlobal {
      acSubmissionNum { difficulty count submissions }
    }
  }
}
"""

_Q_SUBMISSIONS = """
query submissionList($offset: Int!, $limit: Int!, $questionSlug: String!) {
  questionSubmissionList(offset: $offset, limit: $limit, questionSlug: $questionSlug) {
    submissions {
      id
      statusDisplay
      lang
      runtime
      memory
      timestamp
      url
    }
  }
}
"""


# --------------------------------------------------------------------------- client

class LeetCode:
    def __init__(
        self,
        creds: Credentials | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.creds = creds
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": f"{BASE}/",
            "Origin": BASE,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        cookies: dict[str, str] = {}
        if creds:
            headers["x-csrftoken"] = creds.csrf
            cookies = creds.as_cookies()
        self._http = httpx.Client(
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            follow_redirects=True,
            transport=transport,  # tests inject a mock here
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "LeetCode":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def authenticated(self) -> bool:
        return self.creds is not None

    def _require_auth(self) -> None:
        if not self.creds:
            raise AuthError("not logged in — run `lc login` first")

    # ----------------------------------------------------------------- transport

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {"query": query, "variables": variables or {}}
        try:
            resp = self._http.post(GRAPHQL, json=payload)
        except httpx.HTTPError as exc:
            raise LeetCodeError(f"network error talking to LeetCode: {exc}") from exc

        if resp.status_code in (401, 403):
            if self.creds:
                raise AuthError("LeetCode rejected the session — run `lc login` again")
            # Anonymous reads get blocked too (Cloudflare) — logging in is not the fix.
            raise LeetCodeError(f"LeetCode blocked the request (HTTP {resp.status_code})")
        if resp.status_code >= 400:
            raise LeetCodeError(f"LeetCode returned HTTP {resp.status_code}")

        try:
            body = resp.json()
        except json.JSONDecodeError as exc:
            raise LeetCodeError("LeetCode returned a non-JSON response") from exc

        if body.get("errors"):
            message = "; ".join(e.get("message", "?") for e in body["errors"])
            # Premium problems and logged-out reads surface as GraphQL errors.
            if "authentication" in message.lower() or "login" in message.lower():
                raise AuthError(message)
            raise LeetCodeError(message)
        return body.get("data") or {}

    # ----------------------------------------------------------------- account

    def user_status(self) -> dict[str, Any]:
        data = self.graphql(_Q_USER_STATUS)
        return data.get("userStatus") or {}

    def profile(self, username: str) -> dict[str, Any]:
        return self.graphql(_Q_PROFILE, {"username": username})

    # ----------------------------------------------------------------- problems

    def problem_list(
        self,
        limit: int = 100,
        skip: int = 0,
        difficulty: str | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
        search: str | None = None,
        category: str = "all-code-essentials",
    ) -> tuple[int, list[ProblemSummary]]:
        filters: dict[str, Any] = {}
        if difficulty:
            filters["difficulty"] = difficulty.upper()
        if tags:
            filters["tags"] = tags
        if status:
            filters["status"] = status.upper()
        if search:
            filters["searchKeywords"] = search

        data = self.graphql(
            _Q_PROBLEM_LIST,
            {"categorySlug": category, "limit": limit, "skip": skip, "filters": filters},
        )
        block = data.get("problemsetQuestionList") or {}
        return block.get("total", 0), [
            _to_summary(q) for q in (block.get("questions") or [])
        ]

    def iter_all_problems(
        self, page_size: int = 500, progress: Callable[[int, int], None] | None = None
    ) -> Iterator[ProblemSummary]:
        skip = 0
        total = None
        while True:
            count, batch = self.problem_list(limit=page_size, skip=skip)
            total = count if total is None else total
            if not batch:
                break
            yield from batch
            skip += len(batch)
            if progress:
                progress(skip, total or 0)
            if skip >= (total or 0):
                break

    def problem(self, slug: str) -> Problem:
        data = self.graphql(_Q_QUESTION, {"titleSlug": slug})
        q = data.get("question")
        if not q:
            raise LeetCodeError(f"no such problem: {slug}")
        return _to_problem(q)

    def daily(self) -> tuple[str, ProblemSummary]:
        data = self.graphql(_Q_DAILY)
        block = data.get("activeDailyCodingChallengeQuestion") or {}
        question = block.get("question")
        if not question:
            raise LeetCodeError("could not fetch today's daily problem")
        return block.get("date", ""), _to_summary(question)

    def submissions(self, slug: str, limit: int = 10) -> list[dict[str, Any]]:
        self._require_auth()
        data = self.graphql(
            _Q_SUBMISSIONS, {"offset": 0, "limit": limit, "questionSlug": slug}
        )
        block = data.get("questionSubmissionList") or {}
        return block.get("submissions") or []

    # ----------------------------------------------------------------- judge

    def run(
        self, problem: Problem, lang: str, code: str, data_input: str
    ) -> JudgeResult:
        """Run against sample (or custom) input — LeetCode calls this 'interpret'."""
        self._require_auth()
        body = {
            "lang": lang,
            "question_id": problem.question_id,
            "typed_code": code,
            "data_input": data_input,
        }
        payload = self._judge_post(f"{BASE}/problems/{problem.slug}/interpret_solution/",
                                   problem.slug, body)
        token = payload.get("interpret_id")
        if not token:
            raise LeetCodeError(f"judge did not return a run id: {payload}")
        return self._poll(token, problem.slug, is_run=True, timeout=90.0)

    def submit(self, problem: Problem, lang: str, code: str) -> JudgeResult:
        self._require_auth()
        body = {
            "lang": lang,
            "question_id": problem.question_id,
            "typed_code": code,
        }
        payload = self._judge_post(f"{BASE}/problems/{problem.slug}/submit/",
                                   problem.slug, body)
        token = payload.get("submission_id")
        if not token:
            raise LeetCodeError(f"judge did not return a submission id: {payload}")
        # Full submissions run the whole test suite, so they get a longer budget.
        return self._poll(str(token), problem.slug, is_run=False, timeout=180.0)

    def _judge_post(self, url: str, slug: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Referer": f"{BASE}/problems/{slug}/"}
        try:
            resp = self._http.post(url, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise LeetCodeError(f"network error talking to the judge: {exc}") from exc

        # GraphQL account reads accept LEETCODE_SESSION alone, so `whoami` can
        # succeed while a stale/wrong CSRF token makes Cloudflare answer judge
        # POSTs with HTTP 499 and an HTML "403 Forbidden" page. A browser loads
        # the problem page first and receives a fresh token; mirror that once,
        # then retry the request instead of dumping the HTML at the user.
        if self._csrf_blocked(resp):
            self._refresh_judge_csrf(slug)
            try:
                resp = self._http.post(url, json=body, headers=headers)
            except httpx.HTTPError as exc:
                raise LeetCodeError(
                    f"network error talking to the judge: {exc}"
                ) from exc

        if self._csrf_blocked(resp):
            raise LeetCodeError(
                "LeetCode blocked the judge request after refreshing CSRF"
            )

        if resp.status_code in (401, 403):
            raise AuthError("LeetCode rejected the session — run `lc login` again")
        if resp.status_code == 429:
            raise LeetCodeError("rate limited by LeetCode — wait a moment and retry")
        if resp.status_code >= 400:
            raise LeetCodeError(
                f"judge returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise LeetCodeError("judge returned a non-JSON response") from exc

    @staticmethod
    def _csrf_blocked(resp: httpx.Response) -> bool:
        content_type = resp.headers.get("content-type", "").lower()
        return (
            resp.status_code in (403, 499)
            and "html" in content_type
            and "403 forbidden" in resp.text[:2_000].lower()
        )

    def _refresh_judge_csrf(self, slug: str) -> None:
        """Load the problem page and adopt the CSRF cookie it just issued."""
        try:
            resp = self._http.get(
                f"{BASE}/problems/{slug}/",
                headers={"Referer": f"{BASE}/problems/{slug}/"},
            )
        except httpx.HTTPError as exc:
            raise LeetCodeError(
                f"could not refresh the judge session: {exc}"
            ) from exc
        if resp.status_code >= 400:
            raise LeetCodeError(
                f"could not refresh the judge session (HTTP {resp.status_code})"
            )

        fresh = next(
            (
                cookie.value
                for cookie in reversed(list(self._http.cookies.jar))
                if cookie.name == "csrftoken"
                and cookie.domain.lstrip(".") == "leetcode.com"
            ),
            "",
        )
        if not fresh:
            raise LeetCodeError(
                "LeetCode did not issue a fresh CSRF token — run `lc login` again"
            )

        # httpx created the configured token as a domainless cookie; retaining
        # it beside LeetCode's new domain cookie sends two csrftoken values and
        # still fails CSRF validation even when the header uses the fresh one.
        jar = self._http.cookies.jar
        for cookie in list(jar):
            if cookie.name == "csrftoken":
                jar.clear(cookie.domain, cookie.path, cookie.name)
        self._http.cookies.set(
            "csrftoken", fresh, domain="leetcode.com", path="/"
        )
        self._http.headers["x-csrftoken"] = fresh

    def _poll(
        self, token: str, slug: str, is_run: bool, timeout: float = 90.0
    ) -> JudgeResult:
        url = f"{BASE}/submissions/detail/{token}/check/"
        headers = {"Referer": f"{BASE}/problems/{slug}/"}
        deadline = time.monotonic() + timeout
        delay = 0.4
        last_error: str | None = None
        while time.monotonic() < deadline:
            try:
                resp = self._http.get(url, headers=headers)
            except httpx.HTTPError as exc:
                # One dropped poll must not lose the verdict — the submission
                # already went in, so keep asking until the deadline.
                last_error = str(exc)
                time.sleep(delay)
                delay = min(delay * 1.3, 2.0)
                continue
            if resp.status_code in (401, 403):
                raise AuthError("LeetCode rejected the session — run `lc login` again")
            if resp.status_code == 429 or resp.status_code >= 500:
                # Throttled or a transient server error — same as a dropped
                # poll: the verdict still exists, keep asking.
                last_error = f"HTTP {resp.status_code}"
                time.sleep(delay)
                delay = min(delay * 1.3, 2.0)
                continue
            if resp.status_code >= 400:
                raise LeetCodeError(f"judge poll failed: HTTP {resp.status_code}")
            last_error = None
            try:
                payload = resp.json()
            except json.JSONDecodeError:
                payload = {}
            state = payload.get("state")
            if state == "SUCCESS":
                return _to_result(payload, is_run=is_run)
            if state == "FAILURE":
                # Terminal: the judge gave up on this run — waiting is useless.
                raise LeetCodeError(
                    "the judge failed to process this submission — try again"
                )
            time.sleep(delay)
            delay = min(delay * 1.3, 2.0)
        if last_error is not None:
            raise LeetCodeError(f"lost the judge while waiting for the verdict: {last_error}")
        raise LeetCodeError("timed out waiting for the judge")


def split_testcases(problem: Problem, data_input: str) -> list[str]:
    """Split a judge input blob back into one string per test case.

    LeetCode concatenates the cases: each spans one line per function
    parameter — or two lines (operations, then arguments) for class-design
    problems, whose metadata has no "params".
    """
    lines = data_input.split("\n")
    while lines and not lines[-1]:
        lines.pop()
    params = problem.meta.get("params")
    per = len(params) if params else 2
    return ["\n".join(lines[i:i + per]) for i in range(0, len(lines), per)]


# --------------------------------------------------------------------------- mapping

def _to_summary(q: dict[str, Any]) -> ProblemSummary:
    return ProblemSummary(
        frontend_id=str(q.get("frontendQuestionId", "")),
        title=q.get("title", ""),
        slug=q.get("titleSlug", ""),
        difficulty=q.get("difficulty", ""),
        ac_rate=float(q.get("acRate") or 0.0),
        paid_only=bool(q.get("paidOnly")),
        status=q.get("status"),
        tags=[t["name"] for t in (q.get("topicTags") or [])],
    )


def _to_problem(q: dict[str, Any]) -> Problem:
    stats = {}
    if q.get("stats"):
        try:
            stats = json.loads(q["stats"])
        except json.JSONDecodeError:
            stats = {}
    meta = {}
    if q.get("metaData"):
        try:
            meta = json.loads(q["metaData"])
        except json.JSONDecodeError:
            meta = {}

    ac_rate = 0.0
    raw_rate = stats.get("acRate", "")
    if isinstance(raw_rate, str) and raw_rate.endswith("%"):
        try:
            ac_rate = float(raw_rate[:-1])
        except ValueError:
            ac_rate = 0.0

    return Problem(
        question_id=str(q.get("questionId", "")),
        frontend_id=str(q.get("questionFrontendId", "")),
        title=q.get("title", ""),
        slug=q.get("titleSlug", ""),
        difficulty=q.get("difficulty", ""),
        content=q.get("content") or "",
        paid_only=bool(q.get("isPaidOnly")),
        likes=int(q.get("likes") or 0),
        dislikes=int(q.get("dislikes") or 0),
        ac_rate=ac_rate,
        total_accepted=str(stats.get("totalAccepted", "")),
        total_submission=str(stats.get("totalSubmission", "")),
        sample_testcase=q.get("sampleTestCase") or "",
        example_testcases=q.get("exampleTestcases") or "",
        hints=list(q.get("hints") or []),
        tags=[t["name"] for t in (q.get("topicTags") or [])],
        snippets={
            s["langSlug"]: s["code"] for s in (q.get("codeSnippets") or []) if s.get("code")
        },
        meta=meta,
    )


def _as_lines(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _to_result(payload: dict[str, Any], is_run: bool) -> JudgeResult:
    status = payload.get("status_msg") or "Unknown"
    accepted = status == "Accepted"
    if is_run:
        # A run has no verdict of its own; it "passes" when every sample matches.
        # LeetCode reports that three different ways depending on the problem type.
        if "correct_answer" in payload:
            accepted = bool(payload["correct_answer"])
        elif payload.get("compare_result"):
            accepted = set(payload["compare_result"]) == {"1"}
        else:
            accepted = bool(payload.get("run_success")) and not payload.get(
                "runtime_error"
            )

    error = (
        payload.get("full_compile_error")
        or payload.get("compile_error")
        or payload.get("full_runtime_error")
        or payload.get("runtime_error")
        or ""
    )

    return JudgeResult(
        raw=payload,
        accepted=accepted,
        status=status,
        is_run=is_run,
        total_correct=payload.get("total_correct"),
        total_testcases=payload.get("total_testcases"),
        runtime=payload.get("status_runtime") or payload.get("display_runtime") or "",
        memory=payload.get("status_memory") or "",
        runtime_percentile=payload.get("runtime_percentile"),
        memory_percentile=payload.get("memory_percentile"),
        error=error,
        last_testcase=payload.get("last_testcase") or payload.get("input") or "",
        code_output=_as_lines(payload.get("code_answer") or payload.get("code_output")),
        expected_output=_as_lines(
            payload.get("expected_code_answer") or payload.get("expected_output")
        ),
        std_output="".join(_as_lines(payload.get("std_output_list") or payload.get("std_output"))),
    )
