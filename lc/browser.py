"""The user's real web browser: opening pages in it, and reading the cookie
stores browser_cookie3 does not know about.

Both jobs are trivial on macOS and desktop Linux and broken inside WSL, where
the browser lives on the Windows side of the fence: ``webbrowser.open`` finds
no Linux browser and silently does nothing, and the cookie stores sit under
/mnt/c in Windows layouts. URLs are routed through ``explorer.exe`` (always on
a stock WSL PATH) or wslu's ``wslview``; of the Windows cookie stores only
Firefox's is usable — plain SQLite — while Chrome and Edge seal theirs with
DPAPI/app-bound keys that only the browser itself can open.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import tempfile
import webbrowser
from pathlib import Path

_PROC_VERSION = Path("/proc/version")


def is_wsl() -> bool:
    """Running inside Windows Subsystem for Linux?"""
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in _PROC_VERSION.read_text().lower()
    except OSError:
        return False


def open_url(url: str) -> bool:
    """Open *url* in the user's browser; False when nothing could take it."""
    if is_wsl() and not os.environ.get("BROWSER"):
        for exe in ("wslview", "explorer.exe"):
            opener = shutil.which(exe)
            if opener is None:
                continue
            try:
                # explorer.exe exits 1 even when it opens the page, so
                # launching at all is the only success signal there is.
                subprocess.run([opener, url], capture_output=True, timeout=15)
                return True
            except (OSError, subprocess.SubprocessError):
                continue
    return webbrowser.open(url)


def windows_firefox_cookies(domain: str = "leetcode.com") -> list[dict[str, str]] | None:
    """One name→value jar per Windows Firefox profile with cookies for *domain*.

    None means no profile database was found at all — the same "no cookie
    store readable" contract as cli._read_browser_cookies.
    """
    databases = [
        db
        for root in _windows_profile_roots()
        for db in sorted(root.glob("AppData/Roaming/Mozilla/Firefox/Profiles/*/cookies.sqlite"))
    ]
    jars: list[dict[str, str]] = []
    readable = False
    for db in databases:
        try:
            jar = _domain_cookies(db, domain)
        except (OSError, sqlite3.Error):
            continue
        readable = True
        if jar:
            jars.append(jar)
    return jars if readable else None


def _domain_cookies(db: Path, domain: str) -> dict[str, str]:
    """Read one profile's cookies for *domain* from a snapshot of *db*.

    Firefox keeps the database open and the newest writes sit in the WAL
    sidecar, so copy database and sidecars and let sqlite replay the log
    on the copy.
    """
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / db.name
        shutil.copy(db, snapshot)
        for suffix in (".sqlite-wal", ".sqlite-shm"):
            sidecar = db.with_suffix(suffix)
            if sidecar.exists():
                shutil.copy(sidecar, snapshot.with_suffix(suffix))
        conn = sqlite3.connect(snapshot)
        try:
            rows = conn.execute(
                "SELECT name, value FROM moz_cookies WHERE host IN (?, ?)",
                (domain, "." + domain),
            ).fetchall()
        finally:
            conn.close()
    return dict(rows)


def _windows_profile_roots() -> list[Path]:
    """Windows user-profile directories visible from WSL, best guess first.

    %USERPROFILE% (resolved by cmd.exe, translated by wslpath) is
    authoritative; scanning the conventional /mnt/c/Users covers interop
    being disabled.
    """
    roots: list[Path] = []
    profile = _windows_userprofile()
    if profile is not None and profile.is_dir():
        roots.append(profile)
    users = Path("/mnt/c/Users")
    if users.is_dir():
        try:
            roots += [p for p in sorted(users.iterdir()) if p.is_dir() and p not in roots]
        except OSError:
            pass
    return roots


def _windows_userprofile() -> Path | None:
    cmd, wslpath = shutil.which("cmd.exe"), shutil.which("wslpath")
    if cmd is None or wslpath is None:
        return None
    try:
        # cwd must be Windows-visible or cmd.exe warns about UNC paths.
        windows = subprocess.run(
            [cmd, "/c", "echo %USERPROFILE%"],
            capture_output=True, text=True, timeout=10,
            cwd="/mnt/c" if Path("/mnt/c").is_dir() else None,
        ).stdout.strip()
        if not windows or windows.startswith("%"):
            return None
        linux = subprocess.run(
            [wslpath, "-u", windows], capture_output=True, text=True, timeout=10
        ).stdout.strip()
        return Path(linux) if linux else None
    except (OSError, subprocess.SubprocessError):
        return None
