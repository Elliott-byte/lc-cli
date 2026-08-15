"""Command line interface."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console, Group
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from datetime import date

from . import __version__, browser, editors, fx, gitsync, review, store
from .api import (
    AuthError,
    JudgeResult,
    LeetCode,
    LeetCodeError,
    Problem,
    ProblemSummary,
    split_testcases,
)
from .config import (
    Credentials,
    clear_credentials,
    home,
    load_config,
    load_credentials,
    save_config,
    save_credentials,
)
from .langs import BY_SLUG, LANGUAGES, Language, resolve
from .langs import choose as langs_choose
from .render import difficulty_text, problem_header, render_statement, status_mark
from . import workspace

app = typer.Typer(
    name="lc",
    help="Practice LeetCode from your terminal. Bare `lc` opens the full-screen browser.",
    add_completion=False,
)
console = Console()
err = Console(stderr=True)


# --------------------------------------------------------------------------- helpers

def _error(message: str, hint: str = "") -> None:
    err.print(Text("✗ ", style="bold red") + Text(message))
    if hint:
        err.print(Text(f"  {hint}", style="dim"))


def die(message: str, hint: str = "") -> None:
    _error(message, hint)
    raise typer.Exit(1)


def client(require_auth: bool = False) -> LeetCode:
    creds = load_credentials()
    if require_auth and not creds:
        die("not logged in", "run `lc login` to paste your LeetCode session cookies")
    return LeetCode(creds)


def _ensure_index(lc: LeetCode) -> None:
    """The cache backs id lookup, filtering and random — populate it on first use."""
    if store.index_size() > 0:
        return
    console.print(Text("First run — downloading the problem index…", style="dim"))
    _sync(lc)


def _sync(lc: LeetCode) -> int:
    collected: list[ProblemSummary] = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("fetching problems…", total=None)

        def tick(done: int, total: int) -> None:
            progress.update(task, description=f"fetching problems… {done}/{total}")

        collected = list(lc.iter_all_problems(progress=tick))
    return store.replace_index(collected)


def resolve_problem(ref: str, lc: LeetCode, fresh: bool = False) -> Problem:
    """Turn a user reference (id / slug / title) into a full Problem."""
    ref = ref.strip()
    slug = ref.lower().replace(" ", "-")

    # A cached statement short-circuits both the index sync and the network, so
    # re-reading a problem you have already opened works offline.
    cached = None if fresh else store.get_statement(slug)
    if cached:
        return cached

    _ensure_index(lc)
    summary = store.find(ref)
    if summary and summary.slug != slug:
        slug = summary.slug
        cached = None if fresh else store.get_statement(slug)
        if cached:
            return cached

    try:
        problem = lc.problem(slug)
    except LeetCodeError as exc:
        if summary is None:
            die(f"no problem matching {ref!r}", _did_you_mean(ref))
        die(str(exc))
        raise
    store.put_statement(problem)
    return problem


def _did_you_mean(ref: str) -> str:
    """Suggest close titles, falling back to per-word matches for typos."""
    matches = store.search(keyword=ref, limit=5)
    if not matches:
        seen: dict[str, ProblemSummary] = {}
        for word in ref.split():
            if len(word) < 3:
                continue
            for m in store.search(keyword=word, limit=4):
                seen.setdefault(m.slug, m)
        matches = list(seen.values())[:5]
    if not matches:
        return "try `lc list <keyword>` to search"
    return "did you mean: " + ", ".join(f"{m.frontend_id}. {m.title}" for m in matches)


def _current_dir_problem() -> Optional[tuple[str, Language, Path]]:
    return workspace.find_by_path(load_config(), Path.cwd())


def pick_language(config, problem: Problem, requested: str | None) -> Language:
    if requested:
        lang = resolve(requested)
        if lang is None:
            die(f"unknown language {requested!r}",
                "supported: " + ", ".join(sorted(BY_SLUG)))
        assert lang is not None
        if lang.slug not in problem.snippets:
            available = ", ".join(sorted(problem.snippets))
            die(f"LeetCode has no {lang.name} starter code here",
                f"available: {available}")
        return lang

    lang = langs_choose(config.lang, config.favorite_langs, problem.snippets)
    if lang is None:
        die("this problem has no starter code lc understands")
        raise typer.Exit(1)
    return lang


# --------------------------------------------------------------------------- output

def problems_table(rows: list[ProblemSummary], show_tags: bool = False) -> Table:
    table = Table(box=None, pad_edge=False, header_style="dim")
    table.add_column("", width=1)
    table.add_column("#", justify="right", style="dim", width=5)
    table.add_column("Title", no_wrap=True, overflow="ellipsis")
    table.add_column("Difficulty", width=10)
    table.add_column("AC%", justify="right", width=6)
    if show_tags:
        table.add_column("Tags", style="cyan")

    for p in rows:
        title = Text(p.title)
        if p.paid_only:
            title.append("  🔒", style="yellow")
        cells = [
            status_mark(p.status),
            p.frontend_id,
            title,
            difficulty_text(p.difficulty),
            f"{p.ac_rate:.1f}",
        ]
        if show_tags:
            cells.append(", ".join(p.tags[:3]))
        table.add_row(*cells)
    return table


def print_result(result: JudgeResult, problem: Problem, data_input: str = "") -> None:
    verdict = Text(result.display_status,
                   style="bold green" if result.accepted else "bold red")
    if result.accepted:
        verdict = Text("✔ ", style="bold green") + verdict
    else:
        verdict = Text("✗ ", style="bold red") + verdict

    parts: list = [verdict]

    if result.error:
        parts += [Text(""), Panel(Text(result.error.strip(), style="red"),
                                  title="error", border_style="red", expand=False)]

    if result.total_testcases:
        parts.append(
            Text(f"{result.total_correct or 0}/{result.total_testcases} test cases passed",
                 style="dim")
        )

    if result.is_run and (result.code_output or result.expected_output):
        cases = split_testcases(problem, data_input) if data_input else []
        table = Table(box=None, pad_edge=False, header_style="dim")
        table.add_column("case", style="dim", width=5)
        if cases:
            table.add_column("input", overflow="fold", max_width=44)
        table.add_column("output")
        table.add_column("expected")
        pairs = max(len(result.code_output), len(result.expected_output))
        for i in range(pairs):
            got = result.code_output[i] if i < len(result.code_output) else ""
            want = result.expected_output[i] if i < len(result.expected_output) else ""
            if not got and not want:
                continue  # the judge pads its answer arrays with a trailing ""
            ok = got == want
            row = [Text(str(i + 1), style="green" if ok else "red")]
            if cases:
                row.append(Text(cases[i] if i < len(cases) else "", style="dim"))
            row += [
                Text(got, style="" if ok else "red"),
                Text(want, style="dim"),
            ]
            table.add_row(*row)
        parts += [Text(""), table]

    if not result.is_run and not result.accepted and result.last_testcase:
        label = "failing input"
        if result.total_testcases:
            label += f" — case {(result.total_correct or 0) + 1} of {result.total_testcases}"
        parts += [
            Text(""),
            Text(label, style="dim"),
            Panel(Text(result.last_testcase), border_style="dim", expand=False),
        ]
        if result.code_output:
            parts.append(Text(f"  got:      {result.code_output[0]}", style="red"))
        if result.expected_output:
            parts.append(Text(f"  expected: {result.expected_output[0]}", style="green"))

    if result.std_output.strip():
        parts += [
            Text(""),
            Text("stdout", style="dim"),
            Panel(Text(result.std_output.strip()), border_style="dim", expand=False),
        ]

    if result.runtime:
        line = Text(f"runtime {result.runtime}", style="dim")
        if result.runtime_percentile:
            line.append(f" (beats {result.runtime_percentile:.1f}%)", style="dim")
        if result.memory:
            line.append(f"   memory {result.memory}", style="dim")
            if result.memory_percentile:
                line.append(f" (beats {result.memory_percentile:.1f}%)", style="dim")
        parts += [Text(""), line]

    console.print(Panel(Group(*parts), title=f"[{problem.frontend_id}] {problem.title}",
                        border_style="green" if result.accepted else "red"))

    if os.environ.get("LC_DEBUG"):
        # The judge's payload shape varies by problem type; this is what to paste
        # into a bug report when a verdict is displayed wrongly.
        console.print(
            Panel(
                Syntax(json.dumps(result.raw, indent=2, ensure_ascii=False), "json",
                       theme="ansi_dark", word_wrap=True),
                title="raw judge payload (LC_DEBUG)",
                border_style="dim",
            )
        )


# --------------------------------------------------------------------------- account

LOGIN_URL = "https://leetcode.com/accounts/login/"


@app.command()
def login(
    session: str = typer.Option("", "--session", help="LEETCODE_SESSION cookie value"),
    csrf: str = typer.Option("", "--csrf", help="csrftoken cookie value"),
    paste: bool = typer.Option(
        False, "--paste", help="copy the cookies out of DevTools by hand"
    ),
) -> None:
    """Log in by reading the session cookies from your browser.

    With no signed-in browser session it opens the LeetCode login page and
    waits. `--paste` skips the browser and asks for LEETCODE_SESSION and
    csrftoken directly (DevTools → Application → Cookies).
    """
    status: dict | None = None
    if not (session and csrf):
        if paste or session or csrf:
            session, csrf = _prompt_for_cookies(session, csrf)
        else:
            auto = _login_via_browser()
            if auto is None:
                session, csrf = _prompt_for_cookies(session, csrf)
            else:
                session, csrf, status = auto

    if not session or not csrf:
        die("both cookies are required")

    if status is None:
        status = _signed_in_status(session, csrf)
        if status is None:
            die("LeetCode says those cookies are not signed in",
                "make sure you copied LEETCODE_SESSION in full — it is long")
            raise typer.Exit(1)

    creds = Credentials(session=session, csrf=csrf, username=status.get("username", ""))
    save_credentials(creds)
    badge = " (premium)" if status.get("isPremium") else ""
    console.print(
        Text("✔ ", style="bold green")
        + Text(f"logged in as {creds.username}{badge}")
    )


def _signed_in_status(session: str, csrf: str, probe: bool = False) -> dict | None:
    """user_status for these cookies, or None when they are not signed in.

    ``probe`` marks a best-effort candidate check during browser login: there
    a network hiccup means "try the next cookie jar", not a fatal error.
    """
    with LeetCode(Credentials(session=session, csrf=csrf)) as lc:
        try:
            status = lc.user_status()
        except LeetCodeError as exc:
            if probe:
                return None
            die(f"could not verify the session: {exc}")
            raise
    return status if status.get("isSignedIn") else None


def _prompt_for_cookies(session: str = "", csrf: str = "") -> tuple[str, str]:
    if not session:
        console.print(
            Panel(
                Text.from_markup(
                    "1. Sign in at [blue underline]https://leetcode.com[/]\n"
                    "2. DevTools → Application → Cookies → https://leetcode.com\n"
                    "3. Copy the values of [bold]LEETCODE_SESSION[/] and [bold]csrftoken[/]"
                ),
                title="where to find your cookies",
                border_style="dim",
            )
        )
        session = typer.prompt("LEETCODE_SESSION", hide_input=True).strip()
    if not csrf:
        csrf = typer.prompt("csrftoken").strip()
    return session, csrf


def _read_browser_cookies() -> list[dict[str, str]] | None:
    """LeetCode cookie candidates, one per browser that has a session.

    Each browser's jar stays separate — merging them (browser_cookie3.load)
    would let a stale session in one browser shadow the one you just signed
    in with in another. Under WSL the Windows Firefox profiles are read too
    (browser_cookie3 only knows Linux paths, and Windows Chrome/Edge encrypt
    theirs beyond reach). Returns None when no store is readable at all.
    """
    candidates: list[dict[str, str]] = []
    readable = False

    try:
        import browser_cookie3  # type: ignore
        loaders = list(browser_cookie3.all_browsers)
    except ImportError:
        loaders = []
    for loader in loaders:
        try:
            jar = loader(domain_name="leetcode.com")
        except Exception:  # browser_cookie3 raises a wide variety of errors
            continue
        readable = True
        cookies = {c.name: c.value for c in jar}
        if cookies.get("LEETCODE_SESSION") and cookies.get("csrftoken"):
            candidates.append(cookies)

    if browser.is_wsl():
        jars = browser.windows_firefox_cookies()
        if jars is not None:
            readable = True
            for cookies in jars:
                if cookies.get("LEETCODE_SESSION") and cookies.get("csrftoken"):
                    candidates.append(cookies)

    return candidates if readable else None


def _login_via_browser(attempts: int = 5) -> tuple[str, str, dict] | None:
    """Pull a signed-in session out of a local browser.

    Opens the login page and waits when no browser is signed in yet.
    Returns None when no cookie store is readable at all, so login() can
    fall back to pasting.
    """
    candidates = _read_browser_cookies()
    if candidates is None:
        console.print(
            Text("could not read any browser's cookies — paste them instead", style="dim")
        )
        return None

    opened = False
    for _ in range(attempts):
        for cookies in candidates:
            session = cookies["LEETCODE_SESSION"]
            csrf = cookies["csrftoken"]
            status = _signed_in_status(session, csrf, probe=True)
            if status is not None:
                return session, csrf, status
        if not opened:
            console.print(
                Text("no signed-in LeetCode session in your browser — opening the login page…",
                     style="dim")
            )
            if not browser.open_url(LOGIN_URL):
                console.print(Text(f"could not open a browser — go to {LOGIN_URL}",
                                   style="dim"))
            if browser.is_wsl():
                console.print(
                    Text("WSL can only read Windows Firefox cookies — signing in with "
                         "Chrome or Edge? run `lc login --paste` instead", style="dim")
                )
            opened = True
        try:
            # Browsers flush cookies to disk lazily; a beat before re-reading
            # makes the first retry much more likely to see the new session.
            console.input(
                "sign in there, wait a few seconds, then press [bold]Enter[/] to retry "
            )
        except EOFError:
            break
        time.sleep(1.0)
        candidates = _read_browser_cookies() or []
    die("still no signed-in browser session",
        "run `lc login --paste` to enter the cookies by hand")
    raise typer.Exit(1)


@app.command()
def logout() -> None:
    """Forget the stored session cookies."""
    clear_credentials()
    console.print(Text("✔ logged out", style="green"))


@app.command()
def whoami() -> None:
    """Show the account lc is using."""
    with client(require_auth=True) as lc:
        status = lc.user_status()
    if not status.get("isSignedIn"):
        die("session expired", "run `lc login` again")
    console.print(
        Text("● ", style="green")
        + Text(status.get("username", "?"), style="bold")
        + Text(" (premium)" if status.get("isPremium") else "", style="yellow")
    )


# --------------------------------------------------------------------------- browsing

@app.command()
def sync() -> None:
    """Refresh the local problem index (also picks up your solved status)."""
    with client() as lc:
        count = _sync(lc)
    console.print(Text(f"✔ indexed {count} problems", style="green"))


@app.command("list")
def list_problems(
    keyword: str = typer.Argument("", help="filter by title or slug"),
    difficulty: str = typer.Option("", "--difficulty", "-d", help="easy | medium | hard"),
    tag: str = typer.Option("", "--tag", "-t", help="topic tag, e.g. 'Dynamic Programming'"),
    status: str = typer.Option("", "--status", "-s", help="solved | attempted | todo"),
    limit: int = typer.Option(30, "--limit", "-n"),
    offset: int = typer.Option(0, "--offset"),
    free: bool = typer.Option(False, "--free", help="hide premium-only problems"),
    tags: bool = typer.Option(False, "--tags", help="show topic tags"),
) -> None:
    """Browse the problem set."""
    with client() as lc:
        _ensure_index(lc)

    rows = store.search(
        keyword=keyword, difficulty=difficulty, status=status, tag=tag,
        include_paid=not free, limit=limit, offset=offset,
    )
    if not rows:
        console.print(Text("no problems matched", style="dim"))
        return

    total = store.count(
        keyword=keyword, difficulty=difficulty, status=status, tag=tag,
        include_paid=not free,
    )
    console.print(problems_table(rows, show_tags=tags))
    shown = offset + len(rows)
    if shown < total:
        console.print(
            Text(f"\n{shown} of {total} — more with --offset {shown}", style="dim")
        )


@app.command()
def show(
    ref: str = typer.Argument(..., help="problem id, slug or title"),
    fresh: bool = typer.Option(False, "--fresh", help="bypass the local cache"),
    web: bool = typer.Option(False, "--web", help="open in your browser instead"),
) -> None:
    """Print a problem statement."""
    with client() as lc:
        problem = resolve_problem(ref, lc, fresh=fresh)

    if web:
        if not browser.open_url(problem.url):
            console.print(problem.url)
        return

    console.print()
    console.print(problem_header(problem))
    console.print()
    if problem.paid_only and not problem.content:
        die("this is a premium problem and your account cannot read it")
    console.print(render_statement(problem.content))
    if problem.hints:
        console.print(Text("Hints", style="bold dim"))
        for i, hint in enumerate(problem.hints, 1):
            console.print(render_statement(f"<p>{i}. {hint}</p>"))


@app.command()
def daily(
    pick_it: bool = typer.Option(False, "--pick", "-p", help="also set up a solution file"),
) -> None:
    """Show today's daily challenge."""
    with client() as lc:
        date, summary = lc.daily()
        console.print(Text(f"Daily challenge · {date}", style="bold"))
        console.print(problems_table([summary]))
        if pick_it:
            console.print()
            _pick(lc, summary.slug, None, open_editor=True, overwrite=False)


