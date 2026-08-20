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

#: Who review-deck commits are authored by when the user has not said. Not the
#: user's global git identity: a machine with none still has to be able to sync.
DEFAULT_AUTHOR_NAME = "lc"
DEFAULT_AUTHOR_EMAIL = "lc@localhost"


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
    #: Who `lc review sync` commits as. Blank means lc's own identity; set them
    #: to an address your host knows you by and it attributes the deck to you.
    review_author_name: str = ""
    review_author_email: str = ""
    #: Let a submit verdict grade the problem by itself — accepted a level up,
    #: a failure a level down. Off by default: grading is a judgement about
    #: recall, and the judge only knows whether the code passed.
    review_autograde: bool = False
    #: Keys in config.json this version does not know about — kept so settings
    #: written by a newer lc survive a round-trip through this one.
    extra: dict = field(default_factory=dict, repr=False)

    @property
    def workspace_path(self) -> Path:
        # Path("") is Path(".") — a blank setting would quietly scatter solution
        # files through whatever directory lc was launched from.
        return Path(self.workspace or DEFAULT_WORKSPACE).expanduser()

    @property
    def review_author(self) -> tuple[str, str]:
        """(name, email) for deck commits, falling back to lc's own identity."""
        return (self.review_author_name.strip() or DEFAULT_AUTHOR_NAME,
                self.review_author_email.strip() or DEFAULT_AUTHOR_EMAIL)

    @property
    def autograde(self) -> bool:
        """Whether a submit verdict moves the level on its own.

        `is True`, not bool(): config.json is hand-editable, and a stray
        "false" is a truthy *string* — rescheduling a deck off the back of one
        is the worse mistake.
        """
        return self.review_autograde is True

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
