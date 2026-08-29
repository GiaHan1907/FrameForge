"""Widget session-state mapping for FrameForge.

Every Streamlit widget has an explicit ``key=`` parameter, so its value is
always available via ``st.session_state[key]``.  This module provides:

* ``WIDGET_KEYS`` – dict mapping Python variable names to session-state keys.
* ``read_widget(key, default)`` – read a single widget value.
* ``read_widgets()`` – read all widget values into a plain dict.

Functions that need widget values (``build_args``, ``validate_ui_configuration``,
etc.) accept a ``widgets: dict`` parameter populated by ``read_widgets()``.
This removes their dependency on module-level globals and lets them live in
separate, testable modules.
"""

from __future__ import annotations

from typing import Any

try:
    import streamlit as st
except ImportError:  # pragma: no cover – allows import without Streamlit
    st = None  # type: ignore[assignment]

# ── Variable-name → session-state-key mapping ────────────────────────────
# Keys are the Python variable names used in streamlit_app.py.
# Values are the explicit ``key=`` parameters on the widgets.

WIDGET_KEYS: dict[str, str] = {
    # Source / output paths
    "video_dir_text": "video_dir_text",
    "screenshot_dir_text": "screenshot_dir_text",
    # Download panel
    "download_urls_text": "download_urls_text",
    "download_quality": "download_quality",
    "playlist_max_items": "playlist_max_items",
    "download_retry_count": "download_retry_count",
    # Upload
    "uploaded_files": "uploaded_files",
    # Wizard step 02 – frame selection
    "mode_label": "mode_label",
    "start": "start",
    "limit_end": "limit_end",
    "end": "end",
    "every": "every",
    "max_screenshots": "max_screenshots",
    "target_count_after_filter": "target_count_after_filter",
    # Scene detection (conditional)
    "scene_threshold": "scene_threshold",
    "min_scene_gap": "min_scene_gap",
    "flash_return_ratio": "flash_return_ratio",
    "flash_brightness_threshold": "flash_brightness_threshold",
    "scene_confirmations": "scene_confirmations",
    # Wizard step 03 – quality & speed
    "worker_choice": "worker_choice",
    "analysis_width": "analysis_width",
    "min_free_ram_gb": "min_free_ram_gb",
    "analysis_fps": "analysis_fps",
    "extract_worker_choice": "extract_worker_choice",
    # Wizard step 03 – sharpness & dedup
    "min_sharpness": "min_sharpness",
    "duplicate_threshold": "duplicate_threshold",
    "motion_blur_threshold": "motion_blur_threshold",
    # Wizard step 04 – output
    "encode_profile": "encode_profile",
    "image_format": "image_format",
    "crop_ratio": "crop_ratio",
    "quality": "quality",
    "width": "width",
    "overwrite": "overwrite",
    "retry_count": "retries",
    "retry_delay": "retry_delay",
    "disk_reserve_mb": "disk_reserve_mb",
    "use_scene_cache": "use_scene_cache",
    "cross_run_duplicates": "cross_run_duplicates",
    # Timeline
    "selected_video_filter": "timeline_video_filter",
    "scene_query": "timeline_scene_query",
    "selected_range": "timeline_time_filter",
    "zoom_percent": "timeline_zoom",
    # Scene interaction
    "selected_label": "interactive_scene_choice",
    "adjusted_timestamp": "interactive_scene_timestamp",
    # Preview
    "preview_name": "preview_name",
    "selected_preview_time": "preview_timestamp_slider",
    # Presets
    "selected": "personal_preset_choice",
    "preset_name": "personal_preset_name",
    "imported": "import_ui_config",
    # Update channel
    "channel_choice": "update_channel_choice",
    # Wizard navigation
    "wizard_step": "wizard_step",
    # Recovery
    "recovery_index": "recovery_queue_choice",
}


def read_widget(key: str, default: Any = None) -> Any:
    """Read a single widget value from ``st.session_state``."""
    if st is None:  # pragma: no cover
        return default
    return st.session_state.get(key, default)


def read_widgets() -> dict[str, Any]:
    """Read all mapped widget values into a plain dict.

    The returned dict uses *variable names* as keys (not session-state keys)
    so that callers can access ``widgets["start"]`` etc.

    Special handling:
    * ``downloaded_paths`` — derived from session_state (list of Path objects
      filtered to existing files), not a direct widget value.
    """
    if st is None:  # pragma: no cover
        result = {var: None for var in WIDGET_KEYS}
        result["downloaded_paths"] = []
        return result
    result = {var: st.session_state.get(ss_key) for var, ss_key in WIDGET_KEYS.items()}
    # downloaded_paths is not a widget — it's a list of Path objects derived
    # from session_state["downloaded_paths"] (list of strings), filtered to
    # files that still exist on disk.
    from pathlib import Path
    raw = st.session_state.get("downloaded_paths", [])
    result["downloaded_paths"] = [
        Path(item) for item in raw if Path(item).exists()
    ]
    return result
