"""The on-disk workspace: one directory per problem.

    ~/leetcode/0001-two-sum/
        README.md      rendered statement, for reading in an editor
        solution.py    starter code + the user's work
        .lc.json       which problem/language this directory is for

The whole solution file is what gets submitted. Older lc versions added a
generated comment header; `strip_header` still removes those before judging.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .api import Problem
from .config import Config
from .langs import Language, by_extension, resolve


def slug_dir_name(frontend_id: str, slug: str) -> str:
    try:
        padded = f"{int(frontend_id):04d}"
    except ValueError:
        padded = frontend_id or "0000"
    return f"{padded}-{slug}"


@dataclass
class Solution:
    directory: Path
    file: Path
    language: Language
    problem_slug: str
    question_id: str
    frontend_id: str

    @property
    def code(self) -> str:
        return self.file.read_text()


def problem_dir(config: Config, problem: Problem) -> Path:
    return config.workspace_path / slug_dir_name(problem.frontend_id, problem.slug)


def starter_code(problem: Problem, lang: Language) -> str:
    """Build the exact initial solution text used on disk and in the editor."""
    snippet = problem.snippets.get(lang.slug, "")
    if not snippet:
        available = ", ".join(sorted(problem.snippets)) or "none"
        raise ValueError(
            f"LeetCode has no {lang.name} starter code for this problem "
            f"(available: {available})"
        )
    # Only trailing newlines come off: LeetCode's Python snippets end with the
    # body's indentation, and stripping that leaves a file that will not compile.
    return snippet.rstrip("\n") + "\n"


def statement_markdown(problem: Problem) -> str:
    """A README for the problem directory, so the statement reads well in an editor."""
    from .render import to_markdown

    head = [
        f"# [{problem.frontend_id}] {problem.title}",
        "",
        f"- Difficulty: {problem.difficulty}",
        f"- Tags: {', '.join(problem.tags) or '—'}",
        f"- Link: {problem.url}",
        "",
        "---",
        "",
    ]
    parts = ["\n".join(head), to_markdown(problem.content)]
    if problem.hints:
        # Hints are HTML fragments too, not plain text.
        rendered = [to_markdown(h).strip().replace("\n", " ") for h in problem.hints]
        parts.append("\n## Hints\n")
        parts.append("\n".join(f"{i}. {h}" for i, h in enumerate(rendered, 1)) + "\n")
    return "\n".join(parts)


def create(
    config: Config, problem: Problem, lang: Language, overwrite: bool = False
) -> Solution:
    directory = problem_dir(config, problem)
    directory.mkdir(parents=True, exist_ok=True)

    stem = "Solution" if lang.slug == "java" else "solution"
    file = directory / f"{stem}{lang.ext}"

    if not file.exists() or overwrite:
        file.write_text(starter_code(problem, lang))

    (directory / "README.md").write_text(statement_markdown(problem))
    (directory / ".lc.json").write_text(
        json.dumps(
            {
                "slug": problem.slug,
                "question_id": problem.question_id,
                "frontend_id": problem.frontend_id,
                "title": problem.title,
                "lang": lang.slug,
                "file": file.name,
            },
            indent=2,
        )
        + "\n"
    )
    return Solution(
        directory=directory,
        file=file,
        language=lang,
        problem_slug=problem.slug,
        question_id=problem.question_id,
        frontend_id=problem.frontend_id,
    )


def restart_review(problem: Problem, solution: Solution, today: date) -> bool:
    """Restore starter code once for this day's due-review session.

    The date lives beside the recorded solution rather than in the synced deck:
    opening the editor twice on one machine must not erase work from the first
    visit, while another machine should still begin its own clean recall attempt.
    Returns whether this call performed the reset.
    """
    meta_path = solution.directory / ".lc.json"
    try:
        raw = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    except json.JSONDecodeError:
        raw = {}
    meta = raw if isinstance(raw, dict) else {}
    stamp = today.isoformat()
    if meta.get("review_started") == stamp:
        return False

    # Keep the language and recorded filename that were already in use. A
    # review restart clears the answer; it must not strand it by re-picking in
    # the config default language, the failure ordinary reopen avoids.
    solution.file.write_text(starter_code(problem, solution.language))
    meta.update({
        "slug": problem.slug,
        "question_id": problem.question_id,
        "frontend_id": problem.frontend_id,
        "title": problem.title,
        "lang": solution.language.slug,
        "file": solution.file.name,
        "review_started": stamp,
    })
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    return True


def load(config: Config, problem: Problem, lang: Language | None = None) -> Solution | None:
    """Find an existing solution file for a problem, optionally for a given language."""
    directory = problem_dir(config, problem)
    if not directory.is_dir():
        return None

    meta_path = directory / ".lc.json"
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except json.JSONDecodeError:
            meta = {}

    if lang is None and meta.get("lang"):
        lang = resolve(meta["lang"])

    # The file this workspace was created with wins over a directory scan, so a
    # helper file the user added alongside it never gets submitted by accident.
    recorded = directory / meta["file"] if meta.get("file") else None
    if recorded is not None and recorded.is_file():
        if lang is not None and recorded.suffix == lang.ext:
            candidates = [recorded]
        elif lang is None and by_extension(recorded.suffix):
            candidates = [recorded]
        else:
            candidates = []
    else:
        candidates = []

    if not candidates:
        candidates = sorted(
            p for p in directory.iterdir()
            if p.is_file() and p.name not in (".lc.json", "README.md")
        )
        if lang is not None:
            # Never fall back to another language's file — submitting Python as
            # Go would be a confusing waste of a submission.
            candidates = [p for p in candidates if p.suffix == lang.ext]

    for path in candidates:
        found = lang or by_extension(path.suffix)
        if found is None:
            continue
        return Solution(
            directory=directory,
            file=path,
            language=found,
            problem_slug=problem.slug,
            question_id=meta.get("question_id", problem.question_id),
            frontend_id=problem.frontend_id,
        )
    return None


def find_by_path(config: Config, path: Path) -> tuple[str, Language, Path] | None:
    """Resolve a solution file (or its directory) back to a problem slug.

    Used so `lc test` with no arguments works from inside a problem directory.
    """
    path = path.expanduser().resolve()
    start = path if path.is_dir() else path.parent
    # Walk up like git does, so `lc test` also works from a scratch/ subdir
    # the user made inside the problem directory.
    directory = next(
        (d for d in (start, *start.parents) if (d / ".lc.json").exists()), None
    )
    if directory is None:
        return None
    try:
        meta = json.loads((directory / ".lc.json").read_text())
    except json.JSONDecodeError:
        return None

    lang = resolve(meta.get("lang", "")) or by_extension(path.suffix)
    file = path if path.is_file() else directory / meta.get("file", "")
    if lang is None or not file.exists():
        return None
    return meta.get("slug", ""), lang, file


def strip_header(code: str, lang: Language) -> str:
    """Drop a legacy lc-generated header comment before submitting.

    New solutions contain only starter code. Older lc versions wrote a leading
    comment block; the problem URL distinguishes it from the user's comments.
    """
    marker = re.escape(lang.comment)
    match = re.match(rf"\A(?:{marker}[^\n]*\n)+[ \t]*\n", code)
    if match and "leetcode.com/problems/" in match.group(0):
        return code[match.end():]
    return code


def open_in_editor(config: Config, target: Path) -> bool:
    editor = config.resolve_editor()
    if not editor:
        return False
    try:
        # shlex so an editor path with spaces ('/Apps/My Editor/code' -w) works.
        command = shlex.split(editor)
        if not command:
            return False
        subprocess.run([*command, str(target)], check=False)
    except (OSError, ValueError):
        return False
    return True