@app.command()
def random(
    difficulty: str = typer.Option("", "--difficulty", "-d"),
    tag: str = typer.Option("", "--tag", "-t"),
    status: str = typer.Option("todo", "--status", "-s", help="solved | attempted | todo"),
    paid: bool = typer.Option(False, "--paid", help="include premium-only problems"),
    pick_it: bool = typer.Option(False, "--pick", "-p", help="also set up a solution file"),
) -> None:
    """Pick a random problem you have not solved."""
    with client() as lc:
        _ensure_index(lc)
        summary = store.random_problem(
            difficulty=difficulty, tag=tag, status=status, include_paid=paid
        )
        if summary is None:
            die("nothing matched those filters")
            return
        console.print(problems_table([summary]))
        if pick_it:
            console.print()
            _pick(lc, summary.slug, None, open_editor=True, overwrite=False)


@app.command()
def tags(limit: int = typer.Option(30, "--limit", "-n")) -> None:
    """List topic tags and how many problems carry each."""
    with client() as lc:
        _ensure_index(lc)
    table = Table(box=None, header_style="dim")
    table.add_column("Tag", style="cyan")
    table.add_column("Problems", justify="right", style="dim")
    for name, n in store.all_tags()[:limit]:
        table.add_row(name, str(n))
    console.print(table)


