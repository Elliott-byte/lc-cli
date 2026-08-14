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


def play(console: Console, big: bool) -> None:
    """Celebrate in the terminal; silent when piped or LC_NO_FX is set."""
    if os.environ.get("LC_NO_FX") or not console.is_terminal:
        return
    if big:
        width, height, bursts, frames = min(console.width - 2, 64), 13, 3, 34
    else:
        width, height, bursts, frames = min(console.width - 2, 36), 8, 1, 16
    with Live(console=console, transient=True, auto_refresh=False) as live:
        for frame in firework_frames(width, height, bursts, frames):
            live.update(frame, refresh=True)
            time.sleep(0.045)
