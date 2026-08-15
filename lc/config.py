"""Config, credential storage and on-disk layout.

Everything lc owns lives under ``$LC_HOME`` (default ``~/.lc``)::

    config.json     user settings
    cookies.json    LeetCode session cookies, chmod 600
    cache.db        sqlite cache of the problem set + statements

Solution files live in a separate, user-visible workspace (default ``~/leetcode``)
so they are easy to keep under version control.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_HOME = Path.home() / ".lc"
DEFAULT_WORKSPACE = Path.home() / "leetcode"


def home() -> Path:
    path = Path(os.environ.get("LC_HOME", DEFAULT_HOME)).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return home() / "config.json"


def cookies_path() -> Path:
    return home() / "cookies.json"


def cache_path() -> Path:
    return home() / "cache.db"


@dataclass
class Config:
    """User settings. Unknown keys in config.json are preserved on save."""

    workspace: str = str(DEFAULT_WORKSPACE)
    lang: str = "python3"
    editor: str = ""
    #: Extra languages to offer in the `pick --lang` prompt, beyond the favourites.
    favorite_langs: list[str] = field(
        default_factory=lambda: ["python3", "javascript", "golang", "cpp", "java"]
    )
    #: Review-deck spacing: days until the next review, one entry per level.
    #: Empty means lc's default Ebbinghaus curve — see `lc config curve`.
    review_curve: list[int] = field(default_factory=list)
    #: Git remote the review deck syncs with, e.g. git@github.com:you/lc-review.git
    review_repo: str = ""
    #: Keys in config.json this version does not know about — kept so settings
    #: written by a newer lc survive a round-trip through this one.
    extra: dict = field(default_factory=dict, repr=False)

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace).expanduser()

    def resolve_editor(self) -> str | None:
        for candidate in (self.editor, os.environ.get("LC_EDITOR"), os.environ.get("VISUAL"),
                          os.environ.get("EDITOR")):
            if candidate:
                return candidate
        return None


def load_config() -> Config:
    path = config_path()
    if not path.exists():
        return Config()
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return Config()
    known = set(Config.__dataclass_fields__) - {"extra"}
    config = Config(**{k: v for k, v in raw.items() if k in known})
    config.extra = {k: v for k, v in raw.items() if k not in known}
    return config


def save_config(config: Config) -> None:
    data = asdict(config)
    extra = data.pop("extra")
    config_path().write_text(json.dumps({**extra, **data}, indent=2) + "\n")


# --------------------------------------------------------------------------- creds

@dataclass
class Credentials:
    session: str
    csrf: str
    username: str = ""

    def as_cookies(self) -> dict[str, str]:
        return {"LEETCODE_SESSION": self.session, "csrftoken": self.csrf}


def load_credentials() -> Credentials | None:
    """Read stored cookies, falling back to env vars for CI / scripted use."""
    env_session = os.environ.get("LEETCODE_SESSION")
    env_csrf = os.environ.get("LEETCODE_CSRF")
    if env_session and env_csrf:
        return Credentials(session=env_session, csrf=env_csrf)

    path = cookies_path()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if not raw.get("session") or not raw.get("csrf"):
        return None
    return Credentials(
        session=raw["session"], csrf=raw["csrf"], username=raw.get("username", "")
    )


def save_credentials(creds: Credentials) -> None:
    path = cookies_path()
    # Session cookies are bearer credentials — the file must be owner-only from
    # the moment it exists, not chmodded after the fact.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(asdict(creds), indent=2) + "\n")
    # An older, more permissive file keeps its mode through O_CREAT — fix it.
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def clear_credentials() -> None:
    cookies_path().unlink(missing_ok=True)
