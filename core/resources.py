"""Resource management for FrameForge video processing.

Extracted from video_screenshot_advanced.py to separate concerns.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path


class InsufficientResources(RuntimeError):
    """Tài nguyên khả dụng thấp hơn ngưỡng an toàn của job."""


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
    """Ước lượng RAM tổng cộng của hệ thống bằng stdlib, trả None nếu không đọc được."""
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


def estimate_screenshot_count(duration: float, args: argparse.Namespace) -> int:
    """Ước tính số screenshot sẽ tạo từ duration và cấu hình."""
    configured = int(getattr(args, "max_screenshots", 0) or 0)
    if configured > 0:
        return configured
    if getattr(args, "count", None) is not None:
        return max(1, int(args.count))
    every = getattr(args, "every", None)
    if every is not None and float(every) > 0:
        return max(1, math.ceil(max(0.0, duration) / float(every)))
    return 0


def resource_admission_guard(output_root: Path, args: argparse.Namespace) -> dict[str, object]:
    """Kiểm tra RAM/disk trước khi cấp thêm video vào queue."""
    from core.pipeline import ensure_free_disk_space

    free_disk = ensure_free_disk_space(
        output_root,
        required_bytes=0,
        reserve_bytes=int(getattr(args, "disk_reserve_bytes", 0) or 0),
    )
    ram = available_ram_gb()
    minimum_ram = float(getattr(args, "min_free_ram_gb", 0.0) or 0.0)
    if ram is not None and minimum_ram > 0 and ram < minimum_ram:
        raise InsufficientResources(
            f"RAM khả dụng chỉ còn {ram:.1f} GB, thấp hơn ngưỡng {minimum_ram:.1f} GB."
        )
    return {"free_disk_bytes": free_disk, "available_ram_gb": ram}


def resource_guard(output_dir: Path, duration: float, args: argparse.Namespace) -> dict[str, object]:
    """Kiểm tra RAM/disk trước khi bắt đầu xử lý một video."""
    from core.pipeline import ensure_free_disk_space

    estimated_count = estimate_screenshot_count(duration, args)
    bytes_per_image = 4 * 1024**2 if getattr(args, "format", "jpg") == "png" else 2 * 1024**2
    estimated_bytes = estimated_count * bytes_per_image
    free_disk = ensure_free_disk_space(
        output_dir,
        required_bytes=estimated_bytes,
        reserve_bytes=int(getattr(args, "disk_reserve_bytes", 0) or 0),
    )
    ram = available_ram_gb()
    minimum_ram = float(getattr(args, "min_free_ram_gb", 0.0) or 0.0)
    if ram is not None and minimum_ram > 0 and ram < minimum_ram:
        raise InsufficientResources(
            f"RAM khả dụng chỉ còn {ram:.1f} GB, thấp hơn ngưỡng {minimum_ram:.1f} GB."
        )
    return {
        "estimated_screenshots": estimated_count,
        "estimated_output_bytes": estimated_bytes,
        "free_disk_bytes": free_disk,
        "available_ram_gb": round(ram, 3) if ram is not None else None,
    }


def finalize_report_diagnostics(reports: dict[str, object], args: argparse.Namespace) -> dict[str, object]:
    """Bổ sung shortfall diagnostics vào report sau khi xử lý xong."""
    target_mode = bool(getattr(args, "target_count_after_filter", False))
    target = int(getattr(args, "max_screenshots", 0) or 0) if target_mode else 0
    saved = int(reports.get("saved", 0) or 0)
    shortfall = max(0, target - saved) if target > 0 else 0
    reports["target_screenshots"] = target
    reports["target_count_after_filter"] = target_mode
    reports["forced_fallback_saved"] = int(reports.get("forced_fallback_saved", 0) or 0)
    reports["forced_fallback_reasons"] = list(reports.get("forced_fallback_reasons", []) or [])
    reports["force_fill_shortfall"] = max(
        0,
        int(reports.get("force_fill_shortfall", shortfall) or 0),
    )
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
            "không đủ candidate hợp lệ hoặc frame đọc được để fallback."
        )
    elif reports["forced_fallback_saved"]:
        reports["shortfall_message"] = (
            f"Đã đủ {target} screenshot; trong đó {reports['forced_fallback_saved']} ảnh "
            "được lưu bằng fallback sau khi filter loại candidate."
        )
    else:
        reports["shortfall_message"] = None
    return reports
