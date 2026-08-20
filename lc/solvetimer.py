"""The solve clock's state, shared between the TUI, the CLI and Vim.

``$LC_HOME/timer.json`` holds the one active clock: which problem, seconds
banked while paused, when the running stretch began (epoch, null while
paused or stopped), and whether an accepted submit already ended it. A file
rather than app memory because the solve itself happens outside the TUI —
in Vim, whose statusline reads this to draw the clock, and whose ``\\s``
submits through the CLI, which stops it.

Wall-clock time, not monotonic: three processes read these stamps.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass

from .config import home


def timer_path():
    return home() / "timer.json"


@dataclass
class Timer:
    slug: str
    accum: float = 0.0
    started: float | None = None
    done: bool = False

    @property
    def running(self) -> bool:
        return self.started is not None

    def elapsed(self, now: float | None = None) -> float:
        run = (now or time.time()) - self.started if self.running else 0.0
        return self.accum + max(0.0, run)


def load() -> Timer | None:
    try:
        raw = json.loads(timer_path().read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("slug"), str):
        return None
    try:
        accum = max(0.0, float(raw.get("accum", 0.0)))
    except (TypeError, ValueError):
        accum = 0.0
    started = raw.get("started")
    try:
        started = float(started) if started is not None else None
    except (TypeError, ValueError):
        started = None
    return Timer(slug=raw["slug"], accum=accum, started=started,
                 done=raw.get("done") is True)


def save(timer: Timer) -> None:
    path = timer_path()
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(asdict(timer)) + "\n")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def clear() -> None:
    timer_path().unlink(missing_ok=True)


def begin(slug: str) -> Timer:
    """Opening a problem starts (or resumes) its clock.

    A different problem — or one already clocked out by a submit — starts
    from zero; reopening the one being solved just keeps counting.
    """
    timer = load()
    if timer is None or timer.slug != slug or timer.done:
        timer = Timer(slug=slug)
    if not timer.running:
        timer.started = time.time()
    save(timer)
    return timer


def pause() -> Timer | None:
    timer = load()
    if timer is None or timer.done or not timer.running:
        return timer
    timer.accum = timer.elapsed()
    timer.started = None
    save(timer)
    return timer


def resume() -> Timer | None:
    timer = load()
    if timer is None or timer.done or timer.running:
        return timer
    timer.started = time.time()
    save(timer)
    return timer


def stop_if(slug: str) -> Timer | None:
    """An accepted submit of *slug* ends its clock; anything else is not ours
    to touch. Returns the stopped timer, or None when nothing matched."""
    timer = load()
    if timer is None or timer.slug != slug or timer.done:
        return None
    timer.accum = timer.elapsed()
    timer.started = None
    timer.done = True
    save(timer)
    return timer


def reset() -> Timer | None:
    """Restart the active clock from zero, running — same problem, fresh
    attempt. Works on a stopped clock too: that is "go again"."""
    timer = load()
    if timer is None:
        return None
    fresh = Timer(slug=timer.slug, started=time.time())
    save(fresh)
    return fresh


def clock(seconds: float) -> str:
    """mm:ss under an hour, h:mm:ss beyond — a solve clock, not a datetime."""
    total = int(seconds)
    h, rest = divmod(total, 3600)
    m, sec = divmod(rest, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
