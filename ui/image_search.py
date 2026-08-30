"""
Image Search page — find and download images from Google by location.

Streamlit page that allows users to:
1. Search Google Images by place name / address / coordinates
2. Browse results in a gallery grid
3. Select and download images locally
"""

from __future__ import annotations

import streamlit as st
from pathlib import Path

from core.google_images import (
    ImageResult,
    download_image,
    download_images,
    search_google_images,
)


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    layout="wide",
    page_icon="🔍",
    page_title="Tìm ảnh theo địa điểm",
)


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    .search-result-card {
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px;
        padding: 8px;
        transition: transform 0.15s ease;
    }
    .search-result-card:hover {
        transform: translateY(-2px);
    }
    .result-title {
        font-size: 0.75rem;
        color: rgba(255,255,255,0.6);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        margin-top: 4px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.markdown(
    """
    # 🔍 Tìm ảnh theo địa điểm

    Tìm kiếm ảnh từ Google Images theo tên địa điểm, địa chỉ, hoặc tọa độ.
    """
)


# ---------------------------------------------------------------------------
# Search controls
# ---------------------------------------------------------------------------

col_input, col_count = st.columns([4, 1])

with col_input:
    location = st.text_input(
        "📍 Địa điểm",
        placeholder="VD: Hồ Hoàn Kiếm, Hà Nội / Eiffel Tower, Paris / 21.0285, 105.8542",
        label_visibility="visible",
    )

with col_count:
    num_results = st.slider("Số ảnh", min_value=5, max_value=50, value=20, step=5)


# ---------------------------------------------------------------------------
# Search button + results
# ---------------------------------------------------------------------------

if st.button("🔍 Tìm kiếm", type="primary", use_container_width=True):
    if not location.strip():
        st.warning("Vui lòng nhập địa điểm cần tìm")
    else:
        with st.spinner(f"Đang tìm ảnh '{location}' trên Google..."):
            results = search_google_images(
                query=location.strip(),
                num_results=num_results,
            )
        st.session_state["image_results"] = results
        st.session_state["search_query"] = location.strip()

        if not results:
            st.info("Không tìm thấy ảnh nào. Thử địa điểm khác hoặc giảm số lượng ảnh.")
        else:
            st.success(f"Tìm thấy {len(results)} ảnh cho '{location.strip()}'")


# ---------------------------------------------------------------------------
# Display results
# ---------------------------------------------------------------------------

if "image_results" in st.session_state and st.session_state["image_results"]:
    results: list[ImageResult] = st.session_state["image_results"]
    query: str = st.session_state.get("search_query", "")

    st.divider()
    st.markdown(f"### Kết quả: **{query}** ({len(results)} ảnh)")

    # --- Selection state ---
    if "selected_images" not in st.session_state:
        st.session_state["selected_images"] = set()

    # --- Gallery grid (4 columns) ---
    COLS = 4
    for row_start in range(0, len(results), COLS):
        row_items = results[row_start : row_start + COLS]
        cols = st.columns(COLS)

        for col_idx, img in enumerate(row_items):
            global_idx = row_start + col_idx
            with cols[col_idx]:
                # Checkbox for selection
                selected = st.checkbox(
                    "Chọn",
                    key=f"img_sel_{global_idx}",
                    value=global_idx in st.session_state["selected_images"],
                )

                if selected:
                    st.session_state["selected_images"].add(global_idx)
                else:
                    st.session_state["selected_images"].discard(global_idx)

                # Display image
                st.image(
                    img.url,
                    caption=img.title[:40] if img.title else f"Ảnh #{global_idx + 1}",
                    use_container_width=True,
                )

    # --- Download section ---
    selected_indices = sorted(st.session_state["selected_images"])

    if selected_indices:
        st.divider()
        st.markdown(f"### 📥 Download ({len(selected_indices)} ảnh đã chọn)")

        col_dir, col_btn = st.columns([3, 1])

        with col_dir:
            save_dir = st.text_input(
                "📁 Thư mục lưu",
                value=str(Path.home() / "Downloads" / "FrameForge"),
                key="download_dir",
            )

        with col_btn:
            st.write("")  # spacer
            st.write("")
            download_btn = st.button(
                "📥 Download",
                type="primary",
                use_container_width=True,
            )

        if download_btn:
            urls = [results[i].url for i in selected_indices]

            with st.spinner(f"Đang download {len(urls)} ảnh..."):
                paths = download_images(urls, save_dir)

            if paths:
                st.success(f"Đã download {len(paths)} ảnh vào `{save_dir}`")

                # Show downloaded files
                with st.expander("📋 Danh sách file đã download"):
                    for p in paths:
                        st.code(str(p), language=None)
            else:
                st.error("Không download được ảnh nào. Kiểm tra lại đường dẫn.")

    # --- Clear results ---
    st.divider()
    if st.button("🗑️ Xóa kết quả"):
        st.session_state.pop("image_results", None)
        st.session_state.pop("search_query", None)
        st.session_state.pop("selected_images", None)
        st.rerun()

else:
    # Empty state
    st.divider()
    st.markdown(
        """
        <div style="text-align: center; padding: 3rem 1rem; color: rgba(255,255,255,0.4);">
            <p style="font-size: 3rem; margin-bottom: 0.5rem;">📍</p>
            <p style="font-size: 1.1rem;">Nhập địa điểm để bắt đầu tìm kiếm</p>
            <p style="font-size: 0.85rem;">VD: Hồ Hoàn Kiếm, Hà Nội / Ben Thanh Market, HCMC</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
