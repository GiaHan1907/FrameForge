"""
Sidebar + wizard configuration widgets for FrameForge.

Defines the full wizard configuration form as a declarative dict of
WidgetEntry lists - one per wizard step (01 Nguồn video / 02 Cách chọn
frame / 03 Chất lượng & tốc độ / 04 Đầu ra).  The sidebar itself stays
compact (brand only); all configuration widgets are rendered inside the
"⚙️ Xử lý video" tab, one expander per step.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from core.pipeline import (
    CROP_RATIO_LABELS,
    ENCODE_PROFILE_LABELS,
    recommend_workers,
)

from ui.widgets import (
    Checkbox,
    Custom,
    Expander,
    NumberInput,
    Radio,
    Selectbox,
    Slider,
    WidgetEntry,
)


def render_sidebar() -> None:
    """Render the compact sidebar (brand only)."""
    _render_brand()
    st.divider()


def build_wizard_entries(
    *,
    uploaded_files: Any,
    downloaded_paths: list[Any],
    mode_label: str,
    limit_end: bool,
    image_format: str,
    max_screenshots: int,
    worker_count: int | None,
    preset_options: list[str] | None = None,
    on_change_preset: Any = None,
) -> dict[str, list[WidgetEntry]]:
    """Build the wizard configuration form, grouped by step.

    Returns a dict keyed by the step heading (``01 · Nguồn video`` ...)
    so callers can render each step inside its own ``st.expander`` in the
    main processing tab.  Parameters are the *current* values of key
    widgets that affect conditional visibility; Streamlit widgets read
    their own defaults from ``st.session_state`` via the ``key``
    parameter, so only layout-driving values need to be passed.
    """
    recommended = recommend_workers(worker_count)

    # ── Step 01: Nguồn video ──────────────────────────────────────
    step_01: list[WidgetEntry] = [
        Custom(lambda: _render_file_status(uploaded_files, downloaded_paths)),
    ]

    # ── Step 02: Cách chọn frame ──────────────────────────────────
    step_02: list[WidgetEntry] = [
        Selectbox(
            "Preset cấu hình",
            "preset_choice",
            options=preset_options or [],
            on_change=on_change_preset,
            help="Áp dụng nhanh nhóm thông số; bạn vẫn có thể tinh chỉnh từng trường sau đó.",
        ),
        Custom(lambda: _render_preset_status()),
        Radio(
            "Chế độ xử lý",
            "mode_label",
            options=["Best frame per scene", "Scene detection", "Mỗi N giây", "Đúng N frame"],
        ),
        NumberInput("Bắt đầu từ giây", "start", min_value=0.0, step=1.0),
        Checkbox("Giới hạn thời điểm kết thúc", "limit_end"),
        NumberInput(
            "Kết thúc ở giây", "end",
            min_value=0.1, value=60.0, step=1.0,
            disabled=not limit_end,
        ),
        NumberInput(
            "Số screenshot mỗi video", "max_screenshots",
            min_value=1, max_value=1000, value=20, step=1,
            help="Số ảnh mục tiêu mỗi video. Khi bật chế độ ép đủ, FrameForge sẽ dùng fallback có kiểm soát nếu filter loại quá nhiều frame.",
        ),
        Checkbox(
            "Ép đủ số ảnh yêu cầu (fallback cuối)", "target_count_after_filter",
            value=True,
            help="Áp dụng cho mọi mode. Filter vẫn chạy bình thường trước; nếu còn thiếu, hệ thống sẽ lưu candidate bị loại ít rủi ro nhất.",
        ),
    ]

    # ── Conditional: scene detection settings ──────────────────────
    scene_mode = mode_label in {"Best frame per scene", "Scene detection"}
    if scene_mode:
        step_02.append(Slider("Độ nhạy thay đổi cảnh", "scene_threshold", 0.05, 0.95, 0.05,
                              help="Thấp hơn sẽ nhạy hơn và có thể tạo nhiều scene hơn."))
        step_02.append(Expander(
            "Scene detection nâng cao", expanded=False, entries=[
                NumberInput("Khoảng cách tối thiểu giữa scene (giây)", "min_scene_gap",
                            min_value=0.1, step=0.1),
                Slider("Ngưỡng chống flash", "flash_return_ratio", 0.10, 0.95, 0.05,
                       help="Thấp hơn giúp bỏ các thay đổi ngắn quay lại cảnh cũ."),
                Slider("Độ lệch sáng tối đa khi nhận diện flash", "flash_brightness_threshold",
                       0.01, 0.50, 0.01),
                Slider("Số frame xác nhận thay đổi cảnh", "scene_confirmations",
                       1, 5, 1,
                       help="Tăng lên để chống nhiễu/flash; giảm xuống 1 cho chuyển cảnh rất nhanh."),
            ],
        ))
    elif mode_label == "Mỗi N giây":
        step_02.append(NumberInput(
            "Khoảng cách giữa các frame (giây)", "every",
            min_value=0.05, value=5.0, step=0.5,
        ))
    # "Đúng N frame" - count is derived from max_screenshots, no extra widget

    # ── Step 03: Chất lượng & tốc độ ──────────────────────────────
    step_03: list[WidgetEntry] = [
        Custom(lambda r=recommended: _render_worker_caption(r)),
        Selectbox(
            "Video xử lý song song", "worker_choice",
            options=["Auto (khuyến nghị)", 1, 2, 3, 4],
            help="Auto tự cân bằng theo CPU/RAM. Mỗi worker xử lý một video độc lập.",
        ),
        Expander(
            "Hiệu năng phân tích", expanded=False, entries=[
                NumberInput("Chiều rộng phân tích", "analysis_width",
                            min_value=160, max_value=1920, step=80,
                            help="Frame được thu nhỏ trước khi đo scene, độ nét và trùng lặp."),
                NumberInput("RAM khả dụng tối thiểu (GB)", "min_free_ram_gb",
                            min_value=0.0, max_value=64.0, step=0.5,
                            help="Tạm dừng/không bắt đầu job nếu RAM khả dụng thấp hơn ngưỡng; 0 để tắt."),
                NumberInput("FPS phân tích scene", "analysis_fps",
                            min_value=1.0, max_value=30.0, step=1.0,
                            help="Giảm FPS để tăng tốc; tăng FPS nếu cảnh thay đổi rất nhanh."),
                Selectbox(
                    "Process trích frame fixed/count", "extract_worker_choice",
                    options=["Auto (khuyến nghị)", 1, 2, 3, 4],
                    help="Chỉ áp dụng cho Mỗi N giây/Đúng N frame khi có từ 8 timestamp.",
                ),
            ],
        ),
        Expander(
            "Lọc mờ · trùng lặp", expanded=False, entries=[
                NumberInput(
                    "Ngưỡng độ nét tối thiểu", "min_sharpness",
                    min_value=0.0, step=10.0,
                    help="Điểm đã chuẩn hóa về chiều rộng tham chiếu 640 px. Đặt 0 để tắt lọc mờ.",
                ),
                Slider(
                    "Ngưỡng trùng dHash", "duplicate_threshold",
                    0, 32, 1,
                    help="Khoảng cách càng nhỏ thì frame càng giống. Đặt 0 để tắt lọc trùng.",
                ),
                Slider(
                    "Ngưỡng motion blur", "motion_blur_threshold",
                    0.0, 1.0, 0.05,
                    help="Điểm càng cao càng có nguy cơ nhòe chuyển động. Đặt 0 để tắt.",
                ),
            ],
        ),
    ]

    # ── Step 04: Đầu ra ───────────────────────────────────────────
    step_04: list[WidgetEntry] = [
        Selectbox(
            "Profile encode", "encode_profile",
            options=list(ENCODE_PROFILE_LABELS),
            help="Nhanh giảm chi phí encode; Chất lượng cao ưu tiên tối ưu kích thước/chất lượng file.",
        ),
        Selectbox(
            "Định dạng ảnh", "image_format",
            options=["jpg", "png", "webp"],
        ),
        Selectbox(
            "Tỉ lệ crop screenshot", "crop_ratio",
            options=list(CROP_RATIO_LABELS),
            help="Crop chính giữa, không kéo giãn hình. Chiều rộng đầu ra áp dụng sau khi crop.",
        ),
        Slider(
            "Chất lượng JPG/WebP", "quality",
            1, 100, 1,
            disabled=image_format == "png",
        ),
        NumberInput(
            "Chiều rộng đầu ra (0 = giữ nguyên)", "width",
            min_value=0, step=64,
        ),
        Checkbox("Ghi đè file đầu ra đã tồn tại", "overwrite"),
        Expander(
            "Retry · cache · nâng cao", expanded=False, entries=[
                NumberInput(
                    "Số lần retry mỗi video", "retries",
                    min_value=0, max_value=5, step=1,
                    help="Nếu một video lỗi tạm thời, FrameForge sẽ tự thử lại trước khi chuyển sang video kế tiếp.",
                ),
                NumberInput(
                    "Thời gian chờ retry (giây)", "retry_delay",
                    min_value=0.0, max_value=30.0, step=0.5,
                ),
                NumberInput(
                    "Vùng đệm dung lượng tối thiểu (MB)", "disk_reserve_mb",
                    min_value=0, max_value=8192, step=128,
                    help="Không bắt đầu hoặc tiếp tục ghi khi dung lượng trống thấp hơn vùng đệm này.",
                ),
                Checkbox(
                    "Dùng cache phân tích scene", "use_scene_cache",
                    help="Lần chạy sau sẽ seek tới các timestamp đã chọn thay vì phân tích lại toàn bộ video.",
                ),
                Checkbox(
                    "Loại duplicate giữa các lần chạy", "cross_run_duplicates",
                    help="Dùng dHash index trong thư mục screenshot để tránh lưu lại frame gần giống đã xuất trước đó.",
                ),
            ],
        ),
    ]

    return {
        "01 · Nguồn video": step_01,
        "02 · Cách chọn frame": step_02,
        "03 · Chất lượng & tốc độ": step_03,
        "04 · Đầu ra": step_04,
    }


# ── Custom renderers ──────────────────────────────────────────────────


def _render_brand() -> None:
    st.markdown(
        """
        <div class="sidebar-brand">
          <span class="mark">✦</span><strong>FrameForge</strong>
          <p>Video screenshot studio<br>Scene-aware · Fast · Clean</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_file_status(uploaded_files: Any, downloaded_paths: list[Any]) -> None:
    st.file_uploader(
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


def _render_preset_status() -> None:
    if st.session_state.get("preset_status"):
        st.caption(st.session_state.pop("preset_status"))


def _render_worker_caption(recommended: int) -> None:
    st.caption(f"Đề xuất hiện tại: **{recommended} worker** theo cấu hình máy.")
