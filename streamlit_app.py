from __future__ import annotations

import atexit
import contextlib
import copy
import io
import cv2
import numpy as np
from datetime import datetime

import html
import json
import math
import mimetypes
import multiprocessing as mp
import os
import re
import sys
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from core.config import FrameForgeConfig

import streamlit as st

mp.freeze_support()

from updater import initialize_yt_dlp
from app_config import load_output_dirs, save_output_dirs
from app_update import (
    get_update_channel,
    initialize_app_update,
    launch_rollback_installer,
    rollback_app_now,
    set_update_channel,
    update_app_now,
)

# Kiểm tra tối đa một lần mỗi 24 giờ; bản mới chỉ được kích hoạt từ lần chạy kế tiếp.
update_status = initialize_yt_dlp(
    auto_update=os.environ.get("FRAMEFORGE_AUTO_UPDATE", "1").lower() not in {"0", "false", "no", "off"}
)
app_update_status = initialize_app_update()

from core.pipeline import (
    InsufficientDiskSpace,
    ProcessingCancelled,
    cleanup_frameforge_cache,
    cleanup_frameforge_temp_dirs,
    current_process_rss_bytes,
    free_disk_bytes,
    CROP_RATIO_LABELS,
    CROP_RATIO_VALUES,
    ENCODE_PROFILE_LABELS,
    ensure_free_disk_space,
    processing_signature,
    recommend_workers,
    recommended_extract_workers,
    timestamp_label,
)
from core.resources import available_ram_gb
from core.utils import format_bytes
from ui.logic import (
    _pause_processing_job,
    _resume_processing_job,
    format_eta,
    parse_progress_units,
    progress_telemetry,
    build_preview_timestamps,
    normalize_output_dir,
    frameforge_user_data_root,
    personal_presets_path,
    job_history_path,
    read_json_list,
    make_zip,
    make_download_zip,
    append_job_history,
    _pause_processing_job,
    _resume_processing_job,
)
from ui.preview import (
    preview_video_duration,
    quick_scene_preview,
    preview_crop_overlay,
    preview_frame_at,
)
from ui.presets import (
    init_presets,
    current_personal_preset,
    save_personal_preset,
    apply_personal_preset,
    export_ui_config,
    import_ui_config,
)
from ui.desktop import (
    terminate_desktop_process_tree as _terminate_desktop_process_tree,
    finish_processing_job as _finish_processing_job,
    shutdown_processing_job as _shutdown_processing_job,
    desktop_session_watchdog as _desktop_session_watchdog,
)
from ui.queue_ui import ProcessingQueueAdapter as _ProcessingQueueAdapter
from ui.session import read_widgets
from ui.wizard import (
    build_args as _build_args,
    validate_ui_configuration as _validate_ui_configuration,
    wizard_summary as _wizard_summary,
)
from video_screenshot_advanced import process_videos
from timeline_utils import build_timeline_entries, filter_timeline_entries
from core.resources import InsufficientResources
from queue_per_video import classify_error, render_queue_per_video
from persistent_queue import PersistentQueueStore
from video_downloader import (
    QUALITY_FORMATS,
    DownloadFailure,
    download_public_videos,
    ffmpeg_health,
    is_supported_public_url,
    result_summary,
)


cleanup_frameforge_temp_dirs(older_than_seconds=24 * 60 * 60, max_total_bytes=2 * 1024**3)

WIZARD_STEPS = ("01 · Nguồn", "02 · Chọn frame", "03 · Chất lượng", "04 · Đầu ra")

PRESET_CONFIGS = {
    "Nhanh": {
        "mode_label": "Scene detection",
        "scene_threshold": 0.35,
        "min_scene_gap": 0.8,
        "flash_return_ratio": 0.55,
        "flash_brightness_threshold": 0.20,
        "scene_confirmations": 1,
        "analysis_width": 320,
        "analysis_fps": 4.0,
        "extract_worker_choice": "Auto (khuyến nghị)",
        "min_sharpness": 70.0,
        "duplicate_threshold": 6,
        "motion_blur_threshold": 0.35,
        "image_format": "jpg",
        "crop_ratio": "Không crop",
        "encode_profile": "Nhanh",
        "quality": 85,
        "width": 1280,
        "retries": 1,
        "retry_delay": 0.5,
        "disk_reserve_mb": 512,
        "use_scene_cache": True,
        "cross_run_duplicates": True,
    },
    "Cân bằng": {
        "mode_label": "Best frame per scene",
        "scene_threshold": 0.30,
        "min_scene_gap": 0.5,
        "flash_return_ratio": 0.55,
        "flash_brightness_threshold": 0.18,
        "scene_confirmations": 2,
        "analysis_width": 640,
        "analysis_fps": 8.0,
        "extract_worker_choice": "Auto (khuyến nghị)",
        "min_sharpness": 100.0,
        "duplicate_threshold": 6,
        "motion_blur_threshold": 0.30,
        "image_format": "jpg",
        "crop_ratio": "Không crop",
        "encode_profile": "Chất lượng cao",
        "quality": 95,
        "width": 0,
        "retries": 2,
        "retry_delay": 1.0,
        "disk_reserve_mb": 512,
        "use_scene_cache": True,
        "cross_run_duplicates": True,
    },
    "Chất lượng cao": {
        "mode_label": "Best frame per scene",
        "scene_threshold": 0.25,
        "min_scene_gap": 0.4,
        "flash_return_ratio": 0.50,
        "flash_brightness_threshold": 0.15,
        "scene_confirmations": 3,
        "analysis_width": 960,
        "analysis_fps": 12.0,
        "extract_worker_choice": "Auto (khuyến nghị)",
        "min_sharpness": 120.0,
        "duplicate_threshold": 4,
        "motion_blur_threshold": 0.25,
        "image_format": "jpg",
        "crop_ratio": "Không crop",
        "encode_profile": "Chất lượng cao",
        "quality": 98,
        "width": 1920,
        "retries": 2,
        "retry_delay": 1.0,
        "disk_reserve_mb": 1024,
        "use_scene_cache": True,
        "cross_run_duplicates": True,
    },
    "Video dọc / TikTok": {
        "mode_label": "Best frame per scene",
        "scene_threshold": 0.30,
        "min_scene_gap": 0.5,
        "flash_return_ratio": 0.55,
        "flash_brightness_threshold": 0.18,
        "scene_confirmations": 2,
        "analysis_width": 640,
        "analysis_fps": 8.0,
        "extract_worker_choice": "Auto (khuyến nghị)",
        "min_sharpness": 100.0,
        "duplicate_threshold": 6,
        "motion_blur_threshold": 0.30,
        "image_format": "jpg",
        "crop_ratio": "9:16",
        "encode_profile": "Nhanh",
        "quality": 92,
        "width": 1080,
        "retries": 2,
        "retry_delay": 1.0,
        "disk_reserve_mb": 512,
        "use_scene_cache": True,
        "cross_run_duplicates": True,
    },
}
init_presets(PRESET_CONFIGS)


def apply_preset(name: str) -> None:
    for key, value in PRESET_CONFIGS[name].items():
        st.session_state[key] = value
    st.session_state["preset_status"] = f"Đã áp dụng preset: {name}"


def apply_selected_preset() -> None:
    apply_preset(str(st.session_state.get("preset_choice", "Cân bằng")))


def validate_ui_configuration() -> dict[str, list[str]]:
    """Thin wrapper: reads widget values from session_state and delegates to ui.wizard."""
    widgets = read_widgets()
    source_count = len(widgets.get("uploaded_files") or []) + len(widgets.get("downloaded_paths") or [])
    screenshot_dir_value = str(st.session_state.get("screenshot_dir", "") or "").strip()
    worker_choice = widgets.get("worker_choice", "Auto (khuyến nghị)")
    workers_value = "auto" if worker_choice == "Auto (khuyến nghị)" else worker_choice
    return _validate_ui_configuration(
        widgets,
        source_count=source_count,
        screenshot_dir=screenshot_dir_value,
        workers_value=workers_value,
    )


