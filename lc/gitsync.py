"""Keep the review deck in a git repo, so it follows you between machines.

``lc config repo <url>`` points lc at a repository you own; lc keeps a private
clone of it in ``$LC_HOME/review-repo`` and writes two files there:

    review.json   the deck itself — the file lc reads back
    REVIEW.md     the same deck as a table, so GitHub renders it

The clone is disposable: the deck of record is ``$LC_HOME/review.json``, and
every sync resets the clone to the remote before merging in Python. That way
a divergence is a merge lc controls, never a conflict git asks about.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import review, store
from .config import Config, home

#: Where the deck lives inside the repo. Deliberately not README.md — pointing
#: lc at a repo that already has one must never overwrite it.
DECK_FILE = "review.json"
TABLE_FILE = "REVIEW.md"

TIMEOUT = 120


class SyncError(Exception):
    """Anything that stopped a sync, phrased for a terminal."""


def repo_dir() -> Path:
    return home() / "review-repo"


def _git(*args: str, cwd: Path | None = None) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
    except FileNotFoundError:
        raise SyncError("git is not installed") from None
    except subprocess.TimeoutExpired:
        raise SyncError(
            f"git {args[0]} timed out after {TIMEOUT}s — is the remote asking "
            "for a password?"
        ) from None
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        raise SyncError(f"git {args[0]}: {detail[-1] if detail else 'failed'}")
    return proc.stdout.strip()


def _remote_url(path: Path) -> str:
    try:
        return _git("remote", "get-url", "origin", cwd=path)
    except SyncError:
        return ""


def ensure_clone(url: str) -> Path:
    """A clone of *url* ready to read, cloning or re-pointing it as needed."""
    path = repo_dir()
    if (path / ".git").is_dir():
        if _remote_url(path) != url:
            # The configured repo changed — start over rather than push a deck
            # into whichever repository happened to be cloned first.
            _git("remote", "set-url", "origin", url, cwd=path)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise SyncError(f"{path} exists but is not a git clone — remove it")
    _git("clone", "--quiet", url, str(path))
    return path


def _branch(path: Path) -> str:
    # symbolic-ref, not rev-parse: a clone of an empty repo has an unborn HEAD
    # with no commit to resolve, and that is exactly the first-sync case.
    return _git("symbolic-ref", "--short", "HEAD", cwd=path)


def fetch_remote_deck(url: str) -> tuple[Path, dict[str, review.ReviewItem]]:
    """Reset the clone to the remote and read the deck it holds."""
    path = ensure_clone(url)
    branch = _branch(path)
    _git("fetch", "--quiet", "origin", cwd=path)
    remote_refs = _git("branch", "--remotes", "--list", f"origin/{branch}", cwd=path)
    if remote_refs:
        # The clone is ours to overwrite; the deck of record is ~/.lc/review.json.
        _git("reset", "--hard", "--quiet", f"origin/{branch}", cwd=path)
    return path, read_deck(path)


def read_deck(path: Path) -> dict[str, review.ReviewItem]:
    deck_path = path / DECK_FILE
    if not deck_path.exists():
        return {}
    try:
        raw = json.loads(deck_path.read_text())
    except (json.JSONDecodeError, OSError):
        raise SyncError(f"{DECK_FILE} in the repo is not readable JSON") from None
    return review.items_from_raw(raw)


def write_deck(path: Path, items: dict[str, review.ReviewItem]) -> None:
    (path / DECK_FILE).write_text(review.dumps(items))
    (path / TABLE_FILE).write_text(render_table(items))


def render_table(items: dict[str, review.ReviewItem]) -> str:
    """The deck as Markdown, so the repo page is readable on GitHub."""
    today = date.today()
    lines = [
        "# Review deck",
        "",
        f"{len(items)} problem(s) · {review.due_count(items, today)} due · "
        f"synced {today.isoformat()}",
        "",
        "| # | Problem | Difficulty | Level | Next review |",
        "| ---: | --- | --- | ---: | --- |",
    ]
    for item in review.order(items):
        days = item.due_in(today)
        when = "**today**" if days == 0 else (
            f"**{-days}d overdue**" if days < 0 else f"{item.due} ({days}d)"
        )
        title = item.title or item.slug
        link = f"[{title}](https://leetcode.com/problems/{item.slug}/)"
        lines.append(
            f"| {item.frontend_id} | {link} | {item.difficulty or '—'} "
            f"| {item.level} | {when} |"
        )
    lines.append("")
    lines.append("<sub>Written by [lc](https://github.com/Elliott-byte/lc-cli) "
                 "— `lc review sync`.</sub>")
    return "\n".join(lines) + "\n"


def _commit_and_push(path: Path, message: str) -> bool:
    """Commit the deck files and push. False when there was nothing to commit."""
    _git("add", "--", DECK_FILE, TABLE_FILE, cwd=path)
    if not _git("status", "--porcelain", "--", DECK_FILE, TABLE_FILE, cwd=path):
        return False
    # -c so lc never depends on (or edits) the user's global git identity.
    _git("-c", "user.name=lc", "-c", "user.email=lc@localhost",
         "commit", "--quiet", "-m", message, cwd=path)
    _git("push", "--quiet", "origin", f"HEAD:{_branch(path)}", cwd=path)
    return True


# ------------------------------------------------------------------- status

#: Where the last outcome is remembered. Cache, not user data: losing it to a
#: deleted cache.db costs one "unknown" until the next sync.
_AT_KEY = "review_synced_at"
_ERR_KEY = "review_sync_error"


@dataclass
class SyncStatus:
    """What to show about syncing, worked out from local files only.

    Deliberately network-free: this is recomputed on every deck refresh, and
    a UI that reached for the network to redraw a status line would stall.
    ``pending`` therefore means "differs from the clone as it was last
    fetched", not "differs from GitHub right now".
    """

    state: str          # off | never | clean | pending | failed
    pending: int = 0
    synced_at: float | None = None
    error: str = ""

    @property
    def icon(self) -> str:
        return {"off": "", "never": "○", "clean": "✔",
                "pending": "↑", "failed": "✗"}[self.state]


def record_sync(error: str = "") -> None:
    """Remember how the last sync went, for the status line."""
    if error:
        store.set_meta(_ERR_KEY, error)
        return
    store.set_meta(_AT_KEY, str(time.time()))
    store.set_meta(_ERR_KEY, "")


def last_sync() -> float | None:
    raw = store.get_meta(_AT_KEY)
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def status(config: Config) -> SyncStatus:
    """The current sync state. Reads local files only — never the network."""
    if not config.review_repo.strip():
        return SyncStatus("off")

    at, error = last_sync(), store.get_meta(_ERR_KEY) or ""
    path = repo_dir()
    if not (path / ".git").is_dir():
        # Configured but never cloned, or the clone was thrown away.
        return SyncStatus("failed", synced_at=at, error=error) if error else \
            SyncStatus("never", synced_at=at)

    try:
        cloned = read_deck(path)
    except SyncError as exc:
        return SyncStatus("failed", synced_at=at, error=str(exc))

    local = review.load()
    pending = sum(1 for slug, item in local.items() if cloned.get(slug) != item)
    pending += sum(1 for slug in cloned if slug not in local)
    if error:
        return SyncStatus("failed", pending=pending, synced_at=at, error=error)
    if pending:
        return SyncStatus("pending", pending=pending, synced_at=at)
    return SyncStatus("clean", synced_at=at)


def ago(when: float | None, now: float | None = None) -> str:
    """'just now' / '4m ago' / '3h ago' / '2d ago' — never a raw timestamp."""
    if when is None:
        return "never"
    seconds = max(0.0, (time.time() if now is None else now) - when)
    if seconds < 90:
        return "just now"
    for size, unit in ((3600.0, "m"), (86400.0, "h"), (float("inf"), "d")):
        if seconds < size:
            step = {"m": 60.0, "h": 3600.0, "d": 86400.0}[unit]
            return f"{int(seconds // step)}{unit} ago"
    return "a while ago"


def summary(config: Config) -> str:
    """One line for the Review pane and `lc review`."""
    state = status(config)
    if state.state == "off":
        return ""
    when = ago(state.synced_at)
    if state.state == "never":
        return f"{state.icon} not synced yet — press g"
    if state.state == "failed":
        detail = f": {state.error}" if state.error else ""
        return f"{state.icon} last sync failed{detail}"
    if state.state == "pending":
        plural = "" if state.pending == 1 else "s"
        return f"{state.icon} {state.pending} change{plural} to push · synced {when}"
    return f"{state.icon} synced {when}"


def pull(url: str) -> tuple[int, int]:
    """Merge the repo's deck into the local one. Returns (added, updated)."""
    try:
        _, remote = fetch_remote_deck(url)
        local = review.load()
        merged, added, updated = review.merge(local, remote)
        if added or updated:
            review.save(merged)
    except SyncError as exc:
        record_sync(error=str(exc))
        raise
    record_sync()
    return added, updated


def push(url: str) -> tuple[int, bool]:
    """Publish the local deck. Returns (problems pushed, whether it changed).

    The remote is merged in first, so a deck another machine pushed while you
    were away survives instead of being overwritten.
    """
    try:
        path, remote = fetch_remote_deck(url)
        local = review.load()
        merged, added, updated = review.merge(local, remote)
        if added or updated:
            review.save(merged)
        write_deck(path, merged)
        changed = _commit_and_push(path, f"review: {len(merged)} problem(s)")
    except SyncError as exc:
        record_sync(error=str(exc))
        raise
    record_sync()
    return len(merged), changed


def sync(url: str) -> tuple[int, int, bool]:
    """Pull then push. Returns (added, updated, whether the remote changed)."""
    added, updated = pull(url)
    _, changed = push(url)
    return added, updated, changed
