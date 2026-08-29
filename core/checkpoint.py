"""Checkpoint, scene-cache, and duplicate-index I/O.

Extracted from ``core/pipeline.py`` to keep the checkpoint subsystem
independently testable and readable.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from core.utils import atomic_write_json as _atomic_write_json
from core.utils import read_json as _read_json


# ── Signature helpers ─────────────────────────────────────────────────


def processing_signature(args) -> str:
    values = {
        key: str(value)
        for key, value in vars(args).items()
        if key not in {
            "workers", "retries", "retry_delay", "resume",
            "checkpoint_path", "cache_root", "duplicate_root", "queue_db",
        }
    }
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def scene_cache_key(video: Path, metadata: dict[str, float | int], args) -> str:
    payload = {
        "cache_version": 2,
        "video": str(video.resolve()),
        "size": video.stat().st_size,
        "mtime_ns": video.stat().st_mtime_ns,
        "metadata": metadata,
        "scene_threshold": float(args.scene_threshold),
        "min_scene_gap": float(args.min_scene_gap),
        "flash_return_ratio": float(args.flash_return_ratio),
        "flash_brightness_threshold": float(args.flash_brightness_threshold),
        "scene_confirmations": int(args.scene_confirmations),
        "analysis_width": int(args.analysis_width),
        "analysis_fps": float(args.analysis_fps),
        "best_frame_per_scene": bool(args.best_frame_per_scene),
        "min_sharpness": float(args.min_sharpness),
        "motion_blur_threshold": float(getattr(args, "motion_blur_threshold", 0.0)),
        "max_screenshots": int(getattr(args, "max_screenshots", 0) or 0),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_run_signature(args) -> str:
    """Tạo chữ ký ổn định từ cấu hình xử lý, không phụ thuộc path runtime."""
    ignored = {
        "queue_db", "queue_run_signature", "checkpoint_path",
        "resume", "cache_root", "duplicate_root",
    }
    values = {key: value for key, value in vars(args).items() if key not in ignored}
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ── Checkpoint I/O ───────────────────────────────────────────────────


def checkpoint_path(output_root: Path, args) -> Path:
    configured = getattr(args, "checkpoint_path", None)
    return Path(configured) if configured else output_root / ".frameforge_checkpoint.json"


def load_checkpoint(path: Path) -> dict[str, object]:
    value = _read_json(path)
    return value if value and value.get("version") == 1 else {"version": 1, "completed": {}}


def save_checkpoint(path: Path, run_signature: str, completed: dict[str, object]) -> None:
    _atomic_write_json(
        path,
        {
            "version": 1,
            "updated_at": time.time(),
            "run_signature": run_signature,
            "completed": completed,
        },
    )


# ── Scene cache I/O ──────────────────────────────────────────────────


def load_scene_cache(path: Path, key: str) -> dict[str, object] | None:
    value = _read_json(path)
    if not value or value.get("cache_version") != 2 or value.get("cache_key") != key:
        return None
    selected = value.get("selected_times")
    scene_times = value.get("scene_times")
    if not isinstance(selected, list) or not isinstance(scene_times, list):
        return None
    return value


def save_scene_cache(
    path: Path, key: str, video: Path,
    selected_times: list[float], scene_times: list[float],
) -> None:
    _atomic_write_json(
        path,
        {
            "cache_version": 2,
            "cache_key": key,
            "video": str(video),
            "created_at": time.time(),
            "selected_times": [round(float(item), 3) for item in selected_times],
            "scene_times": [round(float(item), 3) for item in scene_times],
        },
    )


# ── Duplicate index I/O ──────────────────────────────────────────────


def _dhash_bucket_keys(hash_value: int) -> tuple[str, ...]:
    """Tạo 8 bucket theo từng byte của dHash 64-bit.

    Hai hash có khoảng cách Hamming <= 6 phải cùng ít nhất một bucket byte,
    nên cách tra cứu này vẫn đầy đủ cho threshold mặc định mà không quét toàn
    bộ index. Index v1 chỉ có mảng hash vẫn được nạp và tự nâng cấp khi ghi.
    """
    value = int(hash_value) & ((1 << 64) - 1)
    return tuple(f"{offset}:{(value >> (offset * 8)) & 0xFF:02x}" for offset in range(8))


def _build_duplicate_buckets(hashes: set[int]) -> dict[str, set[int]]:
    buckets: dict[str, set[int]] = {}
    for hash_value in hashes:
        for key in _dhash_bucket_keys(hash_value):
            buckets.setdefault(key, set()).add(int(hash_value))
    return buckets


def load_duplicate_index(path: Path) -> tuple[set[int], dict[str, set[int]]]:
    value = _read_json(path)
    raw = value.get("hashes", []) if value else []
    hashes = {
        int(item) for item in raw
        if isinstance(item, (int, str)) and str(item).isdigit()
    } if isinstance(raw, list) else set()
    raw_buckets = value.get("buckets") if value else None
    buckets: dict[str, set[int]] = {}
    if isinstance(raw_buckets, dict):
        for key, raw_values in raw_buckets.items():
            if not isinstance(key, str) or not isinstance(raw_values, list):
                continue
            values = {
                int(item) for item in raw_values
                if isinstance(item, (int, str)) and str(item).isdigit()
            }
            values.intersection_update(hashes)
            if values:
                buckets[key] = values
    indexed_hashes: set[int] = set()
    for values in buckets.values():
        indexed_hashes.update(values)
    if indexed_hashes != hashes:
        buckets = _build_duplicate_buckets(hashes) if hashes else {}
    return hashes, buckets


def load_duplicate_hashes(path: Path) -> set[int]:
    return load_duplicate_index(path)[0]


def save_duplicate_hashes(
    path: Path, hashes: set[int],
    buckets: dict[str, set[int]] | None = None,
) -> None:
    index = buckets if buckets is not None else _build_duplicate_buckets(hashes)
    _atomic_write_json(
        path,
        {
            "version": 2,
            "updated_at": time.time(),
            "hashes": sorted(int(item) for item in hashes),
            "buckets": {
                key: sorted(int(item) for item in values)
                for key, values in sorted(index.items()) if values
            },
        },
    )


# ── Path helpers (used by checkpoint I/O callers) ────────────────────


def scene_cache_path(video: Path, cache_root: Path) -> Path:
    identity = hashlib.sha1(str(video.resolve()).encode("utf-8")).hexdigest()[:16]
    return cache_root / f"{video.stem}.{identity}.scene-cache.json"


def duplicate_index_path(video: Path, duplicate_root: Path) -> Path:
    identity = hashlib.sha1(str(video.resolve()).encode("utf-8")).hexdigest()[:16]
    return duplicate_root / f"{video.stem}.{identity}.hashes.json"
