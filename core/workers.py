"""Worker recommendation, argument validators, and metric requirements.

Extracted from ``core/pipeline.py`` to isolate CPU/RAM budgeting logic
and make it independently testable.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass


# ── Memory helper ─────────────────────────────────────────────────────


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
        getattr(args, "cross_run_duplicate_threshold", duplicate_threshold)
        or duplicate_threshold
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
