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
)
from core.resources import available_ram_gb
from core.utils import format_bytes
from ui.logic import (
    _pause_processing_job,
    _resume_processing_job,
    format_eta,
    progress_telemetry,
    build_preview_timestamps,
    normalize_output_dir,
    frameforge_user_data_root,
    make_zip,
    make_download_zip,
    _pause_processing_job,
    _resume_processing_job,
)
from ui.preview import (
    preview_video_duration,
    quick_scene_preview,
    preview_crop_overlay,
    preview_frame_at,
)
from ui.preview_section import render_preview_section
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
    shutdown_processing_job as _shutdown_processing_job,
    desktop_session_watchdog as _desktop_session_watchdog,
)
from ui.queue_ui import ProcessingQueueAdapter as _ProcessingQueueAdapter
from ui.processing import start_processing_job as _start_processing_job_core
from ui.processing import poll_processing_job as _poll_processing_job_core
from ui.session import read_widgets
from ui.wizard import (
    build_args as _build_args,
    validate_ui_configuration as _validate_ui_configuration,
    wizard_summary as _wizard_summary,
)
from video_screenshot_advanced import process_videos
from ui.timeline import show_scene_timeline, render_personal_config_panel, render_job_history
from ui.dashboard import render_resource_meter, render_queue_dashboard, error_actions
from ui.processing_view import render_processing_job
from core.resources import InsufficientResources
from queue_per_video import render_queue_per_video
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
        with st.spinner("Đang tải, xác minh SHA-256 và mở Setup…"):
            app_update_status = update_app_now(timeout=30.0)
        if app_update_status.downloaded and app_update_status.installer_path:
            st.success(app_update_status.message)
        else:
            st.error(app_update_status.message)

if app_update_status.rollback_available and app_update_status.rollback_version:
    with st.expander(f"Rollback về FrameForge {app_update_status.rollback_version}", expanded=False):
        st.caption("Chỉ dùng rollback khi bản hiện tại gặp lỗi. Installer rollback vẫn được kiểm tra HTTPS và SHA-256 trước khi mở.")
        if st.button("Tải bản rollback", key="download_rollback"):
            with st.spinner("Đang tải và xác minh installer rollback…"):
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
from ui.download_section import render_download_section
render_download_section()

# Sidebar controls
from ui.sidebar import build_sidebar_entries
from ui.widgets import render_entries

# Sidebar controls (declarative)
with st.sidebar:
    # Image search page link
    st.page_link("ui/image_search.py", label="🔍 Tìm ảnh theo địa điểm", icon="🔍")
    st.divider()

    render_entries(build_sidebar_entries(
        uploaded_files=st.session_state.get("uploaded_files"),
        downloaded_paths=downloaded_paths,
        mode_label=st.session_state.get("mode_label", "Best frame per scene"),
        limit_end=st.session_state.get("limit_end", False),
        image_format=st.session_state.get("image_format", "jpg"),
        max_screenshots=st.session_state.get("max_screenshots", 20),
        worker_count=len(uploaded_files) if uploaded_files else None,
        preset_options=list(PRESET_CONFIGS),
        on_change_preset=apply_selected_preset,
    ))

# Read widget values from session_state (populated by declarative sidebar)
uploaded_files = st.session_state.get("uploaded_files")
mode_label = st.session_state.get("mode_label", "Best frame per scene")
start = float(st.session_state.get("start", 0.0))
end = float(st.session_state.get("end", 60.0))
limit_end = bool(st.session_state.get("limit_end", False))
every = st.session_state.get("every")
max_screenshots = int(st.session_state.get("max_screenshots", 20))
scene_threshold = float(st.session_state.get("scene_threshold", 0.30))
analysis_fps = float(st.session_state.get("analysis_fps", 1.0))
analysis_width = int(st.session_state.get("analysis_width", 640))
min_free_ram_gb = float(st.session_state.get("min_free_ram_gb", 0.0))
crop_ratio = st.session_state.get("crop_ratio", "Không crop")
image_format = st.session_state.get("image_format", "jpg")
width = int(st.session_state.get("width", 0))
quality = int(st.session_state.get("quality", 95))

def build_args() -> FrameForgeConfig:
    """Thin wrapper: reads widget values from session_state and delegates to ui.wizard."""
    widgets = read_widgets()
    source_count = len(widgets.get("uploaded_files") or []) + len(widgets.get("downloaded_paths") or [])
    return _build_args(widgets, source_count=source_count)




def _start_processing_job(args: FrameForgeConfig, input_paths: list[Path], output_dir: Path, work_dir: Path) -> None:
    """Thin wrapper: delegates to ui.processing with session_state."""
    _start_processing_job_core(st.session_state, args, input_paths, output_dir, work_dir)



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

render_preview_section({
    "uploaded_files": uploaded_files,
    "downloaded_paths": downloaded_paths,
    "mode_label": mode_label,
    "start": start,
    "end": end,
    "limit_end": limit_end,
    "every": every,
    "count": count,
    "max_screenshots": max_screenshots,
    "crop_ratio": crop_ratio,
    "scene_threshold": scene_threshold,
    "analysis_fps": analysis_fps,
})

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

render_processing_job()

st.markdown(
    '<div style="margin-top:2.4rem;padding-top:1rem;border-top:1px solid #e6eaf0;color:#8b95a7;font-size:.78rem;">FrameForge · Scene-aware video screenshot studio · Pipeline đọc một lần, phân tích nhanh và lọc chất lượng tự động.</div>',
    unsafe_allow_html=True,
)
