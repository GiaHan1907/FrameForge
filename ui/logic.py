"""Pure utility functions extracted from streamlit_app.py.

Every function in this module is free of Streamlit (``st.``), cv2, tkinter,
threading, and session_state dependencies.  This makes each function
independently testable with standard unittest.
"""

from __future__ import annotations

import io
import json
import math
import os
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path

from core.pipeline import recommended_extract_workers


# ── Formatting / progress helpers ──────────────────────────────────────


def format_eta(seconds: float | None) -> str:
    """Format seconds into a human-readable ETA string."""
    if seconds is None or not math.isfinite(float(seconds)) or seconds < 0:
        return "\u2014"
    total = int(round(float(seconds)))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}g {minutes:02d}p"
    if minutes:
        return f"{minutes}p {secs:02d}s"
    return f"{secs}s"


def parse_progress_units(message: str) -> tuple[int, int] | None:
    """Extract (done, total) from a progress message like '3/10 mốc'."""
    match = re.search(r"(\d+)\s*/\s*(\d+)\s*(?:m\u1ed1c|frame)", message)
    if not match:
        return None
    return int(match.group(1)), max(1, int(match.group(2)))


def progress_telemetry(item: dict[str, object]) -> dict[str, float | int | None]:
    """Compute FPS, ETA, and other telemetry from a progress item dict."""
    done = int(item.get("units_done", 0) or 0)
    total = int(item.get("units_total", 0) or 0)
    started_at = float(item.get("started_at", 0.0) or 0.0)
    elapsed = max(0.0, time.monotonic() - started_at) if started_at else 0.0
    fps = done / elapsed if done > 0 and elapsed > 0.2 else None
    eta = ((total - done) / fps) if fps and total > done else None
    return {
        "fps": fps,
        "eta": eta,
        "rss": int(item.get("rss_bytes", 0) or 0),
        "done": done,
        "total": total,
    }


# ── Preview timestamp helpers ──────────────────────────────────────────


def build_preview_timestamps(
    duration: float | None,
    mode: str,
    start: float,
    end: float | None,
    every: float | None,
    count: int,
    maximum: int,
) -> list[float]:
    """Build a list of preview timestamps based on the selected mode."""
    actual_end = (
        min(float(duration), float(end))
        if duration and end is not None
        else float(duration or end or 0.0)
    )
    actual_start = max(0.0, min(float(start), actual_end))
    if actual_end <= actual_start:
        return []
    if mode == "\u0110\u00fang N frame":
        total = max(1, int(count))
        if total == 1:
            return [round((actual_start + actual_end) / 2, 3)]
        safe_end = max(actual_start, actual_end - 0.1)
        return [
            round(actual_start + index * (safe_end - actual_start) / (total - 1), 3)
            for index in range(total)
        ]
    interval = float(every or 5.0)
    timestamps: list[float] = []
    current = actual_start
    while current < actual_end and len(timestamps) < max(1, int(maximum)):
        timestamps.append(round(current, 3))
        current += interval
    if mode in {"Best frame per scene", "Scene detection"} and maximum > 0:
        timestamps = timestamps[:maximum]
    return timestamps


# ── Path utilities ─────────────────────────────────────────────────────


def normalize_output_dir(value: str, fallback: Path) -> Path:
    """Resolve and create the output directory, falling back if empty."""
    raw = (value or "").strip()
    path = Path(os.path.expandvars(os.path.expanduser(raw))) if raw else fallback
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def frameforge_user_data_root() -> Path:
    """Return the platform-appropriate user data root for FrameForge."""
    base = os.environ.get("APPDATA") if os.name == "nt" else None
    return Path(base or (Path.home() / ".frameforge")) / "ui"


def personal_presets_path() -> Path:
    """Path to the personal presets JSON file."""
    return frameforge_user_data_root() / "presets.json"


def job_history_path() -> Path:
    """Path to the job history JSON file."""
    return frameforge_user_data_root() / "job_history.json"


# ── File I/O helpers ───────────────────────────────────────────────────


def read_json_list(path: Path) -> list[dict[str, object]]:
    """Read a JSON file and return it as a list, or [] on error."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, ValueError, TypeError):
        return []


def make_zip(directory: Path, report_path: Path) -> bytes:
    """Create an in-memory ZIP archive of a directory + report file."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(directory.rglob("*")):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(directory))
        if report_path.is_file():
            archive.write(report_path, report_path.name)
    return buffer.getvalue()


def make_download_zip(paths: list[Path]) -> bytes:
    """Create an in-memory ZIP archive from a list of file paths."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            if path.is_file():
                archive.write(path, path.name)
    return buffer.getvalue()


def append_job_history(job: dict[str, object]) -> None:
    """Append a completed job entry to the persistent job history file."""
    path = job_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    reports = job.get("reports") or []
    entry = {
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "status": job.get("status"),
        "output_dir": str(job.get("output_dir", "")),
        "video_count": len(job.get("input_paths") or []),
        "saved": sum(
            int(item.get("saved", 0) or 0)
            for item in reports
            if isinstance(item, dict)
        ),
        "shortfall": sum(
            int(item.get("shortfall", 0) or 0)
            for item in reports
            if isinstance(item, dict)
        ),
        "error": job.get("error"),
    }
    history = read_json_list(path)
    history.insert(0, entry)
    path.write_text(
        json.dumps(history[:200], ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Queue state helpers ────────────────────────────────────────────────


def _pause_processing_job(job: dict[str, object]) -> None:
    """Set the pause flag on a processing job dict."""
    pause_event = job.get("pause_event")
    if pause_event is not None:
        pause_event.set()
    job["status"] = "paused"
    job["message"] = (
        "Tạm d\u1eebng queue; video hi\u1ec7n t\u1ea1i s\u1ebd ho\u00e0n t\u1eaft r\u1ed3i ch\u1edd ti\u1ebfp t\u1ee5c."
    )


def _resume_processing_job(job: dict[str, object]) -> None:
    """Clear the pause flag on a processing job dict."""
    pause_event = job.get("pause_event")
    if pause_event is not None:
        pause_event.clear()
    job["status"] = "running"
    job["message"] = "\u0110\u00e3 ti\u1ebfp t\u1ee5c queue."
