"""Pure pipeline helpers — no cv2/numpy dependency.

All functions in this module are intentionally kept free of OpenCV/NumPy so
that ``core/cli.py`` can import them without triggering the heavy cv2 import
chain.  This also makes every function here testable with standard unittest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import time
from typing import Callable
from pathlib import Path

from dataclasses import dataclass

from core.utils import atomic_write_json as _atomic_write_json
from core.utils import read_json as _read_json
from core.utils import format_bytes

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


def current_process_rss_bytes() -> int:
    """Đọc RSS của process hiện tại bằng stdlib, trả 0 nếu không đọc được."""
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
        return 0


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


# ── Path helpers ──────────────────────────────────────────────────────


def scene_cache_path(video: Path, cache_root: Path) -> Path:
    identity = hashlib.sha1(str(video.resolve()).encode("utf-8")).hexdigest()[:16]
    return cache_root / f"{video.stem}.{identity}.scene-cache.json"


def duplicate_index_path(video: Path, duplicate_root: Path) -> Path:
    identity = hashlib.sha1(str(video.resolve()).encode("utf-8")).hexdigest()[:16]
    return duplicate_root / f"{video.stem}.{identity}.hashes.json"


def _path_size_bytes(path: Path) -> int:
    if path.is_file():
        try:
            return int(path.stat().st_size)
        except OSError:
            return 0
    total = 0
    try:
        for child in path.rglob("*"):
            if child.is_file():
                try:
                    total += int(child.stat().st_size)
                except OSError:
                    continue
    except OSError:
        return total
    return total


# ── Signature / checkpoint helpers ────────────────────────────────────


def processing_signature(args) -> str:
    values = {
        key: str(value)
        for key, value in vars(args).items()
        if key not in {"workers", "retries", "retry_delay", "resume", "checkpoint_path", "cache_root", "duplicate_root", "queue_db"}
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
    ignored = {"queue_db", "queue_run_signature", "checkpoint_path", "resume", "cache_root", "duplicate_root"}
    values = {key: value for key, value in vars(args).items() if key not in ignored}
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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


def save_scene_cache(path: Path, key: str, video: Path, selected_times: list[float], scene_times: list[float]) -> None:
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
    hashes = {int(item) for item in raw if isinstance(item, (int, str)) and str(item).isdigit()} if isinstance(raw, list) else set()
    raw_buckets = value.get("buckets") if value else None
    buckets: dict[str, set[int]] = {}
    if isinstance(raw_buckets, dict):
        for key, raw_values in raw_buckets.items():
            if not isinstance(key, str) or not isinstance(raw_values, list):
                continue
            values = {int(item) for item in raw_values if isinstance(item, (int, str)) and str(item).isdigit()}
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


def save_duplicate_hashes(path: Path, hashes: set[int], buckets: dict[str, set[int]] | None = None) -> None:
    index = buckets if buckets is not None else _build_duplicate_buckets(hashes)
    _atomic_write_json(
        path,
        {
            "version": 2,
            "updated_at": time.time(),
            "hashes": sorted(int(item) for item in hashes),
            "buckets": {key: sorted(int(item) for item in values) for key, values in sorted(index.items()) if values},
        },
    )


# ── Cleanup helpers ───────────────────────────────────────────────────


def cleanup_frameforge_temp_dirs(
    temp_root: Path | None = None,
    prefix: str = "video_screenshot_web_",
    older_than_seconds: int = 24 * 60 * 60,
    max_total_bytes: int | None = None,
) -> int:
    """Dọn work directory cũ theo tuổi và quota, không đụng thư mục đang dùng."""
    root = temp_root or Path(tempfile.gettempdir())
    cutoff = time.time() - max(0, older_than_seconds)
    candidates: list[tuple[Path, float, int]] = []
    try:
        paths = list(root.glob(f"{prefix}*"))
    except OSError:
        return 0
    for candidate in paths:
        try:
            stat = candidate.stat()
            if candidate.is_dir() and stat.st_mtime < cutoff:
                candidates.append((candidate, float(stat.st_mtime), _path_size_bytes(candidate)))
        except OSError:
            continue
    candidates.sort(key=lambda item: item[1])
    removed = 0
    total = sum(item[2] for item in candidates)
    quota = int(max_total_bytes or 0)
    for candidate, _mtime, size in candidates:
        if quota > 0 and total <= quota:
            break
        try:
            shutil.rmtree(candidate, ignore_errors=True)
            if not candidate.exists():
                removed += 1
                total = max(0, total - size)
        except OSError:
            continue
    return removed


def cleanup_frameforge_cache(
    cache_root: Path,
    max_total_bytes: int = 0,
    older_than_seconds: int = 7 * 24 * 60 * 60,
) -> int:
    """Xóa cache scene cũ nhất khi vượt quota; quota 0 nghĩa là không xóa."""
    quota = max(0, int(max_total_bytes))
    if quota <= 0 or not cache_root.exists():
        return 0
    cutoff = time.time() - max(0, int(older_than_seconds))
    try:
        files = [path for path in cache_root.glob("*.json") if path.is_file()]
    except OSError:
        return 0
    entries: list[tuple[Path, float, int]] = []
    total = 0
    for path in files:
        try:
            stat = path.stat()
            size = int(stat.st_size)
            total += size
            if stat.st_mtime < cutoff:
                entries.append((path, float(stat.st_mtime), size))
        except OSError:
            continue
    entries.sort(key=lambda item: item[1])
    removed = 0
    for path, _mtime, size in entries:
        if total <= quota:
            break
        try:
            path.unlink()
            removed += 1
            total = max(0, total - size)
        except OSError:
            continue
    return removed


# ── Arg validators ────────────────────────────────────────────────────


def positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("giá trị phải lớn hơn 0")
    return number


def non_negative_float(value: str) -> float:
    number = float(value)
    if number < 0:
        raise argparse.ArgumentTypeError("giá trị không được âm")
    return number


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("giá trị phải lớn hơn 0")
    return number


def non_negative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("giá trị không được âm")
    return number


def threshold_01(value: str) -> float:
    number = float(value)
    if not 0 <= number <= 1:
        raise argparse.ArgumentTypeError("giá trị phải nằm trong khoảng 0 đến 1")
    return number


# ── Worker helpers ────────────────────────────────────────────────────


def recommend_workers(video_count: int | None = None) -> int:
    """Đề xuất worker thận trọng; ưu tiên không làm đầy RAM khi xử lý video lớn."""
    cpu_count = os.cpu_count() or 2
    memory_gb = _available_memory_gb()
    if cpu_count <= 2:
        workers = 1
    elif cpu_count <= 4:
        workers = 2
    elif cpu_count <= 8:
        workers = 3
    else:
        workers = 4
    if memory_gb is not None:
        if memory_gb < 8:
            workers = 1
        elif memory_gb < 16:
            workers = min(workers, 2)
        elif memory_gb < 32:
            workers = min(workers, 3)
    if video_count is not None:
        workers = min(workers, max(1, video_count))
    return max(1, workers)


def worker_value(value: str) -> int | str:
    if value.lower() == "auto":
        return "auto"
    return positive_int(value)


def recommended_extract_workers() -> int:
    cpu_count = os.cpu_count() or 1
    return max(1, min(4, max(1, cpu_count // 2)))


def adaptive_extract_workers(
    video_worker_count: int = 1,
    requested_workers: int | str | None = 0,
    target_count: int | None = None,
    duration_seconds: float | None = None,
) -> int:
    """Chọn số process trích frame theo CPU/RAM, duration và số timestamp.

    Video ngắn hoặc job ít timestamp ưu tiên tuần tự để tránh chi phí spawn/seek.
    """
    outer_workers = max(1, int(video_worker_count))
    if target_count is not None and int(target_count) < 8:
        return 1
    if isinstance(requested_workers, str) and requested_workers.lower() == "auto":
        requested = recommended_extract_workers()
    else:
        try:
            requested = int(requested_workers or 0)
        except (TypeError, ValueError):
            requested = 1
        if requested <= 0:
            requested = recommended_extract_workers()
    cpu_budget = max(1, math.ceil((os.cpu_count() or 2) / outer_workers))
    memory_budget = 4
    duration_budget = 4
    if duration_seconds is not None:
        try:
            duration = max(0.0, float(duration_seconds))
        except (TypeError, ValueError):
            duration = 0.0
        samples = max(0, int(target_count or 0))
        if duration < 30.0 and samples < 96:
            duration_budget = 1
        elif duration < 90.0 and samples < 160:
            duration_budget = 1
        elif duration < 180.0 and samples < 240:
            duration_budget = 2
        elif duration < 300.0 and samples < 360:
            duration_budget = 3
    memory_gb = _available_memory_gb()
    if memory_gb is not None:
        if memory_gb < 8:
            memory_budget = 1
        elif memory_gb < 16:
            memory_budget = 2
        elif memory_gb < 32:
            memory_budget = 3
    return max(1, min(4, requested, cpu_budget, memory_budget, duration_budget))


# ── Video discovery ───────────────────────────────────────────────────


def find_videos(source: Path, recursive: bool) -> list[Path]:
    if source.is_file():
        return [source]
    if not source.is_dir():
        raise FileNotFoundError(f"Không tìm thấy đầu vào: {source}")
    iterator = source.rglob("*") if recursive else source.glob("*")
    return sorted(
        path for path in iterator
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )


# ── Formatting helpers ────────────────────────────────────────────────


def timestamp_label(seconds: float) -> str:
    milliseconds = int(round((seconds - int(seconds)) * 1000))
    whole_seconds = int(seconds)
    if milliseconds == 1000:
        whole_seconds += 1
        milliseconds = 0
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}-{minutes:02d}-{secs:02d}.{milliseconds:03d}"


# ── Stage timing helpers ──────────────────────────────────────────────


def new_stage_timings() -> dict[str, float | int]:
    return {
        "decode_ms": 0.0,
        "analysis_ms": 0.0,
        "encode_ms": 0.0,
        "write_ms": 0.0,
        "decode_count": 0,
        "analysis_count": 0,
        "encode_count": 0,
        "write_count": 0,
    }


def record_stage_timing(
    timings: dict[str, float | int] | None,
    stage: str,
    started_at: float,
) -> None:
    if timings is None:
        return
    elapsed_ms = max(0.0, (time.perf_counter() - started_at) * 1000.0)
    timings[f"{stage}_ms"] = round(float(timings.get(f"{stage}_ms", 0.0)) + elapsed_ms, 3)
    timings[f"{stage}_count"] = int(timings.get(f"{stage}_count", 0)) + 1


# ── Metric requirements ──────────────────────────────────────────────


@dataclass(frozen=True)
class MetricRequirements:
    need_sharpness: bool
    need_motion_blur: bool
    need_hash: bool
    need_histogram: bool


def metric_requirements(args) -> "MetricRequirements":
    """Tính toán metric nào cần thiết dựa trên config."""
    scene_detection = bool(getattr(args, "scene_detection", False))
    duplicate_threshold = int(getattr(args, "duplicate_threshold", 0) or 0)
    cross_run_enabled = bool(getattr(args, "cross_run_duplicates", True))
    cross_run_threshold = int(
        getattr(args, "cross_run_duplicate_threshold", duplicate_threshold) or duplicate_threshold
    )
    return MetricRequirements(
        need_sharpness=(
            float(getattr(args, "min_sharpness", 0.0) or 0.0) > 0
            or (scene_detection and bool(getattr(args, "best_frame_per_scene", False)))
        ),
        need_motion_blur=float(getattr(args, "motion_blur_threshold", 0.0) or 0.0) > 0,
        need_hash=(duplicate_threshold > 0 or (cross_run_enabled and cross_run_threshold > 0)),
        need_histogram=scene_detection,
    )


# ── Private helpers ───────────────────────────────────────────────────


def _available_memory_gb() -> float | None:
    """Ước lượng RAM hệ thống bằng stdlib, trả None nếu không đọc được."""
    try:
        if sys.platform == "win32":
            import ctypes

            class MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatusEx()
            status.dwLength = ctypes.sizeof(MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.ullTotalPhys / (1024**3)
        page_size = os.sysconf("SC_PAGE_SIZE")
        page_count = os.sysconf("SC_PHYS_PAGES")
        return (page_size * page_count) / (1024**3)
    except (AttributeError, OSError, ValueError, TypeError):
        return None
