from __future__ import annotations

import contextlib
import io
from datetime import datetime
import html
import json
import mimetypes
import multiprocessing as mp
import os
import sys
import shutil
import tempfile
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

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

from video_screenshot_advanced import (
    InsufficientDiskSpace,
    ProcessingCancelled,
    cleanup_frameforge_temp_dirs,
    ensure_free_disk_space,
    format_bytes,
    process_videos,
    recommend_workers,
    recommended_extract_workers,
    timestamp_label,
)
from timeline_utils import build_timeline_entries, filter_timeline_entries
from video_downloader import (
    QUALITY_FORMATS,
    download_public_videos,
    ffmpeg_health,
    is_supported_public_url,
    result_summary,
)


cleanup_frameforge_temp_dirs(older_than_seconds=24 * 60 * 60)

st.set_page_config(
    page_title="FrameForge · Video Screenshot",
    page_icon="🎞️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');

    :root {
        --ink: #172033;
        --muted: #667085;
        --line: #e6eaf0;
        --surface: #ffffff;
        --canvas: #f5f7fb;
        --blue: #3867f2;
        --violet: #7447e8;
        --green: #159570;
    }

    html, body, [class*="css"] {
        font-family: 'DM Sans', sans-serif;
    }

    [data-testid="stAppViewContainer"] {
        background: var(--canvas);
    }

    [data-testid="stHeader"] {
        background: transparent;
    }

    [data-testid="stSidebar"] {
        background: #111827;
        border-right: 1px solid #202a3b;
    }

    [data-testid="stSidebar"] * {
        color: #e8edf5;
    }

    [data-testid="stSidebar"] .stCaption,
    [data-testid="stSidebar"] small {
        color: #9aa8bd !important;
    }

    [data-testid="stSidebar"] hr {
        border-color: #2a3548;
    }

    [data-testid="stSidebar"] [data-testid="stExpander"] {
        background: #172235;
        border: 1px solid #26344a;
        border-radius: 12px;
    }

    [data-testid="stSidebar"] input,
    [data-testid="stSidebar"] textarea,
    [data-testid="stSidebar"] [data-baseweb="select"] > div {
        background: #1b2940;
        border-color: #34445d;
        color: #ffffff;
    }

    .block-container {
        max-width: 1440px;
        padding-top: 2.2rem;
        padding-bottom: 3rem;
    }

    h1, h2, h3 {
        font-family: 'Space Grotesk', sans-serif !important;
        color: var(--ink);
        letter-spacing: -0.03em;
    }

    .hero {
        position: relative;
        overflow: hidden;
        padding: 2.2rem 2.4rem;
        border-radius: 24px;
        color: white;
        background: linear-gradient(120deg, #233b90 0%, #3867f2 48%, #7547e9 100%);
        box-shadow: 0 18px 40px rgba(45, 72, 170, 0.22);
        margin-bottom: 1.35rem;
    }

    .hero::after {
        content: '';
        position: absolute;
        width: 280px;
        height: 280px;
        top: -135px;
        right: 6%;
        border: 1px solid rgba(255,255,255,.22);
        border-radius: 50%;
        box-shadow: 0 0 0 26px rgba(255,255,255,.06), 0 0 0 52px rgba(255,255,255,.04);
    }

    .hero-kicker {
        position: relative;
        z-index: 1;
        display: inline-flex;
        align-items: center;
        gap: .45rem;
        padding: .32rem .7rem;
        border-radius: 999px;
        color: #dfe8ff;
        background: rgba(255,255,255,.13);
        border: 1px solid rgba(255,255,255,.2);
        font-size: .77rem;
        font-weight: 700;
        letter-spacing: .1em;
        text-transform: uppercase;
    }

    .hero h1 {
        position: relative;
        z-index: 1;
        margin: .85rem 0 .45rem;
        color: white;
        font-size: clamp(2rem, 4vw, 3.25rem);
        line-height: 1.04;
    }

    .hero p {
        position: relative;
        z-index: 1;
        max-width: 680px;
        margin: 0;
        color: #e7edff;
        font-size: 1.05rem;
        line-height: 1.6;
    }

    .sidebar-brand {
        padding: .7rem .2rem 1.2rem;
    }

    .sidebar-brand .mark {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 38px;
        height: 38px;
        margin-right: .55rem;
        border-radius: 12px;
        color: white;
        background: linear-gradient(135deg, #4b7bff, #9a64ff);
        font-size: 1.3rem;
        vertical-align: middle;
    }

    .sidebar-brand strong {
        color: white;
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1.18rem;
        vertical-align: middle;
    }

    .sidebar-brand p {
        margin: .65rem 0 0;
        color: #98a7bd;
        font-size: .82rem;
        line-height: 1.5;
    }

    .eyebrow {
        margin: 1.4rem 0 .55rem;
        color: #748097;
        font-size: .72rem;
        font-weight: 700;
        letter-spacing: .12em;
        text-transform: uppercase;
    }

    .section-heading {
        display: flex;
        align-items: center;
        gap: .55rem;
        margin: 1.2rem 0 .72rem;
        color: var(--ink);
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1.15rem;
        font-weight: 700;
    }

    .section-heading span {
        display: inline-flex;
        width: 26px;
        height: 26px;
        align-items: center;
        justify-content: center;
        border-radius: 8px;
        color: #315bd9;
        background: #e9efff;
        font-size: .85rem;
    }

    .info-card {
        height: 100%;
        padding: 1rem 1.05rem;
        border: 1px solid var(--line);
        border-radius: 16px;
        background: var(--surface);
        box-shadow: 0 5px 16px rgba(29, 42, 68, .04);
    }

    .info-card .label {
        color: var(--muted);
        font-size: .78rem;
        font-weight: 600;
    }

    .info-card .value {
        margin-top: .28rem;
        color: var(--ink);
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1.15rem;
        font-weight: 700;
    }

    .info-card .sub {
        margin-top: .2rem;
        color: #8b95a7;
        font-size: .72rem;
    }

    .step-card {
        min-height: 126px;
        padding: 1.05rem;
        border: 1px solid var(--line);
        border-radius: 16px;
        background: white;
    }

    .step-num {
        display: inline-flex;
        width: 27px;
        height: 27px;
        align-items: center;
        justify-content: center;
        border-radius: 9px;
        color: white;
        background: linear-gradient(135deg, var(--blue), var(--violet));
        font-size: .8rem;
        font-weight: 700;
    }

    .step-card strong {
        display: block;
        margin-top: .7rem;
        color: var(--ink);
        font-family: 'Space Grotesk', sans-serif;
        font-size: .95rem;
    }

    .step-card p {
        margin: .28rem 0 0;
        color: var(--muted);
        font-size: .78rem;
        line-height: 1.45;
    }

    div[data-testid="stMetric"] {
        padding: 1rem 1.1rem;
        border: 1px solid var(--line);
        border-radius: 16px;
        background: white;
        box-shadow: 0 5px 16px rgba(29, 42, 68, .04);
    }

    div[data-testid="stMetricLabel"] {
        color: var(--muted);
    }

    div[data-testid="stMetricValue"] {
        color: var(--ink);
        font-family: 'Space Grotesk', sans-serif;
    }

    .stButton > button[kind="primary"] {
        min-height: 3rem;
        border: 0;
        border-radius: 12px;
        background: linear-gradient(110deg, #3867f2, #7547e9);
        box-shadow: 0 10px 20px rgba(64, 88, 220, .2);
        font-weight: 700;
    }

    .stButton > button[kind="primary"]:hover {
        border: 0;
        background: linear-gradient(110deg, #2d59df, #663bd4);
    }

    [data-testid="stFileUploader"] {
        border-radius: 14px;
    }

    [data-testid="stFileUploaderDropzone"] {
        border: 1px dashed #516483;
        background: #172235;
    }

    .result-banner {
        padding: 1rem 1.15rem;
        border: 1px solid #bce9d8;
        border-radius: 14px;
        color: #12694f;
        background: #effbf6;
        font-weight: 600;
    }

    .muted-note {
        color: var(--muted);
        font-size: .84rem;
        line-height: 1.55;
    }

    .timeline-card {
        padding: 1rem 1.1rem;
        border: 1px solid var(--line);
        border-radius: 16px;
        background: #ffffff;
        box-shadow: 0 8px 24px rgba(23, 32, 51, .05);
    }

    .timeline-axis,
    .timeline-row {
        display: grid;
        grid-template-columns: minmax(170px, 1.1fr) minmax(180px, 3fr) 80px;
        align-items: center;
        gap: .75rem;
    }

    .timeline-axis {
        margin-bottom: .7rem;
        color: var(--muted);
        font-size: .72rem;
        font-weight: 700;
        letter-spacing: .04em;
        text-transform: uppercase;
    }

    .timeline-axis span:nth-child(2) { text-align: center; }
    .timeline-axis span:last-child,
    .timeline-time { text-align: right; }

    .timeline-row {
        padding: .5rem 0;
        border-top: 1px solid #f0f2f6;
    }

    .timeline-name,
    .timeline-time {
        color: var(--ink);
        font-size: .82rem;
    }

    .timeline-time { color: var(--muted); font-variant-numeric: tabular-nums; }

    .timeline-track {
        position: relative;
        height: 8px;
        border-radius: 999px;
        background: linear-gradient(90deg, #e9edff, #f0eaff);
    }

    .timeline-dot {
        position: absolute;
        top: 50%;
        width: 14px;
        height: 14px;
        border: 3px solid #ffffff;
        border-radius: 50%;
        background: linear-gradient(135deg, var(--blue), var(--violet));
        box-shadow: 0 2px 8px rgba(56, 103, 242, .35);
        transform: translate(-50%, -50%);
    }

    .scene-table-wrap { overflow-x: auto; margin-top: .8rem; }
    .scene-table {
        width: 100%;
        border-collapse: collapse;
        overflow: hidden;
        border: 1px solid var(--line);
        border-radius: 12px;
        background: #ffffff;
        color: var(--ink);
        font-size: .82rem;
    }
    .scene-table th,
    .scene-table td { padding: .55rem .7rem; border-bottom: 1px solid #f0f2f6; text-align: left; }
    .scene-table th { color: var(--muted); background: #fafbff; font-size: .72rem; letter-spacing: .04em; text-transform: uppercase; }
    .scene-table tr:last-child td { border-bottom: 0; }
    .scene-table td:nth-child(2),
    .scene-table td:nth-child(3) { font-variant-numeric: tabular-nums; white-space: nowrap; }

    /* Compact, centered video preview. Streamlit's player is fluid by default. */
    div[data-testid="stVideo"] {
        max-width: 720px;
        margin: .35rem auto 0;
        padding: .55rem;
        border: 1px solid #dfe5f0;
        border-radius: 16px;
        background: #111827;
        box-shadow: 0 8px 24px rgba(23, 32, 51, .10);
    }
    div[data-testid="stVideo"] video {
        display: block;
        width: 100% !important;
        max-height: 420px !important;
        border-radius: 10px;
        background: #0b1220;
        object-fit: contain;
    }
    .preview-note {
        padding: .9rem 1rem;
        border: 1px solid var(--line);
        border-radius: 14px;
        color: var(--muted);
        background: #ffffff;
        font-size: .82rem;
        line-height: 1.55;
    }
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


def normalize_output_dir(value: str, fallback: Path) -> Path:
    raw = (value or "").strip()
    path = Path(os.path.expandvars(os.path.expanduser(raw))) if raw else fallback
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def make_zip(directory: Path, report_path: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path != report_path:
                archive.write(path, path.relative_to(directory))
        archive.write(report_path, report_path.name)
    return buffer.getvalue()


def make_download_zip(paths: list[Path]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            if path.exists() and path.is_file():
                archive.write(path, path.name)
    return buffer.getvalue()


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
        pattern = f"*_{timestamp_label(nearest)}.*"
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
      <div class="hero-kicker">● Intelligent video toolkit</div>
      <h1>FrameForge</h1>
      <p>Cắt screenshot đẹp và chính xác hơn từ video — tự nhận diện phân cảnh, chọn frame sắc nét nhất và loại bỏ ảnh mờ hoặc trùng lặp.</p>
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
        if st.button("Chọn…", key="choose_video_dir", use_container_width=True, help="Mở folder picker để chọn nơi lưu video tải xuống."):
            selected = choose_local_directory("Chọn thư mục lưu video")
            if selected:
                st.session_state["download_dir"] = selected
                st.session_state["video_dir_text"] = selected
                st.rerun()
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
        if st.button("Chọn…", key="choose_screenshot_dir", use_container_width=True, help="Mở folder picker để chọn nơi lưu screenshot."):
            selected = choose_local_directory("Chọn thư mục gốc lưu screenshot")
            if selected:
                st.session_state["screenshot_dir"] = selected
                st.session_state["screenshot_dir_text"] = selected
                st.rerun()
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
download_col, quality_col, limit_col, retry_col, action_col = st.columns([2.1, 1.05, 0.75, 0.7, 0.9])
with download_col:
    download_urls_text = st.text_area(
        "Queue URL",
        placeholder="Mỗi dòng một URL video hoặc playlist...",
        height=76,
        label_visibility="collapsed",
    )
with quality_col:
    download_quality = st.selectbox(
        "Chất lượng",
        list(QUALITY_FORMATS),
        index=0,
        label_visibility="collapsed",
    )
with limit_col:
    playlist_max_items = st.number_input(
        "Tối đa mỗi playlist",
        min_value=1,
        max_value=500,
        value=50,
        step=1,
        help="Giới hạn số video lấy từ mỗi playlist.",
    )
with retry_col:
    download_retry_count = st.number_input(
        "Retry tải",
        min_value=0,
        max_value=5,
        value=2,
        step=1,
        help="Số lần thử lại mỗi URL khi mạng hoặc nguồn tạm thời lỗi.",
    )
with action_col:
    download_clicked = st.button("⇩ Tải queue", use_container_width=True)

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

            def download_hook(data: dict[str, object]) -> None:
                downloaded = int(data.get("downloaded_bytes") or 0)
                total = int(data.get("total_bytes") or data.get("total_bytes_estimate") or 0)
                fraction = downloaded / total if total > 0 else 0.0
                filename = Path(str(data.get("filename") or "video")).name
                state = str(data.get("status") or "downloading")
                if state == "finished":
                    fraction = 1.0
                download_progress.progress(
                    min(1.0, max(0.0, fraction)),
                    text=f"{state} · {filename} · {fraction:.0%}",
                )

            with st.spinner(f"Đang tải queue gồm {len(download_urls)} URL..."):
                download_results = download_public_videos(
                    download_urls,
                    Path(st.session_state["download_dir"]),
                    download_quality,
                    max_playlist_items=int(playlist_max_items),
                    max_retries=int(download_retry_count),
                    retry_delay_seconds=1.0,
                    progress_hook=download_hook,
                )
            download_progress.progress(1.0, text=f"Đã tải xong {len(download_results)} video")
            for result in download_results:
                if str(result.path) not in st.session_state["downloaded_paths"]:
                    st.session_state["downloaded_paths"].append(str(result.path))
            downloaded_paths = [Path(item) for item in st.session_state["downloaded_paths"]]
            st.success(f"Đã tải {len(download_results)} video từ {len(download_urls)} URL.")
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
        help="Có thể chọn nhiều video để xử lý trong cùng một lần.",
    )
    if uploaded_files:
        st.caption(f"✓ Đã chọn {len(uploaded_files)} video tải lên")
    if downloaded_paths:
        st.caption(f"✓ Có {len(downloaded_paths)} video đã tải từ URL")
    if not uploaded_files and not downloaded_paths:
        st.caption("Chưa có video nào được chọn")

    st.markdown('<div class="eyebrow">02 · Cách chọn frame</div>', unsafe_allow_html=True)
    mode_label = st.radio(
        "Chế độ xử lý",
        ["Best frame per scene", "Scene detection", "Mỗi N giây", "Đúng N frame"],
        index=0,
        help="Best frame per scene giữ ảnh sắc nét nhất trong từng cảnh; Scene detection giữ frame đầu của từng cảnh.",
    )

    start = st.number_input("Bắt đầu từ giây", min_value=0.0, value=0.0, step=1.0)
    limit_end = st.checkbox("Giới hạn thời điểm kết thúc")
    end = st.number_input(
        "Kết thúc ở giây",
        min_value=0.1,
        value=60.0,
        step=1.0,
        disabled=not limit_end,
    )

    scene_threshold = 0.30
    min_scene_gap = 0.5
    flash_return_ratio = 0.55
    flash_brightness_threshold = 0.18
    scene_confirmations = 2
    every = None
    count = None

    if mode_label in {"Best frame per scene", "Scene detection"}:
        with st.expander("Tinh chỉnh scene detection", expanded=True):
            scene_threshold = st.slider(
                "Độ nhạy thay đổi cảnh",
                0.05,
                0.95,
                0.30,
                0.05,
                help="Thấp hơn sẽ nhạy hơn và có thể tạo nhiều scene hơn.",
            )
            min_scene_gap = st.number_input(
                "Khoảng cách tối thiểu giữa scene (giây)",
                min_value=0.1,
                value=0.5,
                step=0.1,
            )
            flash_return_ratio = st.slider(
                "Ngưỡng chống flash",
                0.10,
                0.95,
                0.55,
                0.05,
                help="Thấp hơn giúp bỏ các thay đổi ngắn quay lại cảnh cũ.",
            )
            flash_brightness_threshold = st.slider(
                "Độ lệch sáng tối đa khi nhận diện flash",
                0.01,
                0.50,
                0.18,
                0.01,
            )
            scene_confirmations = st.slider(
                "Số frame xác nhận thay đổi cảnh",
                1,
                5,
                2,
                help="Tăng lên để chống nhiễu/flash; giảm xuống 1 cho chuyển cảnh rất nhanh.",
            )
    elif mode_label == "Mỗi N giây":
        every = st.number_input(
            "Khoảng cách giữa các frame (giây)",
            min_value=0.05,
            value=5.0,
            step=0.5,
        )
    else:
        count = st.number_input("Số frame cần lấy", min_value=1, value=20, step=1)

    st.markdown('<div class="eyebrow">03 · Chất lượng & tốc độ</div>', unsafe_allow_html=True)
    recommended_workers = recommend_workers(len(uploaded_files) if uploaded_files else None)
    worker_choice = st.selectbox(
        "Video xử lý song song",
        ["Auto (khuyến nghị)", 1, 2, 3, 4],
        index=0,
        help="Auto tự cân bằng theo CPU/RAM. Mỗi worker xử lý một video độc lập.",
    )
    workers = "auto" if worker_choice == "Auto (khuyến nghị)" else int(worker_choice)
    st.caption(f"Đề xuất hiện tại: **{recommended_workers} worker** theo cấu hình máy.")
    with st.expander("Hiệu năng phân tích", expanded=False):
        analysis_width = st.number_input(
            "Chiều rộng phân tích",
            min_value=160,
            max_value=1920,
            value=640,
            step=80,
            help="Frame được thu nhỏ trước khi đo scene, độ nét và trùng lặp.",
        )
        analysis_fps = st.number_input(
            "FPS phân tích scene",
            min_value=1.0,
            max_value=30.0,
            value=8.0,
            step=1.0,
            help="Giảm FPS để tăng tốc; tăng FPS nếu cảnh thay đổi rất nhanh.",
        )
        extract_worker_choice = st.selectbox(
            "Process trích frame fixed/count",
            ["Auto (khuyến nghị)", 1, 2, 3, 4],
            index=0,
            help="Chỉ áp dụng cho Mỗi N giây/Đúng N frame khi có từ 8 timestamp. Scene mode vẫn decode tuần tự để giữ cache scene chính xác.",
        )

    min_sharpness = st.number_input(
        "Ngưỡng độ nét tối thiểu",
        min_value=0.0,
        value=100.0,
        step=10.0,
        help="Điểm đã chuẩn hóa về chiều rộng tham chiếu 640 px. Đặt 0 để tắt lọc mờ.",
    )
    duplicate_threshold = st.slider(
        "Ngưỡng trùng dHash",
        0,
        32,
        6,
        help="Khoảng cách càng nhỏ thì frame càng giống. Đặt 0 để tắt lọc trùng.",
    )
    motion_blur_threshold = st.slider(
        "Ngưỡng motion blur",
        0.0,
        1.0,
        0.30,
        0.05,
        help="Điểm càng cao càng có nguy cơ nhòe chuyển động. Đặt 0 để tắt.",
    )

    st.markdown('<div class="eyebrow">04 · Đầu ra</div>', unsafe_allow_html=True)
    image_format = st.selectbox("Định dạng ảnh", ["jpg", "png", "webp"], index=0)
    quality = st.slider(
        "Chất lượng JPG/WebP",
        1,
        100,
        95,
        disabled=image_format == "png",
    )
    width = st.number_input(
        "Chiều rộng đầu ra (0 = giữ nguyên)",
        min_value=0,
        value=0,
        step=64,
    )
    overwrite = st.checkbox("Ghi đè file đầu ra đã tồn tại", value=True)
    retry_count = st.number_input(
        "Số lần retry mỗi video",
        min_value=0,
        max_value=5,
        value=2,
        step=1,
        help="Nếu một video lỗi tạm thời, FrameForge sẽ tự thử lại trước khi chuyển sang video kế tiếp.",
    )
    retry_delay = st.number_input(
        "Thời gian chờ retry (giây)",
        min_value=0.0,
        max_value=30.0,
        value=1.0,
        step=0.5,
    )
    disk_reserve_mb = st.number_input(
        "Vùng đệm dung lượng tối thiểu (MB)",
        min_value=0,
        max_value=8192,
        value=512,
        step=128,
        help="Không bắt đầu hoặc tiếp tục ghi khi dung lượng trống thấp hơn vùng đệm này.",
    )
    use_scene_cache = st.checkbox(
        "Dùng cache phân tích scene",
        value=True,
        help="Lần chạy sau sẽ seek tới các timestamp đã chọn thay vì phân tích lại toàn bộ video.",
    )
    cross_run_duplicates = st.checkbox(
        "Loại duplicate giữa các lần chạy",
        value=True,
        help="Dùng dHash index trong thư mục screenshot để tránh lưu lại frame gần giống đã xuất trước đó.",
    )


def build_args() -> SimpleNamespace:
    return SimpleNamespace(
        start=float(start),
        end=float(end) if limit_end else None,
        every=float(every) if every is not None else None,
        count=int(count) if count is not None else None,
        scene_detection=mode_label in {"Best frame per scene", "Scene detection"},
        best_frame_per_scene=mode_label == "Best frame per scene",
        scene_threshold=float(scene_threshold),
        min_scene_gap=float(min_scene_gap),
        flash_return_ratio=float(flash_return_ratio),
        flash_brightness_threshold=float(flash_brightness_threshold),
        scene_confirmations=int(scene_confirmations),
        analysis_width=int(analysis_width),
        analysis_fps=float(analysis_fps),
        extract_workers=(recommended_extract_workers() if extract_worker_choice == "Auto (khuyến nghị)" else int(extract_worker_choice)),
        extract_min_targets=8,
        min_sharpness=float(min_sharpness),
        motion_blur_threshold=float(motion_blur_threshold),
        duplicate_threshold=int(duplicate_threshold),
        format=image_format,
        quality=int(quality),
        width=int(width) if width else None,
        overwrite=bool(overwrite),
        workers=workers,
        retries=int(retry_count),
        retry_delay=float(retry_delay),
        disk_reserve_bytes=int(disk_reserve_mb) * 1024**2,
        use_scene_cache=bool(use_scene_cache),
        cross_run_duplicates=bool(cross_run_duplicates),
        cross_run_duplicate_threshold=int(duplicate_threshold),
        resume=False,
        checkpoint_path=None,
        cache_root=None,
        duplicate_root=None,
    )


def _start_processing_job(args: SimpleNamespace, input_paths: list[Path], output_dir: Path, work_dir: Path) -> None:
    cancel_event = threading.Event()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="frameforge-ui")
    progress_state = {str(path): {"phase": "queued", "fraction": 0.0, "message": "Đang xếp hàng"} for path in input_paths}
    completed = {"count": 0}

    def on_progress(video: Path, phase: str, fraction: float, message: str) -> None:
        progress_state[str(video)] = {"phase": phase, "fraction": fraction, "message": message}

    def on_complete(video: Path, report: dict[str, object]) -> None:
        completed["count"] += 1
        progress_state[str(video)] = {
            "phase": "completed" if "error" not in report else "error",
            "fraction": 1.0,
            "message": f"Đã hoàn tất · lưu {report.get('saved', 0)} ảnh" if "error" not in report else str(report.get("error")),
        }

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
    )
    st.session_state["processing_job"] = {
        "status": "running",
        "future": future,
        "executor": executor,
        "cancel_event": cancel_event,
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


def _finish_processing_job(job: dict[str, object], keep_work_dir: bool = False) -> None:
    if job.get("cleaned") and not keep_work_dir:
        return
    work_dir = Path(str(job["work_dir"]))
    if not keep_work_dir:
        shutil.rmtree(work_dir, ignore_errors=True)
        job["cleaned"] = True
    else:
        job["resumable"] = work_dir.exists()
    executor = job.get("executor")
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)
        job["executor"] = None


def _poll_processing_job() -> dict[str, object] | None:
    job = st.session_state.get("processing_job")
    if not isinstance(job, dict) or job.get("status") != "running":
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
    except ProcessingCancelled as exc:
        job["status"] = "cancelled"
        job["error"] = str(exc)
        job["message"] = "Đã hủy xử lý; checkpoint và các screenshot đã ghi trước đó vẫn được giữ lại để tiếp tục."
    except InsufficientDiskSpace as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        job["message"] = str(exc)
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        job["message"] = f"Không thể xử lý queue: {exc}"
    _finish_processing_job(job, keep_work_dir=str(job.get("status")) == "cancelled")
    return job


@st.fragment(run_every=1.0)
def _render_processing_job() -> None:
    job = _poll_processing_job()
    if not job:
        return
    status = str(job.get("status"))
    if status == "running":
        st.markdown('<div class="section-heading"><span>◌</span> Tiến trình xử lý</div>', unsafe_allow_html=True)
        input_paths = list(job.get("input_paths", []))
        progress_state = job.get("progress", {})
        fractions = [float(progress_state.get(str(path), {}).get("fraction", 0.0)) for path in input_paths]
        overall = sum(fractions) / max(1, len(fractions))
        completed = int(job.get("completed", {}).get("count", 0))
        st.progress(overall, text=f"Tổng thể: {overall:.0%} · hoàn tất {completed}/{len(input_paths)} video")
        for path in input_paths:
            item = progress_state.get(str(path), {})
            phase = str(item.get("phase", "queued"))
            fraction = float(item.get("fraction", 0.0))
            message = str(item.get("message", "Đang chờ"))
            st.caption(f"**{path.name}** · {phase} · {fraction:.0%} · {message}")
        if st.button("Hủy xử lý", key="cancel_processing", type="secondary"):
            cancel_event = job.get("cancel_event")
            if cancel_event is not None:
                cancel_event.set()
            job["message"] = "Đang dừng an toàn sau checkpoint gần nhất..."
            st.warning(job["message"])
        else:
            st.caption("Bạn có thể hủy; FrameForge sẽ giải phóng VideoCapture và dọn file tạm.")
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
        st.error(str(job.get("message", "Có lỗi khi xử lý queue.")))
        return
    reports = job.get("reports") or []
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
    metric_a, metric_b, metric_c, metric_d, metric_e = st.columns(5)
    metric_a.metric("Đã lưu", total_saved)
    metric_b.metric("Loại vì mờ", total_blurry)
    metric_c.metric("Motion blur", total_motion_blur)
    metric_d.metric("Loại vì trùng", total_duplicate)
    metric_e.metric("Lỗi / retry", f"{total_errors} / {max(0, total_attempts - len(reports))}")
    st.caption(f"Tổng số lượt thử xử lý: {total_attempts} · retry tự động theo từng video.")

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
st.markdown('<div class="section-heading"><span>✦</span> Tổng quan</div>', unsafe_allow_html=True)
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

if uploaded_files or downloaded_paths:
    st.markdown('<div class="section-heading"><span>▷</span> Xem trước video</div>', unsafe_allow_html=True)
    preview_entries = [(Path(item.name).name, "upload", item) for item in (uploaded_files or [])]
    preview_entries += [(path.name, "download", path) for path in downloaded_paths]
    preview_names = [entry[0] for entry in preview_entries]
    preview_name = st.selectbox(
        "Chọn video để xem trước",
        preview_names,
        label_visibility="collapsed",
    )
    preview_entry = next(entry for entry in preview_entries if entry[0] == preview_name)
    preview_mime = mimetypes.guess_type(preview_name)[0] or "video/mp4"
    preview_col, preview_note_col = st.columns([1.55, 0.85], gap="large")
    with preview_col:
        if preview_entry[1] == "upload":
            st.video(preview_entry[2].getvalue(), format=preview_mime, subtitles=None, width=720)
        else:
            st.video(str(preview_entry[2]), format=preview_mime, subtitles=None, width=720)
    with preview_note_col:
        st.markdown(
            "<div class='preview-note'><strong>Preview gọn</strong><br>"
            "Khung xem trước được giới hạn chiều rộng và chiều cao để không lấn át phần điều khiển. "
            "Một số codec như MKV/TS có thể không được trình duyệt hỗ trợ.</div>",
            unsafe_allow_html=True,
        )

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
job_running = isinstance(active_job, dict) and active_job.get("status") == "running"

st.markdown("<br>", unsafe_allow_html=True)
run_col, hint_col = st.columns([1, 2.2])
with run_col:
    run_clicked = st.button(
        "▶  Bắt đầu xử lý",
        type="primary",
        use_container_width=True,
        disabled=(not uploaded_files and not downloaded_paths) or job_running,
    )
with hint_col:
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
    try:
        screenshot_root = normalize_output_dir(
            st.session_state.get("screenshot_dir", ""),
            Path.home() / "Videos" / "FrameForge" / "screenshots",
        )
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