@app.command()
def stat() -> None:
    """Your solve counts by difficulty."""
    creds = load_credentials()
    with client(require_auth=True) as lc:
        # Credentials supplied via env vars carry no username — ask LeetCode.
        username = (creds.username if creds else "") or lc.user_status().get(
            "username", ""
        )
        if not username:
            die("session expired", "run `lc login` again")
        data = lc.profile(username)

    totals = {d["difficulty"]: d["count"] for d in data.get("allQuestionsCount") or []}
    matched = data.get("matchedUser") or {}
    solved = {
        d["difficulty"]: d["count"]
        for d in (matched.get("submitStatsGlobal") or {}).get("acSubmissionNum") or []
    }

    table = Table(box=None, header_style="dim")
    table.add_column("Difficulty")
    table.add_column("Solved", justify="right")
    table.add_column("Total", justify="right", style="dim")
    table.add_column("", width=22)

    for level in ("Easy", "Medium", "Hard"):
        done, total = solved.get(level, 0), totals.get(level, 0)
        ratio = done / total if total else 0
        filled = int(ratio * 20)
        bar = Text("█" * filled + "░" * (20 - filled),
                   style={"Easy": "green", "Medium": "yellow", "Hard": "red"}[level])
        table.add_row(difficulty_text(level), str(done), str(total), bar)

    table.add_row(
        Text("All", style="bold"),
        Text(str(solved.get("All", 0)), style="bold"),
        str(totals.get("All", 0)),
        "",
    )
    console.print(table)
    ranking = (matched.get("profile") or {}).get("ranking")
    if ranking:
        console.print(Text(f"\nglobal ranking: {ranking:,}", style="dim"))


