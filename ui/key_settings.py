"""Settings-tab management surface for search API keys.

Lets the user see, per image-search source, whether a key is stored
(core/key_store.py, encrypted DPAPI), whether a FRAMEFORGE_* env var
overrides it, and delete a stored key - without opening each source's
search widget.  Keys are only ever shown masked (last 4 characters);
full keys never leave the encrypted store.

Deleting a stored key is two-step: the first Xóa click only arms a
confirmation bar (per source, session state), and the key is removed only
by a second explicit "Xóa lần nữa để xác nhận" click or abandoned via Hủy -
one accidental click can never destroy the only stored copy.

The row data comes from ui/logic.search_key_rows(), which is built on
core/key_store.py's owned resolution rule (resolve_api_key) - nothing is
re-derived here.
"""

from __future__ import annotations

import streamlit as st

from core import key_store
from ui.logic import search_key_rows

__all__ = ["render_settings_api_keys"]


def _armed_key(source: str) -> str:
    return f"_settings_key_armed_{source}"


def render_settings_api_keys(store: "key_store.ApiKeyStore | None" = None) -> None:
    """Render the per-source API-key list in the settings tab."""
    store = store or key_store.default_store()
    rows = search_key_rows(store)
    with st.expander("🔑 API key tìm ảnh theo địa điểm", expanded=False):
        st.caption(
            "Key được lưu mã hóa trên máy (DPAPI) và chỉ hiển thị dạng ẩn "
            "(4 ký tự cuối). Nếu có biến môi trường FRAMEFORGE_*_API_KEY, "
            "biến đó được ưu tiên hơn key đã lưu. Xóa key cần xác nhận 2 lần."
        )
        for row in rows:
            source = row["source"]
            armed = bool(st.session_state.get(_armed_key(source), False))
            if not row["stored"]:
                # a key removed elsewhere (e.g. the search widget) disarms us
                st.session_state.pop(_armed_key(source), None)
                armed = False

            cols = st.columns([1.6, 2.4, 1.2, 0.8])
            cols[0].markdown(f"**{row['label']}**")
            if not row["needs_key"]:
                cols[1].write("Không cần key")
                cols[2].write("—")
                cols[3].write("")
                continue
            if row["env_override"]:
                cols[1].markdown(f"⚠️ Được ghi đè bởi biến môi trường `{row['env_name']}`")
            elif row["stored"]:
                cols[1].write("Đã lưu trên máy (mã hóa)")
            else:
                cols[1].write("Chưa lưu — nhập key trong tab Tải video công khai")
            cols[2].markdown(f"`{row['stored_masked']}`" if row["stored"] else "—")
            if row["stored"]:
                if armed:
                    cols[3].markdown("⚠️ Đang chờ xác nhận")
                elif cols[3].button(
                    "🗑 Xóa",
                    key=f"_settings_key_delete_{source}",
                    help="Bấm để yêu cầu xóa; cần xác nhận lần nữa trước khi key bị xóa.",
                ):
                    st.session_state[_armed_key(source)] = True
                    st.rerun()
            else:
                cols[3].write("")

            # Two-step confirmation bar, below the row, only when armed.
            if row["stored"] and armed:
                warn_col, confirm_col, cancel_col = st.columns([3.4, 1.6, 0.7])
                warn_col.warning(
                    f"Xóa key đã lưu của **{row['label']}**? Không thể hoàn tác và "
                    "key không thể xem lại đầy đủ - chỉ 4 ký tự cuối được lưu hiển thị."
                )
                if confirm_col.button(
                    "Xóa lần nữa để xác nhận",
                    key=f"_settings_key_delete_confirm_{source}",
                ):
                    store.delete(source)
                    st.session_state.pop(_armed_key(source), None)
                    st.rerun()
                if cancel_col.button("Hủy", key=f"_settings_key_delete_cancel_{source}"):
                    st.session_state.pop(_armed_key(source), None)
                    st.rerun()