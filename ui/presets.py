"""Personal presets and job history functions.

These functions handle user preset configuration and job history persistence.
They use st.session_state but no other Streamlit UI calls.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import streamlit as st

from ui.logic import (
    frameforge_user_data_root,
    job_history_path,
    personal_presets_path,
    read_json_list,
)

# Re-export for backward compatibility
__all__ = [
    "PERSONAL_PRESET_KEYS",
    "current_personal_preset",
    "save_personal_preset",
    "apply_personal_preset",
    "export_ui_config",
    "import_ui_config",
]

# These must be set by the main app after PRESET_CONFIGS is defined
PERSONAL_PRESET_KEYS: tuple[str, ...] = ()

# Default preset values (fallback when session_state is not set)
_DEFAULT_PRESET: dict[str, object] = {}


def init_presets(preset_configs: dict[str, dict[str, object]]) -> None:
    """Initialize PERSONAL_PRESET_KEYS from PRESET_CONFIGS.

    Must be called once at startup after PRESET_CONFIGS is defined.
    """
    global PERSONAL_PRESET_KEYS, _DEFAULT_PRESET
    PERSONAL_PRESET_KEYS = tuple(preset_configs.get("\u00c2n b\u1eb1ng", {}).keys())
    _DEFAULT_PRESET = preset_configs.get("\u00c2n b\u1eb1ng", {})


def current_personal_preset() -> dict[str, object]:
    """Read current widget values as a personal preset dict."""
    return {
        key: st.session_state.get(key, _DEFAULT_PRESET.get(key))
        for key in PERSONAL_PRESET_KEYS
    }


def save_personal_preset(name: str) -> None:
    """Save current configuration as a named personal preset."""
    clean_name = str(name).strip()[:80]
    if not clean_name:
        return
    path = personal_presets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    presets = [
        item for item in read_json_list(path) if item.get("name") != clean_name
    ]
    presets.append({
        "name": clean_name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "config": current_personal_preset(),
    })
    path.write_text(
        json.dumps(presets, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def apply_personal_preset(preset: dict[str, object]) -> None:
    """Apply a personal preset to session_state widget values."""
    config = preset.get("config") if isinstance(preset, dict) else None
    if not isinstance(config, dict):
        return
    for key in PERSONAL_PRESET_KEYS:
        if key in config:
            st.session_state[key] = config[key]


def export_ui_config() -> bytes:
    """Export current configuration as JSON bytes."""
    payload = {
        "schema": 1,
        "app": "FrameForge",
        "version": "0.1.29",
        "config": current_personal_preset(),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def import_ui_config(uploaded_config: object) -> tuple[bool, str]:
    """Import configuration from an uploaded JSON file."""
    try:
        raw = uploaded_config.getvalue() if hasattr(uploaded_config, "getvalue") else b""
        payload = json.loads(raw.decode("utf-8"))
        config = payload.get("config", payload) if isinstance(payload, dict) else None
        if not isinstance(config, dict):
            return False, "File c\u1ea5u h\u00ecnh kh\u00f4ng c\u00f3 object config h\u1ee3p l\u1ec7."
        changed = 0
        for key in PERSONAL_PRESET_KEYS:
            if key in config:
                st.session_state[key] = config[key]
                changed += 1
        return changed > 0, (
            f"\u0110\u00e3 nh\u1eadp {changed} tr\u01b0\u1eddng c\u1ea5u h\u00ecnh; "
            "giao di\u1ec7n s\u1ebd t\u1ea3i l\u1ea1i \u0111\u1ec3 \u00e1p d\u1ee5ng."
        )
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, TypeError) as exc:
        return False, f"Kh\u00f4ng th\u1ec3 \u0111\u1ecdc file c\u1ea5u h\u00ecnh: {exc}"