def preview_scene_timeline(duration: float, estimated: list[float], actual: list[float]) -> None:
    """Hiển thị timeline nhẹ với phân biệt marker ước tính và marker scene thật."""
    safe_duration = max(float(duration or 0.0), 0.001)
    estimated_marks = "".join(
        f'<span title="Ước tính {value:.3f}s" style="left:{max(0,min(100,value/safe_duration*100)):.2f}%"></span>'
        for value in estimated
    )
    actual_marks = "".join(
        f'<b title="Scene thật {value:.3f}s" style="left:{max(0,min(100,value/safe_duration*100)):.2f}%"></b>'
        for value in actual
    )
    st.markdown(
        f'<div class="scene-timeline"><div class="track">{estimated_marks}{actual_marks}</div><div class="timeline-legend"><span>● Ước tính</span><strong>◆ Scene thật</strong><em>0s — {safe_duration:.1f}s</em></div></div>',
        unsafe_allow_html=True,
    )


def wizard_summary() -> dict[str, str]:
    """Thin wrapper: reads widget values from session_state and delegates to ui.wizard."""
    widgets = read_widgets()
    source_count = len(widgets.get("uploaded_files") or []) + len(widgets.get("downloaded_paths") or [])
    return _wizard_summary(widgets, source_count=source_count)


st.session_state.setdefault("preset_choice", "Cân bằng")
for _preset_key, _preset_value in PRESET_CONFIGS["Cân bằng"].items():
    st.session_state.setdefault(_preset_key, _preset_value)
st.session_state.setdefault("wizard_step", WIZARD_STEPS[0])

st.set_page_config(
    page_title="FrameForge · Video Screenshot",
    page_icon="🎞️",
    layout="wide",
    initial_sidebar_state="expanded",
)

_css_path = Path(__file__).resolve().parent / "ui" / "styles.css"
st.markdown(
    """
    <style>
    """ + (
        _css_path.read_text(encoding="utf-8") if _css_path.exists() else ""
    ) + """
    </style>
    """,
    unsafe_allow_html=True,
)


