"""Wizard helper functions extracted from streamlit_app.py.

These functions read widget values from a ``widgets: dict`` parameter
(populated by ``ui.session.read_widgets()``) instead of module-level globals.
This makes them testable without a Streamlit runtime.
"""

from __future__ import annotations

from typing import Any

from core.config import FrameForgeConfig
from core.pipeline import recommended_extract_workers


def build_args(widgets: dict[str, Any], *, source_count: int = 0) -> FrameForgeConfig:
    """Build a ``FrameForgeConfig`` from the current widget values.

    Parameters
    ----------
    widgets:
        Dict returned by ``ui.session.read_widgets()``.  Keys are Python
        variable names (``"start"``, ``"mode_label"``, etc.).
    source_count:
        Number of uploaded + downloaded videos (used for context, not
        stored in config).
    """
    mode_label = widgets.get("mode_label", "Best frame per scene")
    every = widgets.get("every")
    _ms_raw = widgets.get("max_screenshots")
    max_screenshots = int(_ms_raw) if _ms_raw is not None else 20
    extract_worker_choice = widgets.get("extract_worker_choice", "Auto (khuyến nghị)")
    worker_choice = widgets.get("worker_choice", "Auto (khuyến nghị)")

    # Derived: count and workers
    if mode_label == "Đúng N frame":
        count = max_screenshots
    else:
        count = None

    workers = "auto" if worker_choice == "Auto (khuyến nghị)" else int(worker_choice)

    return FrameForgeConfig(
        start=float(widgets.get("start") or 0),
        end=float(widgets["end"]) if widgets.get("limit_end") else None,
        every=float(every) if every is not None else None,
        count=int(count) if count is not None else None,
        max_screenshots=max_screenshots,
        target_count_after_filter=bool(widgets.get("target_count_after_filter", True)),
        target_candidate_multiplier=3,
        target_candidate_multiplier_max=5,
        repair_manifest=False,
        min_free_ram_gb=float(widgets.get("min_free_ram_gb") or 0.0),
        scene_detection=mode_label in {"Best frame per scene", "Scene detection"},
        best_frame_per_scene=mode_label == "Best frame per scene",
        scene_threshold=float(widgets.get("scene_threshold") or 0.30),
        min_scene_gap=float(widgets.get("min_scene_gap") or 0.5),
        flash_return_ratio=float(widgets.get("flash_return_ratio") or 0.55),
        flash_brightness_threshold=float(widgets.get("flash_brightness_threshold") or 0.18),
        scene_confirmations=int(widgets.get("scene_confirmations") or 2),
        analysis_width=int(widgets.get("analysis_width") or 640),
        analysis_fps=float(widgets.get("analysis_fps") or 1.0),
        extract_workers=(
            recommended_extract_workers()
            if extract_worker_choice == "Auto (khuyến nghị)"
            else int(extract_worker_choice)
        ),
        extract_min_targets=8,
        min_sharpness=float(widgets.get("min_sharpness") or 0.0),
        motion_blur_threshold=float(widgets.get("motion_blur_threshold") or 0.3),
        duplicate_threshold=int(widgets.get("duplicate_threshold") or 0),
        format=str(widgets.get("image_format") or "jpg"),
        quality=int(widgets.get("quality") or 95),
        crop_ratio=widgets.get("crop_ratio"),
        encode_profile=str(widgets.get("encode_profile") or "Chất lượng cao"),
        width=int(widgets["width"]) if widgets.get("width") else None,
        overwrite=bool(widgets.get("overwrite")),
        workers=workers,
        retries=int(widgets.get("retry_count") or 3),
        retry_delay=float(widgets.get("retry_delay") or 2.0),
        disk_reserve_bytes=int(widgets.get("disk_reserve_mb") or 500) * 1024**2,
        use_scene_cache=bool(widgets.get("use_scene_cache", True)),
        cross_run_duplicates=bool(widgets.get("cross_run_duplicates")),
        cross_run_duplicate_threshold=int(widgets.get("duplicate_threshold") or 0),
        resume=False,
        checkpoint_path=None,
        cache_root=None,
        duplicate_root=None,
        queue_db=None,
    )


