from __future__ import annotations

import contextlib
import io
import html
import json
import mimetypes
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import streamlit as st

from updater import initialize_yt_dlp
from app_update import initialize_app_update, launch_pending_installer, maybe_update_app

# Kiểm tra tối đa một lần mỗi 24 giờ; bản mới chỉ được kích hoạt từ lần chạy kế tiếp.
update_status = initialize_yt_dlp(
    auto_update=os.environ.get("FRAMEFORGE_AUTO_UPDATE", "1").lower() not in {"0", "false", "no", "off"}
)
app_update_status = initialize_app_update()

from video_screenshot_advanced import process_videos, recommend_workers
from video_downloader import (
    QUALITY_FORMATS,
    download_public_videos,
    ffmpeg_health,
    is_supported_public_url,
    result_summary,
)


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


def make_zip(directory: Path, report_path: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
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


def show_scene_timeline(reports: list[dict[str, object]]) -> None:
    rows = []
    for report in reports:
        video_name = Path(str(report.get("video", "video"))).name
        scene_times = report.get("scene_times", [])
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
    max_time = max(float(row["time_seconds"]) for row in rows) or 1.0
    timeline_rows = []
    for row in rows:
        video_label = html.escape(str(row["video"]))
        scene_number = int(row["scene"])
        timestamp = float(row["time_seconds"])
        position = min(100.0, max(0.0, timestamp / max_time * 100.0))
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
        f"{max_time:.3f}s</span></div>"
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


# Header
if update_status.updated:
    st.info(f"Đã tải bản yt-dlp {update_status.latest_version}; bản cập nhật sẽ được kích hoạt ở lần mở ứng dụng kế tiếp.")
elif update_status.message and "mới nhất" not in update_status.message and "tắt" not in update_status.message and update_status.checked:
    st.caption(f"yt-dlp updater: {update_status.message}")

if app_update_status.available:
    st.info(f"Có bản cập nhật FrameForge {app_update_status.latest_version}. {app_update_status.message}")
    if app_update_status.downloaded and app_update_status.installer_path:
        if st.button("Mở Setup để cài bản cập nhật", type="primary"):
            if launch_pending_installer():
                st.success("Đã mở Setup. Hãy hoàn tất trình cài đặt rồi khởi động lại FrameForge.")
            else:
                st.error("Không tìm thấy file Setup đã tải.")
    else:
        if st.button("Tải và xác minh Setup mới"):
            with st.spinner("Đang tải và kiểm tra SHA-256 của Setup..."):
                app_update_status = maybe_update_app(force=True)
            if app_update_status.downloaded:
                st.success(app_update_status.message)
            else:
                st.error(app_update_status.message)

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

# Download public video queue
if "download_dir" not in st.session_state:
    st.session_state["download_dir"] = tempfile.mkdtemp(prefix="frameforge_downloads_")
if "downloaded_paths" not in st.session_state:
    st.session_state["downloaded_paths"] = []
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
download_col, quality_col, limit_col, action_col = st.columns([2.3, 1.15, 0.85, 0.9])
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
            with st.spinner(f"Đang tải queue gồm {len(download_urls)} URL..."):
                download_results = download_public_videos(
                    download_urls,
                    Path(st.session_state["download_dir"]),
                    download_quality,
                    max_playlist_items=int(playlist_max_items),
                )
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
        min_sharpness=float(min_sharpness),
        motion_blur_threshold=float(motion_blur_threshold),
        duplicate_threshold=int(duplicate_threshold),
        format=image_format,
        quality=int(quality),
        width=int(width) if width else None,
        overwrite=bool(overwrite),
        workers=workers,
    )


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

