from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

CONFIG_DIR_NAME = "VideoScreenshotFilter"
CONFIG_FILE_NAME = "config.json"
CONFIG_VERSION = 1


def app_config_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    directory = root / CONFIG_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def config_path() -> Path:
    return app_config_dir() / CONFIG_FILE_NAME


def default_output_dirs() -> dict[str, str]:
    root = Path.home() / "Videos" / "FrameForge"
    return {
        "download_dir": str(root / "videos"),
        "screenshot_dir": str(root / "screenshots"),
    }


def load_output_dirs() -> dict[str, str]:
    defaults = default_output_dirs()
    try:
        payload: Any = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return defaults
    if not isinstance(payload, dict):
        return defaults
    for key in defaults:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            defaults[key] = value.strip()
    return defaults


def save_output_dirs(download_dir: str, screenshot_dir: str) -> Path:
    path = config_path()
    payload = {
        "schema": CONFIG_VERSION,
        "download_dir": str(download_dir).strip(),
        "screenshot_dir": str(screenshot_dir).strip(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix="config-", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return path