def choose_local_directory(title: str) -> str | None:
    """Mở native folder picker khi app chạy local trên Windows/macOS/Linux desktop."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            pass
        selected = filedialog.askdirectory(title=title, mustexist=False)
        root.destroy()
        return selected or None
    except Exception:
        return None


def choose_and_store_directory(directory_key: str, widget_key: str, title: str) -> None:
    """Folder picker callback; widget state may be changed safely inside callback."""
    selected = choose_local_directory(title)
    if selected:
        st.session_state[directory_key] = selected
        st.session_state[widget_key] = selected


def find_recoverable_queue_jobs(root: Path) -> list[dict[str, object]]:
    jobs: list[dict[str, object]] = []
    if not root.exists():
        return jobs
    for database in sorted(root.rglob(".frameforge_queue.sqlite3"), key=lambda path: path.stat().st_mtime, reverse=True):
        try:
            with PersistentQueueStore(database) as store:
                for info in store.list_recoverable_jobs():
                    items = store.snapshot(str(info["job_id"]))
                    existing = sum(Path(item.video_path).is_file() for item in items)
                    if existing:
                        jobs.append({"database": database, "info": info, "items": items, "existing": existing})
        except (OSError, ValueError, TypeError):
            continue
    return jobs[:10]


def show_scene_timeline(reports: list[dict[str, object]], output_dir: Path | None = None) -> None:
    rows = []
    for report in reports:
        video_name = Path(str(report.get("video", "video"))).name
        scene_times = report.get("scene_times", [])
        if not isinstance(scene_times, list) or not scene_times:
            scene_times = report.get("selected_times", [])
        if isinstance(scene_times, list):
            for scene_number, timestamp in enumerate(scene_times, start=1):
                rows.append(
                    {
                        "video": video_name,
                        "scene": scene_number,
                        "time_seconds": float(timestamp),
                    }
                )
    if not rows:
        st.info("Chưa có mốc scene để hiển thị.")
        return

    st.markdown('<div class="section-heading"><span>◈</span> Scene timeline</div>', unsafe_allow_html=True)
    all_selected_times = [
        float(timestamp)
        for report in reports
        for timestamp in (report.get("selected_times", []) if isinstance(report.get("selected_times", []), list) else [])
    ]
    max_time = max([float(row["time_seconds"]) for row in rows] + all_selected_times + [1.0])
    timeline_entries = build_timeline_entries(reports)
    video_options = ["Tất cả"] + sorted({str(entry["video"]) for entry in timeline_entries})
    filter_col, query_col, range_col, zoom_col = st.columns([1.1, 1.2, 1.8, 1.0])
    with filter_col:
        selected_video_filter = st.selectbox("Lọc video", video_options, key="timeline_video_filter")
    with query_col:
        scene_query = st.text_input("Lọc scene", placeholder="Ví dụ: scene 2", key="timeline_scene_query")
    with range_col:
        selected_range = st.slider(
            "Khoảng thời gian (giây)",
            min_value=0.0,
            max_value=float(max_time),
            value=(0.0, float(max_time)),
            step=0.001,
            format="%.3f s",
            key="timeline_time_filter",
        )
    with zoom_col:
        zoom_percent = st.slider("Zoom", 25, 100, 100, 5, format="%d%%", key="timeline_zoom")
    filtered_entries = filter_timeline_entries(
        timeline_entries,
        video_name=selected_video_filter,
        query=scene_query,
        min_seconds=selected_range[0],
        max_seconds=selected_range[1],
    )
    if not filtered_entries:
        st.info("Không có scene phù hợp với bộ lọc hiện tại.")
        return
    rows = filtered_entries
    range_start, range_end = float(selected_range[0]), float(selected_range[1])
    filter_span = max(range_end - range_start, 1e-3)
    visible_span = max(filter_span * zoom_percent / 100.0, min(filter_span, 1.0))
    visible_center = (range_start + range_end) / 2.0
    view_start = max(range_start, visible_center - visible_span / 2.0)
    view_end = min(range_end, view_start + visible_span)
    view_start = max(range_start, view_end - visible_span)
    timeline_rows = []
    for row in rows:
        video_label = html.escape(str(row["video"]))
        scene_number = int(row["scene"])
        timestamp = float(row["time_seconds"])
        position = min(100.0, max(0.0, (timestamp - view_start) / max(view_end - view_start, 1e-6) * 100.0))
        timeline_rows.append(
            f"<div class='timeline-row'>"
            f"<div class='timeline-name'>{video_label} · Scene {scene_number}</div>"
            f"<div class='timeline-track'><span class='timeline-dot' style='left:{position:.2f}%'></span></div>"
            f"<div class='timeline-time'>{timestamp:.3f}s</div>"
            f"</div>"
        )
    st.markdown(
        "<div class='timeline-card'>"
        "<div class='timeline-axis'><span>0s</span><span>Scene markers</span><span>"
        f"{view_end:.3f}s</span></div>"
        + "".join(timeline_rows)
        + "</div>",
        unsafe_allow_html=True,
    )
    table_rows = []
    for row in rows:
        table_rows.append(
            "<tr>"
            f"<td>{html.escape(str(row['video']))}</td>"
            f"<td>{int(row['scene'])}</td>"
            f"<td>{float(row['time_seconds']):.3f}s</td>"
            "</tr>"
        )
    st.markdown(
        "<div class='scene-table-wrap'><table class='scene-table'>"
        "<thead><tr><th>Video</th><th>Scene</th><th>Timestamp</th></tr></thead>"
        "<tbody>" + "".join(table_rows) + "</tbody></table></div>",
        unsafe_allow_html=True,
    )

    st.markdown("**Timeline tương tác**")
    interactive_options = [
        (
            f"{entry['video']} · Scene {int(entry['scene'])} · {float(entry['representative_seconds']):.3f}s",
            entry,
        )
        for entry in filtered_entries
    ]
    labels = [item[0] for item in interactive_options]
    selected_label = st.selectbox("Chọn scene/frame", labels, key="interactive_scene_choice")
    selected_entry = next(item[1] for item in interactive_options if item[0] == selected_label)
    selected_timestamp = float(selected_entry["representative_seconds"])
    adjusted_timestamp = st.slider(
        "Mốc preview (giây)",
        min_value=float(view_start),
        max_value=float(view_end),
        value=min(float(view_end), max(float(view_start), selected_timestamp)),
        step=0.001,
        format="%.3f s",
        key="interactive_scene_timestamp",
    )
    st.caption(
        f"Đã chọn **{selected_entry['video']} · Scene {int(selected_entry['scene'])}** tại "
        f"**{adjusted_timestamp:.3f}s**. Zoom {zoom_percent}% · mốc gần nhất được dùng để preview."
    )
    if output_dir is not None:
        nearest = float(selected_entry["representative_seconds"])
        pattern = f"*{timestamp_label(nearest)}.*"

        preview_candidates = sorted(output_dir.rglob(pattern))
        if preview_candidates:
            st.image(str(preview_candidates[0]), caption=f"Preview gần nhất · {nearest:.3f}s", use_container_width=True)
        else:
            st.info("Chưa tìm thấy file ảnh tương ứng trong output run này.")


# Header
current_channel = get_update_channel()
channel_choice = st.selectbox(
    "Kênh cập nhật",
    ["stable", "beta"],
    index=0 if current_channel == "stable" else 1,
    format_func=lambda value: "Stable — bản ổn định" if value == "stable" else "Beta — bản thử nghiệm",
    key="update_channel_choice",
)
if channel_choice != current_channel:
    set_update_channel(channel_choice)
    st.success(f"Đã chuyển sang kênh {channel_choice}. Kiểm tra lại feed ở lần tải giao diện kế tiếp.")
    st.rerun()

if update_status.updated:
    st.info(f"Đã tải bản yt-dlp {update_status.latest_version}; bản cập nhật sẽ được kích hoạt ở lần mở ứng dụng kế tiếp.")
elif update_status.message and "mới nhất" not in update_status.message and "tắt" not in update_status.message and update_status.checked:
    st.caption(f"yt-dlp updater: {update_status.message}")

if app_update_status.available:
    channel_label = "Beta" if app_update_status.channel == "beta" else "Stable"
    st.info(f"[{channel_label}] Có bản cập nhật FrameForge {app_update_status.latest_version}. {app_update_status.message}")
    if app_update_status.release_notes:
        with st.expander("Xem release notes", expanded=False):
            st.markdown(app_update_status.release_notes)
            if app_update_status.release_notes_url:
                st.markdown(f"[Mở release notes trên GitHub]({app_update_status.release_notes_url})")
    if st.button("Cập nhật ngay", type="primary", use_container_width=False):
        with st.spinner("Đang tải, xác minh SHA-256 và mở Setup..."):
            app_update_status = update_app_now(timeout=30.0)
        if app_update_status.downloaded and app_update_status.installer_path:
            st.success(app_update_status.message)
        else:
            st.error(app_update_status.message)

if app_update_status.rollback_available and app_update_status.rollback_version:
    with st.expander(f"Rollback về FrameForge {app_update_status.rollback_version}", expanded=False):
        st.caption("Chỉ dùng rollback khi bản hiện tại gặp lỗi. Installer rollback vẫn được kiểm tra HTTPS và SHA-256 trước khi mở.")
        if st.button("Tải bản rollback", key="download_rollback"):
            with st.spinner("Đang tải và xác minh installer rollback..."):
                rollback_status = rollback_app_now(timeout=30.0)
            if rollback_status.downloaded:
                st.success(rollback_status.message)
            else:
                st.error(rollback_status.message)
        if st.button("Mở installer rollback", key="launch_rollback"):
            if launch_rollback_installer():
                st.success("Đã mở installer rollback. Hãy hoàn tất cài đặt rồi khởi động lại FrameForge.")
            else:
                st.error("Chưa có installer rollback hợp lệ; hãy tải lại trước.")

st.markdown(
    """
    <section class="hero">
      <div>
        <div class="hero-kicker">Scene-aware video toolkit</div>
        <h1>FrameForge</h1>
        <p>Cắt screenshot từ video bằng pipeline đọc một lần — nhận diện phân cảnh, chọn frame sắc nét nhất, loại bỏ mờ và trùng lặp.</p>
      </div>
    </section>
    """,
    unsafe_allow_html=True,
)

# User-selected output directories, persisted in the per-user config file.
output_dirs = load_output_dirs()
if "download_dir" not in st.session_state:
    st.session_state["download_dir"] = output_dirs["download_dir"]
if "screenshot_dir" not in st.session_state:
    st.session_state["screenshot_dir"] = output_dirs["screenshot_dir"]
if "downloaded_paths" not in st.session_state:
    st.session_state["downloaded_paths"] = []

st.markdown('<div class="section-heading"><span>⌂</span> Nơi lưu file</div>', unsafe_allow_html=True)
st.markdown(
    '<p class="muted-note">Chọn thư mục ngay từ đầu. Video tải xuống sẽ lưu trực tiếp vào thư mục video; mỗi lần xử lý screenshot sẽ tạo một thư mục con riêng để không trộn với kết quả cũ.</p>',
    unsafe_allow_html=True,
)
video_path_col, screenshot_path_col = st.columns(2, gap="large")
with video_path_col:
    video_input_col, video_pick_col = st.columns([4.4, 1.1], vertical_alignment="bottom")
    with video_input_col:
        video_dir_text = st.text_input(
            "Thư mục lưu video",
            value=st.session_state["download_dir"],
            key="video_dir_text",
            help="Đường dẫn local trên máy đang chạy FrameForge.",
        )
    with video_pick_col:
        st.button(
            "Chọn…",
            key="choose_video_dir",
            use_container_width=True,
            help="Mở folder picker để chọn nơi lưu video tải xuống.",
            on_click=choose_and_store_directory,
            args=("download_dir", "video_dir_text", "Chọn thư mục lưu video"),
        )
    st.session_state["download_dir"] = video_dir_text
with screenshot_path_col:
    screenshot_input_col, screenshot_pick_col = st.columns([4.4, 1.1], vertical_alignment="bottom")
    with screenshot_input_col:
        screenshot_dir_text = st.text_input(
            "Thư mục gốc lưu screenshot",
            value=st.session_state["screenshot_dir"],
            key="screenshot_dir_text",
            help="Mỗi lần xử lý sẽ tạo một thư mục FrameForge_YYYYMMDD_HHMMSS bên trong.",
        )
    with screenshot_pick_col:
        st.button(
            "Chọn…",
            key="choose_screenshot_dir",
            use_container_width=True,
            help="Mở folder picker để chọn nơi lưu screenshot.",
            on_click=choose_and_store_directory,
            args=("screenshot_dir", "screenshot_dir_text", "Chọn thư mục gốc lưu screenshot"),
        )
    st.session_state["screenshot_dir"] = screenshot_dir_text

# Persist the most recent valid paths for the next app start.
try:
    save_output_dirs(
        normalize_output_dir(st.session_state["download_dir"], Path.home() / "Videos" / "FrameForge" / "videos"),
        normalize_output_dir(st.session_state["screenshot_dir"], Path.home() / "Videos" / "FrameForge" / "screenshots"),
    )
except OSError as exc:
    st.caption(f"Không thể ghi config thư mục: {exc}")

# Download public video queue
downloaded_paths = [
    Path(item) for item in st.session_state["downloaded_paths"] if Path(item).exists()
]
st.session_state["downloaded_paths"] = [str(item) for item in downloaded_paths]

st.markdown('<div class="section-heading"><span>⇩</span> Tải video công khai</div>', unsafe_allow_html=True)
st.markdown(
    '<p class="muted-note">Dán một hoặc nhiều URL công khai từ Facebook, TikTok hoặc Pinterest. Mỗi dòng là một video hoặc một playlist; chỉ tải nội dung bạn có quyền sử dụng.</p>',
    unsafe_allow_html=True,
)
download_health = ffmpeg_health()
if download_health["ready_for_merge"]:
    health_source = "nhúng trong bundle" if download_health.get("source") == "embedded" else "trong PATH"
    st.caption(f"✓ FFmpeg sẵn sàng ({health_source}) · {download_health.get('version') or 'version không rõ'}")
else:
    st.warning("Chưa tìm thấy FFmpeg nhúng hoặc trong PATH. Một số format video/audio riêng có thể không ghép được.")
with st.container(border=True):
    st.markdown('<div class="download-panel-title">Danh sách tải</div>', unsafe_allow_html=True)
    download_input_col, quality_col = st.columns([2.35, 1.0], gap="large")
    with download_input_col:
        download_urls_text = st.text_area(
            "URL video hoặc playlist",
            placeholder="Mỗi dòng một URL video hoặc playlist...",
            height=116,
            key="download_urls_text",
            help="Dán URL công khai; mỗi dòng là một video hoặc một playlist.",
        )
    with quality_col:
        download_quality = st.selectbox(
            "Chất lượng tải",
            list(QUALITY_FORMATS),
            index=0,
            key="download_quality",
        )
        st.caption("Nguồn công khai được hỗ trợ bởi yt-dlp.")

    limit_col, retry_col, action_col = st.columns([1.0, 1.0, 1.35], gap="medium")
    with limit_col:
        playlist_max_items = st.number_input(
            "Tối đa mỗi playlist",
            min_value=1,
            max_value=500,
            value=50,
            step=1,
            key="playlist_max_items",
            help="Giới hạn số video lấy từ mỗi playlist.",
        )
    with retry_col:
        download_retry_count = st.number_input(
            "Số lần retry",
            key="download_retry_count",
            min_value=0,
            max_value=5,
            value=2,
            step=1,
            help="Số lần thử lại mỗi URL khi mạng hoặc nguồn tạm thời lỗi.",
        )
    with action_col:
        st.markdown('<div class="download-action-spacer"></div>', unsafe_allow_html=True)
        download_clicked = st.button("⇩  Tải queue", key="download_public_queue", type="primary", use_container_width=True)

if download_clicked:
    download_urls = [line.strip() for line in download_urls_text.splitlines() if line.strip()]
    invalid_urls = [url for url in download_urls if not is_supported_public_url(url)]
    if not download_urls:
        st.warning("Hãy nhập ít nhất một URL.")
    elif invalid_urls:
        st.error("URL không được hỗ trợ hoặc không phải URL công khai:")
        st.code("\n".join(invalid_urls))
    else:
        health = ffmpeg_health()
        if not health["ready_for_merge"]:
            st.warning("Chưa tìm thấy FFmpeg. Video/audio tách riêng có thể không ghép được ở chất lượng cao nhất.")
        try:
            download_progress = st.progress(0.0, text="Đang chuẩn bị queue tải...")
            download_errors: list[DownloadFailure] = []

            def download_hook(data: dict[str, object]) -> None:
                state = str(data.get("status") or "downloading")
                if state == "retrying":
                    code = str(data.get("error_code") or "unknown")
                    next_attempt = int(data.get("next_attempt") or 0)
                    total_attempts = int(data.get("total_attempts") or 0)
                    delay = float(data.get("retry_delay") or 0.0)
                    download_progress.progress(
                        0.0,
                        text=f"retrying · {code} · lần {next_attempt}/{total_attempts} · chờ {delay:.1f}s",
                    )
                    return
                downloaded = int(data.get("downloaded_bytes") or 0)
                total = int(data.get("total_bytes") or data.get("total_bytes_estimate") or 0)
                fraction = downloaded / total if total > 0 else 0.0
                filename = Path(str(data.get("filename") or "video")).name
                if state == "finished":
                    fraction = 1.0
                download_progress.progress(
                    min(1.0, max(0.0, fraction)),
                    text=f"{state} · {filename} · {fraction:.0%}",
                )

            def download_error_hook(error: DownloadFailure) -> None:
                download_errors.append(error)

            with st.spinner(f"Đang tải queue gồm {len(download_urls)} URL..."):

                download_results = download_public_videos(
                    download_urls,
                    Path(st.session_state["download_dir"]),
                    download_quality,
                    max_playlist_items=int(playlist_max_items),
                    max_retries=int(download_retry_count),
                    retry_delay_seconds=1.0,
                    progress_hook=download_hook,
                    error_hook=download_error_hook,
                )
            download_progress.progress(1.0, text=f"Đã tải xong {len(download_results)} video")
            for result in download_results:
                if str(result.path) not in st.session_state["downloaded_paths"]:
                    st.session_state["downloaded_paths"].append(str(result.path))
            downloaded_paths = [Path(item) for item in st.session_state["downloaded_paths"]]
            if download_results:
                st.success(f"Đã tải {len(download_results)} video từ {len(download_urls)} URL.")
            if download_errors:
                st.warning(f"Có {len(download_errors)} URL không tải được; queue vẫn giữ các video thành công.")
                for error in download_errors[:10]:
                    st.error(f"[{error.code}] {error.label}\nURL: {error.url}\n{error.message}\nGợi ý: {error.suggestion}")
                if len(download_errors) > 10:
                    st.caption(f"... và {len(download_errors) - 10} lỗi khác trong queue.")
            for result in download_results[:10]:
                st.caption(f"✓ {result_summary(result)}")
            if len(download_results) > 10:
                st.caption(f"... và {len(download_results) - 10} video khác trong queue.")
            if download_results:
                st.download_button(
                    "Tải toàn bộ video queue (.zip)",
                    data=make_download_zip([result.path for result in download_results]),
                    file_name="frameforge_downloads.zip",
                    mime="application/zip",
                    key="downloaded_video_zip_button",
                )
        except DownloadFailure as exc:
            st.error(f"[{exc.code}] {exc.label}\nURL: {exc.url}\n{exc.message}\nGợi ý: {exc.suggestion}")
            st.caption(f"Đã thử {exc.attempts} lần; lỗi này được phân loại là không thể retry tự động.")
        except Exception as exc:
            st.error(f"Không thể hoàn tất queue: {exc}")
            st.caption("Ứng dụng vẫn giữ các file đã tải thành công trước khi xảy ra lỗi.")

# Sidebar controls
with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-brand">
          <span class="mark">✦</span><strong>FrameForge</strong>
          <p>Video screenshot studio<br>Scene-aware · Fast · Clean</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<div class="eyebrow">01 · Nguồn video</div>', unsafe_allow_html=True)
    uploaded_files = st.file_uploader(
        "Chọn một hoặc nhiều video",
        type=["mp4", "mov", "mkv", "avi", "webm", "m4v", "ts", "mts"],
        accept_multiple_files=True,
        key="uploaded_files",
        help="Có thể chọn nhiều video để xử lý trong cùng một lần.",
    )
    if uploaded_files:
        st.caption(f"✓ Đã chọn {len(uploaded_files)} video tải lên")
    if downloaded_paths:
        st.caption(f"✓ Có {len(downloaded_paths)} video đã tải từ URL")
    if not uploaded_files and not downloaded_paths:
        st.caption("Chưa có video nào được chọn")

    st.markdown('<div class="eyebrow">02 · Cách chọn frame</div>', unsafe_allow_html=True)
    st.selectbox(
        "Preset cấu hình",
        list(PRESET_CONFIGS),
        key="preset_choice",
        on_change=apply_selected_preset,
        help="Áp dụng nhanh nhóm thông số; bạn vẫn có thể tinh chỉnh từng trường sau đó.",
    )
    if st.session_state.get("preset_status"):
        st.caption(st.session_state.pop("preset_status"))
    mode_label = st.radio(
        "Chế độ xử lý",
        ["Best frame per scene", "Scene detection", "Mỗi N giây", "Đúng N frame"],
        index=0,
        key="mode_label",
        help="Best frame per scene giữ ảnh sắc nét nhất trong từng cảnh; Scene detection giữ frame đầu của từng cảnh.",
    )

    start = st.number_input("Bắt đầu từ giây", min_value=0.0, value=0.0, step=1.0, key="start")
    limit_end = st.checkbox("Giới hạn thời điểm kết thúc", key="limit_end")
    end = st.number_input(
        "Kết thúc ở giây",
        min_value=0.1,
        value=60.0,
        step=1.0,
        key="end",
        disabled=not limit_end,
    )

    scene_threshold = 0.30
    min_scene_gap = 0.5
    flash_return_ratio = 0.55
    flash_brightness_threshold = 0.18
    scene_confirmations = 2
    every = None
    count = None
    max_screenshots = st.number_input(
        "Số screenshot mỗi video",
        min_value=1,
        max_value=1000,
        value=20,
        step=1,
        key="max_screenshots",
        help=(
            "Số ảnh mục tiêu mỗi video. Khi bật chế độ ép đủ, FrameForge sẽ dùng fallback có kiểm soát "
            "nếu filter loại quá nhiều frame."
        ),
    )
    target_count_after_filter = st.checkbox(
        "Ép đủ số ảnh yêu cầu (fallback cuối)",
        key="target_count_after_filter",
        value=True,
        help=(
            "Áp dụng cho mọi mode. Filter vẫn chạy bình thường trước; nếu còn thiếu, hệ thống sẽ lưu "
            "candidate bị loại ít rủi ro nhất và ghi rõ số ảnh fallback trong report."
        ),
    )

    if mode_label in {"Best frame per scene", "Scene detection"}:
        with st.expander("Tinh chỉnh scene detection", expanded=True):
            scene_threshold = st.slider(
                "Độ nhạy thay đổi cảnh",
                0.05,
                0.95,
                step=0.05,
                key="scene_threshold",
                help="Thấp hơn sẽ nhạy hơn và có thể tạo nhiều scene hơn.",
            )
            min_scene_gap = st.number_input(
                "Khoảng cách tối thiểu giữa scene (giây)",
                min_value=0.1,
                step=0.1,
                key="min_scene_gap",
            )
            flash_return_ratio = st.slider(
                "Ngưỡng chống flash",
                0.10,
                0.95,
                step=0.05,
                key="flash_return_ratio",
                help="Thấp hơn giúp bỏ các thay đổi ngắn quay lại cảnh cũ.",
            )
            flash_brightness_threshold = st.slider(
                "Độ lệch sáng tối đa khi nhận diện flash",
                0.01,
                0.50,
                step=0.01,
                key="flash_brightness_threshold",
            )
            scene_confirmations = st.slider(
                "Số frame xác nhận thay đổi cảnh",
                1,
                5,
                key="scene_confirmations",
                help="Tăng lên để chống nhiễu/flash; giảm xuống 1 cho chuyển cảnh rất nhanh.",
            )
    elif mode_label == "Mỗi N giây":
        every = st.number_input(
            "Khoảng cách giữa các frame (giây)",
            min_value=0.05,
            value=5.0,
            step=0.5,
            key="every",
        )
    else:
        count = int(max_screenshots)

    st.markdown('<div class="eyebrow">03 · Chất lượng & tốc độ</div>', unsafe_allow_html=True)
    recommended_workers = recommend_workers(len(uploaded_files) if uploaded_files else None)
    worker_choice = st.selectbox(
        "Video xử lý song song",
        ["Auto (khuyến nghị)", 1, 2, 3, 4],
        index=0,
        key="worker_choice",
        help="Auto tự cân bằng theo CPU/RAM. Mỗi worker xử lý một video độc lập.",
    )
    workers = "auto" if worker_choice == "Auto (khuyến nghị)" else int(worker_choice)
    st.caption(f"Đề xuất hiện tại: **{recommended_workers} worker** theo cấu hình máy.")
    with st.expander("Hiệu năng phân tích", expanded=False):
        analysis_width = st.number_input(
            "Chiều rộng phân tích",
            min_value=160,
            max_value=1920,
            step=80,
            key="analysis_width",
            help="Frame được thu nhỏ trước khi đo scene, độ nét và trùng lặp.",
        )
        min_free_ram_gb = st.number_input(
            "RAM khả dụng tối thiểu (GB)",
            min_value=0.0,
            max_value=64.0,
            step=0.5,
            key="min_free_ram_gb",
            help="Tạm dừng/không bắt đầu job nếu RAM khả dụng thấp hơn ngưỡng; 0 để tắt.",
        )
        analysis_fps = st.number_input(
            "FPS phân tích scene",
            min_value=1.0,
            max_value=30.0,
            step=1.0,
            key="analysis_fps",
            help="Giảm FPS để tăng tốc; tăng FPS nếu cảnh thay đổi rất nhanh.",
        )
        extract_worker_choice = st.selectbox(
            "Process trích frame fixed/count",
            ["Auto (khuyến nghị)", 1, 2, 3, 4],
            index=0,
            key="extract_worker_choice",
            help="Chỉ áp dụng cho Mỗi N giây/Đúng N frame khi có từ 8 timestamp. Scene mode vẫn decode tuần tự để giữ cache scene chính xác.",
        )

    min_sharpness = st.number_input(
        "Ngưỡng độ nét tối thiểu",
        min_value=0.0,
        step=10.0,
        key="min_sharpness",
        help="Điểm đã chuẩn hóa về chiều rộng tham chiếu 640 px. Đặt 0 để tắt lọc mờ.",
    )
    duplicate_threshold = st.slider(
        "Ngưỡng trùng dHash",
        0,
        32,
        key="duplicate_threshold",
        help="Khoảng cách càng nhỏ thì frame càng giống. Đặt 0 để tắt lọc trùng.",
    )
    motion_blur_threshold = st.slider(
        "Ngưỡng motion blur",
        0.0,
        1.0,
        step=0.05,
        key="motion_blur_threshold",
        help="Điểm càng cao càng có nguy cơ nhòe chuyển động. Đặt 0 để tắt.",
    )

    st.markdown('<div class="eyebrow">04 · Đầu ra</div>', unsafe_allow_html=True)
    encode_profile = st.selectbox(
        "Profile encode",
        list(ENCODE_PROFILE_LABELS),
        key="encode_profile",
        help="Nhanh giảm chi phí encode; Chất lượng cao ưu tiên tối ưu kích thước/chất lượng file.",
    )
    image_format = st.selectbox(
        "Định dạng ảnh",
         ["jpg", "png", "webp"],
        key="image_format",

    )
    crop_ratio = st.selectbox(
        "Tỉ lệ crop screenshot",
        list(CROP_RATIO_LABELS),
        key="crop_ratio",
        help="Crop chính giữa, không kéo giãn hình. Chiều rộng đầu ra áp dụng sau khi crop.",
    )
    quality = st.slider(
        "Chất lượng JPG/WebP",
        1,
        100,
        key="quality",
        disabled=image_format == "png",
    )
    width = st.number_input(
        "Chiều rộng đầu ra (0 = giữ nguyên)",
        min_value=0,
        step=64,
        key="width",
    )
    overwrite = st.checkbox(
        "Ghi đè file đầu ra đã tồn tại",
        key="overwrite",
    )
    retry_count = st.number_input(
        "Số lần retry mỗi video",
        min_value=0,
        max_value=5,
        step=1,
        key="retries",
        help="Nếu một video lỗi tạm thời, FrameForge sẽ tự thử lại trước khi chuyển sang video kế tiếp.",
    )
    retry_delay = st.number_input(
        "Thời gian chờ retry (giây)",
        min_value=0.0,
        max_value=30.0,
        step=0.5,
        key="retry_delay",
    )
    disk_reserve_mb = st.number_input(
        "Vùng đệm dung lượng tối thiểu (MB)",
        min_value=0,
        max_value=8192,
        step=128,
        key="disk_reserve_mb",
        help="Không bắt đầu hoặc tiếp tục ghi khi dung lượng trống thấp hơn vùng đệm này.",
    )
    use_scene_cache = st.checkbox(
        "Dùng cache phân tích scene",
        key="use_scene_cache",
        help="Lần chạy sau sẽ seek tới các timestamp đã chọn thay vì phân tích lại toàn bộ video.",
    )
    cross_run_duplicates = st.checkbox(
        "Loại duplicate giữa các lần chạy",
        key="cross_run_duplicates",
        help="Dùng dHash index trong thư mục screenshot để tránh lưu lại frame gần giống đã xuất trước đó.",
    )


def build_args() -> FrameForgeConfig:
    """Thin wrapper: reads widget values from session_state and delegates to ui.wizard."""
    widgets = read_widgets()
    source_count = len(widgets.get("uploaded_files") or []) + len(widgets.get("downloaded_paths") or [])
    return _build_args(widgets, source_count=source_count)




def render_personal_config_panel() -> None:
    with st.expander("Preset cá nhân và cấu hình", expanded=False):
        saved = read_json_list(personal_presets_path())
        names = [str(item.get("name")) for item in saved if item.get("name")]
        if names:
            selected = st.selectbox("Preset cá nhân", names, key="personal_preset_choice")
            if st.button("Áp dụng preset cá nhân", key="apply_personal_preset"):
                apply_personal_preset(next(item for item in saved if item.get("name") == selected))
                st.success(f"Đã áp dụng preset: {selected}")
                st.rerun()
        preset_name = st.text_input("Tên preset mới", key="personal_preset_name", placeholder="Ví dụ: Reels sắc nét")
        if st.button("Lưu preset hiện tại", key="save_personal_preset"):
            save_personal_preset(preset_name)
            st.success("Đã lưu preset cá nhân.")
            st.rerun()
        st.download_button("Xuất cấu hình JSON", data=export_ui_config(), file_name="frameforge-config.json", mime="application/json", key="export_ui_config")
        imported = st.file_uploader("Nhập cấu hình JSON", type=["json"], key="import_ui_config")
        if imported is not None and st.session_state.get("last_imported_config") != imported.file_id:
            ok, message = import_ui_config(imported)
            st.session_state["last_imported_config"] = imported.file_id
            (st.success if ok else st.error)(message)
            if ok:
                st.rerun()


def render_job_history() -> None:
    history = list(reversed(read_json_list(job_history_path())))
    with st.expander(f"Lịch sử job ({len(history)})", expanded=False):
        if not history:
            st.caption("Chưa có job nào được lưu.")
            return
        st.dataframe(history[:20], use_container_width=True, hide_index=True)


def _start_processing_job(args: FrameForgeConfig, input_paths: list[Path], output_dir: Path, work_dir: Path) -> None:
    args.queue_db = Path(str(getattr(args, "queue_db", "") or output_dir / ".frameforge_queue.sqlite3"))
    cancel_event = threading.Event()
    pause_event = threading.Event()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="frameforge-ui")
    progress_state = {
        str(path): {
            "phase": "queued",
            "fraction": 0.0,
            "message": "Đang xếp hàng",
            "started_at": time.monotonic(),
            "units_done": 0,
            "units_total": 0,
            "rss_bytes": current_process_rss_bytes(),
        }
        for path in input_paths
    }
    completed = {"count": 0}

    def on_progress(video: Path, phase: str, fraction: float, message: str) -> None:
        key = str(video)
        state = progress_state.setdefault(
            key,
            {"started_at": time.monotonic(), "units_done": 0, "units_total": 0},
        )
        state.update({
            "phase": phase,
            "fraction": fraction,
            "message": message,
            "rss_bytes": current_process_rss_bytes(),
        })
        units = parse_progress_units(message)
        if units is not None:
            state["units_done"], state["units_total"] = units

    def on_complete(video: Path, report: dict[str, object]) -> None:
        completed["count"] += 1
        if "error" not in report:
            try:
                input_root = work_dir.resolve() / "input"
                resolved_video = video.resolve()
                if resolved_video.is_relative_to(input_root):
                    resolved_video.unlink(missing_ok=True)
            except OSError:
                pass
        state = progress_state.setdefault(str(video), {"started_at": time.monotonic()})
        state.update({
            "phase": "completed" if "error" not in report else "error",
            "fraction": 1.0,
            "message": f"Đã hoàn tất · lưu {report.get('saved', 0)} ảnh" if "error" not in report else str(report.get("error")),
            "rss_bytes": current_process_rss_bytes(),
            "attempts": int(report.get("attempts", 1) or 1),
            "saved": int(report.get("saved", 0) or 0),
        })
        if report.get("requested") is not None:
            state["units_done"] = int(report.get("requested", 0) or 0)
            state["units_total"] = int(report.get("requested", 0) or 0)

    future = executor.submit(
        process_videos,
        input_paths,
        output_dir,
        None,
        args,
        on_complete,
        on_progress,
        cancel_event,
        args.retries,
        args.retry_delay,
        pause_event,
    )
    job = {
        "status": "running",
        "future": future,
        "executor": executor,
        "cancel_event": cancel_event,
        "pause_event": pause_event,
        "progress": progress_state,
        "completed": completed,
        "input_paths": input_paths,
        "output_dir": output_dir,
        "work_dir": work_dir,
        "args": args,
        "reports": None,
        "error": None,
        "cleaned": False,
    }
    st.session_state["processing_job"] = job
    shutdown_state = st.session_state.get("_frameforge_shutdown_state")
    if isinstance(shutdown_state, dict):
        shutdown_state["job"] = job



def _retry_failed_processing(job: dict[str, object], positions: set[int] | None = None) -> bool:
    reports = job.get("reports") or []
    failed_paths: list[Path] = []
    for position, report in enumerate(reports):
        if positions is not None and position not in positions:
            continue
        if not isinstance(report, dict) or "error" not in report:
            continue
        candidate = Path(str(report.get("video", "")))
        if candidate.is_file():
            failed_paths.append(candidate)
    if not failed_paths:
        return False
    args = job.get("args")
    if args is None:
        return False
    retry_args = copy.copy(args)
    retry_args.resume = False
    _start_processing_job(
        retry_args,
        failed_paths,
        Path(str(job["output_dir"])),
        Path(str(job["work_dir"])),
    )
    return True


def render_resource_meter(args: object | None = None, output_root: Path | None = None) -> None:
    """Render system resource meter.  Uses read_widgets() for fallback values."""
    if output_root is None:
        output_root = normalize_output_dir(
            st.session_state.get("screenshot_dir", ""),
            Path.home() / "Videos" / "FrameForge" / "screenshots",
        )
    try:
        free_disk = free_disk_bytes(output_root)
    except OSError:
        free_disk = 0
    ram_available = available_ram_gb()
    _w = read_widgets()
    _fallback_ram = float(_w.get("min_free_ram_gb") or 0.0)
    _fallback_disk_mb = float(_w.get("disk_reserve_mb") or 500)
    ram_threshold = float(getattr(args, "min_free_ram_gb", _fallback_ram) or 0.0) if args is not None else _fallback_ram
    disk_threshold = float(getattr(args, "disk_reserve_bytes", _fallback_disk_mb * 1024 * 1024) or 0.0) if args is not None else _fallback_disk_mb * 1024 * 1024
    ram_label = "Không đọc được" if ram_available is None else f"{ram_available:.1f} GB"
    disk_label = format_bytes(free_disk)
    ram_ok = ram_available is None or ram_available >= ram_threshold
    disk_ok = free_disk >= disk_threshold
    state = "Ổn định" if ram_ok and disk_ok else "Cần chú ý"
    st.markdown(f"**Tài nguyên hệ thống** · `{state}`")
    meter_a, meter_b, meter_c = st.columns(3)
    with meter_a:
        st.metric("RAM khả dụng", ram_label, f"ngưỡng {ram_threshold:.1f} GB")
    with meter_b:
        st.metric("Disk còn trống", disk_label, f"reserve {format_bytes(disk_threshold)}")
    with meter_c:
        st.metric("RSS FrameForge", format_bytes(current_process_rss_bytes()))
    if not ram_ok:
        st.warning("RAM dưới ngưỡng admission; queue sẽ chờ tài nguyên trước khi cấp thêm video.")
    if not disk_ok:
        st.warning("Disk dưới vùng đệm an toàn; hãy chọn thư mục khác hoặc dọn dung lượng trước khi chạy.")


def render_queue_dashboard(snapshot: dict[str, object]) -> None:
    total = int(snapshot.get("total", 0) or 0)
    fraction = float(snapshot.get("fraction", 0.0) or 0.0)
    st.markdown("#### Queue dashboard")
    dashboard = st.columns(6)
    values = [
        ("Tổng video", total),
        ("Đang chạy", int(snapshot.get("active", 0) or 0)),
        ("Đang chờ", int(snapshot.get("queued", 0) or 0)),
        ("Hoàn tất", int(snapshot.get("completed", 0) or 0)),
        ("Lỗi", int(snapshot.get("failed", 0) or 0)),
        ("Đã hủy", int(snapshot.get("cancelled", 0) or 0)),
    ]
    for column, (label, value) in zip(dashboard, values):
        column.metric(label, value)
    st.progress(max(0.0, min(1.0, fraction)), text=f"Tiến độ tổng: {fraction:.0%}")


def error_actions(error: str, *, key_prefix: str) -> None:
    diagnostic = json.dumps({
        "app": "FrameForge",
        "version": "0.1.27",
        "error": str(error),
    }, ensure_ascii=False, indent=2)
    col_a, col_b = st.columns([1, 1])
    with col_a:
        st.download_button("Tải diagnostic", data=diagnostic, file_name="frameforge-diagnostic.json", mime="application/json", key=f"{key_prefix}_diagnostic", use_container_width=True)
    with col_b:
        st.caption("Diagnostic chỉ chứa version và lỗi rút gọn; không bao gồm cookie hoặc thông tin đăng nhập.")


def _start_desktop_session_watchdog() -> None:
    """Bật auto-shutdown chỉ cho launcher desktop, không ảnh hưởng `streamlit run`."""
    if os.environ.get("FRAMEFORGE_DESKTOP_LIFECYCLE", "0").lower() not in {"1", "true", "yes", "on"}:
        return
    if st.session_state.get("_frameforge_watchdog_started"):
        return
    try:
        from streamlit.runtime.scriptrunner_utils.script_run_context import get_script_run_ctx

        context = get_script_run_ctx(suppress_warning=True)
        session_id = context.session_id if context is not None else None
    except Exception:
        session_id = None
    if not session_id:
        return
    state: dict[str, object] = {"job": None, "shutdown_requested": False}
    st.session_state["_frameforge_watchdog_started"] = True
    st.session_state["_frameforge_shutdown_state"] = state

    def cleanup_at_exit() -> None:
        job = state.get("job")
        if isinstance(job, dict) and job.get("status") in {"running", "paused"}:
            _shutdown_processing_job(job)

    atexit.register(cleanup_at_exit)
    threading.Thread(
        target=_desktop_session_watchdog,
        args=(session_id, state),
        name="frameforge-session-watchdog",
        daemon=True,
    ).start()


def _poll_processing_job() -> dict[str, object] | None:
    job = st.session_state.get("processing_job")
    if not isinstance(job, dict) or job.get("status") not in {"running", "paused"}:
        return job if isinstance(job, dict) else None
    future = job.get("future")
    if future is None or not future.done():
        return job
    try:
        reports = future.result()
        output_dir = Path(str(job["output_dir"]))
        report_path = output_dir / "report.json"
        report_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
        job["reports"] = reports
        job["report_path"] = report_path
        job["status"] = "completed"
        job["message"] = "Đã xử lý xong queue."
        append_job_history(job)
    except ProcessingCancelled as exc:
        job["status"] = "cancelled"
        job["error"] = str(exc)
        job["message"] = "Đã hủy xử lý; checkpoint và các screenshot đã ghi trước đó vẫn được giữ lại để tiếp tục."
    except (InsufficientDiskSpace, InsufficientResources) as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        job["message"] = str(exc)
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        job["message"] = f"Không thể xử lý queue: {exc}"
    has_failures = any(isinstance(item, dict) and "error" in item for item in (job.get("reports") or []))
    _finish_processing_job(job, keep_work_dir=str(job.get("status")) == "cancelled" or has_failures)
    return job


_start_desktop_session_watchdog()


@st.fragment(run_every=1.0)
def _render_processing_job() -> None:
    job = _poll_processing_job()
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
                    _start_processing_job(
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
    failed_reports = [item for item in reports if isinstance(item, dict) and "error" in item]
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
            st.warning(
                f"Đã đủ mục tiêu {total_target} screenshot; {total_fallback} ảnh được lấy bằng fallback sau filter."
            )
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


# Main overview
st.markdown('<div class="section-heading" aria-label="Tổng quan FrameForge"><span>✦</span> Tổng quan</div>', unsafe_allow_html=True)
st.markdown('<div aria-live="polite">Dùng phím Tab để di chuyển giữa các control; Enter hoặc Space để kích hoạt nút đang được focus.</div>', unsafe_allow_html=True)
overview_a, overview_b, overview_c, overview_d = st.columns(4)
with overview_a:
    st.markdown(
        f'<div class="info-card"><div class="label">Video đã chọn</div><div class="value">{len(uploaded_files or []) + len(downloaded_paths)}</div><div class="sub">Upload + download</div></div>',
        unsafe_allow_html=True,
    )
with overview_b:
    short_mode = "Best / scene" if mode_label == "Best frame per scene" else mode_label
    st.markdown(
        f'<div class="info-card"><div class="label">Chế độ</div><div class="value">{short_mode}</div><div class="sub">Cách chọn frame</div></div>',
        unsafe_allow_html=True,
    )
with overview_c:
    st.markdown(
        f'<div class="info-card"><div class="label">Phân tích</div><div class="value">{int(analysis_width)} px</div><div class="sub">{float(analysis_fps):g} FPS · đọc một lần</div></div>',
        unsafe_allow_html=True,
    )
with overview_d:
    quality_label = "JPG/WebP" if image_format != "png" else "PNG"
    st.markdown(
        f'<div class="info-card"><div class="label">Đầu ra</div><div class="value">{quality_label}</div><div class="sub">Sharpness + dHash</div></div>',
        unsafe_allow_html=True,
    )

st.markdown('<div class="section-heading"><span>◎</span> Wizard cấu hình 4 bước</div>', unsafe_allow_html=True)
wizard_step = st.radio(
    "Bước cấu hình",
    list(WIZARD_STEPS),
    key="wizard_step",
    horizontal=True,
    label_visibility="collapsed",
)
summary = wizard_summary()
validation = validate_ui_configuration()
validation_errors = validation["errors"]
validation_warnings = validation["warnings"]
summary_cols = st.columns(4)
for summary_col, step_name in zip(summary_cols, WIZARD_STEPS):
    summary_key = step_name.split(" · ", 1)[1]
    summary_col.markdown(
        f'<div class="info-card"><div class="label">{html.escape(step_name)}</div><div class="value" style="font-size:1rem">{html.escape(summary[summary_key])}</div><div class="sub">{"Đang chỉnh" if wizard_step == step_name else "Đã cấu hình"}</div></div>',
        unsafe_allow_html=True,
    )
st.markdown(
    f'<div class="sticky-summary"><strong>Sẵn sàng xử lý</strong> · {html.escape(summary["Nguồn"])} · {html.escape(summary["Chọn frame"])} · {html.escape(summary["Đầu ra"])}<br><span class="status-pill">{"Cấu hình hợp lệ" if not validation_errors else f"Cần sửa {len(validation_errors)} mục"}</span><span class="status-pill">{"Có cảnh báo" if validation_warnings else "Không có cảnh báo"}</span></div>',
    unsafe_allow_html=True,
)
if validation_errors:
    st.error("Chưa thể bắt đầu xử lý. Hãy kiểm tra các mục sau: " + " · ".join(validation_errors))
if validation_warnings:
    st.warning("Lưu ý cấu hình: " + " · ".join(validation_warnings))
st.caption({
    "01 · Nguồn": "Chọn video upload hoặc video đã tải công khai.",
    "02 · Chọn frame": "Chọn scene, best frame, mỗi N giây hoặc đúng N frame.",
    "03 · Chất lượng": "Điều chỉnh phân tích, lọc mờ/trùng và worker.",
    "04 · Đầu ra": "Chọn crop ratio, format, chất lượng và encode profile.",
}[wizard_step])

if uploaded_files or downloaded_paths:

    st.markdown('<div class="section-heading"><span>▷</span> Preview workspace</div>', unsafe_allow_html=True)
    preview_entries = [(Path(item.name).name, "upload", item) for item in (uploaded_files or [])]
    preview_entries += [(path.name, "download", path) for path in downloaded_paths]
    preview_names = [entry[0] for entry in preview_entries]
    preview_name = st.selectbox("Chọn video để xem preview", preview_names, label_visibility="collapsed", key="preview_name")
    preview_entry = next(entry for entry in preview_entries if entry[0] == preview_name)
    preview_mime = mimetypes.guess_type(preview_name)[0] or "video/mp4"
    preview_duration = preview_video_duration(preview_entry[2])
    preview_timestamps = build_preview_timestamps(
        preview_duration, mode_label, float(start), float(end) if limit_end else None,
        float(every) if every is not None else None, int(count or max_screenshots), int(max_screenshots),
    )
    actual_scene_marks = st.session_state.get("quick_scene_preview_marks", [])
    with st.container(border=True):
        preview_col, crop_preview_col = st.columns([1.15, 1], gap="large")
        with preview_col:
            st.markdown("**Video gốc**")
            if preview_entry[1] == "upload":
                st.video(preview_entry[2].getvalue(), format=preview_mime, subtitles=None, width=560)
            else:
                st.video(str(preview_entry[2]), format=preview_mime, subtitles=None, width=560)
            st.caption("File nguồn chỉ được đọc để xem; không bị thay đổi.")
        with crop_preview_col:
            st.markdown(f"**Crop overlay · {crop_ratio}**")
            overlay = preview_crop_overlay(preview_entry[2], crop_ratio)
            if overlay is not None:
                st.image(overlay, use_container_width=True)
                st.caption("Vùng sáng có viền xanh là phần được giữ lại.")
            else:
                st.info("Không thể tạo frame preview cho codec này; engine vẫn có thể xử lý video.")
        st.markdown("**Phân bố screenshot dự kiến · timeline tương tác**")
        if preview_duration:
            preview_scene_timeline(float(preview_duration), preview_timestamps, actual_scene_marks)
        timeline_col, action_col = st.columns([2, 1])
        with timeline_col:
            max_preview_time = max(0.1, float(preview_duration or end or 1.0))
            selected_preview_time = st.slider("Mốc preview", 0.0, max_preview_time, min(max_preview_time / 2, max_preview_time), 0.1, key="preview_timestamp_slider")
        with action_col:
            st.markdown("**Scene detection**")
            if st.button("Phân tích nhanh scene thật", key="quick_scene_preview_button"):
                st.session_state["quick_scene_preview_marks"] = quick_scene_preview(
                    preview_entry[2], float(scene_threshold), float(start), float(end) if limit_end else None, float(analysis_fps)
                )
                st.rerun()
        selected_frame = preview_frame_at(preview_entry[2], selected_preview_time, crop_ratio)
        if selected_frame is not None:
            st.image(selected_frame, caption=f"Frame gallery · {selected_preview_time:.1f}s · crop {crop_ratio}", use_container_width=True)
        if preview_timestamps:
            st.caption(f"Gallery hiện tại: {len(preview_timestamps)} mốc dự kiến · chọn thanh trượt để xem frame tại timestamp bất kỳ.")
        if actual_scene_marks:
            st.success(f"Đã phân tích {len(actual_scene_marks)} scene marker thực tế.")
        else:
            st.info("Chưa có marker scene thật. Bấm ‘Phân tích scene thật’ để chạy phân tích nhanh.")

render_personal_config_panel()
render_job_history()

st.markdown('<div class="section-heading"><span>→</span> Quy trình hoạt động</div>', unsafe_allow_html=True)
step_a, step_b, step_c = st.columns(3)
with step_a:
    st.markdown(
        '<div class="step-card"><span class="step-num">1</span><strong>Đọc video một lần</strong><p>Phân tích tuần tự ở độ phân giải thấp để xử lý nhanh và tiết kiệm bộ nhớ.</p></div>',
        unsafe_allow_html=True,
    )
with step_b:
    st.markdown(
        '<div class="step-card"><span class="step-num">2</span><strong>Chọn frame tốt nhất</strong><p>Nhận diện scene, chấm điểm độ nét và loại các frame mờ hoặc quá giống nhau.</p></div>',
        unsafe_allow_html=True,
    )
with step_c:
    st.markdown(
        '<div class="step-card"><span class="step-num">3</span><strong>Tải kết quả</strong><p>Xem timeline, preview ảnh và tải toàn bộ screenshot cùng báo cáo JSON.</p></div>',
        unsafe_allow_html=True,
    )

active_job = st.session_state.get("processing_job")
job_running = isinstance(active_job, dict) and active_job.get("status") in {"running", "paused"}

if not job_running:
    recovery_root = normalize_output_dir(
        st.session_state.get("screenshot_dir", ""),
        Path.home() / "Videos" / "FrameForge" / "screenshots",
    )
    recoverable_jobs = find_recoverable_queue_jobs(recovery_root)
    if recoverable_jobs:
        st.markdown("#### Queue có thể khôi phục")
        recovery_labels = [
            f"{Path(str(item['database'])).parent.name} · {item['info'].get('state', 'interrupted')} · {item['existing']} file nguồn"
            for item in recoverable_jobs
        ]
        recovery_index = st.selectbox("Chọn queue cũ", range(len(recovery_labels)), format_func=lambda index: recovery_labels[index], key="recovery_queue_choice")
        selected_recovery = recoverable_jobs[int(recovery_index)]
        resume_args_preview = build_args()
        stored_signature = str(selected_recovery["info"].get("run_signature", ""))
        current_signature = processing_signature(resume_args_preview)
        signature_matches = bool(stored_signature and stored_signature == current_signature)
        st.caption("Các item đã hoàn tất sẽ được bỏ qua theo checkpoint; item interrupted sẽ tiếp tục bằng stable item ID.")
        if not signature_matches:
            st.warning("Cấu hình hiện tại khác cấu hình của queue cũ. Hãy chọn lại preset/tham số cũ hoặc tạo job mới; không tự động resume để tránh sai cache và output.")
        if st.button("Tiếp tục queue đã gián đoạn", key="resume_persistent_queue", type="primary", disabled=not signature_matches):
            recovery_info = selected_recovery["info"]
            recovery_items = selected_recovery["items"]
            resume_args = resume_args_preview
            resume_args.resume = True
            resume_args.queue_db = Path(str(selected_recovery["database"]))
            resume_args.queue_run_signature = str(recovery_info.get("run_signature", ""))
            recovery_output = Path(str(selected_recovery["database"])).parent
            resume_args.checkpoint_path = recovery_output / ".frameforge_checkpoint.json"
            resume_args.cache_root = recovery_root / ".frameforge_scene_cache"
            resume_args.duplicate_root = recovery_root / ".frameforge_duplicate_index"
            resume_paths = [Path(item.video_path) for item in recovery_items]
            _start_processing_job(resume_args, resume_paths, recovery_output, recovery_output)
            st.rerun()

st.markdown("<br>", unsafe_allow_html=True)
run_col, hint_col = st.columns([1, 2.2])
with run_col:
    run_clicked = st.button(
        "▶  Bắt đầu xử lý",
        type="primary",
        use_container_width=True,
        disabled=bool(validation_errors) or job_running,
    )
with hint_col:
    render_resource_meter(build_args() if (uploaded_files or downloaded_paths) else None)
    if not uploaded_files and not downloaded_paths:
        st.markdown(
            '<p class="muted-note">Upload video hoặc tải video công khai ở phía trên để kích hoạt xử lý. Gợi ý: bắt đầu với <b>Best frame per scene</b> và threshold scene 0.30.</p>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<p class="muted-note">Sẵn sàng xử lý <b>{len(uploaded_files or []) + len(downloaded_paths)} video</b> bằng chế độ <b>{mode_label}</b>. Kết quả sẽ được lọc theo sharpness, motion blur và dHash.</p>',
            unsafe_allow_html=True,
        )

if run_clicked:
    args = build_args()
    work_dir: Path | None = None
    if validation_errors:
        st.error("Không thể bắt đầu queue vì cấu hình chưa hợp lệ.")
    try:
        screenshot_root = normalize_output_dir(
            st.session_state.get("screenshot_dir", ""),
            Path.home() / "Videos" / "FrameForge" / "screenshots",
        )
        cleanup_frameforge_cache(screenshot_root / ".frameforge_scene_cache", max_total_bytes=1 * 1024**3)
        free_bytes = ensure_free_disk_space(
            screenshot_root,
            required_bytes=0,
            reserve_bytes=args.disk_reserve_bytes,
        )
        work_dir = Path(tempfile.mkdtemp(prefix="video_screenshot_web_"))
        input_dir = work_dir / "input"
        output_dir = screenshot_root / f"FrameForge_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        args.cache_root = screenshot_root / ".frameforge_scene_cache"
        args.duplicate_root = screenshot_root / ".frameforge_duplicate_index"
        args.checkpoint_path = output_dir / ".frameforge_checkpoint.json"
        args.resume = False
        input_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        input_paths = list(downloaded_paths)
        for uploaded in (uploaded_files or []):
            input_path = input_dir / Path(uploaded.name).name
            input_path.write_bytes(uploaded.getbuffer())
            input_paths.append(input_path)
        _start_processing_job(args, input_paths, output_dir, work_dir)
        st.info(f"Đã xếp {len(input_paths)} video vào queue · còn trống {format_bytes(free_bytes)} trước khi xử lý.")
        st.rerun()
    except InsufficientDiskSpace as exc:
        if work_dir is not None:
            shutil.rmtree(work_dir, ignore_errors=True)
        st.error(str(exc))
    except OSError as exc:
        if work_dir is not None:
            shutil.rmtree(work_dir, ignore_errors=True)
        st.error(f"Không thể tạo thư mục xử lý tạm: {exc}")

_render_processing_job()

st.markdown(
    '<div style="margin-top:2.4rem;padding-top:1rem;border-top:1px solid #e6eaf0;color:#8b95a7;font-size:.78rem;">FrameForge · Scene-aware video screenshot studio · Pipeline đọc một lần, phân tích nhanh và lọc chất lượng tự động.</div>',
    unsafe_allow_html=True,
)
