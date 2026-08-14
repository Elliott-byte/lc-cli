"""Terminal fireworks for accepted verdicts.

Frames are plain Rich ``Text`` grids so the same animation plays in the CLI
(via ``Live``) and in the TUI (a widget updated on a timer). Bursts rise from
the bottom, explode into two shells of sparks that age from ✦ to ·, and droop
under a little gravity; x is stretched ×2 because terminal cells are tall.
"""

from __future__ import annotations

import math
import os
import random
import time

from rich.console import Console
from rich.live import Live
from rich.text import Text

_COLORS = (
    "bright_yellow", "bright_magenta", "bright_cyan", "bright_green",
    "bright_red", "gold1", "orchid1", "turquoise2",
)
_SPARKS = "✦*+·"  # young → old
_RISE = 3         # frames a rocket spends climbing
_LIFE = 8         # frames a burst keeps sparkling


def firework_frames(
    width: int, height: int, bursts: int, frames: int,
    rng: random.Random | None = None,
) -> list[Text]:
    rng = rng or random.Random()
    plans = []
    for i in range(bursts):
        plans.append((
            _RISE + i * max(3, (frames - _RISE - _LIFE) // max(bursts, 1)),
            width // 2 if bursts == 1 else rng.randint(width // 6, width - 1 - width // 6),
            rng.randint(2, max(2, height // 2)),
            rng.choice(_COLORS),
            rng.randint(10, 14),
            rng.uniform(0.8, 1.3),
            rng.uniform(0, math.pi),
        ))

    out: list[Text] = []
    for f in range(frames):
        grid: list[list[tuple[str, str] | None]] = [
            [None] * width for _ in range(height)
        ]
        for f0, cx, cy, color, rays, speed, jitter in plans:
            t = f - f0
            if t < 0:
                climbed = t + _RISE + 1  # 1.._RISE on the frames before f0
                if climbed >= 1:
                    y = (height - 1) - int((height - 1 - cy) * climbed / _RISE)
                    if 0 <= y < height:
                        grid[y][cx] = ("·", color)
                continue
            if t > _LIFE:
                continue
            radius = speed * (1.2 * t + 0.8)
            for k in range(rays):
                angle = 2 * math.pi * k / rays + jitter
                for shell, scale in ((0, 1.0), (1, 0.55)):
                    x = cx + radius * scale * math.cos(angle) * 2.0
                    y = cy + radius * scale * math.sin(angle) + 0.06 * t * t
                    xi, yi = round(x), round(y)
                    if 0 <= xi < width and 0 <= yi < height:
                        spark = _SPARKS[min(len(_SPARKS) - 1, (t + shell) // 2)]
                        grid[yi][xi] = (spark, color)

        if frames - f <= 6:
            # A shimmer of dust while the last sparks die out.
            for _ in range(width * height // 40):
                x, y = rng.randrange(width), rng.randrange(height)
                if grid[y][x] is None and rng.random() < 0.5:
                    grid[y][x] = ("·", rng.choice(_COLORS))

        text = Text()
        for row in grid:
            for cell in row:
                if cell is None:
                    text.append(" ")
                else:
                    text.append(cell[0], style=f"bold {cell[1]}")
            text.append("\n")
        out.append(text)
    return out


#: Hand-keyed collapse, every frame facing the way orz faces: head to the
#: left, propping arm to its right, folded legs rightmost.
#: stand → legs fold under → arms drop → bow left → hands down → orz.
_DEFEAT_SMALL = (
    ("     o     ", "    /|\\    ", "     |     ", "    / \\    "),
    ("     o     ", "    /|\\    ", "     |     ", "    |\\     "),
    ("     o     ", "    /|\\    ", "     |     ", "    ||     "),
    ("     o     ", "     |     ", "     |     ", "    ||     "),
    ("    o      ", "     \\     ", "     \\     ", "    ||     "),
    ("           ", "   o_      ", "     \\     ", "    ||     "),
    ("           ", "           ", "           ", "   orz     "),
)

_DEFEAT_BIG = (
    ("      O      ", "     /|\\     ", "      |      ", "      |      ", "     / \\     "),
    ("      O      ", "     /|\\     ", "      |      ", "      |      ", "     |\\      "),
    ("      O      ", "     /|\\     ", "      |      ", "      |      ", "     ||      "),
    ("      O      ", "      |      ", "      |      ", "      |      ", "     ||      "),
    ("     O       ", "      \\      ", "      \\      ", "      \\      ", "     ||      "),
    ("             ", "    O        ", "     \\_      ", "      \\      ", "     ||      "),
    ("             ", "             ", "    O_       ", "      \\      ", "     ||      "),
    ("             ", "             ", "             ", "             ", "   O r z     "),
)

_RAIN_COLS = ((2, 6, 10), (4, 8, 12), (3, 7, 11))


def defeat_frames(big: bool = False) -> list[Text]:
    """The collapse, then the pose held while despair accumulates.

    The big version kneels under a rain cloud that rolls in for the hold.
    """
    art = _DEFEAT_BIG if big else _DEFEAT_SMALL
    frames = [_defeat_text(art[i], big, rain=-1, dots=0) for i in range(len(art))]
    holds = (0, 0, 1, 2, 3) if big else (1, 2, 3)
    for i, dots in enumerate(holds):
        frames.append(_defeat_text(art[-1], big, rain=i if big else -1, dots=dots))
    return frames


def _defeat_text(art: tuple[str, ...], big: bool, rain: int, dots: int) -> Text:
    width = len(art[0])
    text = Text()
    if big:
        cloud = " ~ ~ ~ ~ ~ ~ " if rain >= 0 else " " * width
        text.append(cloud[:width] + "\n", style="dim")
    for n, row in enumerate(art):
        if rain >= 1:
            drops = _RAIN_COLS[(rain + n) % len(_RAIN_COLS)]
            row = "".join(
                "'" if i in drops and c == " " else c for i, c in enumerate(row)
            )
        style = "bold red" if "r z" in row or "orz" in row else "dim"
        text.append(row + "\n", style=style)
    text.append("─" * width, style="dim")
    if dots:
        text.append(" " + "." * dots, style="dim red")
    text.append("\n")
    return text


def _quiet(console: Console) -> bool:
    return bool(os.environ.get("LC_NO_FX")) or not console.is_terminal


def _animate(console: Console, frames: list[Text], interval: float) -> None:
    with Live(console=console, transient=True, auto_refresh=False) as live:
        for frame in frames:
            live.update(frame, refresh=True)
            time.sleep(interval)


def play(console: Console, big: bool) -> None:
    """Celebrate in the terminal; silent when piped or LC_NO_FX is set."""
    if _quiet(console):
        return
    if big:
        width, height, bursts, frames = min(console.width - 2, 74), 15, 4, 40
    else:
        width, height, bursts, frames = min(console.width - 2, 46), 10, 2, 20
    _animate(console, firework_frames(width, height, bursts, frames), 0.045)


def defeat(console: Console, big: bool = False) -> None:
    """Take the loss with a little dignity; same quiet rules as play()."""
    if _quiet(console):
        return
    _animate(console, defeat_frames(big), 0.09)
