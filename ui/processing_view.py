"""Processing job fragment — live polling and result display.

Extracted from ``streamlit_app.py`` to isolate the ``@st.fragment``
processing view into a dedicated module.  The fragment polls the
background job every second and renders status, metrics, downloads,
and preview images.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import streamlit as st

from ui.dashboard import error_actions, render_queue_dashboard, render_resource_meter
from ui.logic import make_zip
from ui.queue_ui import ProcessingQueueAdapter as _ProcessingQueueAdapter
from ui.timeline import show_scene_timeline
from queue_per_video import render_queue_per_video


def poll_processing_job() -> dict[str, object] | None:
    """Thin wrapper: delegates to ui.processing with session_state."""
    from ui.processing import poll_processing_job as _poll_core
    return _poll_core(st.session_state)


def start_processing_job(
    args: Any,
    input_paths: list[Path],
    output_dir: Path,
    work_dir: Path,
) -> None:
    """Thin wrapper: delegates to ui.processing with session_state."""
    from ui.processing import start_processing_job as _start_core
    _start_core(st.session_state, args, input_paths, output_dir, work_dir)


@st.fragment(run_every=1.0)
def render_processing_job() -> None:
    """Poll and render the current processing job status."""
    job = poll_processing_job()
    if not job:
        return
    status = str(job.get("status"))

    if status in {"running", "paused"}:
        adapter = _ProcessingQueueAdapter(job)
        snapshot = adapter.snapshot()
        render_queue_dashboard(snapshot)
        render_resource_meter(job.get("args"), Path(str(job.get("output_dir", ""))).parent)
        render_queue_per_video(adapter, key_prefix="processing_queue")
        return

    if status == "cancelled":
        st.warning(str(job.get("message", "Đã hủy xử lý.")))
        work_dir = Path(str(job.get("work_dir", "")))
        if job.get("resumable") and work_dir.exists():
            if st.button("Tiếp tục từ checkpoint", key="resume_processing", type="primary"):
                args = job.get("args")
                if args is not None:
                    args.resume = True
                    start_processing_job(
                        args,
                        list(job.get("input_paths", [])),
                        Path(str(job["output_dir"])),
                        work_dir,
                    )
                    st.rerun()
        return

    if status == "error":
        message = str(job.get("message", "Có lỗi khi xử lý queue."))
        st.error(message)
        error_actions(message, key_prefix="queue_error")
        return

    reports = job.get("reports") or []
    if status == "completed":
        render_queue_per_video(_ProcessingQueueAdapter(job), key_prefix="processing_queue_done")

    _render_completed_results(job, reports)


def _render_completed_results(job: dict[str, Any], reports: list[dict[str, Any]]) -> None:
    """Render the completed/error results: metrics, downloads, preview."""
    output_dir = Path(str(job["output_dir"]))
    report_path = Path(str(job["report_path"]))
    zip_bytes = make_zip(output_dir, report_path)
    st.success(f"Đã lưu screenshot và report trực tiếp tại: {output_dir}")

    total_saved = sum(int(item.get("saved", 0)) for item in reports)
    total_blurry = sum(int(item.get("rejected_blurry", 0)) for item in reports)
    total_duplicate = sum(int(item.get("rejected_duplicate", 0)) for item in reports)
    total_motion_blur = sum(int(item.get("rejected_motion_blur", 0)) for item in reports)
    total_errors = sum(int(item.get("capture_errors", 0)) for item in reports) + sum("error" in item for item in reports)
    total_attempts = sum(int(item.get("attempts", 1)) for item in reports)
    total_target = sum(int(item.get("target_screenshots", 0) or 0) for item in reports)
    total_shortfall = sum(int(item.get("shortfall", 0) or 0) for item in reports)
    total_fallback = sum(int(item.get("forced_fallback_saved", 0) or 0) for item in reports)

    metric_a, metric_b, metric_c, metric_d, metric_e = st.columns(5)
    metric_a.metric("Đã lưu", total_saved)
    metric_b.metric("Loại vì mờ", total_blurry)
    metric_c.metric("Motion blur", total_motion_blur)
    metric_d.metric("Loại vì trùng", total_duplicate)
    metric_e.metric("Lỗi / retry", f"{total_errors} / {max(0, total_attempts - len(reports))}")

    adaptive_workers = sorted({int(item.get("adaptive_extract_workers", 1)) for item in reports if "error" not in item})
    video_workers = sorted({int(item.get("video_workers", 1)) for item in reports if "error" not in item})
    adaptive_label = ", ".join(str(value) for value in adaptive_workers) or "1"
    video_label = ", ".join(str(value) for value in video_workers) or "1"

    if total_target > 0:
        if total_shortfall:
            st.warning(f"Thiếu {total_shortfall} screenshot so với mục tiêu {total_target}. Xem từng video để biết lý do bị loại.")
        elif total_fallback:
            st.warning(f"Đã đủ mục tiêu {total_target} screenshot; {total_fallback} ảnh được lấy bằng fallback sau filter.")
        else:
            st.success(f"Đã đạt mục tiêu {total_target} screenshot sau filter.")

    st.caption(
        f"Tổng số lượt thử xử lý: {total_attempts} · retry tự động theo từng video · "
        f"video worker: {video_label} · extraction worker thực tế/video: {adaptive_label}."
    )

    st.markdown("#### Queue theo video")
    for report in reports:
        video_name = Path(str(report.get("video", "video không xác định"))).name
        if "error" in report:
            st.error(f"✕ {video_name} · thất bại · {report.get('error')}")
        else:
            shortfall = int(report.get("shortfall", 0) or 0)
            fallback = int(report.get("forced_fallback_saved", 0) or 0)
            suffix = f" · thiếu {shortfall}" if shortfall else (f" · fallback {fallback}" if fallback else "")
            state_label = "hoàn tất có fallback" if fallback else "hoàn tất"
            st.success(f"✓ {video_name} · {state_label} · lưu {int(report.get('saved', 0))} ảnh{suffix} · {int(report.get('attempts', 1))} lần thử")
            if report.get("shortfall_message"):
                st.caption(str(report["shortfall_message"]))

    download_col, report_col = st.columns([1, 1])
    with download_col:
        st.download_button(
            "⬇  Tải screenshot + report ZIP",
            data=zip_bytes,
            file_name="screenshots_filtered.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True,
            key="processing_zip_download",
        )
    with report_col:
        st.download_button(
            "Tải report JSON",
            data=json.dumps(reports, ensure_ascii=False, indent=2),
            file_name="report.json",
            mime="application/json",
            use_container_width=True,
            key="processing_report_download",
        )

    show_scene_timeline(reports, output_dir)
    _render_result_preview(output_dir)


def _render_result_preview(output_dir: Path) -> None:
    """Render preview grid of generated screenshots."""
    image_files = sorted(output_dir.rglob("*.jpg")) + sorted(output_dir.rglob("*.png")) + sorted(output_dir.rglob("*.webp"))
    if image_files:
        st.markdown(
            f'<div class="section-heading"><span>▦</span> Preview <small style="color:#8b95a7;font-family:DM Sans;font-size:.78rem;font-weight:500;">{len(image_files)} ảnh được tạo</small></div>',
            unsafe_allow_html=True,
        )
        preview_files = image_files[:24]
        columns = st.columns(4)
        for index, image_path in enumerate(preview_files):
            with columns[index % 4]:
                st.image(str(image_path), caption=image_path.name, use_container_width=True)
        if len(image_files) > len(preview_files):
            st.info(f"Chỉ hiển thị {len(preview_files)} ảnh đầu tiên; toàn bộ ảnh nằm trong file ZIP.")
    else:
        st.warning("Không có frame nào vượt qua các bộ lọc đã chọn.")