# --------------------------------------------------------------------------- solving

def _pick(
    lc: LeetCode, ref: str, lang_name: str | None, open_editor: bool, overwrite: bool
) -> workspace.Solution:
    config = load_config()
    problem = resolve_problem(ref, lc)
    if problem.paid_only and not problem.snippets:
        die("this is a premium problem and your account cannot open it")

    lang = pick_language(config, problem, lang_name)
    try:
        solution = workspace.create(config, problem, lang, overwrite=overwrite)
    except ValueError as exc:
        die(str(exc))
        raise

    console.print(
        Text("✔ ", style="green")
        + Text(f"[{problem.frontend_id}] {problem.title} ", style="bold")
        + difficulty_text(problem.difficulty)
    )
    console.print(Text(f"  {solution.file}", style="dim"))

    if open_editor and not workspace.open_in_editor(config, solution.file):
        console.print(
            Text("  (set $EDITOR or `lc config editor <cmd>` to auto-open)", style="dim")
        )
    return solution


@app.command()
def pick(
    ref: str = typer.Argument(..., help="problem id, slug or title"),
    lang: str = typer.Option("", "--lang", "-l", help="override the default language"),
    edit: bool = typer.Option(True, "--edit/--no-edit", help="open in $EDITOR"),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="reset the file back to the starter code"
    ),
) -> None:
    """Set up a solution file for a problem and open it."""
    with client() as lc:
        _pick(lc, ref, lang or None, open_editor=edit, overwrite=overwrite)


