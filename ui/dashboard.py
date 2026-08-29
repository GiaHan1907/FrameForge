"""Resource meter, queue dashboard, and error action renderers.

Extracted from ``streamlit_app.py`` to isolate status display components.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st

from core.pipeline import current_process_rss_bytes, free_disk_bytes
from core.resources import available_ram_gb
from core.utils import format_bytes
from ui.logic import normalize_output_dir
from ui.session import read_widgets


def render_resource_meter(args: Any = None, output_root: Path | None = None) -> None:
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
    """Render queue progress dashboard with metrics and progress bar."""
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
    """Render error diagnostic download button and privacy note."""
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
