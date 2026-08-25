# FrameForge minimal profile findings

- PyInstaller syntax check: passed for all application Python modules.
- Profile: `video_screenshot_filter_minimal.spec`.
- Linux onedir measured size: **339,840,270 bytes / 324.10 MiB** before embedded Windows FFmpeg; the measurement excludes symlink targets being counted twice.
- Smoke test: packaged executable started Streamlit successfully and returned **HTTP 200** on `http://127.0.0.1:8501/`.
- Runtime log showed no `Traceback`, `ModuleNotFoundError`, `ImportError`, or `Exception`.
- Largest remaining directories: OpenCV native/libs about 153 MiB combined; Streamlit about 30 MiB; NumPy/native libs about 57 MiB combined; yt-dlp about 12 MiB.
- PyArrow, Pandas, PyDeck, Matplotlib, and Botocore were not present in the reported top-level package directories after the explicit excludes. Streamlit still ships a static `PlotlyChart` JavaScript asset, so excluding the Python `plotly` package does not remove every Plotly-related asset.
- This result is Linux-only and excludes Windows embedded FFmpeg. It is not a Windows size guarantee.
