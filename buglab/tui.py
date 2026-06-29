from __future__ import annotations

import math
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


BRAILLE_DOTS = ((0, 0, 0x01), (0, 1, 0x02), (0, 2, 0x04), (1, 0, 0x08), (1, 1, 0x10), (1, 2, 0x20), (0, 3, 0x40), (1, 3, 0x80))
TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".md", ".json", ".toml", ".yaml", ".yml", ".txt", ".csv"}
IGNORED_DIRS = {".git", ".buglab", ".venv", "node_modules", "__pycache__", "dist", "build", "coverage"}


@dataclass(frozen=True)
class TuiConfig:
    repo: str | Path = "."
    mode: str = "find"
    frames: int = 96
    delay: float = 0.055
    no_clear: bool = False
    overwatch_assets: str | Path | None = None
    no_overwatch_assets: bool = False


class DotMaxCanvas:
    """Small braille canvas: two columns by four rows per terminal glyph."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self._dots = set()

    def set(self, x: float, y: float) -> None:
        ix = int(round(x))
        iy = int(round(y))
        if 0 <= ix < self.width and 0 <= iy < self.height:
            self._dots.add((ix, iy))

    def line(self, x1: float, y1: float, x2: float, y2: float, *, samples: int = 24) -> None:
        for index in range(samples + 1):
            t = index / max(1, samples)
            self.set(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)

    def render(self) -> str:
        rows = []
        for cell_y in range(0, self.height, 4):
            chars = []
            for cell_x in range(0, self.width, 2):
                bits = 0
                for dx, dy, bit in BRAILLE_DOTS:
                    if (cell_x + dx, cell_y + dy) in self._dots:
                        bits |= bit
                chars.append(chr(0x2800 + bits))
            rows.append("".join(chars).rstrip())
        return "\n".join(rows)


def run_tui(config: TuiConfig | None = None, **kwargs: object) -> int:
    config = config or TuiConfig(**kwargs)
    repo = Path(config.repo).resolve()
    stats = count_repo(repo)
    overwatch = {} if config.no_overwatch_assets else load_overwatch_assets(config.overwatch_assets)
    frames = config.frames if config.frames > 0 else 10_000_000
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        for frame in range(frames):
            progress = (frame % 96) / 95
            tokens_done = round(stats["estimated_tokens"] * progress)
            tok_sec = round(tokens_done / max(0.35, progress * 5.2))
            if not config.no_clear:
                clear()
            print(render_frame(repo, config.mode, frame, stats, tokens_done, tok_sec, overwatch))
            time.sleep(max(0, config.delay))
            if config.no_clear:
                break
    except KeyboardInterrupt:
        return 130
    return 0


def render_frame(
    repo: Path,
    mode: str,
    frame: int,
    stats: dict[str, int],
    tokens_done: int,
    tok_sec: int,
    overwatch: dict[str, object] | None = None,
) -> str:
    fix_mode = mode in {"fix", "find_fix", "find-and-fix", "find_and_fix"}
    accent = ansi("95") if fix_mode else ansi("92")
    red = ansi("91")
    amber = ansi("93")
    reset = ansi("0")
    canvas = swarm_canvas(frame, fix_mode)
    policy = "PONYTAIL FIX: smallest verified patch, tests first" if fix_mode else "PONYTAIL FIND: smallest reproducible evidence, no proxy scoring"
    lines = [
            f"{accent}BUGLAB TUI{reset}  {repo.name}  mode={'find+fix' if fix_mode else 'find'}",
            f"{policy}",
    ]
    if overwatch:
        lines.extend(overwatch_header(overwatch, frame, accent, reset))
    lines.extend(
        [
            "",
            canvas.render(),
            "",
            *network_link_lines(frame, fix_mode, overwatch),
            "",
            f"agents {bar((frame % 24) / 23, 22, accent)} 7 active",
            f"loc    {bar(stats['loc'] / max(1, stats['loc']), 22, accent)} {stats['loc']:,}",
            f"tokens {bar(tokens_done / max(1, stats['estimated_tokens']), 22, accent)} {tokens_done:,}/{stats['estimated_tokens']:,}",
            f"speed  {speedometer(tok_sec, fix_mode)} {tok_sec:,} tok/sec",
            "",
            f"{red}red/yellow = candidate bugs{reset}  {accent}purple/green = {'fixed verified' if fix_mode else 'evidence found'}{reset}  {amber}truth = precision/recall/F1{reset}",
        ]
    )
    return "\n".join(lines)


def network_link_lines(frame: int, fix_mode: bool, overwatch: dict[str, object] | None = None) -> list[str]:
    theme_names = list((overwatch or {}).get("themes") or [])
    preferred = [name for name in theme_names if name in {"packets", "circuit", "matrix", "comet", "heartbeat", "hazard", "scanline"}]
    if not preferred:
        preferred = ["packets", "circuit", "matrix", "comet"]
    channels = [
        ("planner", "runner", 0.86),
        ("runner", "visual", 0.64),
        ("visual", "verifier", 0.78),
        ("verifier", "report", 0.52),
    ]
    color = ansi("95") if fix_mode else ansi("92")
    dim = ansi("90")
    reset = ansi("0")
    rows = ["network"]
    for index, (source, target, load) in enumerate(channels):
        theme = preferred[(frame + index) % len(preferred)]
        phase = frame * 0.11 + index * 0.27
        rows.append(
            f"  {source:<8} {color}{loading_bar(load, 30, phase, theme)}{reset} {target:<8} "
            f"{dim}{theme} {round(load * 100):>3}%{reset}"
        )
    return rows


def loading_bar(ratio: float, width: int, phase: float, theme: str) -> str:
    ratio = min(1.0, max(0.0, ratio))
    filled = int(round(ratio * width))
    if theme == "packets":
        cells = ["─" if i < filled else "·" for i in range(width)]
        for packet in range(max(1, filled // 7)):
            pos = int(((phase * 0.7 + packet / max(1, filled // 7)) % 1.0) * max(1, filled))
            if pos < width:
                cells[pos] = "█"
            if pos + 1 < width and pos + 1 < filled:
                cells[pos + 1] = "▌"
        return "".join(cells)
    if theme == "circuit":
        pulse = int((phase % 1.0) * max(1, filled))
        return "".join("█" if i == pulse else "╪" if i < filled and i % 5 == 2 else "═" if i < filled else "·" for i in range(width))
    if theme == "matrix":
        glyphs = "░▒▓█"
        return "".join(glyphs[(i + int(phase * 6)) % len(glyphs)] if i < filled else "·" for i in range(width))
    if theme == "comet":
        head = int((phase % 1.0) * max(1, filled))
        cells = []
        for i in range(width):
            if i >= filled:
                cells.append("·")
                continue
            distance = (head - i) % max(1, filled)
            cells.append("█" if distance < 1 else "▓" if distance < 2 else "▒" if distance < 4 else "░")
        return "".join(cells)
    if theme == "heartbeat":
        pos = int((phase % 1.0) * max(1, filled))
        spike = ["▁", "█", "▂", "▆"]
        return "".join(spike[i - pos] if 0 <= i - pos < len(spike) and i < filled else "▄" if i < filled else "·" for i in range(width))
    if theme == "hazard":
        offset = int(phase * 5)
        return "".join(("█" if (i + offset) % 3 == 0 else "▞") if i < filled else "░" for i in range(width))
    scan = int((phase % 1.0) * max(1, filled))
    return "".join("█" if i < filled and abs(i - scan) < 2 else "▓" if i < filled else "░" for i in range(width))


def overwatch_header(overwatch: dict[str, object], frame: int, accent: str, reset: str) -> list[str]:
    themes = list(overwatch.get("themes") or [])
    gauges = list(overwatch.get("gauges") or [])
    fields = list(overwatch.get("fields") or [])
    logos = list(overwatch.get("logo") or [])
    theme = themes[frame % len(themes)] if themes else "dotmax"
    gauge = gauges[(frame // 2) % len(gauges)] if gauges else "braille"
    field = fields[(frame // 3) % len(fields)] if fields else "swarm"
    lines = [
        f"{accent}OVERWATCH ASSETS{reset}  theme={theme}  gauge={gauge}  field={field}",
    ]
    if logos:
        width = 54
        lines.extend(f"{accent}{line[:width]}{reset}" for line in logos[:3])
    return lines


def swarm_canvas(frame: int, fix_mode: bool) -> DotMaxCanvas:
    canvas = DotMaxCanvas(76, 28)
    center = (38, 14)
    agents = [(12, 8), (14, 22), (62, 7), (64, 21), (38, 4), (38, 25)]
    for x, y in agents:
        canvas.line(x, y, center[0], center[1], samples=18)
        canvas.set(x, y)
    radius_x = 26
    radius_y = 9
    for index in range(32):
        angle = (index / 32) * math.tau
        canvas.set(center[0] + math.cos(angle) * radius_x, center[1] + math.sin(angle) * radius_y)
    for tail in range(7):
        angle = ((frame - tail * 2) / 32) * math.tau
        x = center[0] + math.cos(angle) * radius_x
        y = center[1] + math.sin(angle) * radius_y
        canvas.set(x, y)
        if fix_mode:
            canvas.set(x - 1, y)
            canvas.set(x, y - 1)
    for offset in range(4):
        angle = ((frame + offset * 8) / 32) * math.tau
        canvas.set(center[0] + math.cos(angle) * 7, center[1] + math.sin(angle) * 3)
    return canvas


def speedometer(tok_sec: int, fix_mode: bool) -> str:
    max_rate = max(1000, math.ceil(tok_sec / 1000) * 1000)
    ratio = min(1.0, tok_sec / max_rate)
    needle = min(20, max(0, round(ratio * 20)))
    left = "." * needle
    right = " " * (20 - needle)
    color = ansi("95") if fix_mode else ansi("92")
    return f"{color}[{left}^{right}]{ansi('0')}"


def bar(ratio: float, width: int, color: str) -> str:
    filled = min(width, max(0, round(ratio * width)))
    return f"{color}{'█' * filled}{'░' * (width - filled)}{ansi('0')}"


def count_repo(repo: Path) -> dict[str, int]:
    loc = 0
    bytes_seen = 0
    files = 0
    for path in iter_text_files(repo):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        files += 1
        bytes_seen += len(data)
        text = data.decode("utf-8", errors="ignore")
        loc += sum(1 for line in text.splitlines() if line.strip())
    return {"loc": loc, "files": files, "estimated_tokens": max(1, round(bytes_seen / 4))}


def load_overwatch_assets(root: str | Path | None = None) -> dict[str, object]:
    asset_root = resolve_overwatch_root(root)
    if not asset_root:
        return {}
    readme = asset_root / "README.md"
    source = asset_root / "overwatch.py"
    assets: dict[str, object] = {"root": str(asset_root)}
    if readme.is_file():
        text = readme.read_text(encoding="utf-8", errors="replace")
        assets["logo"] = extract_last_text_fence(text)
    if source.is_file():
        code = source.read_text(encoding="utf-8", errors="replace")
        assets["themes"] = extract_tuple_names(code, "BAR_THEMES")
        assets["gauges"] = extract_tuple_names(code, "GAUGE_STYLES")
        assets["fields"] = extract_tuple_names(code, "FIELD_STYLES")
        assets["schemes"] = re.findall(r'"name"\s*:\s*"([^"]+)"', code)
    return assets


def resolve_overwatch_root(root: str | Path | None = None) -> Path | None:
    candidates = []
    if root:
        candidates.append(Path(root).expanduser())
    env_root = os.getenv("BUGLAB_OVERWATCH_REPO") or os.getenv("OVERWATCH_REPO")
    if env_root:
        candidates.append(Path(env_root).expanduser())
    for candidate in candidates:
        if (candidate / "overwatch.py").is_file() or (candidate / "README.md").is_file():
            return candidate.resolve()
    return None


def extract_last_text_fence(text: str) -> list[str]:
    fences = re.findall(r"```(?:text)?\s*\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    best: list[str] = []
    best_score = 0
    for fence in fences:
        lines = [line.rstrip() for line in fence.splitlines() if line.strip()]
        score = sum(terminal_art_score(line) for line in lines)
        if score > best_score:
            best = lines
            best_score = score
    return best[:8] if best_score >= 8 else []


def terminal_art_score(line: str) -> int:
    score = 0
    for char in line:
        code = ord(char)
        if 0x2800 <= code <= 0x28FF or 0x2500 <= code <= 0x257F or 0x2580 <= code <= 0x259F:
            score += 2
        elif char in "█▓▒░▌▐▁▂▃▄▅▆▇▀■□◆◇▲△▼▽◢◣◤◥":
            score += 1
    return score


def extract_tuple_names(source: str, variable: str) -> list[str]:
    start = source.find(f"{variable} = [")
    if start < 0:
        return []
    end = source.find("\n]", start)
    if end < 0:
        end = min(len(source), start + 5000)
    block = source[start:end]
    names = re.findall(r'\(\s*"([^"]+)"', block)
    return names[:32]


def iter_text_files(repo: Path) -> Iterable[Path]:
    for path in repo.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            rel_parts = path.relative_to(repo).parts
        except ValueError:
            continue
        if any(part in IGNORED_DIRS for part in rel_parts):
            continue
        yield path


def clear() -> None:
    print("\033[2J\033[H", end="")


def ansi(code: str) -> str:
    if os.getenv("NO_COLOR"):
        return ""
    return f"\033[{code}m"
