#!/usr/bin/env python3
"""Validate PyInstaller build outputs. Runs in CI after build step."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REQUIRED_MODULES = [
    "persistent_queue.py",
    "timeline_utils.py",
    "queue_per_video.py",
    "video_screenshot_advanced.py",
    "streamlit_app.py",
    "core/utils.py",
    "core/config.py",
    "core/pipeline.py",
    "core/resources.py",
    "core/manifest.py",
    "core/errors.py",
    "core/network.py",
    "core/cli.py",
    "ui/download_section.py",
    "ui/session.py",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate packaged build outputs")
    parser.add_argument("--dist", default="dist", help="Path to dist/ directory")
    parser.add_argument("--vendor", default="vendor/ffmpeg", help="Path to vendor/ffmpeg/")
    parser.add_argument("--version", required=True, help="Expected version string")
    args = parser.parse_args()

    dist = Path(args.dist)
    vendor = Path(args.vendor)
    errors: list[str] = []

    # 1. Check version file
    version_file = Path("frameforge_version.txt")
    if not version_file.exists():
        errors.append("frameforge_version.txt does not exist")
    else:
        actual = version_file.read_text(encoding="utf-8").strip()
        if actual != args.version:
            errors.append(f"frameforge_version.txt contains '{actual}', expected '{args.version}'")
        else:
            print(f"  version: {actual} OK")

    # 2. Find exe
    if not dist.exists():
        errors.append(f"{dist} directory does not exist")
    else:
        exes = list(dist.rglob("*.exe"))
        if not exes:
            errors.append("No .exe files found in dist/")
            print("  dist/ contents:")
            for f in sorted(dist.rglob("*")):
                if f.is_file():
                    print(f"    {f}")
        else:
            print(f"  exe: {exes[0]}")

    # 3. Check required modules — use pathlib to match relative paths
    all_py = {str(f.relative_to(dist)).replace("\\", "/") for f in dist.rglob("*.py")} if dist.exists() else set()
    for module in REQUIRED_MODULES:
        norm_module = module.replace("\\", "/")
        if norm_module in all_py:
            print(f"  module: {module} OK")
        else:
            # Also check if it's under _internal/ (PyInstaller 6.x)
            if any(norm_module in p for p in all_py):
                print(f"  module: {module} OK (found under _internal/)")
            else:
                errors.append(f"Required module not packaged: {module}")
                # Show what we DO have
                basename = module.split("/")[-1]
                matches = [p for p in all_py if p.endswith("/" + basename)]
                if matches:
                    print(f"  module: {module} MISSING (but found: {matches[0]})")
                else:
                    print(f"  module: {module} MISSING (not found anywhere)")

    # 4. Check styles.css
    css_files = list(dist.rglob("styles.css")) if dist.exists() else []
    if css_files:
        print(f"  styles.css: {css_files[0]}")
    else:
        errors.append("Required UI asset not packaged: styles.css")

    # 5. Check vendor ffmpeg
    for name in ("ffmpeg.exe", "ffprobe.exe", "BUILD_METADATA.txt"):
        path = vendor / name
        if path.exists():
            print(f"  vendor: {name} OK")
        else:
            errors.append(f"Embedded {name} was not found")

    # Result
    if errors:
        print(f"\nFAILED with {len(errors)} error(s):")
        for e in errors:
            print(f"  ERROR: {e}")
        return 1

    print("\nAll validation checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
