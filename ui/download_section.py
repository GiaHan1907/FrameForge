"""Download public video queue section.

Extracted from ``streamlit_app.py`` to isolate the download UI into a
testable module.  The pure logic (URL validation, hook callbacks) can
be unit-tested without a Streamlit runtime.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from video_downloader import (
    QUALITY_FORMATS,
    DownloadFailure,
    download_public_videos,
    ffmpeg_health,
    is_supported_public_url,
    result_summary,
)
from ui.logic import make_download_zip


# ---------------------------------------------------------------------------
# Pure helpers (testable without Streamlit)
# ---------------------------------------------------------------------------


def validate_download_urls(urls_text: str) -> tuple[list[str], list[str]]:
    """Parse and validate a block of URL text.

    Returns ``(valid_urls, invalid_urls)``.
    """
    urls = [line.strip() for line in urls_text.splitlines() if line.strip()]
    invalid = [url for url in urls if not is_supported_public_url(url)]
    return urls, invalid


def build_download_hook(progress_bar: Any) -> Any:
    """Return a yt-dlp progress hook closure that updates *progress_bar*."""

    def _hook(data: dict[str, object]) -> None:
        state = str(data.get("status") or "downloading")
        if state == "retrying":
            code = str(data.get("error_code") or "unknown")
            next_attempt = int(data.get("next_attempt") or 0)
            total_attempts = int(data.get("total_attempts") or 0)
            delay = float(data.get("retry_delay") or 0.0)
            progress_bar.progress(
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
        progress_bar.progress(
            min(1.0, max(0.0, fraction)),
            text=f"{state} · {filename} · {fraction:.0%}",
        )

    return _hook


def build_download_error_hook(errors_list: list[DownloadFailure]) -> Any:
    """Return a yt-dlp error hook that appends to *errors_list*."""

    def _hook(error: DownloadFailure) -> None:
        errors_list.append(error)

    return _hook


# ---------------------------------------------------------------------------
# Streamlit rendering
# ---------------------------------------------------------------------------


def render_download_section() -> None:
    """Render the full download public video queue section.

    Reads/writes ``st.session_state["download_dir"]`` and
    ``st.session_state["downloaded_paths"]``.
    """
    # Clean up stale paths
    downloaded_paths = [
        Path(item) for item in st.session_state["downloaded_paths"] if Path(item).exists()
    ]
    st.session_state["downloaded_paths"] = [str(item) for item in downloaded_paths]

    st.markdown('<div class="section-heading"><span>⇩</span> Tải video công khai</div>', unsafe_allow_html=True)
    st.markdown(
        '<p class="muted-note">Dán một hoặc nhiều URL công khai từ Facebook, TikTok hoặc Pinterest. Mỗi dòng là một video hoặc một playlist; chỉ tải nội dung bạn có quyền sử dụng.</p>',
        unsafe_allow_html=True,
    )

    # FFmpeg health
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
                placeholder="Mỗi dòng một URL video hoặc playlist…",
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

    if not download_clicked:
        return

    # --- Validate URLs ---
    urls, invalid_urls = validate_download_urls(download_urls_text)

    if not urls:
        st.warning("Hãy nhập ít nhất một URL.")
        return
    if invalid_urls:
        st.error("URL không được hỗ trợ hoặc không phải URL công khai:")
        st.code("\n".join(invalid_urls))
        return

    # --- Execute download ---
    health = ffmpeg_health()
    if not health["ready_for_merge"]:
        st.warning("Chưa tìm thấy FFmpeg. Video/audio tách riêng có thể không ghép được ở chất lượng cao nhất.")

    try:
        download_progress = st.progress(0.0, text="Đang chuẩn bị queue tải…")
        download_errors: list[DownloadFailure] = []

        hook = build_download_hook(download_progress)
        error_hook = build_download_error_hook(download_errors)

        with st.spinner(f"Đang tải queue gồm {len(urls)} URL…"):
            download_results = download_public_videos(
                urls,
                Path(st.session_state["download_dir"]),
                download_quality,
                max_playlist_items=int(playlist_max_items),
                max_retries=int(download_retry_count),
                retry_delay_seconds=1.0,
                progress_hook=hook,
                error_hook=error_hook,
            )

        download_progress.progress(1.0, text=f"Đã tải xong {len(download_results)} video")

        for result in download_results:
            if str(result.path) not in st.session_state["downloaded_paths"]:
                st.session_state["downloaded_paths"].append(str(result.path))

        if download_results:
            st.success(f"Đã tải {len(download_results)} video từ {len(urls)} URL.")
        if download_errors:
            st.warning(f"Có {len(download_errors)} URL không tải được; queue vẫn giữ các video thành công.")
            for error in download_errors[:10]:
                st.error(f"[{error.code}] {error.label}\nURL: {error.url}\n{error.message}\nGợi ý: {error.suggestion}")
            if len(download_errors) > 10:
                st.caption(f"… và {len(download_errors) - 10} lỗi khác trong queue.")
        for result in download_results[:10]:
            st.caption(f"✓ {result_summary(result)}")
        if len(download_results) > 10:
            st.caption(f"… và {len(download_results) - 10} video khác trong queue.")
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