@app.command()
def edit(ref: str = typer.Argument("", help="problem id, slug or title")) -> None:
    """Open an existing solution file."""
    config = load_config()
    if not ref:
        found = _current_dir_problem()
        if not found:
            die("no problem given and this is not a problem directory")
            return
        _, _, path = found
        if not workspace.open_in_editor(config, path):
            die("no editor configured", "set $EDITOR or run `lc config editor <cmd>`")
        return

    with client() as lc:
        problem = resolve_problem(ref, lc)
    solution = workspace.load(config, problem)
    if solution is None:
        die(f"no solution file yet for {problem.title}", f"run `lc pick {ref}` first")
        return
    if not workspace.open_in_editor(config, solution.file):
        die("no editor configured", "set $EDITOR or run `lc config editor <cmd>`")


def _load_for_judging(
    lc: LeetCode, ref: str, lang_name: str
) -> tuple[Problem, Language, str]:
    config = load_config()
    requested = resolve(lang_name) if lang_name else None
    if lang_name and requested is None:
        die(f"unknown language {lang_name!r}", "supported: " + ", ".join(sorted(BY_SLUG)))

    if not ref:
        found = _current_dir_problem()
        if not found:
            die("no problem given and this is not a problem directory",
                "cd into a problem directory or pass an id: `lc test 1`")
            raise typer.Exit(1)
        slug, dir_lang, path = found
        problem = resolve_problem(slug, lc)
        # An explicit --lang still wins over whatever .lc.json last recorded.
        if requested is None or requested.slug == dir_lang.slug:
            return problem, dir_lang, path.read_text()
        ref = slug

    problem = resolve_problem(ref, lc)
    solution = workspace.load(config, problem, requested)
    if solution is None:
        if requested is not None:
            die(f"no {requested.name} solution file for {problem.title}",
                f"run `lc pick {problem.frontend_id} -l {requested.slug}` first")
        die(f"no solution file for {problem.title}",
            f"run `lc pick {problem.frontend_id}` first")
        raise typer.Exit(1)
    return problem, solution.language, solution.code


@app.command()
def test(
    ref: str = typer.Argument("", help="problem id, slug or title (default: this directory)"),
    lang: str = typer.Option("", "--lang", "-l"),
    input_file: Optional[Path] = typer.Option(
        None, "--input", "-i", help="file with custom test input (one arg per line)"
    ),
    case: str = typer.Option(
        "", "--case", "-c",
        help="inline test input; a literal \\n becomes a newline (input arguments "
             "are newline-separated)",
    ),
) -> None:
    """Run your code against the sample tests on LeetCode's judge."""
    with client(require_auth=True) as lc:
        problem, language, code = _load_for_judging(lc, ref, lang)
        body = workspace.strip_header(code, language)

        if case:
            data_input = case.replace("\\n", "\n")
        elif input_file:
            if not input_file.exists():
                die(f"no such file: {input_file}")
            data_input = input_file.read_text().rstrip("\n")
        else:
            data_input = problem.example_testcases or problem.sample_testcase

        with console.status(
            f"running on LeetCode's judge ({language.name})…", spinner="dots"
        ):
            try:
                result = lc.run(problem, language.slug, body, data_input)
            except LeetCodeError as exc:
                die(str(exc))
                raise
    if result.accepted:
        fx.play(console, big=False)
    else:
        fx.defeat(console, big=False)
    print_result(result, problem, data_input)
    raise typer.Exit(0 if result.accepted else 1)


@app.command()
def submit(
    ref: str = typer.Argument("", help="problem id, slug or title (default: this directory)"),
    lang: str = typer.Option("", "--lang", "-l"),
    yes: bool = typer.Option(False, "--yes", "-y", help="skip the confirmation"),
) -> None:
    """Submit your solution to LeetCode."""
    with client(require_auth=True) as lc:
        problem, language, code = _load_for_judging(lc, ref, lang)
        body = workspace.strip_header(code, language)

        if not yes:
            console.print(
                Text("submitting ", style="dim")
                + Text(f"[{problem.frontend_id}] {problem.title}", style="bold")
                + Text(f" as {language.name}", style="dim")
            )
            if not typer.confirm("continue?", default=True):
                raise typer.Exit(1)

        with console.status("waiting for the judge…", spinner="dots"):
            try:
                result = lc.submit(problem, language.slug, body)
            except LeetCodeError as exc:
                die(str(exc))
                raise

    known = store.find(problem.slug)
    if result.accepted:
        store.update_status(problem.slug, "ac")
    elif known is not None and not known.solved:
        store.update_status(problem.slug, "notac")
    note = review.record_submit(
        problem.slug, result.accepted, review.curve_of(load_config())
    )

    if result.accepted:
        fx.play(console, big=True)
    else:
        fx.defeat(console, big=True)
    print_result(result, problem)
    if note:
        console.print(Text(f"  {note}", style="dim"))
    raise typer.Exit(0 if result.accepted else 1)


