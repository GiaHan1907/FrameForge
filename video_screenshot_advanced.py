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
import json
import math
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".ts", ".mts"
}
REFERENCE_ANALYSIS_WIDTH = 640


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


@dataclass
class PendingCut:
    before_gray: np.ndarray
    before_histogram: np.ndarray
    before_brightness: float
    candidate: FrameCandidate
    confirmations: int = 1


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


def frame_candidate(frame: np.ndarray, timestamp: float, analysis_width: int) -> FrameCandidate:
    gray = resize_for_analysis(frame, analysis_width)
    raw_sharpness = laplacian_variance(gray)
    blur_score = motion_blur_score(gray)
    histogram = color_histogram(frame, analysis_width)
    # Quy về cùng mốc 640 px để threshold ổn định hơn giữa các độ phân giải.
    width_scale = (REFERENCE_ANALYSIS_WIDTH / max(gray.shape[1], 1)) ** 2
    normalized_sharpness = raw_sharpness * width_scale
    return FrameCandidate(
        frame=frame.copy(),
        timestamp=timestamp,
        sharpness=normalized_sharpness,
        motion_blur_score=blur_score,
        hash_value=dhash(gray),
        brightness=float(np.mean(gray)) / 255.0,
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


def save_image(frame: np.ndarray, output: Path, image_format: str, quality: int, width: int | None) -> None:
    if width is not None and frame.shape[1] > width:
        target_height = max(1, round(frame.shape[0] * width / frame.shape[1]))
        frame = cv2.resize(frame, (width, target_height), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    image = Image.fromarray(rgb)
    if image_format == "jpg":
        image.save(output, format="JPEG", quality=quality, optimize=True)
    elif image_format == "webp":
        image.save(output, format="WEBP", quality=quality, method=6)
    else:
        image.save(output, format="PNG", optimize=True)


def accept_and_save(
    candidate: FrameCandidate,
    output_dir: Path,
    video_stem: str,
    index: int,
    args: argparse.Namespace,
    previous_hash: int | None,
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

    filename = f"{video_stem}_{index:05d}_{timestamp_label(candidate.timestamp)}.{args.format}"
    output = output_dir / filename
    if output.exists() and not args.overwrite:
        return "existing", candidate.hash_value
    save_image(candidate.frame, output, args.format, args.quality, args.width)
    print(f"  lưu — {output.name} sharpness={candidate.sharpness:.1f}")
    return "saved", candidate.hash_value


def process_fixed_mode(
    capture: cv2.VideoCapture,
    video: Path,
    output_dir: Path,
    duration: float,
    args: argparse.Namespace,
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

    reports = {
        "selection_mode": "fixed_interval" if args.count is None else "count",
        "requested": len(targets),
        "saved": 0,
        "rejected_blurry": 0,
        "rejected_motion_blur": 0,
        "rejected_duplicate": 0,
        "skipped_existing": 0,
        "capture_errors": 0,
        "scene_times": [],
    }
    target_index = 0
    frame_index = 0
    previous_hash: int | None = None
    while target_index < len(targets):
        ok, frame = capture.read()
        if not ok:
            reports["capture_errors"] = int(reports["capture_errors"]) + (len(targets) - target_index)
            break
        timestamp = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if timestamp <= 0 or not math.isfinite(timestamp):
            timestamp = frame_index / max(args.source_fps, 1.0)
        frame_index += 1
        if timestamp + 1e-6 < targets[target_index]:
            continue
        if timestamp > actual_end + 0.05:
            break
        candidate = frame_candidate(frame, timestamp, args.analysis_width)
        status, previous_hash = accept_and_save(
            candidate, output_dir, video.stem, target_index + 1, args, previous_hash
        )
        reports[status_key(status)] = int(reports[status_key(status)]) + 1
        target_index += 1
    return reports


def status_key(status: str) -> str:
    return {
        "saved": "saved",
        "blurry": "rejected_blurry",
        "duplicate": "rejected_duplicate",
        "motion_blur": "rejected_motion_blur",
        "existing": "skipped_existing",
    }.get(status, "capture_errors")


def process_scene_mode(
    capture: cv2.VideoCapture,
    video: Path,
    output_dir: Path,
    duration: float,
    args: argparse.Namespace,
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
        "skipped_existing": 0,
        "capture_errors": 0,
        "scene_times": [],
        "scene_confirmations": args.scene_confirmations,
        "smart_scene_detection": True,
    }
    previous_gray: np.ndarray | None = None
    previous_histogram: np.ndarray | None = None
    previous_brightness: float | None = None
    next_sample = actual_start
    last_scene_timestamp = actual_start - args.min_scene_gap
    sample_interval = 1.0 / args.analysis_fps
    current_best: FrameCandidate | None = None
    pending: PendingCut | None = None
    previous_hash: int | None = None
    scene_index = 0
    frame_index = 0

    def flush(candidate: FrameCandidate | None, index: int, previous: int | None) -> int | None:
        if candidate is None:
            return previous
        reports["requested"] = int(reports["requested"]) + 1
        status, updated_hash = accept_and_save(candidate, output_dir, video.stem, index, args, previous)
        reports[status_key(status)] = int(reports[status_key(status)]) + 1
        return updated_hash

    while True:
        ok, frame = capture.read()
        if not ok:
            break
        timestamp = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if timestamp <= 0 or not math.isfinite(timestamp):
            timestamp = frame_index / max(args.source_fps, 1.0)
        frame_index += 1
        if timestamp + 1e-6 < actual_start:
            continue
        if timestamp > actual_end:
            break
        if timestamp + 1e-6 < next_sample:
            continue
        next_sample = timestamp + sample_interval
        candidate = frame_candidate(frame, timestamp, args.analysis_width)

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
    return reports


def process_video(
    video: Path,
    output_root: Path,
    source_root: Path | None,
    args: argparse.Namespace,
) -> dict[str, object]:
    metadata = probe_video(video)
    duration = float(metadata["duration"])
    if source_root is not None:
        relative_parent = video.parent.relative_to(source_root)
        output_dir = output_root / relative_parent / video.stem
    else:
        output_dir = output_root / video.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    args.source_fps = float(metadata["fps"])
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"Không mở được video: {video}")
    try:
        if args.scene_detection:
            reports = process_scene_mode(capture, video, output_dir, duration, args)
        else:
            reports = process_fixed_mode(capture, video, output_dir, duration, args)
    finally:
        capture.release()

    reports.update({
        "video": str(video),
        "duration_seconds": round(duration, 3),
        "source_width": int(metadata["width"]),
        "source_height": int(metadata["height"]),
        "source_fps": round(float(metadata["fps"]), 3),
        "analysis_width": args.analysis_width,
        "analysis_fps": args.analysis_fps,
    })
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
) -> dict[str, object]:
    # Mỗi worker có một bản args riêng vì process_video bổ sung source_fps vào args.
    worker_args = copy.copy(args)
    return process_video(video, output_root, source_root, worker_args)


def process_videos(
    videos: list[Path],
    output_root: Path,
    source_root: Path | None,
    args: argparse.Namespace,
    on_complete: Callable[[Path, dict[str, object]], None] | None = None,
) -> list[dict[str, object]]:
    """Xử lý các video độc lập song song và trả báo cáo theo thứ tự đầu vào."""
    if not videos:
        return []

    requested_workers = getattr(args, "workers", 1)
    if isinstance(requested_workers, str) and requested_workers.lower() == "auto":
        requested_workers = recommend_workers(len(videos))
    worker_count = min(max(1, int(requested_workers)), len(videos))
    results: dict[int, dict[str, object]] = {}

    def collect(index: int, video: Path, report: dict[str, object]) -> None:
        results[index] = report
        if on_complete is not None:
            on_complete(video, report)

    if worker_count == 1:
        for index, video in enumerate(videos):
            try:
                report = process_one_video(video, output_root, source_root, args)
            except (RuntimeError, ValueError, OSError) as exc:
                report = {"video": str(video), "error": str(exc)}
                print(f"Bỏ qua {video}: {exc}", file=sys.stderr)
            collect(index, video, report)
        return [results[index] for index in range(len(videos))]

    print(f"Chạy song song {worker_count} worker cho {len(videos)} video")
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="video-worker",
    ) as executor:
        future_map = {
            executor.submit(process_one_video, video, output_root, source_root, args): (index, video)
            for index, video in enumerate(videos)
        }
        for future in as_completed(future_map):
            index, video = future_map[future]
            try:
                report = future.result()
            except (RuntimeError, ValueError, OSError) as exc:
                report = {"video": str(video), "error": str(exc)}
                print(f"Bỏ qua {video}: {exc}", file=sys.stderr)
            collect(index, video, report)

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
    parser.add_argument("--scene-threshold", type=threshold_01, default=0.30, help="Ngưỡng thay đổi cảnh 0–1; thấp hơn nhạy hơn.")
    parser.add_argument("--min-scene-gap", type=positive_float, default=0.5, help="Khoảng cách tối thiểu giữa scene, tính bằng giây.")
    parser.add_argument("--flash-return-ratio", type=threshold_01, default=0.55, help="Tỷ lệ nhận diện flash quay về cảnh cũ.")
    parser.add_argument("--flash-brightness-threshold", type=threshold_01, default=0.18, help="Độ lệch sáng tối đa để xác nhận flash quay về.")
    parser.add_argument("--scene-confirmations", type=positive_int, default=2, help="Số frame liên tiếp cần xác nhận thay đổi cảnh; mặc định: 2.")
    parser.add_argument("--analysis-width", type=positive_int, default=640, help="Chiều rộng phân tích; nhỏ hơn giúp chạy nhanh hơn.")
    parser.add_argument("--analysis-fps", type=positive_float, default=8.0, help="Số frame/giây dùng cho phân tích scene.")
    parser.add_argument("--format", choices=("jpg", "png", "webp"), default="jpg", help="Định dạng ảnh.")
    parser.add_argument("--quality", type=int, choices=range(1, 101), metavar="1-100", default=95, help="Chất lượng JPG/WebP.")
    parser.add_argument("--width", type=positive_int, default=None, help="Chiều rộng ảnh đầu ra; mặc định giữ kích thước nguồn.")
    parser.add_argument("-r", "--recursive", action="store_true", help="Quét cả thư mục con.")
    parser.add_argument("--overwrite", action="store_true", help="Ghi đè ảnh đã tồn tại.")
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
    parser.add_argument("--report", type=Path, default=None, help="Ghi báo cáo JSON.")
    args = parser.parse_args()
    if args.best_frame_per_scene:
        args.scene_detection = True
    return args


def main() -> int:
    args = parse_args()
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

    reports = process_videos(videos, args.output, source_root, args, on_complete)

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
