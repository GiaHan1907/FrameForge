"""Inline image search - renders inside the main app (no page config).

Multiple image sources are supported:
- DuckDuckGo Images (default, no key) - primary engine
- Wikimedia Commons (no key) - CC / public domain, license + author attached
- Openverse (no key; optional token raises rate limits) - CC aggregate
- Pexels / Pixabay / Unsplash - need a free API key (env FRAMEFORGE_*_API_KEY
  or typed inline; the key is kept in session state only)

Optional aspect-ratio crop is applied with Pillow when downloading.
"""

from __future__ import annotations

import os
import streamlit as st
from pathlib import Path

from core.google_images import (
    CROP_RATIOS,
    IMAGE_SOURCES,
    _KEY_REQUIRED_SOURCES,
    download_image,
    download_results,
    search_images,
)

# label the crop dropdown: keep dict order, "original" first
_CROP_CHOICES = ["original"] + [k for k in CROP_RATIOS if k != "original"]
_CROP_LABELS = {
    "original": "Giữ nguyên",
    "1:1": "Vuông 1:1",
    "4:5": "4:5 (Portrait)",
    "3:2": "3:2",
    "16:9": "16:9 (Landscape)",
    "9:16": "9:16 (Story/Reels)",
}

_SOURCE_KEY_HINT = {
    "pexels": "https://www.pexels.com/api/",
    "pixabay": "https://pixabay.com/api/docs/",
    "unsplash": "https://unsplash.com/developers",
    "openverse": "https://api.openverse.org/",
}


def _api_key_from_env(source: str) -> str:
    env_name = {
        "pexels": "FRAMEFORGE_PEXELS_API_KEY",
        "pixabay": "FRAMEFORGE_PIXABAY_API_KEY",
        "unsplash": "FRAMEFORGE_UNSPLASH_ACCESS_KEY",
        "openverse": "FRAMEFORGE_OPENVERSE_TOKEN",
    }.get(source, "")
    return os.environ.get(env_name, "").strip() if env_name else ""


def render_inline_image_search() -> None:
    """Render a compact image-search UI in the main content area."""
    st.subheader("🔍 Tìm ảnh theo địa điểm")

    col_query, col_src, col_count = st.columns([3, 2, 1])
    with col_query:
        query = st.text_input(
            "Địa điểm / keywords",
            placeholder="Ví dụ: Hoàn Kiếm, Hà Nội / Ben Thanh Market, HCMC",
            key="_inline_img_query",
        )
    with col_src:
        labels = [label for _k, label in IMAGE_SOURCES]
        keys = [k for k, _label in IMAGE_SOURCES]
        src_index = st.selectbox(
            "Nguồn ảnh",
            labels,
            index=0,
            key="_inline_img_source",
        )
        source = keys[labels.index(src_index)]
    with col_count:
        max_results = st.slider("Số ảnh", 5, 50, 12, key="_inline_img_max")

    # API key input for sources that need one (unless env var is present)
    api_key = _api_key_from_env(source)
    needs_key = source in _KEY_REQUIRED_SOURCES
    if (needs_key or source == "openverse") and not api_key:
        hint = _SOURCE_KEY_HINT.get(source, "")
        api_key = st.text_input(
            f"🔑 API key cho {labels[keys.index(source)]}",
            value=st.session_state.get("_inline_img_key_" + source, ""),
            key="_inline_img_key_" + source,
            type="password",
            help=("Lấy key miễn phí tại: " + hint) if hint else None,
            placeholder="Dán key vào đây (chỉ lưu trong phiên này)",
        ).strip()
        if source in _KEY_REQUIRED_SOURCES and not api_key:
            st.caption("Nhập API key ở trên để tìm từ nguồn này (hoặc đặt biến môi trường).")

    if st.button("Tìm kiếm", key="_inline_img_search_btn", type="primary"):
        if not query.strip():
            st.warning("Nhập địa điểm hoặc keywords trước khi tìm.")
        else:
            with st.spinner("Đang tìm kiếm..."):
                try:
                    results = search_images(
                        query.strip(),
                        num_results=max_results,
                        source=source,
                        api_keys={source: api_key} if api_key else None,
                    )
                except Exception as exc:
                    st.error(f"Lỗi tìm kiếm: {exc}")
                    results = []
            if not results:
                st.info("Không tìm thấy ảnh nào. Thử địa điểm khác, giảm số lượng ảnh, hoặc đổi nguồn.")
            else:
                st.session_state["_inline_img_results"] = results
                st.session_state["_inline_img_query_display"] = query.strip()
                st.session_state["_inline_img_source_display"] = src_index

    results = st.session_state.get("_inline_img_results")
    if not results:
        return

    display_query = st.session_state.get("_inline_img_query_display", "")
    st.caption(
        f'{len(results)} kết quả cho "{display_query}" - bấm Tải để lưu từng ảnh, '
        f"hoặc Tải tất cả bên dưới. Ảnh nguồn {labels[keys.index(source)]}."
    )

    # License-aware note: when the source attaches license/author, remind to credit.
    if any(getattr(r, "license", "") or getattr(r, "author", "") for r in results):
        st.caption("Nguồn này kèm giấy phép/tác giả - khi tải sẽ ghi file sources.tsv để dễ ghi credit.")

    # Download folder + batch download + crop ratio
    download_dir = Path(
        st.session_state.get("_inline_img_dir", "")
        or str(Path.home() / "Videos" / "FrameForge" / "images")
    )
    col_dir, col_crop, col_all = st.columns([3, 2, 1])
    with col_dir:
        st.text_input(
            "📁 Thư mục lưu ảnh",
            value=str(download_dir),
            key="_inline_img_dir",
        )
    with col_crop:
        crop_label = st.selectbox(
            "Tỷ lệ crop khi tải",
            [_CROP_LABELS[c] for c in _CROP_CHOICES],
            index=0,
            key="_inline_img_crop",
        )
        crop_ratio = _CROP_CHOICES[[_CROP_LABELS[c] for c in _CROP_CHOICES].index(crop_label)]
    with col_all:
        st.write("")
        if st.button("📥 Tải tất cả", key="_inline_img_dl_all", type="primary", use_container_width=True):
            with st.spinner(f"Đang tải {len(results)} ảnh..."):
                outcome = download_results(
                    results,
                    download_dir,
                    crop_ratio=crop_ratio,
                )
            saved = outcome["paths"]
            failed = outcome["failed"]
            if saved:
                msg = f"Đã lưu {len(saved)}/{len(results)} ảnh vào `{download_dir}`"
                if outcome.get("sources_file"):
                    msg += f" (kèm {outcome['sources_file'].name})"
                st.success(msg)
            else:
                st.error("Không tải được ảnh nào. Kiểm tra lại thư mục hoặc thử lại sau.")
            if failed:
                with st.expander(f"⚠️ {len(failed)} ảnh lỗi"):
                    for line in failed:
                        st.code(line, language=None)

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
            if img.license or img.author:
                st.caption(f"License: {img.license or '?'}" + (f" · {img.author[:40]}" if img.author else ""))
            if st.button(f"Tải #{i + 1}", key=f"_dl_img_{i}"):
                try:
                    saved = download_image(img.url, download_dir, crop_ratio=crop_ratio)
                    st.success(f"Đã lưu: {saved.name}")
                except Exception as exc:
                    st.error(f"Lỗi tải: {exc}")

    st.caption("Nguồn ảnh: DuckDuckGo / Wikimedia Commons (CC) / Openverse / Pexels / Pixabay / Unsplash.")