@app.command()
def history(
    ref: str = typer.Argument("", help="problem id, slug or title"),
    limit: int = typer.Option(10, "--limit", "-n"),
) -> None:
    """Your recent submissions for a problem."""
    with client(require_auth=True) as lc:
        if not ref:
            found = _current_dir_problem()
            if not found:
                die("no problem given and this is not a problem directory")
                return
            ref = found[0]
        problem = resolve_problem(ref, lc)
        rows = lc.submissions(problem.slug, limit=limit)

    if not rows:
        console.print(Text("no submissions yet", style="dim"))
        return

    table = Table(box=None, header_style="dim")
    table.add_column("When", style="dim")
    table.add_column("Status")
    table.add_column("Language", style="cyan")
    table.add_column("Runtime", justify="right")
    table.add_column("Memory", justify="right")
    for row in rows:
        ok = row.get("statusDisplay") == "Accepted"
        ts = int(row.get("timestamp") or 0)
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "—"
        table.add_row(
            when,
            Text(row.get("statusDisplay", "?"), style="green" if ok else "red"),
            row.get("lang", ""),
            row.get("runtime", "") or "—",
            row.get("memory", "") or "—",
        )
    console.print(table)


@app.command()
def code(ref: str = typer.Argument("", help="problem id, slug or title")) -> None:
    """Print your current solution with syntax highlighting."""
    with client() as lc:
        problem, language, source = _load_for_judging(lc, ref, "")
    console.print(Syntax(source, language.lexer, theme="ansi_dark", line_numbers=True))


# --------------------------------------------------------------------------- review

review_app = typer.Typer(
    help="Spaced-repetition deck: problems saved to re-solve on a schedule."
)
app.add_typer(review_app, name="review")


def _deck_find(ref: str) -> review.ReviewItem | None:
    """Resolve a user reference against the deck itself, so it works offline."""
    ref = ref.strip()
    unpadded = ref.lstrip("0") or ref
    slug = ref.lower().replace(" ", "-")
    for item in review.live(review.load()).values():
        if item.slug == slug or item.frontend_id in (ref, unpadded):
            return item
        if item.title and item.title.lower() == ref.lower():
            return item
    return None


def due_text(days: int) -> Text:
    """How a review date reads: '-3d' overdue, 'today', or '8d' out."""
    if days < 0:
        return Text(f"{days}d", style="bold red")
    if days == 0:
        return Text("today", style="bold yellow")
    return Text(f"{days}d", style="dim")


@review_app.callback(invoke_without_command=True)
def review_list(ctx: typer.Context) -> None:
    """With no subcommand: show the deck, soonest review first."""
    if ctx.invoked_subcommand is not None:
        return
    items = review.live(review.load())
    if not items:
        console.print(
            Text("review deck is empty — press m in the TUI, or `lc review add 322`",
                 style="dim")
        )
        return

    today = date.today()
    table = Table(box=None, header_style="dim")
    # Budget the title explicitly: left to itself Rich shrinks the fixed
    # columns in a narrow terminal, eating the id — the thing you type into
    # `lc review level 1140 5` — and dropping the level entirely.
    chrome = 5 + 10 + 2 + 6 + 5 * 2  # fixed columns, plus per-column padding
    table.add_column("#", justify="right", style="dim", width=5, no_wrap=True)
    table.add_column("Title", no_wrap=True, overflow="ellipsis",
                     width=max(16, console.width - chrome))
    table.add_column("Difficulty", width=10, no_wrap=True)
    table.add_column("Lv", justify="right", width=2, no_wrap=True)
    table.add_column("Next", justify="right", width=6, no_wrap=True)
    for item in review.order(items):
        table.add_row(
            item.frontend_id,
            item.title or item.slug,
            difficulty_text(item.difficulty) if item.difficulty else Text("—"),
            str(item.level),
            due_text(item.due_in(today)),
        )
    console.print(table)

    due = review.due_count(items, today)
    if due:
        console.print(
            Text(f"\n{due} due — `lc review postpone` pushes them to tomorrow",
                 style="dim")
        )
    config = load_config()
    line = gitsync.summary(config)
    if line:
        state = gitsync.status(config).state
        console.print(
            Text(("" if due else "\n") + line,
                 style={"clean": "green", "pending": "yellow",
                        "failed": "red"}.get(state, "dim"))
        )


@review_app.command("add")
def review_add(
    ref: str = typer.Argument(
        "", help="problem id, slug or title (default: this directory)"
    ),
    level: Optional[int] = typer.Option(
        None, "--level", "-l", min=1, help="starting level"
    ),
) -> None:
    """Save a problem to the review deck."""
    config = load_config()
    curve = review.curve_of(config)

    if not ref:
        # No argument: the problem directory you are sitting in — this is what
        # the editor keys bind to.
        found = _current_dir_problem()
        if not found:
            die("no problem given and this is not a problem directory",
                "cd into a problem directory or pass an id: `lc review add 322`")
            return
        ref = found[0]

    summary = store.find(ref)
    if summary is not None:
        slug, title = summary.slug, summary.title
        frontend_id, difficulty = summary.frontend_id, summary.difficulty
    else:
        # Not in the local index — ask LeetCode (also handles a first run).
        with client() as lc:
            problem = resolve_problem(ref, lc)
        slug, title = problem.slug, problem.title
        frontend_id, difficulty = problem.frontend_id, problem.difficulty

    item = review.add(
        slug, title=title, frontend_id=frontend_id, difficulty=difficulty, curve=curve
    )
    # Only an explicit --level moves an already-saved problem: a plain re-add
    # must never knock a level-3 problem back to 1.
    if level is not None and level != item.level:
        item = review.shift_level(slug, level - item.level, curve)
        assert item is not None
    console.print(
        Text("✔ ", style="green")
        + Text(f"[{item.frontend_id}] {item.title} ", style="bold")
        + Text(f"— level {item.level}, next review in {item.due_in(date.today())}d",
               style="dim")
    )


