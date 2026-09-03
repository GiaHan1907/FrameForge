"""Inline image search — renders inside the main app (no page config)."""

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
    st.subheader("Tìm ảnh theo địa điểm")

    query = st.text_input(
        "Địa điểm / keywords",
        placeholder="Ví dụ: Hoàn Kiếm, Hà Nội",
        key="_inline_img_query",
    )
    max_results = st.slider("Số ảnh tối đa", 5, 50, 12, key="_inline_img_max")

    if st.button("Tìm kiếm", key="_inline_img_search_btn"):
        if not query.strip():
            st.warning("Nhập địa điểm hoặc keywords trước khi tìm.")
            return
        with st.spinner("Đang tìm kiếm..."):
            try:
                results = search_google_images(query.strip(), max_results=max_results)
            except Exception as exc:
                st.error(f"Lỗi tìm kiếm: {exc}")
                return

        if not results:
            st.info("Không tìm thấy ảnh nào.")
            return

        st.session_state["_inline_img_results"] = results
        st.session_state["_inline_img_query_display"] = query.strip()

    results = st.session_state.get("_inline_img_results")
    if results:
        display_query = st.session_state.get("_inline_img_query_display", "")
        st.caption(f"{len(results)} kết quả cho \"{display_query}\"")

        # Download dir
        download_dir = Path(
            st.session_state.get("download_dir", "")
            or str(Path.home() / "Videos" / "FrameForge" / "images")
        )

        cols = st.columns(3)
        for i, img in enumerate(results):
            col = cols[i % 3]
            with col:
                st.image(img.thumbnail_url or img.url, caption=img.title[:60] if img.title else "", use_container_width=True)
                if st.button(f"Tải #{i+1}", key=f"_dl_img_{i}"):
                    try:
                        saved = download_image(img, download_dir)
                        st.success(f"Đã lưu: {saved.name}")
                    except Exception as exc:
                        st.error(f"Lỗi tải: {exc}")
