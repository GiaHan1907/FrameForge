"""Video manifest I/O for FrameForge.

Extracted from video_screenshot_advanced.py to separate concerns.
Each processed video gets a .frameforge_manifest.json listing its
output files and the config that produced them.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from core.utils import atomic_write_json


def verify_video_manifest(video: Path, output_dir: Path, *, repair: bool = False) -> dict[str, object]:
    """Kiểm tra manifest output có khớp với file thực tế không."""
    manifest_path = output_dir / ".frameforge_manifest.json"
    if not manifest_path.is_file():
        return {"status": "missing", "path": str(manifest_path), "missing_files": [], "unexpected_files": []}
    try:
        import json
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"status": "invalid", "path": str(manifest_path), "missing_files": [], "unexpected_files": []}
    listed = payload.get("files", []) if isinstance(payload, dict) else []
    listed = [str(item) for item in listed] if isinstance(listed, list) else []
    missing = [item for item in listed if not (output_dir / item).is_file()]
    unexpected = sorted(
        str(path.relative_to(output_dir))
        for path in output_dir.iterdir()
        if path.is_file() and not path.name.startswith(".") and path.name not in listed
    )
    status = "valid" if not missing and not unexpected else "mismatch"
    if repair and isinstance(payload, dict):
        payload["files"] = sorted(
            str(path.relative_to(output_dir))
            for path in output_dir.iterdir()
            if path.is_file() and path.name != manifest_path.name and not path.name.startswith(".")
        )
        payload["repaired_at"] = time.time()
        atomic_write_json(manifest_path, payload)
        missing, unexpected, status = [], [], "repaired"
    return {"status": status, "path": str(manifest_path), "missing_files": missing, "unexpected_files": unexpected}


def write_video_manifest(video: Path, output_dir: Path, args: argparse.Namespace, reports: dict[str, object]) -> Path:
    """Ghi manifest .frameforge_manifest.json cho video đã xử lý."""
    manifest_path = output_dir / ".frameforge_manifest.json"
    files = sorted(
        str(path.relative_to(output_dir))
        for path in output_dir.iterdir()
        if path.is_file() and path.name != manifest_path.name and not path.name.startswith(".")
    )
    safe_config = {
        "count": getattr(args, "count", None),
        "every": getattr(args, "every", None),
        "max_screenshots": getattr(args, "max_screenshots", 0),
        "target_count_after_filter": getattr(args, "target_count_after_filter", False),
        "scene_detection": getattr(args, "scene_detection", False),
        "best_frame_per_scene": getattr(args, "best_frame_per_scene", False),
        "min_sharpness": getattr(args, "min_sharpness", 0),
        "motion_blur_threshold": getattr(args, "motion_blur_threshold", 0),
        "duplicate_threshold": getattr(args, "duplicate_threshold", 0),
        "format": getattr(args, "format", "jpg"),
        "crop_ratio": getattr(args, "crop_ratio", "Không crop"),
        "width": getattr(args, "width", None),
    }
    payload = {
        "manifest_version": 1,
        "updated_at": time.time(),
        "video": str(video.resolve()),
        "video_size": video.stat().st_size if video.is_file() else None,
        "video_mtime_ns": video.stat().st_mtime_ns if video.exists() else None,
        "files": files,
        "config": safe_config,
        "report": reports,
    }
    atomic_write_json(manifest_path, payload)
    return manifest_path
