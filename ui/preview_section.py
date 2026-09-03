"""Preview workspace section — video preview, crop overlay, scene timeline.

Extracted from ``streamlit_app.py`` to isolate the preview UI into a
testable module that reads widget values from a dict instead of globals.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
import streamlit as st

from ui.logic import build_preview_timestamps
from ui.session import WidgetState
from ui.preview import (
    preview_crop_overlay,
    preview_frame_at,
    preview_video_duration,
    quick_scene_preview,
)


def preview_scene_timeline(duration: float, estimated: list[float], actual: list[float]) -> None:
    """Hiển thị timeline nhẹ với phân biệt marker ước tính và marker scene thật."""
    safe_duration = max(float(duration or 0.0), 0.001)
    estimated_marks = "".join(
        f'<span title="Ước tính {value:.3f}s" style="left:{max(0, min(100, value / safe_duration * 100)):.2f}%"></span>'
        for value in estimated
    )
    actual_marks = "".join(
        f'<b title="Scene thật {value:.3f}s" style="left:{max(0, min(100, value / safe_duration * 100)):.2f}%"></b>'
        for value in actual
    )
    st.markdown(
        f'<div class="scene-timeline"><div class="track">{estimated_marks}{actual_marks}</div>'
        f'<div class="timeline-legend"><span>● Ước tính</span><strong>◆ Scene thật</strong>'
        f"<em>0s — {safe_duration:.1f}s</em></div></div>",
        unsafe_allow_html=True,
    )


def render_preview_section(widgets: WidgetState) -> None:
    """Render the full preview workspace: video player, crop overlay, timeline, scene detection.

    Parameters
    ----------
    widgets:
        ``WidgetState`` returned by ``ui.session.read_widgets()``.
    """
    uploaded_files = widgets.get("uploaded_files") or []
    downloaded_paths = widgets.get("downloaded_paths") or []

    if not uploaded_files and not downloaded_paths:
        return

    mode_label = widgets.get("mode_label", "Best frame per scene")
    start = widgets.get("start", 0.0)
    end = widgets.get("end")
    limit_end = widgets.get("limit_end", False)
    every = widgets.get("every")
    count = widgets.get("count")
    max_screenshots = widgets.get("max_screenshots", 20)
    crop_ratio = widgets.get("crop_ratio", "Không crop")
    scene_threshold = widgets.get("scene_threshold", 0.30)
    analysis_fps = widgets.get("analysis_fps", 1.0)

    st.markdown('<div class="section-heading"><span>▷</span> Preview workspace</div>', unsafe_allow_html=True)

    preview_entries = [(Path(item.name).name, "upload", item) for item in uploaded_files]
    preview_entries += [(Path(path).name, "download", path) for path in downloaded_paths]
    preview_names = [entry[0] for entry in preview_entries]
    preview_name = st.selectbox(
        "Chọn video để xem preview", preview_names,
        label_visibility="collapsed", key="preview_name",
    )
    preview_entry = next(entry for entry in preview_entries if entry[0] == preview_name)
    preview_mime = mimetypes.guess_type(preview_name)[0] or "video/mp4"
    preview_duration = preview_video_duration(preview_entry[2])
    preview_timestamps = build_preview_timestamps(
        preview_duration, mode_label, float(start),
        float(end) if limit_end else None,
        float(every) if every is not None else None,
        int(count or max_screenshots), int(max_screenshots),
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
                st.image(overlay, caption=f"Crop overlay · {crop_ratio}", use_container_width=True)
                st.caption("Vùng sáng có viền xanh là phần được giữ lại.")
            else:
                st.info("Không thể tạo frame preview cho codec này; engine vẫn có thể xử lý video.")

        st.markdown("**Phân bố screenshot dự kiến · timeline tương tác**")
        if preview_duration:
            preview_scene_timeline(float(preview_duration), preview_timestamps, actual_scene_marks)

        timeline_col, action_col = st.columns([2, 1])
        with timeline_col:
            max_preview_time = max(0.1, float(preview_duration or end or 1.0))
            selected_preview_time = st.slider(
                "Mốc preview", 0.0, max_preview_time,
                min(max_preview_time / 2, max_preview_time), 0.1,
                key="preview_timestamp_slider",
            )
        with action_col:
            st.markdown("**Scene detection**")
            if st.button("Phân tích nhanh scene thật", key="quick_scene_preview_button"):
                st.session_state["quick_scene_preview_marks"] = quick_scene_preview(
                    preview_entry[2], float(scene_threshold), float(start),
                    float(end) if limit_end else None, float(analysis_fps),
                )
                st.rerun()

        selected_frame = preview_frame_at(preview_entry[2], selected_preview_time, crop_ratio)
        if selected_frame is not None:
            st.image(
                selected_frame,
                caption=f"Frame gallery · {selected_preview_time:.1f}s · crop {crop_ratio}",
                use_container_width=True,
            )
        if preview_timestamps:
            st.caption(
                f"Gallery hiện tại: {len(preview_timestamps)} mốc dự kiến · "
                "chọn thanh trượt để xem frame tại timestamp bất kỳ."
            )
        if actual_scene_marks:
            st.success(f"Đã phân tích {len(actual_scene_marks)} scene marker thực tế.")
        else:
            st.info("Chưa có marker scene thật. Bấm 'Phân tích scene thật' để chạy phân tích nhanh.")
