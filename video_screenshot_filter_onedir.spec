# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules


packages = ["streamlit", "altair", "pydeck", "PIL", "cv2", "pandas", "numpy", "yt_dlp"]
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
            ("core/config.py", "core")
    ("core/resources.py", "core"),
    ("core/manifest.py", "core"),
    ("ui/styles.css", "ui"),
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
