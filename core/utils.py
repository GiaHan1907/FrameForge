"""Shared utility functions for FrameForge.

Consolidates duplicated helpers that previously lived in app_update.py,
video_screenshot_advanced.py, and video_downloader.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Atomic file I/O
# ---------------------------------------------------------------------------

def atomic_write_json(path: Path, value: dict[str, object]) -> None:
    """Write *value* as JSON to *path* atomically (write-tmp then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def read_json(path: Path) -> dict[str, object] | None:
    """Read a JSON file and return it as a dict, or ``None`` on failure."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


# ---------------------------------------------------------------------------
# Windows process helpers
# ---------------------------------------------------------------------------

def hidden_windows_process_kwargs() -> dict[str, object]:
    """Return ``creationflags`` to hide child-process consoles on Windows."""
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}


# ---------------------------------------------------------------------------
# Byte formatting
# ---------------------------------------------------------------------------

def format_bytes(value: int | float) -> str:
    """Format a byte count into a human-readable string (e.g. ``4.2 MB``)."""
    amount = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TB"
