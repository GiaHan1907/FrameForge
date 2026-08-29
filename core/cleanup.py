"""Cleanup helpers, formatting, stage timing, and video discovery.

Extracted from ``core/pipeline.py`` to isolate operational helpers
from the core pipeline framework.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".ts", ".mts"
}


# ── Path size helper ──────────────────────────────────────────────────


def _path_size_bytes(path: Path) -> int:
    if path.is_file():
        try:
            return int(path.stat().st_size)
        except OSError:
            return 0
    total = 0
    try:
        for child in path.rglob("*"):
            if child.is_file():
                try:
                    total += int(child.stat().st_size)
                except OSError:
                    continue
    except OSError:
        return total
    return total


# ── Cleanup helpers ───────────────────────────────────────────────────


def cleanup_frameforge_temp_dirs(
    temp_root: Path | None = None,
    prefix: str = "video_screenshot_web_",
    older_than_seconds: int = 24 * 60 * 60,
    max_total_bytes: int | None = None,
) -> int:
    """Dọn work directory cũ theo tuổi và quota, không đụng thư mục đang dùng."""
    root = temp_root or Path(tempfile.gettempdir())
    cutoff = time.time() - max(0, older_than_seconds)
    candidates: list[tuple[Path, float, int]] = []
    try:
        paths = list(root.glob(f"{prefix}*"))
    except OSError:
        return 0
    for candidate in paths:
        try:
            stat = candidate.stat()
            if candidate.is_dir() and stat.st_mtime < cutoff:
                candidates.append((candidate, float(stat.st_mtime), _path_size_bytes(candidate)))
        except OSError:
            continue
    candidates.sort(key=lambda item: item[1])
    removed = 0
    total = sum(item[2] for item in candidates)
    quota = int(max_total_bytes or 0)
    for candidate, _mtime, size in candidates:
        if quota > 0 and total <= quota:
            break
        try:
            shutil.rmtree(candidate, ignore_errors=True)
            if not candidate.exists():
                removed += 1
                total = max(0, total - size)
        except OSError:
            continue
    return removed


def cleanup_frameforge_cache(
    cache_root: Path,
    max_total_bytes: int = 0,
    older_than_seconds: int = 7 * 24 * 60 * 60,
) -> int:
    """Xóa cache scene cũ nhất khi vượt quota; quota 0 nghĩa là không xóa."""
    quota = max(0, int(max_total_bytes))
    if quota <= 0 or not cache_root.exists():
        return 0
    cutoff = time.time() - max(0, int(older_than_seconds))
    try:
        files = [path for path in cache_root.glob("*.json") if path.is_file()]
    except OSError:
        return 0
    entries: list[tuple[Path, float, int]] = []
    total = 0
    for path in files:
        try:
            stat = path.stat()
            size = int(stat.st_size)
            total += size
            if stat.st_mtime < cutoff:
                entries.append((path, float(stat.st_mtime), size))
        except OSError:
            continue
    entries.sort(key=lambda item: item[1])
    removed = 0
    for path, _mtime, size in entries:
        if total <= quota:
            break
        try:
            path.unlink()
            removed += 1
            total = max(0, total - size)
        except OSError:
            continue
    return removed


# ── Video discovery ───────────────────────────────────────────────────


def find_videos(source: Path, recursive: bool) -> list[Path]:
    if source.is_file():
        return [source]
    if not source.is_dir():
        raise FileNotFoundError(f"Không tìm thấy đầu vào: {source}")
    iterator = source.rglob("*") if recursive else source.glob("*")
    return sorted(
        path for path in iterator
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )


# ── Formatting helpers ────────────────────────────────────────────────


def timestamp_label(seconds: float) -> str:
    milliseconds = int(round((seconds - int(seconds)) * 1000))
    whole_seconds = int(seconds)
    if milliseconds == 1000:
        whole_seconds += 1
        milliseconds = 0
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}-{minutes:02d}-{secs:02d}.{milliseconds:03d}"


# ── Stage timing helpers ──────────────────────────────────────────────


def new_stage_timings() -> dict[str, float | int]:
    return {
        "decode_ms": 0.0,
        "analysis_ms": 0.0,
        "encode_ms": 0.0,
        "write_ms": 0.0,
        "decode_count": 0,
        "analysis_count": 0,
        "encode_count": 0,
        "write_count": 0,
    }


def record_stage_timing(
    timings: dict[str, float | int] | None,
    stage: str,
    started_at: float,
) -> None:
    if timings is None:
        return
    elapsed_ms = max(0.0, (time.perf_counter() - started_at) * 1000.0)
    timings[f"{stage}_ms"] = round(float(timings.get(f"{stage}_ms", 0.0)) + elapsed_ms, 3)
    timings[f"{stage}_count"] = int(timings.get(f"{stage}_count", 0)) + 1