st.markdown("<br>", unsafe_allow_html=True)
run_col, hint_col = st.columns([1, 2.2])
with run_col:
    run_clicked = st.button(
        "▶  Bắt đầu xử lý",
        type="primary",
        use_container_width=True,
        disabled=not uploaded_files and not downloaded_paths,
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
    work_dir = Path(tempfile.mkdtemp(prefix="video_screenshot_web_"))
    input_dir = work_dir / "input"
    output_dir = work_dir / "screenshots_filtered"
    input_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    reports = []
    input_paths = list(downloaded_paths)
    for uploaded in (uploaded_files or []):
        input_path = input_dir / Path(uploaded.name).name
        input_path.write_bytes(uploaded.getbuffer())
        input_paths.append(input_path)

    try:
        with st.status(
            f"Đang xử lý {len(input_paths)} video bằng {args.workers} worker...",
            expanded=True,
        ) as status:
            progress = st.progress(0, text="Đang chuẩn bị...")
            logs = io.StringIO()
            errors = io.StringIO()
            completed = [0]

            def on_complete(video: Path, report: dict[str, object]) -> None:
                completed[0] += 1
                progress.progress(
                    completed[0] / len(input_paths),
                    text=f"Đã xử lý {completed[0]}/{len(input_paths)} video",
                )
                st.write(f"✓ Hoàn tất **{video.name}** · lưu {report.get('saved', 0)} ảnh")

            with contextlib.redirect_stdout(logs), contextlib.redirect_stderr(errors):
                reports = process_videos(
                    input_paths,
                    output_dir,
                    None,
                    args,
                    on_complete=on_complete,
                )
            with st.expander("Nhật ký xử lý", expanded=False):
                st.code(logs.getvalue() + errors.getvalue())
            status.update(label="Đã xử lý xong", state="complete", expanded=False)

        report_path = work_dir / "report.json"
        report_path.write_text(
            json.dumps(reports, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        zip_bytes = make_zip(output_dir, report_path)

        total_saved = sum(int(item.get("saved", 0)) for item in reports)
        total_blurry = sum(int(item.get("rejected_blurry", 0)) for item in reports)
        total_duplicate = sum(int(item.get("rejected_duplicate", 0)) for item in reports)
        total_motion_blur = sum(int(item.get("rejected_motion_blur", 0)) for item in reports)
        total_errors = sum(int(item.get("capture_errors", 0)) for item in reports)
        st.markdown(

            '<div class="result-banner">✓ Hoàn tất. Các frame đã được phân tích, lọc và đóng gói.</div>',
            unsafe_allow_html=True,
        )
        st.markdown('<div class="section-heading"><span>↗</span> Kết quả xử lý</div>', unsafe_allow_html=True)
        metric_a, metric_b, metric_c, metric_d, metric_e = st.columns(5)
        metric_a.metric("Đã lưu", total_saved)
        metric_b.metric("Loại vì mờ", total_blurry)
        metric_c.metric("Motion blur", total_motion_blur)
        metric_d.metric("Loại vì trùng", total_duplicate)
        metric_e.metric("Lỗi", total_errors)

        download_col, report_col = st.columns([1, 1])
        with download_col:
            st.download_button(
                "⬇  Tải screenshot + report ZIP",
                data=zip_bytes,
                file_name="screenshots_filtered.zip",
                mime="application/zip",
                type="primary",
                use_container_width=True,
            )
        with report_col:
            st.download_button(
                "Tải report JSON",
                data=json.dumps(reports, ensure_ascii=False, indent=2),
                file_name="report.json",
                mime="application/json",
                use_container_width=True,
            )

        show_scene_timeline(reports)

        image_files = (
            sorted(output_dir.rglob("*.jpg"))
            + sorted(output_dir.rglob("*.png"))
            + sorted(output_dir.rglob("*.webp"))
        )
        if image_files:
            st.markdown(
                f'<div class="section-heading"><span>▦</span> Preview <small style="color:#8b95a7;font-family:DM Sans;font-size:.78rem;font-weight:500;">{len(image_files)} ảnh được tạo</small></div>',
                unsafe_allow_html=True,
            )
            preview_files = image_files[:24]
            columns = st.columns(4)
            for index, image_path in enumerate(preview_files):
                with columns[index % 4]:
                    st.image(
                        str(image_path),
                        caption=image_path.name,
                        use_container_width=True,
                    )
            if len(image_files) > len(preview_files):
                st.info(
                    f"Chỉ hiển thị {len(preview_files)} ảnh đầu tiên; toàn bộ ảnh nằm trong file ZIP."
                )
        else:
            st.warning("Không có frame nào vượt qua các bộ lọc đã chọn.")
    except Exception as exc:
        st.error(f"Không thể xử lý: {exc}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

st.markdown(
    '<div style="margin-top:2.4rem;padding-top:1rem;border-top:1px solid #e6eaf0;color:#8b95a7;font-size:.78rem;">FrameForge · Scene-aware video screenshot studio · Pipeline đọc một lần, phân tích nhanh và lọc chất lượng tự động.</div>',
    unsafe_allow_html=True,
)