def validate_ui_configuration(
    widgets: dict[str, Any],
    *,
    source_count: int = 0,
    screenshot_dir: str = "",
    workers_value: Any = None,
) -> dict[str, list[str]]:
    """Validate widget values and return errors/warnings.

    Parameters
    ----------
    widgets:
        Dict returned by ``ui.session.read_widgets()``.
    source_count:
        Number of uploaded + downloaded videos.
    screenshot_dir:
        Current screenshot directory path from session_state.
    workers_value:
        The resolved workers value (string "auto" or int).  If *None*,
        derived from ``widgets["worker_choice"]``.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if source_count == 0:
        errors.append("Hãy chọn ít nhất một video upload hoặc tải video công khai.")

    if not str(screenshot_dir).strip():
        errors.append("Chưa chọn thư mục lưu screenshot.")

    start_val = float(widgets.get("start") or 0)
    end_val = float(widgets.get("end") or 0)
    limit_end = bool(widgets.get("limit_end"))

    if start_val < 0:
        errors.append("Thời điểm bắt đầu không được nhỏ hơn 0 giây.")
    if limit_end and end_val <= start_val:
        errors.append("Thời điểm kết thúc phải lớn hơn thời điểm bắt đầu.")

    _ms_raw = widgets.get("max_screenshots")
    max_screenshots = int(_ms_raw) if _ms_raw is not None else 20
    if max_screenshots < 1:
        errors.append("Số screenshot mỗi video phải từ 1 trở lên.")

    analysis_fps = float(widgets.get("analysis_fps") or 0)
    analysis_width = int(widgets.get("analysis_width") or 0)
    if analysis_fps <= 0 or analysis_width < 64:
        errors.append("Độ phân giải phân tích phải từ 64 px và FPS phải lớn hơn 0.")

    min_sharpness = float(widgets.get("min_sharpness") or 0)
    if min_sharpness > 300:
        warnings.append("Ngưỡng sharpness rất cao; video có thể tạo shortfall lớn.")

    if max_screenshots > 300:
        warnings.append("Screenshot lớn có thể làm tăng thời gian xử lý và dung lượng output.")

    if workers_value is None:
        worker_choice = widgets.get("worker_choice", "Auto (khuyến nghị)")
        workers_value = "auto" if worker_choice == "Auto (khuyến nghị)" else worker_choice

    if isinstance(workers_value, int) or (isinstance(workers_value, str) and workers_value.isdigit()):
        worker_count = int(workers_value)
        min_free_ram_gb = float(widgets.get("min_free_ram_gb") or 0)
        if worker_count > 1 and min_free_ram_gb <= 0:
            warnings.append("Nhiều worker nhưng chưa đặt RAM reserve; nên đặt ngưỡng RAM tối thiểu để queue tự back-pressure.")

    return {"errors": errors, "warnings": warnings}


def wizard_summary(widgets: dict[str, Any], *, source_count: int = 0) -> dict[str, str]:
    """Build a human-readable summary of the current wizard configuration.

    Parameters
    ----------
    widgets:
        Dict returned by ``ui.session.read_widgets()``.
    source_count:
        Number of uploaded + downloaded videos.
    """
    image_format = str(widgets.get("image_format") or "jpg")
    output_format = "PNG" if image_format == "png" else image_format.upper()
    crop_ratio = widgets.get("crop_ratio") or "Không crop"
    crop_label = crop_ratio if crop_ratio != "Không crop" else "Giữ nguyên"
    mode_label = widgets.get("mode_label", "Best frame per scene")
    analysis_width = int(widgets.get("analysis_width") or 640)
    analysis_fps = float(widgets.get("analysis_fps") or 1.0)
    encode_profile = str(widgets.get("encode_profile") or "Chất lượng cao")

    return {
        "Nguồn": f"{source_count} video",
        "Chọn frame": str(mode_label),
        "Chất lượng": f"{analysis_width} px · {analysis_fps:g} FPS",
        "Đầu ra": f"{output_format} · {crop_label} · {encode_profile}",
    }