@review_app.command("rm")
def review_rm(ref: str = typer.Argument(..., help="problem id, slug or title")) -> None:
    """Take a problem off the deck."""
    item = _deck_find(ref)
    if item is None:
        die(f"{ref!r} is not on the review deck", "see the deck with `lc review`")
        return
    review.remove(item.slug)
    console.print(Text(f"✔ removed [{item.frontend_id}] {item.title or item.slug}",
                       style="green"))


@review_app.command("level")
def review_level(
    ref: str = typer.Argument(..., help="problem id, slug or title"),
    level: int = typer.Argument(..., min=1, help="new level (1 = shortest interval)"),
) -> None:
    """Set a problem's level by hand; the next review is scheduled from today."""
    item = _deck_find(ref)
    if item is None:
        die(f"{ref!r} is not on the review deck", "add it with `lc review add`")
        return
    curve = review.curve_of(load_config())
    updated = review.shift_level(item.slug, level - item.level, curve)
    assert updated is not None
    console.print(
        Text("✔ ", style="green")
        + Text(f"[{updated.frontend_id}] {updated.title or updated.slug} ", style="bold")
        + Text(f"— level {updated.level}, next review in "
               f"{updated.due_in(date.today())}d", style="dim")
    )


@review_app.command("postpone")
def review_postpone() -> None:
    """Not today: move everything due today (or overdue) to tomorrow."""
    moved = review.postpone_due()
    if moved:
        console.print(Text(f"✔ postponed {moved} problem(s) to tomorrow", style="green"))
    else:
        console.print(Text("nothing due today", style="dim"))


def _repo_url() -> str:
    url = load_config().review_repo.strip()
    if not url:
        die("no review repo configured",
            "`lc config repo git@github.com:you/lc-review.git` (an empty repo "
            "you own — lc writes review.json and REVIEW.md into it)")
    return url


def _merge_report(added: int, updated: int) -> None:
    if added or updated:
        console.print(
            Text("✔ ", style="green")
            + Text(f"pulled {added} new, {updated} updated", style="")
        )
    else:
        console.print(Text("already up to date", style="dim"))


@review_app.command("pull")
def review_pull() -> None:
    """Bring the deck in your review repo into this machine's deck."""
    url = _repo_url()
    with console.status("pulling the review deck…", spinner="dots"):
        try:
            added, updated = gitsync.pull(url)
        except gitsync.SyncError as exc:
            die(str(exc), exc.hint)
            raise
    _merge_report(added, updated)


@review_app.command("push")
def review_push() -> None:
    """Publish this machine's deck to your review repo."""
    url = _repo_url()
    with console.status("pushing the review deck…", spinner="dots"):
        try:
            total, changed = gitsync.push(url)
        except gitsync.SyncError as exc:
            die(str(exc), exc.hint)
            raise
    if changed:
        console.print(Text(f"✔ pushed {total} problem(s)", style="green"))
    else:
        console.print(Text("nothing to push — the repo already matches", style="dim"))


@review_app.command("sync")
def review_sync() -> None:
    """Pull, then push: make this machine and the repo agree."""
    url = _repo_url()
    with console.status("syncing the review deck…", spinner="dots"):
        try:
            added, updated, changed = gitsync.sync(url)
        except gitsync.SyncError as exc:
            die(str(exc), exc.hint)
            raise
    _merge_report(added, updated)
    console.print(
        Text("✔ pushed" if changed else "✔ repo already matches", style="green")
    )


# --------------------------------------------------------------------------- config

config_app = typer.Typer(help="Read and change lc settings.", no_args_is_help=True)
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show() -> None:
    """Print the current settings."""
    cfg = load_config()
    table = Table(box=None, header_style="dim")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")
    curve = review.curve_of(cfg)
    table.add_row("workspace", str(cfg.workspace_path))
    table.add_row("lang", cfg.lang)
    table.add_row("editor", cfg.resolve_editor() or Text("— (set $EDITOR)", style="dim"))
    table.add_row("favorite_langs", ", ".join(cfg.favorite_langs))
    table.add_row(
        "review curve",
        ", ".join(str(d) for d in curve)
        + (" (default)" if not cfg.review_curve else ""),
    )
    table.add_row("review repo", cfg.review_repo or Text("— (lc config repo …)",
                                                         style="dim"))
    table.add_row("lc home", str(home()))
    console.print(table)


@config_app.command("lang")
def config_lang(name: str = typer.Argument(..., help="default language for `lc pick`")) -> None:
    """Set the default solving language."""
    lang = resolve(name)
    if lang is None:
        die(f"unknown language {name!r}", "supported: " + ", ".join(sorted(BY_SLUG)))
        return
    cfg = load_config()
    cfg.lang = lang.slug
    save_config(cfg)
    console.print(Text(f"✔ default language: {lang.name}", style="green"))


