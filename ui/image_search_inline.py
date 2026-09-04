"""Inline image search - renders inside the main app (no page config).

Searches DuckDuckGo Images (Google blocks non-JS scrapers, so the core
backend falls back to DDG; no API key required).
"""

from __future__ import annotations

import streamlit as st
from pathlib import Path

from core.google_images import (
    download_image,
    download_images,
    search_google_images,
)


def render_inline_image_search() -> None:
    """Render a compact image-search UI in the main content area."""
    st.subheader("🔍 Tìm ảnh theo địa điểm")

    col_query, col_count = st.columns([3, 1])
    with col_query:
        query = st.text_input(
            "Địa điểm / keywords",
            placeholder="Ví dụ: Hoàn Kiếm, Hà Nội / Ben Thanh Market, HCMC",
            key="_inline_img_query",
        )
    with col_count:
        max_results = st.slider("Số ảnh", 5, 50, 12, key="_inline_img_max")

    if st.button("Tìm kiếm", key="_inline_img_search_btn", type="primary"):
        if not query.strip():
            st.warning("Nhập địa điểm hoặc keywords trước khi tìm.")
        else:
            with st.spinner("Đang tìm kiếm..."):
                try:
                    results = search_google_images(query.strip(), num_results=max_results)
                except Exception as exc:
                    st.error(f"Lỗi tìm kiếm: {exc}")
                    results = []
            if not results:
                st.info("Không tìm thấy ảnh nào. Thử địa điểm khác hoặc giảm số lượng ảnh.")
            else:
                st.session_state["_inline_img_results"] = results
                st.session_state["_inline_img_query_display"] = query.strip()

    results = st.session_state.get("_inline_img_results")
    if not results:
        return

    display_query = st.session_state.get("_inline_img_query_display", "")
    st.caption(f'{len(results)} kết quả cho "{display_query}" - bấm Tải để lưu từng ảnh, hoặc Tải tất cả bên dưới.')

    # Download folder + batch download
    download_dir = Path(
        st.session_state.get("_inline_img_dir", "")
        or str(Path.home() / "Videos" / "FrameForge" / "images")
    )
    col_dir, col_all = st.columns([3, 1])
    with col_dir:
        st.text_input(
            "📁 Thư mục lưu ảnh",
            value=str(download_dir),
            key="_inline_img_dir",
        )
    with col_all:
        st.write("")
        if st.button("📥 Tải tất cả", key="_inline_img_dl_all", type="primary", use_container_width=True):
            with st.spinner(f"Đang tải {len(results)} ảnh..."):
                saved = download_images([r.url for r in results], download_dir)
            if saved:
                st.success(f"Đã lưu {len(saved)}/{len(results)} ảnh vào `{download_dir}`")
            else:
                st.error("Không tải được ảnh nào. Kiểm tra lại thư mục hoặc thử lại sau.")

    # Results grid (3 columns)
    cols = st.columns(3)
    for i, img in enumerate(results):
        col = cols[i % 3]
        with col:
            st.image(
                img.thumbnail or img.url,
                caption=(img.title[:60] if img.title else f"Ảnh #{i + 1}"),
                use_container_width=True,
            )
            if st.button(f"Tải #{i + 1}", key=f"_dl_img_{i}"):
                try:
                    saved = download_image(img, download_dir)
                    st.success(f"Đã lưu: {saved.name}")
                except Exception as exc:
                    st.error(f"Lỗi tải: {exc}")

    st.caption("Nguồn: DuckDuckGo Images - không cần API key.")
