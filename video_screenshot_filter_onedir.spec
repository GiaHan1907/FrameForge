# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules


packages = ["streamlit", "altair", "pydeck", "PIL", "cv2", "pandas", "numpy", "yt_dlp", "pyarrow"]
datas = []
binaries = []
hiddenimports = []

for package in packages:
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

hiddenimports += collect_submodules("streamlit")
hiddenimports += collect_submodules("streamlit.web")
hiddenimports += collect_submodules("streamlit.runtime")
hiddenimports += collect_submodules("yt_dlp")
hiddenimports += ["tkinter", "tkinter.filedialog"]

ffmpeg_dir = Path("vendor") / "ffmpeg"
for binary_name in ("ffmpeg.exe", "ffprobe.exe"):
    binary_path = ffmpeg_dir / binary_name
    if binary_path.exists():
        binaries.append((str(binary_path), "vendor/ffmpeg"))
for documentation_path in ffmpeg_dir.glob("*.txt"):
    datas.append((str(documentation_path), "vendor/ffmpeg"))

datas += [
    ("streamlit_app.py", "."),
    ("video_screenshot_advanced.py", "."),
    ("video_downloader.py", "."),
    ("updater.py", "."),
    ("app_update.py", "."),
    ("app_config.py", "."),
    ("persistent_queue.py", "."),
    ("timeline_utils.py", "."),
    ("queue_per_video.py", "."),
    ("core/__init__.py", "core"),
    ("core/utils.py", "core"),
    ("core/config.py", "core"),
    ("core/cv2_helpers.py", "core"),
    ("core/pipeline.py", "core"),
    ("core/resources.py", "core"),
    ("core/targets.py", "core"),
    ("core/manifest.py", "core"),
    ("core/errors.py", "core"),
    ("core/analysis.py", "core"),
    ("core/network.py", "core"),
    ("core/cli.py", "core"),
    ("core/checkpoint.py", "core"),
    ("core/workers.py", "core"),
    ("core/cleanup.py", "core"),
    ("core/google_images.py", "core"),
    ("ui/logic.py", "ui"),
    ("ui/download_section.py", "ui"),
    ("ui/image_search_inline.py", "ui"),
    ("ui/processing.py", "ui"),
    ("ui/processing_view.py", "ui"),
    ("ui/session.py", "ui"),
    ("ui/wizard.py", "ui"),
    ("ui/widgets.py", "ui"),
    ("ui/sidebar.py", "ui"),
    ("ui/preview.py", "ui"),
    ("ui/preview_section.py", "ui"),
    ("ui/presets.py", "ui"),
    ("ui/desktop.py", "ui"),
    ("ui/image_search.py", "ui"),
    ("ui/queue_ui.py", "ui"),
    ("ui/dashboard.py", "ui"),
    ("ui/timeline.py", "ui"),
    ("ui/styles.css", "ui"),
    ("frameforge/__init__.py", "frameforge"),
    ("frameforge/__main__.py", "frameforge"),
    ("frameforge_version.txt", "."),
]


a = Analysis(
    ["windows_launcher.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VideoScreenshotFilter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VideoScreenshotFilter",
)
