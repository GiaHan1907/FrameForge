"""Pure pipeline helpers — no cv2/numpy dependency.

All functions in this module are intentionally kept free of OpenCV/NumPy so
that ``core/cli.py`` can import them without triggering the heavy cv2 import
chain.  This also makes every function here testable with standard unittest.

Sub-modules
-----------
- ``core.checkpoint`` — checkpoint, scene-cache, duplicate-index I/O
- ``core.workers`` — worker recommendation, arg validators, metric requirements
- ``core.cleanup`` — cleanup helpers, formatting, video discovery, stage timing

This module re-exports every public symbol from those sub-modules for
backward compatibility.  New code should import directly from the
appropriate sub-module.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from typing import Callable
from pathlib import Path

from core.utils import format_bytes

# ── Re-export sub-modules (backward compatibility) ────────────────────

from core.checkpoint import (  # noqa: F401, E402
    processing_signature,
    scene_cache_key,
    build_run_signature,
    checkpoint_path,
    load_checkpoint,
    save_checkpoint,
    load_scene_cache,
    save_scene_cache,
    _dhash_bucket_keys,
    _build_duplicate_buckets,
    load_duplicate_index,
    load_duplicate_hashes,
    save_duplicate_hashes,
    scene_cache_path,
    duplicate_index_path,
)

from core.workers import (  # noqa: F401, E402
    _available_memory_gb,
    recommend_workers,
    worker_value,
    recommended_extract_workers,
    adaptive_extract_workers,
    positive_float,
    non_negative_float,
    positive_int,
    non_negative_int,
    threshold_01,
    MetricRequirements,
    metric_requirements,
)

from core.cleanup import (  # noqa: F401, E402
    _path_size_bytes,
    cleanup_frameforge_temp_dirs,
    cleanup_frameforge_cache,
    find_videos,
    timestamp_label,
    new_stage_timings,
    record_stage_timing,
)

# ── Exceptions ────────────────────────────────────────────────────────


class ProcessingCancelled(RuntimeError):
    """Được phát ra khi người dùng yêu cầu dừng pipeline xử lý."""


class InsufficientDiskSpace(RuntimeError):
    """Được phát ra trước khi tạo dữ liệu tạm nếu ổ đĩa không đủ chỗ trống."""


# ── Type aliases ──────────────────────────────────────────────────────

ProgressCallback = Callable[[Path, str, float, str], None]
CancelCheck = Callable[[], bool]

# ── Constants ─────────────────────────────────────────────────────────

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".ts", ".mts"
}
REFERENCE_ANALYSIS_WIDTH = 640
CROP_RATIO_LABELS = ("Không crop", "16:9", "9:16", "4:5", "1:1")
CROP_RATIO_VALUES = {
    "Không crop": None,
    "none": None,
    "16:9": 16 / 9,
    "9:16": 9 / 16,
    "4:5": 4 / 5,
    "1:1": 1.0,
}
ENCODE_PROFILE_LABELS = ("Nhanh", "Chất lượng cao")
ENCODE_PROFILES = {
    "Nhanh": {"jpeg_optimize": False, "webp_method": 3, "png_optimize": False},
    "Chất lượng cao": {"jpeg_optimize": True, "webp_method": 6, "png_optimize": True},
}


# ── Cancellation / progress helpers ───────────────────────────────────


def cancellation_requested(cancel_event=None) -> bool:
    if cancel_event is None:
        return False
    if callable(cancel_event):
        return bool(cancel_event())
    is_set = getattr(cancel_event, "is_set", None)
    return bool(is_set()) if callable(is_set) else bool(cancel_event)


def check_cancelled(cancel_event=None) -> None:
    if cancellation_requested(cancel_event):
        raise ProcessingCancelled("Đã hủy theo yêu cầu người dùng.")


def wait_if_paused(pause_event=None, cancel_event=None, poll_seconds: float = 0.2) -> None:
    """Chờ ở ranh giới video khi queue bị pause, nhưng vẫn phản hồi cancel."""
    while pause_event is not None and pause_event.is_set():
        check_cancelled(cancel_event)
        time.sleep(max(0.05, float(poll_seconds)))


def emit_progress(
    callback: ProgressCallback | None,
    video: Path,
    phase: str,
    fraction: float,
    message: str,
) -> None:
    if callback is None:
        return
    try:
        callback(video, phase, min(1.0, max(0.0, float(fraction))), message)
    except Exception:
        # Progress UI không được phép làm hỏng pipeline xử lý.
        pass


# ── System helpers ────────────────────────────────────────────────────

_rss_cache: tuple[int, float] = (0, 0.0)
_RSS_CACHE_TTL: float = 5.0  # seconds — RSS changes slowly, 5s is plenty


def current_process_rss_bytes() -> int:
    """Đọc RSS của process hiện tại bằng stdlib, trả 0 nếu không đọc được.

    Results are cached for 5 seconds to avoid repeated ctypes FFI calls
    (~45us each on Windows).  RSS changes slowly enough for this TTL.
    """
    global _rss_cache
    now = time.time()
    cached, ts = _rss_cache
    if now - ts < _RSS_CACHE_TTL:
        return cached
    try:
        if sys.platform == "win32":
            import ctypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_ulong),
                    ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(ProcessMemoryCounters)
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(
                ctypes.windll.kernel32.GetCurrentProcess(),
                ctypes.byref(counters),
                counters.cb,
            )
            return int(counters.WorkingSetSize) if ok else 0
        statm = Path("/proc/self/statm")
        if statm.exists():
            resident_pages = int(statm.read_text(encoding="ascii").split()[1])
            return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
        resource = __import__("resource")
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value if sys.platform == "darwin" else value * 1024
    except (AttributeError, ImportError, OSError, TypeError, ValueError, IndexError):
        result = 0
    _rss_cache = (result, time.time())
    return result


def free_disk_bytes(path: Path) -> int:
    path.mkdir(parents=True, exist_ok=True)
    return int(shutil.disk_usage(path).free)


def ensure_free_disk_space(path: Path, required_bytes: int = 0, reserve_bytes: int = 512 * 1024**2) -> int:
    """Kiểm tra đủ dung lượng cho dữ liệu dự kiến và vùng đệm an toàn."""
    free = free_disk_bytes(path)
    needed = max(0, int(required_bytes)) + max(0, int(reserve_bytes))
    if free < needed:
        raise InsufficientDiskSpace(
            f"Ổ đĩa tại {path} chỉ còn {format_bytes(free)}, "
            f"cần tối thiểu {format_bytes(needed)} (gồm vùng đệm an toàn)."
        )
    return free
