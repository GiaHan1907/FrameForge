#!/usr/bin/env python3
"""Cắt screenshot tốc độ cao bằng một lượt đọc video.

Pipeline:
1. OpenCV đọc video tuần tự đúng một lần.
2. Mỗi frame chỉ được phân tích ở độ phân giải nhỏ (`--analysis-width`).
3. Scene detection dùng sai khác trung bình giữa hai frame phân tích.
4. Frame tốt nhất trong mỗi scene được chọn theo điểm Laplacian.
5. Flash ngắn được loại bằng cơ chế xác nhận thay đổi ở frame kế tiếp.
6. Chỉ frame đã chọn mới được mã hóa/lưu ra JPG, PNG hoặc WebP.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import math
import multiprocessing as mp
import os
import shutil
import sys
import tempfile
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Callable
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from persistent_queue import PersistentQueueStore

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


@dataclass
class FrameCandidate:
    frame: np.ndarray
    timestamp: float
    sharpness: float
    motion_blur_score: float
    hash_value: int
    brightness: float
    gray: np.ndarray
    histogram: np.ndarray


@dataclass(frozen=True)
class MetricRequirements:
    need_sharpness: bool
    need_motion_blur: bool
    need_hash: bool
    need_histogram: bool


def metric_requirements(args: argparse.Namespace) -> MetricRequirements:
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


class ProcessingCancelled(RuntimeError):
    """Được phát ra khi người dùng yêu cầu dừng pipeline xử lý."""


class InsufficientDiskSpace(RuntimeError):
    """Được phát ra trước khi tạo dữ liệu tạm nếu ổ đĩa không đủ chỗ trống."""


ProgressCallback = Callable[[Path, str, float, str], None]
CancelCheck = Callable[[], bool]


@dataclass
class PendingCut:
    before_gray: np.ndarray
    before_histogram: np.ndarray
    before_brightness: float
    candidate: FrameCandidate
    confirmations: int = 1


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


def format_bytes(value: int | float) -> str:
    amount = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TB"


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


def _atomic_write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def scene_cache_path(video: Path, cache_root: Path) -> Path:
    identity = hashlib.sha1(str(video.resolve()).encode("utf-8")).hexdigest()[:16]
    return cache_root / f"{video.stem}.{identity}.scene-cache.json"


def duplicate_index_path(video: Path, duplicate_root: Path) -> Path:
    identity = hashlib.sha1(str(video.resolve()).encode("utf-8")).hexdigest()[:16]
    return duplicate_root / f"{video.stem}.{identity}.hashes.json"


def processing_signature(args: argparse.Namespace) -> str:
    values = {
        key: str(value)
        for key, value in vars(args).items()
        if key not in {"workers", "retries", "retry_delay", "resume", "checkpoint_path", "cache_root", "duplicate_root", "queue_db"}
    }
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def scene_cache_key(video: Path, metadata: dict[str, float | int], args: argparse.Namespace) -> str:
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


def build_run_signature(args: argparse.Namespace) -> str:
    """Tạo chữ ký ổn định từ cấu hình xử lý, không phụ thuộc path runtime."""
    ignored = {"queue_db", "queue_run_signature", "checkpoint_path", "resume", "cache_root", "duplicate_root"}
    values = {key: value for key, value in vars(args).items() if key not in ignored}
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def checkpoint_path(output_root: Path, args: argparse.Namespace) -> Path:
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


def available_ram_gb() -> float | None:
    """Đọc RAM khả dụng, hỗ trợ Windows và Linux mà không bắt buộc psutil."""
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
                return status.ullAvailPhys / (1024**3)
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            for line in meminfo.read_text(encoding="ascii").splitlines():
                if line.startswith("MemAvailable:"):
                    return float(line.split()[1]) / (1024**2)
    except (AttributeError, OSError, ValueError, TypeError, IndexError):
        return None
    return None


def available_memory_gb() -> float | None:
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


def recommend_workers(video_count: int | None = None) -> int:
    """Đề xuất worker thận trọng; ưu tiên không làm đầy RAM khi xử lý video lớn."""
    cpu_count = os.cpu_count() or 2
    memory_gb = available_memory_gb()
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


def probe_video(video: Path) -> dict[str, float | int]:
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV không mở được video: {video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    capture.release()
    if not math.isfinite(fps) or fps <= 0:
        fps = 30.0
    duration = frame_count / fps if frame_count > 0 else 0.0
    if duration <= 0:
        raise RuntimeError("Video không có thời lượng hợp lệ.")
    return {
        "fps": fps,
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "duration": duration,
    }


def resized_for_analysis(frame: np.ndarray, analysis_width: int) -> np.ndarray:
    height, width = frame.shape[:2]
    target_width = min(width, analysis_width)
    if target_width == width:
        return frame
    target_height = max(1, round(height * target_width / width))
    return cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)


def resize_for_analysis(frame: np.ndarray, analysis_width: int) -> np.ndarray:
    return cv2.cvtColor(resized_for_analysis(frame, analysis_width), cv2.COLOR_BGR2GRAY)


def color_histogram(frame: np.ndarray, analysis_width: int) -> np.ndarray:
    small = resized_for_analysis(frame, analysis_width)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    histogram = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256])
    histogram = cv2.normalize(histogram, histogram).flatten()
    return histogram.astype(np.float32)


def laplacian_variance(gray: np.ndarray) -> float:
    if min(gray.shape) < 3:
        return 0.0
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def motion_blur_score(gray: np.ndarray) -> float:
    """Ước lượng motion blur trong [0, 1], điểm càng cao càng có nguy cơ bị nhòe chuyển động.

    Motion blur thường làm năng lượng gradient tập trung theo một hướng và làm
    giảm chi tiết cao tần. Đây là heuristic nhanh để lọc frame, không phải bộ
    ước lượng vận tốc chuyển động tuyệt đối.
    """
    if min(gray.shape) < 8:
        return 0.0
    gray_float = gray.astype(np.float32) / 255.0
    grad_x = cv2.Scharr(gray_float, cv2.CV_32F, 1, 0)
    grad_y = cv2.Scharr(gray_float, cv2.CV_32F, 0, 1)
    energy_x = float(np.mean(np.abs(grad_x)))
    energy_y = float(np.mean(np.abs(grad_y)))
    directional_imbalance = abs(energy_x - energy_y) / (energy_x + energy_y + 1e-6)

    grad_energy = float(np.mean(np.sqrt(grad_x * grad_x + grad_y * grad_y)))
    lap_energy = float(np.var(cv2.Laplacian(gray_float, cv2.CV_32F)))
    # Motion blur preserves broad edges but suppresses fine detail, so the
    # Laplacian-to-gradient ratio falls even when the frame has strong edges.
    detail_ratio = math.sqrt(max(lap_energy, 0.0)) / (math.sqrt(max(lap_energy, 0.0)) + grad_energy + 1e-6)
    detail_deficit = 1.0 - min(1.0, detail_ratio * 3.0)

    # Directionality is the main signal; detail deficit reduces false positives
    # on naturally directional scenes that are still sharp.
    score = 0.62 * directional_imbalance + 0.38 * detail_deficit
    return float(min(1.0, max(0.0, score)))


def dhash(gray: np.ndarray) -> int:
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    differences = small[:, 1:] > small[:, :-1]
    hash_value = 0
    for bit in differences.flatten():
        hash_value = (hash_value << 1) | int(bool(bit))
    return hash_value


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def frame_candidate(
    frame: np.ndarray,
    timestamp: float,
    analysis_width: int,
    requirements: MetricRequirements | None = None,
) -> FrameCandidate:
    requirements = requirements or MetricRequirements(True, True, True, True)
    # Tạo ảnh nhỏ đúng một lần; mọi metric phân tích dùng chung buffer này.
    small = resized_for_analysis(frame, analysis_width)
    need_gray = (
        requirements.need_sharpness
        or requirements.need_motion_blur
        or requirements.need_hash
        or requirements.need_histogram
    )
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if need_gray else np.empty((0, 0), dtype=np.uint8)
    raw_sharpness = laplacian_variance(gray) if requirements.need_sharpness else 0.0
    blur_score = motion_blur_score(gray) if requirements.need_motion_blur else 0.0
    histogram = np.empty((0,), dtype=np.float32)
    if requirements.need_histogram:
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        histogram = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256])
        histogram = cv2.normalize(histogram, histogram).flatten().astype(np.float32)
    # Quy về cùng mốc 640 px để threshold ổn định hơn giữa các độ phân giải.
    width_scale = (REFERENCE_ANALYSIS_WIDTH / max(gray.shape[1], 1)) ** 2 if need_gray else 1.0
    normalized_sharpness = raw_sharpness * width_scale
    return FrameCandidate(
        frame=frame.copy(),
        timestamp=timestamp,
        sharpness=normalized_sharpness,
        motion_blur_score=blur_score,
        hash_value=dhash(gray) if requirements.need_hash else 0,
        brightness=float(np.mean(gray)) / 255.0 if need_gray else 0.0,
        gray=gray,
        histogram=histogram,
    )


def normalized_difference(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.mean(cv2.absdiff(left, right))) / 255.0


def histogram_difference(left: np.ndarray, right: np.ndarray) -> float:
    # Correlation is robust to small illumination changes; map [-1, 1] to [0, 1].
    correlation = float(cv2.compareHist(left, right, cv2.HISTCMP_CORREL))
    return min(1.0, max(0.0, (1.0 - correlation) / 2.0))


def smart_scene_difference(
    gray: np.ndarray,
    histogram: np.ndarray,
    previous_gray: np.ndarray | None,
    previous_histogram: np.ndarray | None,
) -> float:
    if previous_gray is None or previous_histogram is None:
        return 0.0
    pixel_difference = normalized_difference(gray, previous_gray)
    color_difference = histogram_difference(histogram, previous_histogram)
    return 0.70 * pixel_difference + 0.30 * color_difference


def better_frame(
    current: FrameCandidate | None,
    candidate: FrameCandidate,
    choose_best: bool = True,
    motion_threshold: float = 0.0,
) -> FrameCandidate:
    if current is None:
        return candidate
    if motion_threshold > 0:
        candidate_ok = candidate.motion_blur_score <= motion_threshold
        current_ok = current.motion_blur_score <= motion_threshold
        if candidate_ok and not current_ok:
            return candidate
        if not candidate_ok and current_ok:
            return current
    if not choose_best:
        return current
    if candidate.sharpness > current.sharpness:
        return candidate
    return current


def timestamp_label(seconds: float) -> str:
    milliseconds = int(round((seconds - int(seconds)) * 1000))
    whole_seconds = int(seconds)
    if milliseconds == 1000:
        whole_seconds += 1
        milliseconds = 0
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}-{minutes:02d}-{secs:02d}.{milliseconds:03d}"


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


def crop_to_aspect_ratio(frame: np.ndarray, crop_ratio: str | None) -> np.ndarray:
    """Crop chính giữa theo tỉ lệ khung hình, không kéo giãn nội dung."""
    if crop_ratio in (None, "", "Không crop", "none"):
        return frame
    target_ratio = CROP_RATIO_VALUES.get(str(crop_ratio))
    if target_ratio is None:
        raise ValueError(f"Tỉ lệ crop không hợp lệ: {crop_ratio}")
    height, width = frame.shape[:2]
    if height <= 0 or width <= 0:
        return frame
    current_ratio = width / height
    if abs(current_ratio - target_ratio) < 1e-6:
        return frame
    if current_ratio > target_ratio:
        cropped_width = max(1, min(width, round(height * target_ratio)))
        left = max(0, (width - cropped_width) // 2)
        return frame[:, left:left + cropped_width]
    cropped_height = max(1, min(height, round(width / target_ratio)))
    top = max(0, (height - cropped_height) // 2)
    return frame[top:top + cropped_height, :]

def save_image(
    frame: np.ndarray,
    output: Path,
    image_format: str,
    quality: int,
    width: int | None,
    crop_ratio: str | None = None,
    encode_profile: str = "Chất lượng cao",
    stage_timings: dict[str, float | int] | None = None,
) -> None:
    profile = ENCODE_PROFILES.get(str(encode_profile))
    if profile is None:
        raise ValueError(f"Encode profile không hợp lệ: {encode_profile}")
    frame = crop_to_aspect_ratio(frame, crop_ratio)
    if width is not None and frame.shape[1] > width:
        target_height = max(1, round(frame.shape[0] * width / frame.shape[1]))
        frame = cv2.resize(frame, (width, target_height), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    image = Image.fromarray(rgb)
    encoded = io.BytesIO()
    encode_started = time.perf_counter()
    if image_format == "jpg":
        image.save(encoded, format="JPEG", quality=quality, optimize=bool(profile["jpeg_optimize"]))
    elif image_format == "webp":
        image.save(encoded, format="WEBP", quality=quality, method=int(profile["webp_method"]))
    else:
        image.save(encoded, format="PNG", optimize=bool(profile["png_optimize"]))
    record_stage_timing(stage_timings, "encode", encode_started)
    write_started = time.perf_counter()
    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(encoded.getvalue())
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    record_stage_timing(stage_timings, "write", write_started)


class InsufficientResources(RuntimeError):
    """Tài nguyên khả dụng thấp hơn ngưỡng an toàn của job."""


def resource_guard(output_dir: Path, duration: float, args: argparse.Namespace) -> dict[str, object]:
    estimated_count = estimate_screenshot_count(duration, args)
    bytes_per_image = 4 * 1024**2 if getattr(args, "format", "jpg") == "png" else 2 * 1024**2
    estimated_bytes = estimated_count * bytes_per_image
    free_disk = ensure_free_disk_space(
        output_dir,
        required_bytes=estimated_bytes,
        reserve_bytes=int(getattr(args, "disk_reserve_bytes", 0) or 0),
    )
    available_ram = available_ram_gb()
    minimum_ram = float(getattr(args, "min_free_ram_gb", 0.0) or 0.0)
    if available_ram is not None and minimum_ram > 0 and available_ram < minimum_ram:
        raise InsufficientResources(
            f"RAM khả dụng chỉ còn {available_ram:.1f} GB, thấp hơn ngưỡng {minimum_ram:.1f} GB."
        )
    return {
        "estimated_screenshots": estimated_count,
        "estimated_output_bytes": estimated_bytes,
        "free_disk_bytes": free_disk,
        "available_ram_gb": round(available_ram, 3) if available_ram is not None else None,
    }


def estimate_screenshot_count(duration: float, args: argparse.Namespace) -> int:
    configured = int(getattr(args, "max_screenshots", 0) or 0)
    if configured > 0:
        return configured
    if getattr(args, "count", None) is not None:
        return max(1, int(args.count))
    every = getattr(args, "every", None)
    if every is not None and float(every) > 0:
        return max(1, math.ceil(max(0.0, duration) / float(every)))
    return 0


def finalize_report_diagnostics(reports: dict[str, object], args: argparse.Namespace) -> dict[str, object]:
    target_mode = bool(getattr(args, "target_count_after_filter", False))
    target = int(getattr(args, "max_screenshots", 0) or 0) if target_mode else 0
    saved = int(reports.get("saved", 0) or 0)
    shortfall = max(0, target - saved) if target > 0 else 0
    reports["target_screenshots"] = target
    reports["target_count_after_filter"] = target_mode
    reports["shortfall"] = shortfall
    reports["shortfall_reasons"] = {
        "rejected_blurry": int(reports.get("rejected_blurry", 0) or 0),
        "rejected_motion_blur": int(reports.get("rejected_motion_blur", 0) or 0),
        "rejected_duplicate": int(reports.get("rejected_duplicate", 0) or 0),
        "rejected_duplicate_cross_run": int(reports.get("rejected_duplicate_cross_run", 0) or 0),
        "capture_errors": int(reports.get("capture_errors", 0) or 0),
    }
    if shortfall:
        reports["shortfall_message"] = (
            f"Thiếu {shortfall} screenshot so với mục tiêu {target}; "
            "hãy nới bộ lọc, tăng phạm vi thời gian hoặc tắt duplicate/blur filter."
        )
    else:
        reports["shortfall_message"] = None
    return reports


def write_video_manifest(video: Path, output_dir: Path, args: argparse.Namespace, reports: dict[str, object]) -> Path:
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
    _atomic_write_json(manifest_path, payload)
    return manifest_path


def accept_and_save(
    candidate: FrameCandidate,
    output_dir: Path,
    video_stem: str,
    index: int,
    args: argparse.Namespace,
    previous_hash: int | None,
    existing_hashes: set[int] | None = None,
    duplicate_buckets: dict[str, set[int]] | None = None,
) -> tuple[str, int | None]:
    if args.min_sharpness > 0 and candidate.sharpness < args.min_sharpness:
        return "blurry", previous_hash
    motion_threshold = float(getattr(args, "motion_blur_threshold", 0.0))
    if motion_threshold > 0 and candidate.motion_blur_score > motion_threshold:
        return "motion_blur", previous_hash
    if (
        args.duplicate_threshold > 0
        and previous_hash is not None
        and hamming_distance(candidate.hash_value, previous_hash) <= args.duplicate_threshold
    ):
        return "duplicate", previous_hash
    cross_run_threshold = int(getattr(args, "cross_run_duplicate_threshold", args.duplicate_threshold))
    comparison_hashes = existing_hashes
    if duplicate_buckets is not None and cross_run_threshold <= 6:
        comparison_hashes = set()
        for bucket_key in _dhash_bucket_keys(candidate.hash_value):
            comparison_hashes.update(duplicate_buckets.get(bucket_key, set()))
    if (
        getattr(args, "cross_run_duplicates", True)
        and cross_run_threshold > 0
        and comparison_hashes
        and any(hamming_distance(candidate.hash_value, item) <= cross_run_threshold for item in comparison_hashes)
    ):
        return "duplicate_cross_run", previous_hash

    filename = f"{timestamp_label(candidate.timestamp)}.{args.format}"
    output = output_dir / filename
    if output.exists() and not args.overwrite:
        return "existing", candidate.hash_value
    save_image(
        candidate.frame,
        output,
        args.format,
        args.quality,
        args.width,
        getattr(args, "crop_ratio", "Không crop"),
        getattr(args, "encode_profile", "Chất lượng cao"),
        getattr(args, "stage_timings", None),
    )
    if existing_hashes is not None:
        existing_hashes.add(candidate.hash_value)
    if duplicate_buckets is not None:
        for bucket_key in _dhash_bucket_keys(candidate.hash_value):
            duplicate_buckets.setdefault(bucket_key, set()).add(candidate.hash_value)
    print(f"  lưu — {output.name} sharpness={candidate.sharpness:.1f}")
    return "saved", candidate.hash_value


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
    Tham số duration có default để giữ tương thích với caller cũ.
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
        # Spawn/seek overhead dominates short fixed/count jobs.
        if duration < 30.0 and samples < 96:
            duration_budget = 1
        elif duration < 90.0 and samples < 160:
            duration_budget = 1
        elif duration < 180.0 and samples < 240:
            duration_budget = 2
        elif duration < 300.0 and samples < 360:
            duration_budget = 3
    memory_gb = available_memory_gb()
    if memory_gb is not None:
        if memory_gb < 8:
            memory_budget = 1
        elif memory_gb < 16:
            memory_budget = 2
        elif memory_gb < 32:
            memory_budget = 3
    return max(1, min(4, requested, cpu_budget, memory_budget, duration_budget))


def _extract_frame_chunk(task: tuple[str, list[tuple[int, float]], str]) -> list[tuple[int, float, str | None, str | None]]:
    video_path, targets, temp_dir = task
    capture = cv2.VideoCapture(video_path)
    result: list[tuple[int, float, str | None, str | None]] = []
    if not capture.isOpened():
        return [(index, timestamp, None, "Không mở được video trong extraction worker") for index, timestamp in targets]
    try:
        for index, timestamp in targets:
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
            ok, frame = capture.read()
            if not ok:
                result.append((index, timestamp, None, "Không đọc được frame tại timestamp"))
                continue
            output = Path(temp_dir) / f"frame_{index:08d}.jpg"
            if not cv2.imwrite(str(output), frame, [cv2.IMWRITE_JPEG_QUALITY, 95]):
                result.append((index, timestamp, None, "Không ghi được frame tạm"))
                continue
            result.append((index, timestamp, str(output), None))
    finally:
        capture.release()
    return result


def process_fixed_mode_multiprocess(
    video: Path,
    output_dir: Path,
    targets: list[float],
    args: argparse.Namespace,
    on_progress: ProgressCallback | None = None,
    cancel_event=None,
    existing_hashes: set[int] | None = None,
    duplicate_buckets: dict[str, set[int]] | None = None,
) -> dict[str, object]:
    reports: dict[str, object] = {
        "selection_mode": "fixed_interval" if args.count is None else "count",
        "requested": len(targets),
        "saved": 0,
        "rejected_blurry": 0,
        "rejected_motion_blur": 0,
        "rejected_duplicate": 0,
        "rejected_duplicate_cross_run": 0,
        "skipped_existing": 0,
        "capture_errors": 0,
        "scene_times": [],
        "extraction_mode": "multiprocessing",
        "extraction_workers": int(getattr(args, "extract_workers", 1)),
        "stage_timings": getattr(args, "stage_timings", None),
    }
    temp_dir = Path(tempfile.mkdtemp(prefix="frameforge_extract_", dir=str(output_dir)))
    worker_count = min(max(2, int(getattr(args, "extract_workers", 2))), len(targets))
    chunk_size = max(1, math.ceil(len(targets) / worker_count))
    chunks = [
        [(index, timestamp) for index, timestamp in enumerate(targets[start:start + chunk_size], start=start)]
        for start in range(0, len(targets), chunk_size)
    ]
    previous_hash: int | None = None
    requirements = metric_requirements(args)
    buffered: dict[int, tuple[int, float, str | None, str | None]] = {}
    next_index = 0
    pool = mp.get_context("spawn").Pool(processes=worker_count)
    try:
        tasks = [(str(video), chunk, str(temp_dir)) for chunk in chunks]
        for chunk_result in pool.imap_unordered(_extract_frame_chunk, tasks):
            check_cancelled(cancel_event)
            for item in chunk_result:
                buffered[item[0]] = item
            while next_index in buffered:
                index, timestamp, frame_path, error = buffered.pop(next_index)
                if error or not frame_path:
                    reports["capture_errors"] = int(reports["capture_errors"]) + 1
                else:
                    decode_started = time.perf_counter()
                    frame = cv2.imread(frame_path)
                    record_stage_timing(getattr(args, "stage_timings", None), "decode", decode_started)
                    if frame is None:
                        reports["capture_errors"] = int(reports["capture_errors"]) + 1
                    else:
                        analysis_started = time.perf_counter()
                        candidate = frame_candidate(frame, timestamp, args.analysis_width, requirements)
                        record_stage_timing(getattr(args, "stage_timings", None), "analysis", analysis_started)
                        status, previous_hash = accept_and_save(
                            candidate, output_dir, video.stem, index + 1, args, previous_hash, existing_hashes, duplicate_buckets
                        )
                        reports[status_key(status)] = int(reports[status_key(status)]) + 1
                next_index += 1
                emit_progress(
                    on_progress,
                    video,
                    "extracting",
                    next_index / max(len(targets), 1),
                    f"Multiprocessing trích frame {next_index}/{len(targets)}",
                )
        pool.close()
        pool.join()
    except BaseException:
        pool.terminate()
        pool.join()
        raise
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    emit_progress(on_progress, video, "saving", 1.0, "Đã hoàn tất trích frame song song và ghi screenshot")
    return reports


def screenshot_limit(args: argparse.Namespace) -> int | None:
    """Trả về số screenshot tối đa mỗi video; None nghĩa là không giới hạn."""
    raw = getattr(args, "max_screenshots", None)
    try:
        value = int(raw or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else None


def candidate_limit(args: argparse.Namespace) -> int | None:
    limit = screenshot_limit(args)
    if limit is None:
        return None
    if getattr(args, "target_count_after_filter", False):
        multiplier = max(1, int(getattr(args, "target_candidate_multiplier", 3) or 3))
        return limit * multiplier
    return limit


def process_fixed_mode(
    capture: cv2.VideoCapture,
    video: Path,
    output_dir: Path,
    duration: float,
    args: argparse.Namespace,
    on_progress: ProgressCallback | None = None,
    cancel_event=None,
    existing_hashes: set[int] | None = None,
    duplicate_buckets: dict[str, set[int]] | None = None,
) -> dict[str, object]:
    actual_start = min(args.start, duration)
    actual_end = duration if args.end is None else min(args.end, duration)
    if actual_end <= actual_start:
        raise ValueError("--end phải lớn hơn --start và nằm trong thời lượng video.")
    if args.count is not None:
        if args.count == 1:
            targets = [(actual_start + actual_end) / 2]
        else:
            safe_end = max(actual_start, actual_end - 0.1)
            step = (safe_end - actual_start) / (args.count - 1)
            targets = [actual_start + index * step for index in range(args.count)]
    else:
        interval = args.every if args.every is not None else 5.0
        targets = []
        current = actual_start
        while current < actual_end:
            targets.append(current)
            current += interval

    limit = screenshot_limit(args)
    target_mode = bool(getattr(args, "target_count_after_filter", False))
    target_candidates = candidate_limit(args)
    if target_candidates is not None and args.count is None:
        targets = targets[:target_candidates]

    effective_extract_workers = adaptive_extract_workers(
        video_worker_count=int(getattr(args, "video_workers", 1)),
        requested_workers=getattr(args, "extract_workers", 1),
        target_count=len(targets),
        duration_seconds=duration,
    )
    reports = {
        "selection_mode": "fixed_interval" if args.count is None else "count",
        "requested": len(targets),
        "saved": 0,
        "rejected_blurry": 0,
        "rejected_motion_blur": 0,
        "rejected_duplicate": 0,
        "rejected_duplicate_cross_run": 0,
        "skipped_existing": 0,
        "capture_errors": 0,
        "scene_times": [],
        "extraction_mode": "sequential",
        "extraction_workers": effective_extract_workers,
        "stage_timings": getattr(args, "stage_timings", None),
    }
    if effective_extract_workers > 1 and len(targets) >= int(getattr(args, "extract_min_targets", 8)) and not target_mode:
        multiprocessing_args = copy.copy(args)
        multiprocessing_args.extract_workers = effective_extract_workers
        return process_fixed_mode_multiprocess(
            video, output_dir, targets, multiprocessing_args, on_progress, cancel_event, existing_hashes, duplicate_buckets
        )
    target_index = 0
    frame_index = 0
    requirements = metric_requirements(args)
    previous_hash: int | None = None
    estimated_frames = max(1, int(max(0.0, actual_end - actual_start) * max(args.source_fps, 1.0)))
    while target_index < len(targets):
        check_cancelled(cancel_event)
        if target_mode and limit is not None and int(reports["saved"]) >= limit:
            break
        decode_started = time.perf_counter()
        ok, frame = capture.read()
        record_stage_timing(getattr(args, "stage_timings", None), "decode", decode_started)
        if not ok:
            reports["capture_errors"] = int(reports["capture_errors"]) + (len(targets) - target_index)
            break
        timestamp = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if timestamp <= 0 or not math.isfinite(timestamp):
            timestamp = frame_index / max(args.source_fps, 1.0)
        frame_index += 1
        if frame_index == 1 or frame_index % 15 == 0:
            fraction = min(0.99, max(0.0, (timestamp - actual_start) / max(actual_end - actual_start, 1e-6)))
            emit_progress(
                on_progress,
                video,
                "analyzing",
                fraction,
                f"Đang phân tích {timestamp:.1f}s · frame {frame_index}/{estimated_frames}",
            )
        if timestamp + 1e-6 < targets[target_index]:
            continue
        if timestamp > actual_end + 0.05:
            break
        analysis_started = time.perf_counter()
        candidate = frame_candidate(frame, timestamp, args.analysis_width, requirements)
        record_stage_timing(getattr(args, "stage_timings", None), "analysis", analysis_started)
        status, previous_hash = accept_and_save(
            candidate, output_dir, video.stem, target_index + 1, args, previous_hash, existing_hashes, duplicate_buckets
        )
        reports[status_key(status)] = int(reports[status_key(status)]) + 1
        emit_progress(
            on_progress,
            video,
            "selecting",
            target_index / max(len(targets), 1),
            f"Đã xử lý {target_index}/{len(targets)} mốc",
        )
        target_index += 1
        emit_progress(
            on_progress,
            video,
            "selecting",
            target_index / max(len(targets), 1),
            f"Đã xử lý {target_index}/{len(targets)} mốc",
        )
    emit_progress(on_progress, video, "saving", 1.0, "Đã hoàn tất ghi screenshot")
    return reports


def status_key(status: str) -> str:
    return {
        "saved": "saved",
        "blurry": "rejected_blurry",
        "duplicate": "rejected_duplicate",
        "motion_blur": "rejected_motion_blur",
        "duplicate_cross_run": "rejected_duplicate_cross_run",
        "existing": "skipped_existing",
    }.get(status, "capture_errors")


def process_scene_mode(
    capture: cv2.VideoCapture,
    video: Path,
    output_dir: Path,
    duration: float,
    args: argparse.Namespace,
    on_progress: ProgressCallback | None = None,
    cancel_event=None,
    existing_hashes: set[int] | None = None,
    duplicate_buckets: dict[str, set[int]] | None = None,
) -> dict[str, object]:
    actual_start = min(args.start, duration)
    actual_end = duration if args.end is None else min(args.end, duration)
    if actual_end <= actual_start:
        raise ValueError("--end phải lớn hơn --start và nằm trong thời lượng video.")

    reports = {
        "selection_mode": "best_frame_per_scene" if args.best_frame_per_scene else "scene_detection",
        "requested": 0,
        "saved": 0,
        "rejected_blurry": 0,
        "rejected_motion_blur": 0,
        "rejected_duplicate": 0,
        "rejected_duplicate_cross_run": 0,
        "skipped_existing": 0,
        "capture_errors": 0,
        "scene_times": [],
        "selected_times": [],
        "scene_confirmations": args.scene_confirmations,
        "smart_scene_detection": True,
    }
    limit = screenshot_limit(args)
    target_mode = bool(getattr(args, "target_count_after_filter", False))
    candidate_budget = candidate_limit(args)
    selected_times: list[float] = []
    previous_gray: np.ndarray | None = None
    previous_histogram: np.ndarray | None = None
    previous_brightness: float | None = None
    next_sample = actual_start
    last_scene_timestamp = actual_start - args.min_scene_gap
    sample_interval = 1.0 / args.analysis_fps
    current_best: FrameCandidate | None = None
    pending: PendingCut | None = None
    previous_hash: int | None = None
    requirements = metric_requirements(args)
    scene_index = 0
    frame_index = 0
    estimated_frames = max(1, int(max(0.0, actual_end - actual_start) * max(args.source_fps, 1.0)))

    def flush(candidate: FrameCandidate | None, index: int, previous: int | None) -> int | None:
        check_cancelled(cancel_event)
        if candidate is None or (target_mode and limit is not None and int(reports["saved"]) >= limit) or (not target_mode and limit is not None and len(selected_times) >= limit):
            return previous
        reports["requested"] = int(reports["requested"]) + 1
        selected_times.append(round(float(candidate.timestamp), 3))
        status, updated_hash = accept_and_save(candidate, output_dir, video.stem, index, args, previous, existing_hashes, duplicate_buckets)
        reports[status_key(status)] = int(reports[status_key(status)]) + 1
        return updated_hash

    while True:
        check_cancelled(cancel_event)
        if (target_mode and limit is not None and int(reports["saved"]) >= limit) or (not target_mode and limit is not None and len(selected_times) >= limit) or (candidate_budget is not None and len(selected_times) >= candidate_budget):
            break
        decode_started = time.perf_counter()
        ok, frame = capture.read()
        record_stage_timing(getattr(args, "stage_timings", None), "decode", decode_started)
        if not ok:
            break
        timestamp = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if timestamp <= 0 or not math.isfinite(timestamp):
            timestamp = frame_index / max(args.source_fps, 1.0)
        frame_index += 1
        if frame_index == 1 or frame_index % 15 == 0:
            fraction = min(0.99, max(0.0, (timestamp - actual_start) / max(actual_end - actual_start, 1e-6)))
            emit_progress(
                on_progress,
                video,
                "analyzing",
                fraction,
                f"Đang phân tích scene tại {timestamp:.1f}s · frame {frame_index}/{estimated_frames}",
            )
        if timestamp + 1e-6 < actual_start:
            continue
        if timestamp > actual_end:
            break
        if timestamp + 1e-6 < next_sample:
            continue
        next_sample = timestamp + sample_interval
        analysis_started = time.perf_counter()
        candidate = frame_candidate(frame, timestamp, args.analysis_width, requirements)
        record_stage_timing(getattr(args, "stage_timings", None), "analysis", analysis_started)
        emit_progress(
            on_progress,
            video,
            "analyzing",
            min(0.99, max(0.0, (timestamp - actual_start) / max(actual_end - actual_start, 1e-6))),
            f"Đang phân tích scene tại {timestamp:.1f}s · frame {frame_index}/{estimated_frames}",
        )

        if current_best is None:
            current_best = candidate
        elif pending is not None:
            return_difference = smart_scene_difference(
                candidate.gray,
                candidate.histogram,
                pending.before_gray,
                pending.before_histogram,
            )
            brightness_return = abs(candidate.brightness - pending.before_brightness)
            is_flash = (
                return_difference <= args.scene_threshold * args.flash_return_ratio
                and brightness_return <= args.flash_brightness_threshold
            )
            if is_flash:
                pending = None
                current_best = better_frame(
                    current_best,
                    candidate,
                    args.best_frame_per_scene,
                    getattr(args, "motion_blur_threshold", 0.0),
                )
            else:
                pending.confirmations += 1
                if pending.confirmations < args.scene_confirmations:
                    # Chưa đủ bằng chứng; giữ scene cũ và chờ frame kế tiếp.
                    continue
                previous_hash = flush(current_best, scene_index + 1, previous_hash)
                scene_index += 1
                reports["scene_times"].append(round(pending.candidate.timestamp, 3))
                last_scene_timestamp = pending.candidate.timestamp
                current_best = pending.candidate
                pending = None
                current_best = better_frame(
                    current_best,
                    candidate,
                    args.best_frame_per_scene,
                    getattr(args, "motion_blur_threshold", 0.0),
                )
        else:
            difference = smart_scene_difference(
                candidate.gray,
                candidate.histogram,
                previous_gray,
                previous_histogram,
            )
            gap_from_last_scene = timestamp - last_scene_timestamp
            quality_ok = (
                (args.min_sharpness <= 0 or candidate.sharpness >= args.min_sharpness)
                and (
                    getattr(args, "motion_blur_threshold", 0.0) <= 0
                    or candidate.motion_blur_score <= args.motion_blur_threshold
                )
            )
            if (
                difference >= args.scene_threshold
                and gap_from_last_scene >= args.min_scene_gap
                and quality_ok
            ):
                pending = PendingCut(
                    before_gray=previous_gray.copy() if previous_gray is not None else candidate.gray.copy(),
                    before_histogram=previous_histogram.copy() if previous_histogram is not None else candidate.histogram.copy(),
                    before_brightness=previous_brightness if previous_brightness is not None else candidate.brightness,
                    candidate=candidate,
                )
            else:
                current_best = better_frame(
                    current_best,
                    candidate,
                    args.best_frame_per_scene,
                    getattr(args, "motion_blur_threshold", 0.0),
                )

        previous_gray = candidate.gray
        previous_histogram = candidate.histogram
        previous_brightness = candidate.brightness

    if pending is not None:
        if pending.confirmations >= args.scene_confirmations:
            previous_hash = flush(current_best, scene_index + 1, previous_hash)
            scene_index += 1
            reports["scene_times"].append(round(pending.candidate.timestamp, 3))
            last_scene_timestamp = pending.candidate.timestamp
            current_best = pending.candidate
        else:
            # Một thay đổi chưa được xác nhận được xem là nhiễu/flash cuối video.
            current_best = better_frame(
                current_best,
                pending.candidate,
                args.best_frame_per_scene,
                getattr(args, "motion_blur_threshold", 0.0),
            )
    flush(current_best, scene_index + 1, previous_hash)
    reports["selected_times"] = selected_times
    emit_progress(on_progress, video, "saving", 1.0, "Đã hoàn tất ghi screenshot")
    return reports


def process_cached_scene_mode(
    capture: cv2.VideoCapture,
    video: Path,
    output_dir: Path,
    args: argparse.Namespace,
    cached: dict[str, object],
    existing_hashes: set[int],
    duplicate_buckets: dict[str, set[int]] | None = None,
    on_progress: ProgressCallback | None = None,
    cancel_event=None,
) -> dict[str, object]:
    limit = screenshot_limit(args)
    target_mode = bool(getattr(args, "target_count_after_filter", False))
    selected_times = [float(item) for item in cached.get("selected_times", [])]
    scene_times = [float(item) for item in cached.get("scene_times", [])]
    if limit is not None:
        cap = candidate_limit(args) if target_mode else limit
        selected_times = selected_times[:cap]
        scene_times = scene_times[:cap]
    reports: dict[str, object] = {
        "selection_mode": "best_frame_per_scene" if args.best_frame_per_scene else "scene_detection",
        "requested": len(selected_times),
        "saved": 0,
        "rejected_blurry": 0,
        "rejected_motion_blur": 0,
        "rejected_duplicate": 0,
        "rejected_duplicate_cross_run": 0,
        "skipped_existing": 0,
        "capture_errors": 0,
        "scene_times": scene_times,
        "selected_times": selected_times,
        "scene_confirmations": args.scene_confirmations,
        "smart_scene_detection": True,
        "cache_hit": True,
        "stage_timings": getattr(args, "stage_timings", None),
    }
    previous_hash: int | None = None
    requirements = metric_requirements(args)
    for index, timestamp in enumerate(selected_times, start=1):
        check_cancelled(cancel_event)
        if target_mode and limit is not None and int(reports["saved"]) >= limit:
            break
        capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
        decode_started = time.perf_counter()
        ok, frame = capture.read()
        record_stage_timing(getattr(args, "stage_timings", None), "decode", decode_started)
        if not ok:
            reports["capture_errors"] = int(reports["capture_errors"]) + 1
            continue
        analysis_started = time.perf_counter()
        candidate = frame_candidate(frame, timestamp, args.analysis_width, requirements)
        record_stage_timing(getattr(args, "stage_timings", None), "analysis", analysis_started)
        status, previous_hash = accept_and_save(
            candidate, output_dir, video.stem, index, args, previous_hash, existing_hashes, duplicate_buckets
        )
        reports[status_key(status)] = int(reports[status_key(status)]) + 1
        emit_progress(
            on_progress,
            video,
            "selecting",
            index / max(len(selected_times), 1),
            f"Dùng cache scene {index}/{len(selected_times)} tại {timestamp:.1f}s",
        )
    emit_progress(on_progress, video, "saving", 1.0, "Đã hoàn tất từ cache scene")
    return reports


def process_video(
    video: Path,
    output_root: Path,
    source_root: Path | None,
    args: argparse.Namespace,
    on_progress: ProgressCallback | None = None,
    cancel_event=None,
) -> dict[str, object]:
    check_cancelled(cancel_event)
    metadata = probe_video(video)
    duration = float(metadata["duration"])
    if source_root is not None:
        relative_parent = video.parent.relative_to(source_root)
        output_dir = output_root / relative_parent / video.stem
    else:
        output_dir = output_root / video.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    resource_info = resource_guard(output_dir, duration, args)
    duplicate_root_value = getattr(args, "duplicate_root", None)
    duplicate_root = Path(duplicate_root_value) if duplicate_root_value else output_root / ".frameforge_hashes"
    duplicate_root.mkdir(parents=True, exist_ok=True)
    duplicate_path = duplicate_index_path(video, duplicate_root)
    existing_hashes, duplicate_buckets = load_duplicate_index(duplicate_path)
    cache_root_value = getattr(args, "cache_root", None)
    cache_root = Path(cache_root_value) if cache_root_value else output_root / ".frameforge_cache"
    cache_path: Path | None = None
    cache_key: str | None = None
    cached: dict[str, object] | None = None
    if args.scene_detection:
        cache_root.mkdir(parents=True, exist_ok=True)
        cache_path = scene_cache_path(video, cache_root)
        cache_key = scene_cache_key(video, metadata, args)
        if getattr(args, "use_scene_cache", True):
            cached = load_scene_cache(cache_path, cache_key)
    cache_message = "cache scene hợp lệ" if cached else ("cần phân tích scene mới" if args.scene_detection else "không dùng scene cache")
    emit_progress(on_progress, video, "preparing", 0.0, f"Đã mở video, kiểm tra disk, nạp {len(existing_hashes)} hash cũ; {cache_message}")

    args.source_fps = float(metadata["fps"])
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"Không mở được video: {video}")
    try:
        if args.scene_detection and cached:
            reports = process_cached_scene_mode(capture, video, output_dir, args, cached, existing_hashes, duplicate_buckets, on_progress, cancel_event)
        elif args.scene_detection:
            reports = process_scene_mode(capture, video, output_dir, duration, args, on_progress, cancel_event, existing_hashes, duplicate_buckets)
        else:
            reports = process_fixed_mode(capture, video, output_dir, duration, args, on_progress, cancel_event, existing_hashes, duplicate_buckets)
    finally:
        capture.release()
    save_duplicate_hashes(duplicate_path, existing_hashes, duplicate_buckets)
    if args.scene_detection and not cached and cache_path is not None and cache_key is not None:
        save_scene_cache(
            cache_path,
            cache_key,
            video,
            [float(item) for item in reports.get("selected_times", [])],
            [float(item) for item in reports.get("scene_times", [])],
        )
    reports["cache_hit"] = bool(cached)
    reports["scene_cache_path"] = str(cache_path) if args.scene_detection and cache_path is not None else None
    reports["resource_guard"] = resource_info

    reports.update({
        "video": str(video),
        "duration_seconds": round(duration, 3),
        "source_width": int(metadata["width"]),
        "source_height": int(metadata["height"]),
        "source_fps": round(float(metadata["fps"]), 3),
        "analysis_width": args.analysis_width,
        "analysis_fps": args.analysis_fps,
    })
    finalize_report_diagnostics(reports, args)
    manifest_path = write_video_manifest(video, output_dir, args, reports)
    reports["manifest_path"] = str(manifest_path)
    print(
        f"  Kết quả: lưu={reports['saved']}, mờ={reports['rejected_blurry']}, "
        f"trùng={reports['rejected_duplicate']}, lỗi={reports['capture_errors']}"
    )
    return reports


def process_one_video(
    video: Path,
    output_root: Path,
    source_root: Path | None,
    args: argparse.Namespace,
    on_progress: ProgressCallback | None = None,
    cancel_event=None,
) -> dict[str, object]:
    # Mỗi worker có một bản args riêng vì process_video bổ sung source_fps vào args.
    worker_args = copy.copy(args)
    return process_video(video, output_root, source_root, worker_args, on_progress, cancel_event)


def process_videos(
    videos: list[Path],
    output_root: Path,
    source_root: Path | None,
    args: argparse.Namespace,
    on_complete: Callable[[Path, dict[str, object]], None] | None = None,
    on_progress: ProgressCallback | None = None,
    cancel_event=None,
    max_retries: int = 0,
    retry_delay_seconds: float = 1.0,
    pause_event=None,
) -> list[dict[str, object]]:
    """Xử lý queue video, retry từng item và trả báo cáo theo thứ tự đầu vào."""
    if not videos:
        return []

    requested_workers = getattr(args, "workers", 1)
    if isinstance(requested_workers, str) and requested_workers.lower() == "auto":
        requested_workers = recommend_workers(len(videos))
    worker_count = min(max(1, int(requested_workers)), len(videos))
    retry_count = max(0, int(max_retries))
    extract_worker_request = getattr(args, "extract_workers", 1)
    extract_worker_count = adaptive_extract_workers(worker_count, extract_worker_request)
    runtime_args = copy.copy(args)
    runtime_args.extract_workers = extract_worker_count
    runtime_args.video_workers = worker_count
    runtime_args.extract_min_targets = max(1, int(getattr(args, "extract_min_targets", 8)))
    results: dict[int, dict[str, object]] = {}
    checkpoint_file = checkpoint_path(output_root, args)
    run_signature = str(getattr(args, "queue_run_signature", "") or processing_signature(args))
    checkpoint = load_checkpoint(checkpoint_file)
    completed_checkpoint = checkpoint.get("completed", {}) if getattr(args, "resume", False) and checkpoint.get("run_signature") == run_signature else {}
    if not isinstance(completed_checkpoint, dict):
        completed_checkpoint = {}
    save_checkpoint(checkpoint_file, run_signature, completed_checkpoint)
    queue_store: PersistentQueueStore | None = None
    queue_job_id: str | None = None
    queue_db_value = getattr(args, "queue_db", None)
    if queue_db_value:
        queue_store = PersistentQueueStore(Path(queue_db_value))
        queue_job_id = queue_store.open_job(videos, run_signature, resume=bool(getattr(args, "resume", False)))
        if getattr(args, "resume", False):
            completed_checkpoint.update(queue_store.completed_reports(queue_job_id))
            save_checkpoint(checkpoint_file, run_signature, completed_checkpoint)

    def wait_retry_delay(seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, float(seconds))
        while True:
            wait_if_paused(pause_event, cancel_event)
            check_cancelled(cancel_event)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.2, remaining))

    def run_item(index: int, video: Path) -> dict[str, object]:
        last_error: Exception | None = None
        for attempt in range(retry_count + 1):
            wait_if_paused(pause_event, cancel_event)
            check_cancelled(cancel_event)
            phase = "retrying" if attempt else "queued"
            message = (
                f"Thử lại {attempt}/{retry_count} cho {video.name}"
                if attempt
                else f"Bắt đầu xử lý {video.name}"
            )
            emit_progress(on_progress, video, phase, 0.0, message)
            if queue_store is not None and queue_job_id is not None:
                queue_store.mark_running(queue_job_id, index, attempt + 1)
            try:
                report = process_one_video(video, output_root, source_root, runtime_args, on_progress, cancel_event)
                report["attempts"] = attempt + 1
                report["video_workers"] = worker_count
                report["configured_extract_workers"] = str(extract_worker_request)
                report["adaptive_extract_workers"] = extract_worker_count
                return report
            except ProcessingCancelled:
                if queue_store is not None and queue_job_id is not None:
                    queue_store.mark_cancelled(queue_job_id, index)
                raise
            except (RuntimeError, ValueError, OSError) as exc:
                last_error = exc
                if attempt >= retry_count:
                    break
                if queue_store is not None and queue_job_id is not None:
                    queue_store.mark_retrying(queue_job_id, index, attempt + 1, str(exc))
                emit_progress(
                    on_progress,
                    video,
                    "retrying",
                    0.0,
                    f"Lỗi lần {attempt + 1}; sẽ thử lại sau {retry_delay_seconds:g}s: {exc}",
                )
                wait_retry_delay(retry_delay_seconds)
        assert last_error is not None
        raise last_error

    def collect(index: int, video: Path, report: dict[str, object]) -> None:
        results[index] = report
        completed_checkpoint[str(video.resolve())] = report
        save_checkpoint(checkpoint_file, run_signature, completed_checkpoint)
        if queue_store is not None and queue_job_id is not None:
            if "error" in report:
                queue_store.mark_failed(queue_job_id, index, int(report.get("attempts", retry_count + 1)), str(report.get("error")), report)
            else:
                queue_store.mark_completed(queue_job_id, index, report)
        if on_complete is not None:
            on_complete(video, report)

    if worker_count == 1:
        for index, video in enumerate(videos):
            try:
                wait_if_paused(pause_event, cancel_event)
                check_cancelled(cancel_event)
            except ProcessingCancelled:
                if queue_store is not None and queue_job_id is not None:
                    queue_store.mark_cancelled(queue_job_id)
                    queue_store.close()
                raise
            checkpoint_key = str(video.resolve())
            if checkpoint_key in completed_checkpoint:
                report = completed_checkpoint[checkpoint_key]
                emit_progress(on_progress, video, "completed", 1.0, "Bỏ qua video đã hoàn tất từ checkpoint")
                collect(index, video, report)
                continue
            try:
                report = run_item(index, video)
            except ProcessingCancelled:
                if queue_store is not None and queue_job_id is not None:
                    queue_store.mark_cancelled(queue_job_id)
                    queue_store.close()
                raise
            except (RuntimeError, ValueError, OSError) as exc:
                report = {"video": str(video), "error": str(exc), "attempts": retry_count + 1}
                print(f"Bỏ qua {video}: {exc}", file=sys.stderr)
            collect(index, video, report)
        if queue_store is not None and queue_job_id is not None:
            queue_store.mark_completed_job(queue_job_id)
            queue_store.close()
        return [results[index] for index in range(len(videos))]

    print(f"Chạy bounded queue với {worker_count} worker cho {len(videos)} video")
    pending_videos: list[tuple[int, Path]] = []
    for index, video in enumerate(videos):
        checkpoint_key = str(video.resolve())
        if checkpoint_key in completed_checkpoint:
            results[index] = completed_checkpoint[checkpoint_key]
            emit_progress(on_progress, video, "completed", 1.0, "Bỏ qua video đã hoàn tất từ checkpoint")
            if on_complete is not None:
                on_complete(video, results[index])
        else:
            pending_videos.append((index, video))

    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="video-worker",
    ) as executor:
        future_map: dict[object, tuple[int, Path]] = {}
        next_pending = 0

        def submit_available() -> None:
            nonlocal next_pending
            while next_pending < len(pending_videos) and len(future_map) < worker_count:
                if pause_event is not None and pause_event.is_set():
                    return
                index, video = pending_videos[next_pending]
                next_pending += 1
                future_map[executor.submit(run_item, index, video)] = (index, video)

        submit_available()
        while future_map or next_pending < len(pending_videos):
            if not future_map:
                # Khi pause sau khi batch hiện tại hoàn tất, không submit thêm item.
                wait_if_paused(pause_event, cancel_event)
                check_cancelled(cancel_event)
                submit_available()
                continue
            done, _ = wait(tuple(future_map), return_when=FIRST_COMPLETED)
            for future in done:
                try:
                    check_cancelled(cancel_event)
                except ProcessingCancelled:
                    if queue_store is not None and queue_job_id is not None:
                        queue_store.mark_cancelled(queue_job_id)
                        queue_store.close()
                    raise
                index, video = future_map.pop(future)
                try:
                    report = future.result()
                except ProcessingCancelled:
                    if queue_store is not None and queue_job_id is not None:
                        queue_store.mark_cancelled(queue_job_id)
                        queue_store.close()
                    raise
                except (RuntimeError, ValueError, OSError) as exc:
                    report = {"video": str(video), "error": str(exc), "attempts": retry_count + 1}
                    print(f"Bỏ qua {video}: {exc}", file=sys.stderr)
                collect(index, video, report)
            submit_available()

    if queue_store is not None and queue_job_id is not None:
        queue_store.mark_completed_job(queue_job_id)
        queue_store.close()
    return [results[index] for index in range(len(videos))]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cắt screenshot bằng một lượt đọc video, có scene detection và lọc chất lượng."
    )
    parser.add_argument("input", type=Path, help="Một file video hoặc thư mục chứa video.")
    parser.add_argument("-o", "--output", type=Path, default=Path("screenshots_filtered"), help="Thư mục lưu ảnh.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--every", type=positive_float, help="Cắt một frame sau mỗi N giây; mặc định: 5.")
    mode.add_argument("--count", type=positive_int, help="Cắt đúng N frame phân bố đều.")
    mode.add_argument("--scene-detection", action="store_true", help="Tự phát hiện thay đổi cảnh.")
    parser.add_argument("--best-frame-per-scene", action="store_true", help="Giữ frame sắc nét nhất trong mỗi scene; tự bật scene detection.")
    parser.add_argument("--start", type=non_negative_float, default=0.0, help="Thời điểm bắt đầu, tính bằng giây.")
    parser.add_argument("--end", type=positive_float, default=None, help="Thời điểm kết thúc, tính bằng giây.")
    parser.add_argument(
        "--max-screenshots",
        type=positive_int,
        default=0,
        help="Số screenshot tối đa cho mỗi video; 0 = không giới hạn. Với --count, --count vẫn là số chính xác.",
    )
    parser.add_argument(
        "--target-count-after-filter",
        action="store_true",
        help="Cố gắng lưu đủ --max-screenshots sau filter; xét tối đa gấp 3 lần số candidate.",
    )
    parser.add_argument(
        "--min-free-ram-gb",
        type=non_negative_float,
        default=0.0,
        help="Không bắt đầu video nếu RAM khả dụng dưới ngưỡng GB; 0 = tắt.",
    )
    parser.add_argument("--scene-threshold", type=threshold_01, default=0.30, help="Ngưỡng thay đổi cảnh 0–1; thấp hơn nhạy hơn.")
    parser.add_argument("--min-scene-gap", type=positive_float, default=0.5, help="Khoảng cách tối thiểu giữa scene, tính bằng giây.")
    parser.add_argument("--flash-return-ratio", type=threshold_01, default=0.55, help="Tỷ lệ nhận diện flash quay về cảnh cũ.")
    parser.add_argument("--flash-brightness-threshold", type=threshold_01, default=0.18, help="Độ lệch sáng tối đa để xác nhận flash quay về.")
    parser.add_argument("--scene-confirmations", type=positive_int, default=2, help="Số frame liên tiếp cần xác nhận thay đổi cảnh; mặc định: 2.")
    parser.add_argument("--analysis-width", type=positive_int, default=640, help="Chiều rộng phân tích; nhỏ hơn giúp chạy nhanh hơn.")
    parser.add_argument("--analysis-fps", type=positive_float, default=8.0, help="Số frame/giây dùng cho phân tích scene.")
    parser.add_argument("--format", choices=("jpg", "png", "webp"), default="jpg", help="Định dạng ảnh.")
    parser.add_argument("--encode-profile", choices=ENCODE_PROFILE_LABELS, default="Chất lượng cao", help="Profile encode: Nhanh hoặc Chất lượng cao.")
    parser.add_argument("--quality", type=int, choices=range(1, 101), metavar="1-100", default=95, help="Chất lượng JPG/WebP.")
    parser.add_argument("--width", type=positive_int, default=None, help="Chiều rộng ảnh đầu ra; mặc định giữ kích thước nguồn.")
    parser.add_argument(
        "--crop-ratio",
        choices=CROP_RATIO_LABELS,
        default="Không crop",
        help="Crop chính giữa theo tỉ lệ trước khi resize/lưu; mặc định không crop.",
    )
    parser.add_argument("-r", "--recursive", action="store_true", help="Quét cả thư mục con.")
    parser.add_argument("--overwrite", action="store_true", help="Ghi đè ảnh đã tồn tại.")
    parser.add_argument("--retries", type=non_negative_int, default=2, help="Số lần retry cho mỗi video lỗi; mặc định: 2.")
    parser.add_argument("--retry-delay", type=non_negative_float, default=1.0, help="Số giây chờ giữa các lần retry.")
    parser.add_argument("--disk-reserve-mb", type=non_negative_int, default=512, help="Dung lượng trống tối thiểu để giữ làm vùng đệm.")
    parser.add_argument("--temp-cleanup-hours", type=non_negative_int, default=24, help="Dọn work directory tạm cũ hơn số giờ này.")
    parser.add_argument("--temp-quota-mb", type=non_negative_int, default=2048, help="Quota work directory tạm cũ; 0 để tắt quota.")
    parser.add_argument("--cache-quota-mb", type=non_negative_int, default=1024, help="Quota scene cache; chỉ xóa cache cũ hơn 7 ngày khi vượt quota, 0 để tắt.")
    parser.add_argument("--resume", action="store_true", help="Tiếp tục từ checkpoint của output run hiện tại.")
    parser.add_argument("--checkpoint", type=Path, default=None, help="Đường dẫn checkpoint JSON; mặc định nằm trong output.")
    parser.add_argument("--cache-dir", type=Path, default=None, help="Thư mục cache scene dùng lại giữa các lần chạy.")
    parser.add_argument("--duplicate-index-dir", type=Path, default=None, help="Thư mục index dHash dùng phát hiện trùng giữa các lần chạy.")
    parser.add_argument("--no-scene-cache", action="store_false", dest="use_scene_cache", help="Tắt cache scene.")
    parser.set_defaults(use_scene_cache=True)
    parser.add_argument("--no-cross-run-duplicates", action="store_false", dest="cross_run_duplicates", help="Tắt lọc trùng với các lần chạy trước.")
    parser.set_defaults(cross_run_duplicates=True)
    parser.add_argument("--min-sharpness", type=non_negative_float, default=100.0, help="Ngưỡng độ nét đã chuẩn hóa về chiều rộng tham chiếu 640 px; 0 để tắt.")
    parser.add_argument("--motion-blur-threshold", type=threshold_01, default=0.30, help="Ngưỡng motion blur 0–1; điểm cao hơn bị loại. Đặt 0 để tắt.")
    parser.add_argument("--duplicate-threshold", type=non_negative_int, default=6, help="Khoảng cách dHash tối đa để xem là trùng; 0 để tắt.")
    default_workers = recommend_workers()
    parser.add_argument(
        "--workers",
        type=worker_value,
        default=default_workers,
        help=f"Số worker hoặc auto theo CPU/RAM; mặc định: {default_workers}.",
    )
    parser.add_argument(
        "--extract-workers",
        type=non_negative_int,
        default=0,
        help="Số process trích frame fixed/count; 0 = tự chọn tối đa 4, 1 = tuần tự.",
    )
    parser.add_argument("--report", type=Path, default=None, help="Ghi báo cáo JSON.")
    parser.add_argument("--queue-db", type=Path, default=None, help="SQLite queue bền vững; mặc định: <output>/.frameforge_queue.sqlite3.")
    args = parser.parse_args()
    if args.best_frame_per_scene:
        args.scene_detection = True
    return args


def main() -> int:
    mp.freeze_support()
    args = parse_args()
    cleanup_frameforge_temp_dirs(
        older_than_seconds=int(args.temp_cleanup_hours) * 60 * 60,
        max_total_bytes=int(args.temp_quota_mb) * 1024**2,
    )
    cleanup_frameforge_cache(
        args.cache_dir or args.output / ".frameforge_cache",
        max_total_bytes=int(args.cache_quota_mb) * 1024**2,
    )
    args.disk_reserve_bytes = int(args.disk_reserve_mb) * 1024**2
    args.cache_root = args.cache_dir
    args.duplicate_root = args.duplicate_index_dir
    args.checkpoint_path = args.checkpoint
    args.queue_db = args.queue_db or args.output / ".frameforge_queue.sqlite3"
    args.cross_run_duplicate_threshold = args.duplicate_threshold
    args.extract_workers = recommended_extract_workers() if args.extract_workers == 0 else max(1, args.extract_workers)
    args.extract_min_targets = 8
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("Cảnh báo: không tìm thấy FFmpeg/ffprobe; pipeline hiện dùng OpenCV nhưng FFmpeg vẫn cần cho môi trường đầy đủ.", file=sys.stderr)
    try:
        videos = find_videos(args.input, args.recursive)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not videos:
        print("Không tìm thấy file video phù hợp.", file=sys.stderr)
        return 1

    args.output.mkdir(parents=True, exist_ok=True)
    source_root = args.input if args.input.is_dir() else None

    def on_complete(video: Path, report: dict[str, object]) -> None:
        if "error" in report:
            print(f"\n[{video.name}] lỗi: {report['error']}", file=sys.stderr)
        else:
            print(f"\n[{video.name}] hoàn tất: lưu={report.get('saved', 0)}")

    def on_progress(video: Path, phase: str, fraction: float, message: str) -> None:
        print(f"[{video.name}] {phase} {fraction:.0%} · {message}")

    try:
        reports = process_videos(
            videos,
            args.output,
            source_root,
            args,
            on_complete,
            on_progress,
            max_retries=args.retries,
            retry_delay_seconds=args.retry_delay,
        )
    except ProcessingCancelled as exc:
        print(str(exc), file=sys.stderr)
        return 130
    except InsufficientDiskSpace as exc:
        print(str(exc), file=sys.stderr)
        return 3

    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nĐã ghi báo cáo: {args.report}")

    saved = sum(int(item.get("saved", 0)) for item in reports)
    blurry = sum(int(item.get("rejected_blurry", 0)) for item in reports)
    motion_blur = sum(int(item.get("rejected_motion_blur", 0)) for item in reports)
    duplicate = sum(int(item.get("rejected_duplicate", 0)) for item in reports)
    errors = sum(int(item.get("capture_errors", 0)) for item in reports) + sum("error" in item for item in reports)
    print(f"\nHoàn tất: lưu={saved}, loại mờ={blurry}, motion blur={motion_blur}, loại trùng={duplicate}, lỗi={errors}.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