@config_app.command("workspace")
def config_workspace(path: Path = typer.Argument(..., help="where solution files live")) -> None:
    """Set the workspace directory."""
    cfg = load_config()
    # Anchor it now: a relative path would re-resolve against the cwd of every
    # future invocation and scatter solution files around.
    cfg.workspace = str(path.expanduser().resolve())
    save_config(cfg)
    cfg.workspace_path.mkdir(parents=True, exist_ok=True)
    console.print(Text(f"✔ workspace: {cfg.workspace_path}", style="green"))


@config_app.command("editor")
def config_editor(command: str = typer.Argument(..., help="e.g. 'code -w' or 'nvim'")) -> None:
    """Set the editor command used by `lc pick` / `lc edit`."""
    cfg = load_config()
    cfg.editor = command
    save_config(cfg)
    console.print(Text(f"✔ editor: {command}", style="green"))


@config_app.command("repo")
def config_repo(
    url: str = typer.Argument(
        ..., help="git remote for the review deck; 'none' unsets it"
    ),
) -> None:
    """Set the git repo `lc review sync` keeps your deck in."""
    cfg = load_config()
    if url.strip().lower() in ("none", "off", ""):
        cfg.review_repo = ""
        save_config(cfg)
        console.print(Text("✔ review repo: none", style="green"))
        return
    cfg.review_repo = url.strip()
    save_config(cfg)
    console.print(Text(f"✔ review repo: {cfg.review_repo}", style="green"))
    console.print(Text("  `lc review sync` publishes review.json + REVIEW.md there",
                       style="dim"))


@config_app.command("curve")
def config_curve(
    days: str = typer.Argument(
        ...,
        help="days per level, comma-separated — e.g. '1,2,4,7,15' means level 1 "
             "reviews after 1 day, level 2 after 2, and the top level is 5; "
             "'reset' restores the default Ebbinghaus curve",
    ),
) -> None:
    """Set the review deck's memory curve (and with it, the number of levels)."""
    cfg = load_config()
    if days.strip().lower() in ("reset", "default"):
        cfg.review_curve = []
        save_config(cfg)
        curve = list(review.DEFAULT_CURVE)
    else:
        try:
            curve = [int(part) for part in days.replace(" ", "").split(",") if part]
        except ValueError:
            die(f"could not read {days!r}", "give days as numbers: `lc config curve 1,2,4,7`")
            return
        if not curve or any(not 1 <= d <= review.MAX_GAP_DAYS for d in curve):
            die(f"each level needs 1 to {review.MAX_GAP_DAYS} days",
                "e.g. `lc config curve 1,2,4,7,15`")
            return
        cfg.review_curve = curve
        save_config(cfg)
    console.print(
        Text("✔ review curve: ", style="green")
        + Text(", ".join(f"{d}d" for d in curve))
        + Text(f"  (levels 1–{len(curve)})", style="dim")
    )


# --------------------------------------------------------------------------- setup

setup_app = typer.Typer(help="Install optional editor integrations.", no_args_is_help=True)
app.add_typer(setup_app, name="setup")


@setup_app.command("vim")
def setup_vim(
    force: bool = typer.Option(
        False, "--force", help="replace a plugin file that has local changes"
    ),
) -> None:
    """Install the Vim plugin: \\t runs `lc test`, \\s runs `lc submit`."""
    try:
        path, status = editors.install_vim_plugin(force=force)
    except FileExistsError as exc:
        die(f"{exc} exists with different content",
            "edited locally, or written by another lc version — re-run with --force to replace it")
        return
    label = "already installed" if status == "unchanged" else status
    console.print(Text(f"✔ {label}: ", style="green") + Text(str(path), style="dim"))

    cfg = load_config()
    if not cfg.resolve_editor():
        cfg.editor = "vim"
        save_config(cfg)
        console.print(Text("✔ editor: vim", style="green"))
    console.print(
        Text("  in a solution buffer: \\t = save + test, \\s = save + submit, "
             "\\p = toggle statement, \\o = open in browser, \\q = save + quit",
             style="dim")
    )


@app.command("langs")
def list_langs() -> None:
    """List the languages LeetCode accepts."""
    table = Table(box=None, header_style="dim")
    table.add_column("Slug", style="cyan")
    table.add_column("Name")
    table.add_column("File", style="dim")
    for lang in LANGUAGES:
        table.add_row(lang.slug, lang.name, f"solution{lang.ext}")
    console.print(table)


@app.command()
def tui(
    ref: str = typer.Argument("", help="open straight to a problem"),
) -> None:
    """Launch the full-screen browser."""
    from .tui import run_tui

    run_tui(ref or None)


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-V", help="show the version"),
) -> None:
    if version:
        console.print(f"lc {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        # Bare `lc` in a terminal opens the TUI; keep printing help for pipes
        # and scripts, where a full-screen app would be hostile.
        if sys.stdin.isatty() and sys.stdout.isatty():
            from .tui import run_tui

            run_tui(None)
        else:
            console.print(ctx.get_help())
        raise typer.Exit()


def main() -> None:
    try:
        app()
    except AuthError as exc:
        # die() raises typer.Exit, but out here nothing catches it — the
        # message would come with a full traceback attached. Exit directly.
        _error(str(exc), "run `lc login`")
        sys.exit(1)
    except LeetCodeError as exc:
        _error(str(exc))
        sys.exit(1)
    except KeyboardInterrupt:
        err.print(Text("\ninterrupted", style="dim"))
        sys.exit(130)


if __name__ == "__main__":
    main()
