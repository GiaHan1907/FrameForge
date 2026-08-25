# UI preview verification

Date: 2026-08-25

The source Streamlit app rendered successfully at http://127.0.0.1:8502 with HTTP 200. The visible layout is a two-column desktop layout with sidebar controls and a main content area. The preview section is conditional and was not visible until a video is uploaded or downloaded, so the CSS was verified statically and the app startup was verified dynamically.

Preview change implemented in streamlit_app.py:
- st.video is placed in a 1.55 / 0.85 two-column layout with a compact explanatory card.
- st.video uses width=720.
- CSS targets div[data-testid="stVideo"] with max-width 720px, max-height 420px on the video element, centered margins, dark background, rounded borders, and object-fit contain.
- The normal initial UI now renders without startup errors after the change.


A 960x540 sample MP4 was uploaded successfully. The rendered preview section showed the video in a compact left column and a Preview gọn note card in the right column. The preview no longer spans the full main content width; the player is centered and constrained by the new CSS. Streamlit rendered the updated section without a runtime error.


The output-folder UI rendered successfully after reload. It showed two path text inputs and two folder-picker buttons before the public download section. The sample processing completed without runtime errors and displayed the selected screenshot output path. The sample was intentionally a solid-color video and produced 0 saved frames because the blur/sharpness filter rejected it; this is expected test behavior, not a UI failure.


After reloading the updated local app, the public release check was visible in the UI as: `Có bản cập nhật FrameForge 0.1.1` with one `Cập nhật ngay` button. The public manifest endpoint returned version 0.1.1 with a canonical installer URL and 64-character SHA-256. The app_config unit test passed. The current UI change also uses compact path-picker rows so text input and `Chọn…` button share one row per output column.


The refreshed UI showed exactly one `Cập nhật ngay` button because the local source version is 0.0.0 while the public latest release is 0.1.1. The public startup check then reported `Đã kiểm tra cập nhật gần đây.` on the next rerun, confirming the 24-hour state cache path. The output-folder controls rendered with compact path inputs and `Chọn…` buttons; no duplicate widget-key or render error appeared.
