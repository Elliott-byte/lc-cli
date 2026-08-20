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
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import review, store
from .config import (
    DEFAULT_AUTHOR_EMAIL,
    DEFAULT_AUTHOR_NAME,
    Config,
    home,
    load_config,
)

#: Where the deck lives inside the repo. Deliberately not README.md — pointing
#: lc at a repo that already has one must never overwrite it.
DECK_FILE = "review.json"
TABLE_FILE = "REVIEW.md"

TIMEOUT = 120


class SyncError(Exception):
    """Anything that stopped a sync, phrased for a terminal.

    ``hint`` is the next thing to try, when lc recognises the failure.
    """

    def __init__(self, message: str, hint: str = "", retryable: bool = False) -> None:
        super().__init__(message)
        self.hint = hint
        #: True when simply doing the whole sync again is the right response.
        self.retryable = retryable


#: Lines git prints that say nothing on their own. The last two are the tail of
#: "Please make sure you have the correct access rights / and the repository
#: exists." — reporting that fragment alone is what a naive "last line of
#: stderr" does, and it reads as gibberish.
_NOISE = (
    "cloning into",
    "please make sure you have the correct access rights",
    "and the repository exists.",
)

#: (needle in git's output) -> (what to say, what to try next, retry?)
_KNOWN = (
    ("permission denied (publickey)",
     "GitHub rejected this machine's SSH key",
     "use the https:// URL for the repo instead, or add a key with "
     "`gh ssh-key add ~/.ssh/id_ed25519.pub`", False),
    ("could not read username",
     "git has no credentials for this repository",
     "run `gh auth setup-git` so git can use your GitHub login", False),
    ("authentication failed",
     "GitHub rejected those credentials",
     "run `gh auth setup-git`, or check the repo URL", False),
    ("repository not found",
     "GitHub says that repository does not exist",
     "check the URL, and that your account can see it", False),
    ("host key verification failed",
     "the SSH host key was not accepted",
     "connect once with `ssh -T git@github.com` to record it", False),
    # The other machine landed a push inside our fetch-to-push window.
    ("failed to push some refs",
     "the other machine pushed while this sync was running",
     "run the sync again — lc will merge both sides", True),
)


def _explain(command: str, output: str) -> SyncError:
    """Turn git's multi-line complaint into one useful sentence, plus a hint."""
    lines = [ln.strip() for ln in output.strip().splitlines() if ln.strip()]
    lines = [ln for ln in lines
             if not any(ln.lower().startswith(n) or ln.lower() == n for n in _NOISE)]

    lowered = " ".join(lines).lower()
    for needle, reason, hint, retryable in _KNOWN:
        if needle in lowered:
            return SyncError(f"git {command}: {reason}", hint, retryable)

    # Nothing recognised: prefer the line git meant as the diagnosis over the
    # last one it happened to print.
    for prefix in ("remote:", "fatal:", "error:"):
        for line in lines:
            if line.lower().startswith(prefix):
                return SyncError(f"git {command}: {line}")
    return SyncError(f"git {command}: {lines[0] if lines else 'failed'}")


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
        raise _explain(_command_name(args), proc.stderr or proc.stdout)
    return proc.stdout.strip()


def _command_name(args: tuple[str, ...]) -> str:
    """The subcommand, for the error message — not `-c` from `git -c k=v commit`."""
    rest = iter(args)
    for arg in rest:
        if arg == "-c":
            next(rest, None)  # skip its value
        elif not arg.startswith("-"):
            return arg
    return "git"


def _remote_url(path: Path) -> str:
    try:
        return _git("remote", "get-url", "origin", cwd=path)
    except SyncError:
        return ""


def ensure_clone(url: str) -> Path:
    """A clone of *url* ready to read, cloning or re-cloning it as needed."""
    path = repo_dir()
    if (path / ".git").is_dir():
        if _remote_url(path) == url:
            return path
        # The configured repo changed, so start over. Re-pointing origin is
        # not enough: a fetch does not prune, so origin/<branch> would still
        # name the *old* repo's commit. The sync then resets onto it, finds
        # the deck already identical, commits nothing and reports success —
        # leaving the newly configured repo empty. Worse, when the old ref is
        # gone the first push carries the old repo's whole history across.
        # The clone is disposable; the deck of record is ~/.lc/review.json.
        shutil.rmtree(path, ignore_errors=True)
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
    """The deck as Markdown, so the repo page is readable on GitHub.

    A pure function of the deck: absolute dates only, nothing derived from
    "today". Anything relative — days overdue, how many are due now — would
    change on its own overnight and commit a diff every morning for a deck
    that never moved. The live view belongs in `lc review` and the TUI, where
    it is recomputed anyway.
    """
    lines = [
        "# Review deck",
        "",
        f"{len(review.live(items))} problem(s), soonest review first.",
        "",
        "| # | Problem | Difficulty | Level | Next review |",
        "| ---: | --- | --- | ---: | --- |",
    ]
    for item in review.order(items):
        title = item.title or item.slug
        link = f"[{title}](https://leetcode.com/problems/{item.slug}/)"
        lines.append(
            f"| {item.frontend_id} | {link} | {item.difficulty or '—'} "
            f"| {item.level} | {item.due or '—'} |"
        )
    lines.append("")
    lines.append("<sub>Written by [lc](https://github.com/Elliott-byte/lc-cli) "
                 "— `lc review sync`.</sub>")
    return "\n".join(lines) + "\n"


