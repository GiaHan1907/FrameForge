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
from ui.sidebar import build_sidebar_entries
from ui.widgets import render_entries

# Sidebar controls (declarative)
with st.sidebar:
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
    """Thin wrapper: delegates to ui.processing with session_state."""
    return _poll_processing_job_core(st.session_state)


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

_render_processing_job()

st.markdown(
    '<div style="margin-top:2.4rem;padding-top:1rem;border-top:1px solid #e6eaf0;color:#8b95a7;font-size:.78rem;">FrameForge · Scene-aware video screenshot studio · Pipeline đọc một lần, phân tích nhanh và lọc chất lượng tự động.</div>',
    unsafe_allow_html=True,
)
