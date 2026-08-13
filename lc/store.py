"""Local sqlite cache.

Two things are cached: the problem index (so `lc list` / id lookup / random are
instant and work offline) and full statements (so re-reading a problem does not
hit the network). Statements expire; the index is refreshed explicitly with
`lc sync` or lazily when it is missing.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from typing import Any, Iterable

from .api import Problem, ProblemSummary
from .config import cache_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS problems (
    slug        TEXT PRIMARY KEY,
    frontend_id TEXT,
    title       TEXT,
    difficulty  TEXT,
    ac_rate     REAL,
    paid_only   INTEGER,
    status      TEXT,
    tags        TEXT
);
CREATE INDEX IF NOT EXISTS problems_frontend_id ON problems(frontend_id);
CREATE INDEX IF NOT EXISTS problems_title ON problems(title);

CREATE TABLE IF NOT EXISTS statements (
    slug       TEXT PRIMARY KEY,
    payload    TEXT,
    fetched_at REAL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

STATEMENT_TTL = 7 * 24 * 3600.0


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(cache_path())
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# --------------------------------------------------------------------------- index

def replace_index(problems: Iterable[ProblemSummary]) -> int:
    rows = [
        (
            p.slug, p.frontend_id, p.title, p.difficulty, p.ac_rate,
            int(p.paid_only), p.status or "", json.dumps(p.tags),
        )
        for p in problems
    ]
    with closing(connect()) as conn, conn:
        conn.execute("DELETE FROM problems")
        conn.executemany(
            "INSERT INTO problems "
            "(slug, frontend_id, title, difficulty, ac_rate, paid_only, status, tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('synced_at', ?)",
            (str(time.time()),),
        )
    return len(rows)


def update_status(slug: str, status: str) -> None:
    with closing(connect()) as conn, conn:
        conn.execute("UPDATE problems SET status = ? WHERE slug = ?", (status, slug))


def index_size() -> int:
    with closing(connect()) as conn:
        return conn.execute("SELECT COUNT(*) FROM problems").fetchone()[0]


def synced_at() -> float | None:
    with closing(connect()) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = 'synced_at'").fetchone()
    if not row:
        return None
    try:
        return float(row[0])
    except (TypeError, ValueError):
        return None


def _row_to_summary(row: sqlite3.Row) -> ProblemSummary:
    return ProblemSummary(
        frontend_id=row["frontend_id"],
        title=row["title"],
        slug=row["slug"],
        difficulty=row["difficulty"],
        ac_rate=row["ac_rate"] or 0.0,
        paid_only=bool(row["paid_only"]),
        status=row["status"] or None,
        tags=json.loads(row["tags"] or "[]"),
    )


def find(ref: str) -> ProblemSummary | None:
    """Look a problem up by frontend id, slug, or exact title (case-insensitive)."""
    ref = ref.strip()
    # "0322" should find problem 322 — directory names pad ids with zeros.
    unpadded = ref.lstrip("0") or ref
    with closing(connect()) as conn:
        row = conn.execute(
            "SELECT * FROM problems WHERE frontend_id IN (?, ?) OR slug = ? "
            "OR lower(title) = lower(?) LIMIT 1",
            (ref, unpadded, ref, ref),
        ).fetchone()
    return _row_to_summary(row) if row else None


def _escape_like(text: str) -> str:
    """Make LIKE match `%` and `_` in the needle literally."""
    return (
        text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    )


def search(
    keyword: str = "",
    difficulty: str = "",
    status: str = "",
    tag: str = "",
    include_paid: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> list[ProblemSummary]:
    clauses: list[str] = []
    params: list[Any] = []
    if keyword:
        needle = f"%{_escape_like(keyword)}%"
        clauses.append(
            "(title LIKE ? ESCAPE '\\' OR slug LIKE ? ESCAPE '\\' OR frontend_id = ?)"
        )
        params += [needle, needle, keyword]
    if difficulty:
        clauses.append("lower(difficulty) = lower(?)")
        params.append(difficulty)
    if status == "solved":
        clauses.append("status = 'ac'")
    elif status == "attempted":
        clauses.append("status = 'notac'")
    elif status == "todo":
        clauses.append("(status IS NULL OR status = '')")
    if tag:
        clauses.append("lower(tags) LIKE lower(?) ESCAPE '\\'")
        params.append(f'%"{_escape_like(tag)}"%')
    if not include_paid:
        clauses.append("paid_only = 0")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = (
        f"SELECT * FROM problems {where} "
        "ORDER BY CAST(frontend_id AS INTEGER) LIMIT ? OFFSET ?"
    )
    with closing(connect()) as conn:
        rows = conn.execute(sql, [*params, limit, offset]).fetchall()
    return [_row_to_summary(r) for r in rows]


def count(**kwargs: Any) -> int:
    """Same filters as :func:`search`, but returns the total match count."""
    kwargs.pop("limit", None)
    kwargs.pop("offset", None)
    return len(search(limit=1_000_000, **kwargs))


def random_problem(
    difficulty: str = "", status: str = "", tag: str = "", include_paid: bool = False
) -> ProblemSummary | None:
    pool = search(
        difficulty=difficulty, status=status, tag=tag,
        include_paid=include_paid, limit=1_000_000,
    )
    if not pool:
        return None
    import random as _random

    return _random.choice(pool)


def all_tags() -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    with closing(connect()) as conn:
        for (blob,) in conn.execute("SELECT tags FROM problems"):
            for tag in json.loads(blob or "[]"):
                counts[tag] = counts.get(tag, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


# ----------------------------------------------------------------------- statements

def get_statement(slug: str, max_age: float = STATEMENT_TTL) -> Problem | None:
    with closing(connect()) as conn:
        row = conn.execute(
            "SELECT payload, fetched_at FROM statements WHERE slug = ?", (slug,)
        ).fetchone()
    if not row:
        return None
    if max_age and time.time() - (row["fetched_at"] or 0) > max_age:
        return None
    try:
        return Problem(**json.loads(row["payload"]))
    except (json.JSONDecodeError, TypeError):
        return None


def put_statement(problem: Problem) -> None:
    payload = json.dumps(problem.__dict__)
    with closing(connect()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO statements (slug, payload, fetched_at) "
            "VALUES (?, ?, ?)",
            (problem.slug, payload, time.time()),
        )


def clear() -> None:
    with closing(connect()) as conn, conn:
        conn.execute("DELETE FROM problems")
        conn.execute("DELETE FROM statements")
        conn.execute("DELETE FROM meta")
