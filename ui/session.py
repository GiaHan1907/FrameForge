"""Widget session-state mapping for FrameForge.

Every Streamlit widget has an explicit ``key=`` parameter, so its value is
always available via ``st.session_state[key]``.  This module provides:

* ``WIDGET_KEYS`` – dict mapping Python variable names to session-state keys.
* ``WidgetState`` – TypedDict with typed defaults for every widget key.
* ``read_widget(key, default)`` – read a single widget value.
* ``read_widgets()`` – read all widget values into a ``WidgetState`` dict.

Functions that need widget values (``build_args``, ``validate_ui_configuration``,
etc.) accept a ``widgets: WidgetState`` parameter populated by ``read_widgets()``.
This removes their dependency on module-level globals and lets them live in
separate, testable modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

try:
    import streamlit as st
except ImportError:  # pragma: no cover – allows import without Streamlit
    st = None  # type: ignore[assignment]


# ── Typed widget state ──────────────────────────────────────────────────


class WidgetState(TypedDict, total=False):
    """Typed, defaulted representation of every Streamlit widget value.

    All fields are ``total=False`` so that ``read_widgets()`` can build the
    dict incrementally.  Consumers access ``widgets["start"]`` and always
    get the correct type — never ``None`` for required numeric/bool fields.
    """

    # Source / output paths
    video_dir_text: str
    screenshot_dir_text: str

    # Download panel
    download_urls_text: str
    download_quality: str
    playlist_max_items: int
    download_retry_count: int

    # Upload
    uploaded_files: list[Any]

    # Wizard step 02 – frame selection
    mode_label: str
    start: float
    limit_end: bool
    end: float
    every: float | None
    max_screenshots: int
    target_count_after_filter: bool

    # Scene detection (conditional)
    scene_threshold: float
    min_scene_gap: float
    flash_return_ratio: float
    flash_brightness_threshold: float
    scene_confirmations: int

    # Wizard step 03 – quality & speed
    worker_choice: str
    analysis_width: int
    min_free_ram_gb: float
    analysis_fps: float
    extract_worker_choice: str

    # Wizard step 03 – sharpness & dedup
    min_sharpness: float
    duplicate_threshold: int
    motion_blur_threshold: float

    # Wizard step 04 – output
    encode_profile: str
    image_format: str
    crop_ratio: str
    quality: int
    width: int
    overwrite: bool
    retry_count: int
    retry_delay: float
    disk_reserve_mb: int
    use_scene_cache: bool
    cross_run_duplicates: bool

    # Timeline
    selected_video_filter: str
    scene_query: str
    selected_range: tuple[float, float] | None
    zoom_percent: int

    # Scene interaction
    selected_label: str
    adjusted_timestamp: float | None

    # Preview
    preview_name: str
    selected_preview_time: float

    # Presets
    selected: str
    preset_name: str
    imported: Any

    # Update channel
    channel_choice: str

    # Wizard navigation
    wizard_step: str

    # Recovery
    recovery_index: int

    # Derived (not from widget — computed by read_widgets)
    downloaded_paths: list[Path]


# ── Default values ──────────────────────────────────────────────────────
# Every widget key maps to a (session_state_key, default) pair.
# Defaults are applied so consumers never see ``None`` for expected types.

_WIDGET_DEFAULTS: dict[str, tuple[str, Any]] = {
    # Source / output paths
    "video_dir_text":            ("video_dir_text",              ""),
    "screenshot_dir_text":       ("screenshot_dir_text",         ""),
    # Download panel
    "download_urls_text":        ("download_urls_text",          ""),
    "download_quality":          ("download_quality",            ""),
    "playlist_max_items":        ("playlist_max_items",          50),
    "download_retry_count":      ("download_retry_count",        2),
    # Upload
    "uploaded_files":            ("uploaded_files",              []),
    # Wizard step 02 – frame selection
    "mode_label":                ("mode_label",                  "Best frame per scene"),
    "start":                     ("start",                       0.0),
    "limit_end":                 ("limit_end",                   False),
    "end":                       ("end",                         60.0),
    "every":                     ("every",                       None),
    "max_screenshots":           ("max_screenshots",             20),
    "target_count_after_filter": ("target_count_after_filter",   True),
    # Scene detection
    "scene_threshold":           ("scene_threshold",             0.30),
    "min_scene_gap":             ("min_scene_gap",               0.5),
    "flash_return_ratio":        ("flash_return_ratio",          0.55),
    "flash_brightness_threshold": ("flash_brightness_threshold", 0.18),
    "scene_confirmations":       ("scene_confirmations",         2),
    # Wizard step 03 – quality & speed
    "worker_choice":             ("worker_choice",               "Auto (khuyến nghị)"),
    "analysis_width":            ("analysis_width",              640),
    "min_free_ram_gb":           ("min_free_ram_gb",             0.0),
    "analysis_fps":              ("analysis_fps",                1.0),
    "extract_worker_choice":     ("extract_worker_choice",       "Auto (khuyến nghị)"),
    # Wizard step 03 – sharpness & dedup
    "min_sharpness":             ("min_sharpness",               0.0),
    "duplicate_threshold":       ("duplicate_threshold",         0),
    "motion_blur_threshold":     ("motion_blur_threshold",       0.3),
    # Wizard step 04 – output
    "encode_profile":            ("encode_profile",              "Chất lượng cao"),
    "image_format":              ("image_format",                "jpg"),
    "crop_ratio":                ("crop_ratio",                  "Không crop"),
    "quality":                   ("quality",                     95),
    "width":                     ("width",                       0),
    "overwrite":                 ("overwrite",                   False),
    "retry_count":               ("retries",                     3),
    "retry_delay":               ("retry_delay",                 2.0),
    "disk_reserve_mb":           ("disk_reserve_mb",             500),
    "use_scene_cache":           ("use_scene_cache",             True),
    "cross_run_duplicates":      ("cross_run_duplicates",        False),
    # Timeline
    "selected_video_filter":     ("timeline_video_filter",       ""),
    "scene_query":               ("timeline_scene_query",        ""),
    "selected_range":            ("timeline_time_filter",        None),
    "zoom_percent":              ("timeline_zoom",               100),
    # Scene interaction
    "selected_label":            ("interactive_scene_choice",    ""),
    "adjusted_timestamp":        ("interactive_scene_timestamp", None),
    # Preview
    "preview_name":              ("preview_name",                ""),
    "selected_preview_time":     ("preview_timestamp_slider",    0.0),
    # Presets
    "selected":                  ("personal_preset_choice",      ""),
    "preset_name":               ("personal_preset_name",        ""),
    "imported":                  ("import_ui_config",            None),
    # Update channel
    "channel_choice":            ("update_channel_choice",       "stable"),
    # Wizard navigation
    "wizard_step":               ("wizard_step",                 "01 — Nguồn"),
    # Recovery
    "recovery_index":            ("recovery_queue_choice",       0),
}


# ── Variable-name → session-state-key mapping (kept for backward compat) ──

WIDGET_KEYS: dict[str, str] = {var: ss_key for var, (ss_key, _default) in _WIDGET_DEFAULTS.items()}


# ── Readers ─────────────────────────────────────────────────────────────


def read_widget(key: str, default: Any = None) -> Any:
    """Read a single widget value from ``st.session_state``."""
    if st is None:  # pragma: no cover
        return default
    return st.session_state.get(key, default)


def read_widgets() -> WidgetState:
    """Read all mapped widget values into a ``WidgetState`` dict.

    Every field is populated with either the live ``session_state`` value
    or the declared default — callers never see ``None`` for typed fields.

    Special handling:
    * ``downloaded_paths`` — derived from ``session_state["downloaded_paths"]``
      (list of strings), filtered to files that still exist on disk.
    """
    result: dict[str, Any] = {}

    for var_name, (ss_key, default) in _WIDGET_DEFAULTS.items():
        if st is None:  # pragma: no cover
            result[var_name] = default
        else:
            raw = st.session_state.get(ss_key)
            # Apply default when raw is None or empty-string for non-str fields
            if raw is None:
                result[var_name] = default
            elif isinstance(default, bool):
                result[var_name] = bool(raw)
            elif isinstance(default, int) and not isinstance(default, bool):
                try:
                    result[var_name] = int(raw)
                except (TypeError, ValueError):
                    result[var_name] = default
            elif isinstance(default, float):
                try:
                    result[var_name] = float(raw)
                except (TypeError, ValueError):
                    result[var_name] = default
            else:
                result[var_name] = raw

    # downloaded_paths is not a widget — it's a list of Path objects derived
    # from session_state["downloaded_paths"] (list of strings), filtered to
    # files that still exist on disk.
    if st is None:  # pragma: no cover
        result["downloaded_paths"] = []
    else:
        raw_paths = st.session_state.get("downloaded_paths", [])
        result["downloaded_paths"] = [
            Path(item) for item in raw_paths if Path(item).exists()
        ]

    return result  # type: ignore[return-value]
