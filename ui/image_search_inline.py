"""Inline image search - renders inside the main app (no page config).

Multiple image sources are supported:
- DuckDuckGo Images (default, no key) - primary engine
- Wikimedia Commons (no key) - CC / public domain, license + author attached
- Openverse (no key; optional token raises rate limits) - CC aggregate
- Pexels / Pixabay / Unsplash - need a free API key (env FRAMEFORGE_*_API_KEY,
  typed inline, or saved encrypted on this machine via core/key_store.py)

Optional aspect-ratio crop is applied with Pillow when downloading.
"""

from __future__ import annotations

import streamlit as st
from pathlib import Path

from core import key_store
from core.google_images import (
    CROP_RATIOS,
    IMAGE_SOURCES,
    _KEY_REQUIRED_SOURCES,
    ImageSearchAuthError,
    download_image,
    download_results,
    search_images,
    validate_api_key,
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


def _auth_error_message(source_label: str, status: int, used_env: str = "", stored: bool = False) -> str:
    """User-facing message when a keyed source rejects the key (401/403).

    Names the source and cause, and hints where to fix the key: the env var
    that supplied it, the encrypted store (re-enter it), or the search box.
    """
    message = (
        f"\U0001f511 {source_label} t\u1eeb ch\u1ed1i API key (HTTP {status}): "
        "key b\u1ecb t\u1eeb ch\u1ed1i/h\u1ebft h\u1ea1n \u2014 ki\u1ec3m tra l\u1ea1i key."
    )
    if used_env:
        message += f" Key \u0111ang l\u1ea5y t\u1eeb bi\u1ebfn m\u00f4i tr\u01b0\u1eddng {used_env} \u2014 ki\u1ec3m tra/\u0111\u1ed5i key \u1edf \u0111\u00f3."
    elif stored:
        message += (
            " Key \u0111ang l\u01b0u tr\u00ean m\u00e1y \u2014 b\u1ecf tick \u201c\U0001f4be L\u01b0u key tr\u00ean "
            "m\u00e1y n\u00e0y\u201d r\u1ed3i b\u1ea5m T\u00ecm ki\u1ebfm \u0111\u1ec3 nh\u1eadp key m\u1edbi."
        )
    else:
        message += " Nh\u1eadp l\u1ea1i key \u1edf \u00f4 ph\u00eda tr\u00ean r\u1ed3i b\u1ea5m Ki\u1ec3m tra key."
    return message


def _key_origin_line(origin: str, env_name: str = "") -> str:
    """Calm one-line statement of which key served a completed search.

    ``origin`` is one of "env" / "store" / "session"; returns "" for
    anything else so anonymous/keyless sources stay silent.  Never contains
    the key itself - not even a masked form.
    """
    if origin == "env":
        return f"\u0110\u00e3 d\u00f9ng key t\u1eeb bi\u1ebfn m\u00f4i tr\u01b0\u1eddng `{env_name}`."
    if origin == "store":
        return "\u0110\u00e3 d\u00f9ng key \u0111\u00e3 l\u01b0u tr\u00ean m\u00e1y (m\u00e3 h\u00f3a)."
    if origin == "session":
        return "\u0110\u00e3 d\u00f9ng key nh\u1eadp trong phi\u00ean n\u00e0y."
    return ""


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
        source_label = labels[keys.index(source)]
    with col_count:
        max_results = st.slider("Số ảnh", 5, 50, 12, key="_inline_img_max")

    # API key input for sources that need one (unless env var is present).
    # Keys can be saved encrypted on this machine (Windows DPAPI) so they
    # don't have to be retyped every session.  The resolution rule (explicit
    # > env var > store) is owned by core/key_store.resolve_api_key(); this
    # widget only renders what that rule reports.
    needs_key = source in _KEY_REQUIRED_SOURCES
    store = key_store.default_store()
    resolution = store.resolve(source)  # no explicit yet -> env > store
    api_key = resolution.value
    stored_key = resolution.stored
    save_key: bool | None = None
    persist_action: str | None = None  # "save" / "delete" when this run persists
    if (needs_key or source == "openverse") and not resolution.from_env:
        hint = _SOURCE_KEY_HINT.get(source, "")
        api_key = st.text_input(
            f"🔑 API key cho {source_label}",
            value=st.session_state.get("_inline_img_key_" + source, stored_key),
            key="_inline_img_key_" + source,
            type="password",
            help=("Lấy key miễn phí tại: " + hint) if hint else None,
            placeholder="Dán key vào đây",
        ).strip()
        if needs_key and not api_key:
            st.caption("Nhập API key ở trên để tìm từ nguồn này (hoặc đặt biến môi trường).")
        save_col, check_col = st.columns([3, 1.4])
        with save_col:
            save_key = st.checkbox(
                "💾 Lưu key trên máy này (mã hóa)",
                value=bool(stored_key),
                key="_inline_img_save_" + source,
                help="Key được mã hóa (Windows: DPAPI) và chỉ tài khoản này đọc được. "
                     "Bỏ tick rồi bấm Tìm kiếm để xóa key đã lưu.",
            )
        with check_col:
            validate_clicked = st.button(
                "Kiểm tra key",
                key="_inline_img_validate_btn",
                use_container_width=True,
                help="Gọi thử nguồn ảnh bằng key vừa nhập — chỉ lưu nếu key hoạt động.",
            )
        # This run's persist action is decided ONCE, before the stored-key
        # caption above the search button: the button's pressed state is
        # already in session_state at run start, so a delete requested below
        # cannot leave a stale "key đã được lưu" caption above it.  The
        # search branch below only executes the action, never re-decides it.
        search_clicked = bool(st.session_state.get("_inline_img_search_btn", False))
        if search_clicked and save_key is not None:
            if api_key and save_key:
                persist_action = "save"
            elif not save_key and stored_key:
                persist_action = "delete"
        if stored_key and persist_action != "delete":
            st.caption("✅ Key đã được lưu trên máy (mã hóa).")
        # Opt-in key validation: probe the backend BEFORE persisting, so a
        # typo'd key is caught at save time instead of on a later confusing
        # search.  Separate from Tìm kiếm - a normal search never waits on
        # this.  A rejected key is never written to the store.
        if validate_clicked:
            if not api_key:
                st.warning("Nhập key vào ô phía trên trước khi kiểm tra.")
            else:
                with st.spinner("Đang kiểm tra key..."):
                    try:
                        validate_api_key(source, api_key)
                    except ImageSearchAuthError as exc:
                        # The TYPED key was rejected (never the stored one),
                        # so the hint is the re-enter one, not the store one.
                        st.error(_auth_error_message(source_label, exc.status))
                    except Exception as exc:
                        st.error(f"Không kiểm tra được key: {exc}")
                    else:
                        try:
                            store.set(source, api_key)
                        except Exception as exc:
                            st.error(f"Key hoạt động nhưng không lưu được: {exc}")
                        else:
                            st.success(
                                f"✅ Key {source_label} hoạt động — đã lưu mã hóa trên máy này."
                            )

    if st.button("Tìm kiếm", key="_inline_img_search_btn", type="primary"):
        if not query.strip():
            st.warning("Nhập địa điểm hoặc keywords trước khi tìm.")
        else:
            with st.spinner("Đang tìm kiếm..."):
                # Persist / remove the key per the checkbox.  The action was
                # decided above the caption (persist_action); execute it here
                # and confirm in the SAME run as the click - the user must not
                # wait for a rerun.
                if persist_action == "save":
                    try:
                        store.set(source, api_key)
                    except Exception as exc:
                        st.error(f"Không lưu được key: {exc} — vẫn dùng key cho phiên này.")
                    else:
                        st.success(
                            f"🔑 Đã lưu key {source_label} mã hóa trên máy này."
                        )
                elif persist_action == "delete":
                    store.delete(source)
                    st.success(f"Đã xóa key {source_label} đã lưu trên máy.")
                auth_rejected = False
                # Store state AFTER this run's persist action: a just-deleted
                # key must not classify as "store" - it no longer serves.
                stored_key_now = stored_key and persist_action != "delete"
                # Which key will serve this search?  env > stored (prefill or
                # engine fallback when the box was cleared) > typed session.
                # Only ever set for keyed sources, and never on auth rejection.
                key_origin: tuple[str, str] | None = None
                if resolution.from_env:
                    key_origin = ("env", resolution.env_name)
                elif stored_key_now and (not api_key or api_key == stored_key):
                    key_origin = ("store", "")
                elif api_key:
                    key_origin = ("session", "")
                try:
                    results = search_images(
                        query.strip(),
                        num_results=max_results,
                        source=source,
                        api_keys={source: api_key} if api_key else None,
                    )
                except ImageSearchAuthError as exc:
                    # Rejected key (401/403): distinct message naming the source
                    # and hinting where the key came from.  Never let it look
                    # like an ordinary "no images found" search.
                    auth_rejected = True
                    st.error(_auth_error_message(
                        source_label,
                        exc.status,
                        used_env=resolution.env_name,
                        stored=bool(stored_key_now),
                    ))
                    results = []
                except Exception as exc:
                    st.error(f"Lỗi tìm kiếm: {exc}")
                    results = []
            if not results:
                if not auth_rejected:
                    st.info("Không tìm thấy ảnh nào. Thử địa điểm khác, giảm số lượng ảnh, hoặc đổi nguồn.")
            else:
                st.session_state["_inline_img_results"] = results
                st.session_state["_inline_img_query_display"] = query.strip()
                st.session_state["_inline_img_source_display"] = src_index
            if key_origin and not auth_rejected:
                # Same-run, calm outcome line: which key served this search.
                st.caption(_key_origin_line(key_origin[0], key_origin[1]))

    results = st.session_state.get("_inline_img_results")
    if not results:
        return

    display_query = st.session_state.get("_inline_img_query_display", "")
    st.caption(
        f'{len(results)} kết quả cho "{display_query}" - bấm Tải để lưu từng ảnh, '
        f"hoặc Tải tất cả bên dưới. Ảnh nguồn {source_label}."
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
