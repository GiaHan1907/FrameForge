"""Scene timeline, personal config panel, and job history renderers.

Extracted from ``streamlit_app.py`` to isolate these self-contained UI
sections into independently testable modules.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

import streamlit as st

from core.pipeline import timestamp_label
from timeline_utils import build_timeline_entries, filter_timeline_entries
from ui.logic import job_history_path, personal_presets_path, read_json_list
from ui.presets import (
    apply_personal_preset,
    export_ui_config,
    import_ui_config,
    save_personal_preset,
)


def show_scene_timeline(reports: list[dict[str, Any]], output_dir: Path | None = None) -> None:
    """Render interactive scene timeline with filter, zoom, and preview."""
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


def render_personal_config_panel() -> None:
    """Render personal presets and config import/export panel."""
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
    """Render job history expander with recent runs."""
    history = list(reversed(read_json_list(job_history_path())))
    with st.expander(f"Lịch sử job ({len(history)})", expanded=False):
        if not history:
            st.caption("Chưa có job nào được lưu.")
            return
        _status_badges = {
            "completed": ("Hoàn tất", "#1a7f37"),
            "success": ("Thành công", "#1a7f37"),
            "error": ("Lỗi", "#d1242f"),
            "cancelled": ("Đã hủy", "#8a8f98"),
        }
        table_rows = []
        for entry in history[:20]:
            status = str(entry.get("status") or "")
            status_label, status_color = _status_badges.get(status, (status or "—", "#8a8f98"))
            finished_at = str(entry.get("finished_at") or "").replace("T", " ")[:19]
            output_dir = str(entry.get("output_dir") or "")
            video_count = entry.get("video_count", "")
            saved = entry.get("saved", "")
            shortfall = entry.get("shortfall", "")
            table_rows.append(
                "<tr>"
                f"<td>{html.escape(finished_at)}</td>"
                f"<td><span style='color:{status_color};font-weight:600'>{html.escape(status_label)}</span></td>"
                f"<td>{html.escape(str(video_count))}</td>"
                f"<td>{html.escape(str(saved))}</td>"
                f"<td>{html.escape(str(shortfall))}</td>"
                f"<td title='{html.escape(output_dir)}'>{html.escape(output_dir[:80])}</td>"
                "</tr>"
            )
        st.markdown(
            "<div class='scene-table-wrap'><table class='scene-table'>"
            "<thead><tr><th>Thời gian</th><th>Trạng thái</th><th>Video</th><th>Ảnh lưu</th><th>Thiếu</th><th>Thư mục xuất</th></tr></thead>"
            "<tbody>" + "".join(table_rows) + "</tbody></table></div>",
            unsafe_allow_html=True,
        )