def _git_identity(path: Path) -> tuple[str, str]:
    """The name and email git already commits as here, empty where unset."""
    # Before the first sync there is no clone to ask from, and a missing cwd
    # would look like "git is missing" rather than "no identity set".
    cwd = path if path.is_dir() else None

    def ask(key: str) -> str:
        try:
            return _git("config", "--get", key, cwd=cwd)
        except SyncError:
            return ""     # unset is not a failure, it just means "nothing here"

    return ask("user.name"), ask("user.email")


def author(path: Path | None = None) -> tuple[str, str, str]:
    """Who to commit the deck as, and where that came from.

    The deck repo is yours and nobody else's, so the commits should read like
    the rest of your work without being configured a second time on every
    machine: your own git identity is the answer unless you say otherwise.
    lc's own name is the last resort, for a machine where git has no identity
    at all — there, `git commit` would fail outright without it.
    """
    cfg = load_config()
    name, email = cfg.review_author_name.strip(), cfg.review_author_email.strip()
    if name and email:
        return name, email, "configured"
    git_name, git_email = _git_identity(path or repo_dir())
    if not name and not email and git_name and git_email:
        return git_name, git_email, "from git"
    return (name or git_name or DEFAULT_AUTHOR_NAME,
            email or git_email or DEFAULT_AUTHOR_EMAIL,
            "configured" if name or email else "lc's own")


def _commit_and_push(path: Path, message: str) -> bool:
    """Commit the deck files and push. False when there was nothing to commit."""
    _git("add", "--", DECK_FILE, TABLE_FILE, cwd=path)
    if not _git("status", "--porcelain", "--", DECK_FILE, TABLE_FILE, cwd=path):
        return False
    # -c rather than writing the clone's config: lc states who it commits as
    # on every call and never edits a git config of yours.
    name, email, _ = author(path)
    _git("-c", f"user.name={name}", "-c", f"user.email={email}",
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


def pull(url: str) -> tuple[int, int, int]:
    """Merge the repo's deck into this machine's. Returns (added, updated,
    removed) — what the pull did to the deck as the user sees it."""
    try:
        _, remote = fetch_remote_deck(url)
        local = review.load()
        merged, added, updated, removed = review.merge(local, remote)
        # Written whenever the merge changed anything — not when the counters
        # are non-zero. A tombstone for a problem this machine never had is
        # counted as neither added nor updated, so guarding on them dropped it
        # and left `status` reporting a change to push that pushing never
        # cleared.
        if merged != local:
            review.save(merged)
    except SyncError as exc:
        record_sync(error=str(exc))
        raise
    record_sync()
    return added, updated, removed


def push(url: str) -> tuple[int, bool]:
    """Publish the local deck. Returns (problems pushed, whether it changed).

    The remote is merged in first, so a deck another machine pushed while you
    were away survives instead of being overwritten. If the other machine
    lands a push inside that window the whole thing is simply redone — with
    two machines syncing often, that race is rare but real, and it is not
    worth showing the user.
    """
    try:
        for attempt in (1, 2):
            try:
                count, changed = _push_once(url)
                break
            except SyncError as exc:
                if attempt == 2 or not exc.retryable:
                    raise
    except SyncError as exc:
        record_sync(error=str(exc))
        raise
    record_sync()
    return count, changed


def _push_once(url: str) -> tuple[int, bool]:
    path, remote = fetch_remote_deck(url)
    local = review.load()
    merged, added, updated, removed = review.merge(local, remote)
    if merged != local:      # see pull(): the counters do not cover tombstones
        review.save(merged)
    write_deck(path, merged)
    count = len(review.live(merged))
    return count, _commit_and_push(path, f"review: {count} problem(s)")


def sync(url: str) -> tuple[int, int, int, bool]:
    """Pull then push. Returns (added, updated, removed, remote changed)."""
    added, updated, removed = pull(url)
    _, changed = push(url)
    return added, updated, removed, changed
