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
from core.utils import atomic_write_json as _atomic_write_json
from core.utils import read_json as _read_json
from core.utils import format_bytes
from core.config import FrameForgeConfig
from core.targets import (
    screenshot_limit,
    candidate_limit,
    candidate_budget_bounds,
    expand_candidate_budget,
)
from core.cv2_helpers import laplacian_variance, motion_blur_score, dhash, hamming_distance
from core.resources import (
    InsufficientResources,
    available_ram_gb,
    estimate_screenshot_count,
    finalize_report_diagnostics,
    resource_admission_guard,
    resource_guard,
)
from core.manifest import verify_video_manifest, write_video_manifest
from core.pipeline import (
    VIDEO_EXTENSIONS,
    REFERENCE_ANALYSIS_WIDTH,
    CROP_RATIO_LABELS,
    CROP_RATIO_VALUES,
    ENCODE_PROFILE_LABELS,
    ENCODE_PROFILES,
    MetricRequirements,
    ProcessingCancelled,
    InsufficientDiskSpace,
    ProgressCallback,
    CancelCheck,
    cancellation_requested,
    check_cancelled,
    wait_if_paused,
    emit_progress,
    current_process_rss_bytes,
    free_disk_bytes,
    ensure_free_disk_space,
    scene_cache_path,
    duplicate_index_path,
    processing_signature,
    scene_cache_key,
    build_run_signature,
    checkpoint_path,
    load_checkpoint,
    save_checkpoint,
    load_scene_cache,
    save_scene_cache,
    load_duplicate_index,
    load_duplicate_hashes,
    save_duplicate_hashes,
    cleanup_frameforge_temp_dirs,
    cleanup_frameforge_cache,
    positive_float,
    non_negative_float,
    positive_int,
    non_negative_int,
    threshold_01,
    recommend_workers,
    worker_value,
    recommended_extract_workers,
    adaptive_extract_workers,
    find_videos,
    _dhash_bucket_keys,
    metric_requirements,
    timestamp_label,
    new_stage_timings,
    record_stage_timing,
)


import cv2
import numpy as np
from PIL import Image
from persistent_queue import PersistentQueueStore

# ── Re-exports for backward compatibility ─────────────────────────────
# These symbols live in core.pipeline but are re-exported here so that
# existing imports from video_screenshot_advanced continue to work.
VideoExtensions = VIDEO_EXTENSIONS
ReferenceAnalysisWidth = REFERENCE_ANALYSIS_WIDTH
CropRatioLabels = CROP_RATIO_LABELS
CropRatioValues = CROP_RATIO_VALUES
EncodeProfileLabels = ENCODE_PROFILE_LABELS
EncodeProfiles = ENCODE_PROFILES


@dataclass(frozen=True)
class FrameCandidate:
    frame: np.ndarray
    timestamp: float
    sharpness: float
    motion_blur_score: float
    hash_value: int
    brightness: float
    gray: np.ndarray
    histogram: np.ndarray



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



def crop_to_aspect_ratio(
    frame: np.ndarray,
    crop_ratio: str | None,
) -> np.ndarray:
    if crop_ratio is None or str(crop_ratio).strip() in ('', 'none', 'Khong crop'):
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


def accept_and_save(
    candidate: FrameCandidate,
    output_dir: Path,
    video_stem: str,
    index: int,
    args: FrameForgeConfig,
    previous_hash: int | None,
    existing_hashes: set[int] | None = None,
    duplicate_buckets: dict[str, set[int]] | None = None,
    *,
    force_fill: bool = False,
) -> tuple[str, int | None]:
    if not force_fill and args.min_sharpness > 0 and candidate.sharpness < args.min_sharpness:
        return "blurry", previous_hash
    motion_threshold = float(args.motion_blur_threshold)
    if not force_fill and motion_threshold > 0 and candidate.motion_blur_score > motion_threshold:
        return "motion_blur", previous_hash
    if (
        not force_fill
        and args.duplicate_threshold > 0
        and previous_hash is not None
        and hamming_distance(candidate.hash_value, previous_hash) <= args.duplicate_threshold
    ):
        return "duplicate", previous_hash
    cross_run_threshold = int(args.cross_run_duplicate_threshold)
    comparison_hashes = existing_hashes
    if duplicate_buckets is not None and cross_run_threshold <= 6:
        comparison_hashes = set()
        for bucket_key in _dhash_bucket_keys(candidate.hash_value):
            comparison_hashes.update(duplicate_buckets.get(bucket_key, set()))
    if (
        not force_fill
        and args.cross_run_duplicates
        and cross_run_threshold > 0
        and comparison_hashes
        and any(hamming_distance(candidate.hash_value, item) <= cross_run_threshold for item in comparison_hashes)
    ):
        return "duplicate_cross_run", previous_hash

    filename = f"{timestamp_label(candidate.timestamp)}.{args.format}"
    output = output_dir / filename
    if output.exists() and not args.overwrite:
        if not force_fill:
            return "existing", candidate.hash_value
        suffix = 1
        while output.exists():
            filename = f"{timestamp_label(candidate.timestamp)}_fallback_{index:04d}_{suffix}.{args.format}"
            output = output_dir / filename
            suffix += 1
    save_image(
        candidate.frame,
        output,
        args.format,
        args.quality,
        args.width,
        args.crop_ratio,
        args.encode_profile,
        args.stage_timings,
    )
    if existing_hashes is not None:
        existing_hashes.add(candidate.hash_value)
    if duplicate_buckets is not None:
        for bucket_key in _dhash_bucket_keys(candidate.hash_value):
            duplicate_buckets.setdefault(bucket_key, set()).add(candidate.hash_value)
    print(f"  lưu — {output.name} sharpness={candidate.sharpness:.1f}")
    return "saved", candidate.hash_value


def force_fill_target(
    fallback_candidates: list[tuple[FrameCandidate, str]],
    output_dir: Path,
    video_stem: str,
    args: FrameForgeConfig,
    reports: dict[str, object],
    previous_hash: int | None,
    existing_hashes: set[int] | None,
    duplicate_buckets: dict[str, set[int]] | None,
) -> int | None:
    """Bù target bằng candidate bị loại, theo thứ tự ít rủi ro nhất.

    Filter vẫn chạy bình thường ở vòng chính. Chỉ khi bật target mode và còn thiếu
    ảnh, vòng này mới nới filter; report ghi rõ số ảnh đã dùng fallback để người
    dùng biết chất lượng có thể thấp hơn ngưỡng ban đầu.
    """
    target = screenshot_limit(args)
    if not args.target_count_after_filter or target is None:
        return previous_hash
    missing = max(0, target - int(reports.get("saved", 0) or 0))
    if missing <= 0 or not fallback_candidates:
        return previous_hash
    reason_rank = {
        "duplicate_cross_run": 0,
        "duplicate": 1,
        "motion_blur": 2,
        "blurry": 3,
        "not_selected": 4,
    }
    ordered = sorted(
        fallback_candidates,
        key=lambda item: (reason_rank.get(item[1], 5), -float(item[0].sharpness), float(item[0].timestamp)),
    )
    used_timestamps: set[float] = set()
    for candidate, reason in ordered:
        if missing <= 0:
            break
        timestamp = round(float(candidate.timestamp), 3)
        if timestamp in used_timestamps:
            continue
        status, previous_hash = accept_and_save(
            candidate,
            output_dir,
            video_stem,
            int(reports.get("saved", 0) or 0) + 1,
            args,
            previous_hash,
            existing_hashes,
            duplicate_buckets,
            force_fill=True,
        )
        if status == "saved":
            reports["saved"] = int(reports.get("saved", 0) or 0) + 1
            reports["forced_fallback_saved"] = int(reports.get("forced_fallback_saved", 0) or 0) + 1
            reports.setdefault("forced_fallback_reasons", []).append(reason)
            missing -= 1
            used_timestamps.add(timestamp)
    reports["force_fill_shortfall"] = max(0, missing)
    return previous_hash


# recommended_extract_workers and adaptive_extract_workers
# → core/pipeline.py (canonical implementations)


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
    args: FrameForgeConfig,
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
        "extraction_workers": max(1, args.extract_workers),
        "stage_timings": args.stage_timings,
    }
    temp_dir = Path(tempfile.mkdtemp(prefix="frameforge_extract_", dir=str(output_dir)))
    worker_count = min(max(2, max(2, args.extract_workers)), len(targets))
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
                    record_stage_timing(args.stage_timings, "decode", decode_started)
                    if frame is None:
                        reports["capture_errors"] = int(reports["capture_errors"]) + 1
                    else:
                        analysis_started = time.perf_counter()
                        candidate = frame_candidate(frame, timestamp, args.analysis_width, requirements)
                        record_stage_timing(args.stage_timings, "analysis", analysis_started)
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


# screenshot_limit, candidate_limit, candidate_budget_bounds,
# expand_candidate_budget → core/targets.py


def process_fixed_mode(
    capture: cv2.VideoCapture,
    video: Path,
    output_dir: Path,
    duration: float,
    args: FrameForgeConfig,
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
    target_mode = bool(args.target_count_after_filter)
    target_candidates, maximum_candidates = candidate_budget_bounds(args)
    if target_candidates is not None and args.count is None and not args.target_count_after_filter:
        targets = targets[:target_candidates]
    if target_candidates is not None and args.count is None and args.target_count_after_filter:
        target_candidates = min(len(targets), target_candidates)

    effective_extract_workers = adaptive_extract_workers(
        video_worker_count=int(args.video_workers or 1),
        requested_workers=args.extract_workers or 1,
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
        "forced_fallback_saved": 0,
        "forced_fallback_reasons": [],
        "force_fill_shortfall": 0,
        "scene_times": [],
        "extraction_mode": "sequential",
        "extraction_workers": effective_extract_workers,
        "stage_timings": args.stage_timings,
    }
    if effective_extract_workers > 1 and len(targets) >= int(args.extract_min_targets) and not target_mode:
        multiprocessing_args = copy.copy(args)
        multiprocessing_args.extract_workers = effective_extract_workers
        return process_fixed_mode_multiprocess(
            video, output_dir, targets, multiprocessing_args, on_progress, cancel_event, existing_hashes, duplicate_buckets
        )
    target_index = 0
    fallback_candidates: list[tuple[FrameCandidate, str]] = []
    frame_index = 0
    requirements = metric_requirements(args)
    previous_hash: int | None = None
    estimated_frames = max(1, int(max(0.0, actual_end - actual_start) * max(args.source_fps, 1.0)))
    while target_index < len(targets) and (target_candidates is None or target_index < target_candidates):
        check_cancelled(cancel_event)
        if target_mode and limit is not None and int(reports["saved"]) >= limit:
            break
        decode_started = time.perf_counter()
        ok, frame = capture.read()
        record_stage_timing(args.stage_timings, "decode", decode_started)
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
        record_stage_timing(args.stage_timings, "analysis", analysis_started)
        status, previous_hash = accept_and_save(
            candidate, output_dir, video.stem, target_index + 1, args, previous_hash, existing_hashes, duplicate_buckets
        )
        reports[status_key(status)] = int(reports[status_key(status)]) + 1
        if target_mode and status != "saved":
            fallback_candidates.append((candidate, status))
        emit_progress(
            on_progress,
            video,
            "selecting",
            target_index / max(len(targets), 1),
            f"Đã xử lý {target_index}/{len(targets)} mốc",
        )
        target_index += 1
        if target_mode and limit is not None and target_candidates is not None:
            rejected = target_index - int(reports["saved"])
            target_candidates = expand_candidate_budget(target_candidates, maximum_candidates, limit, target_index, rejected)
        emit_progress(
            on_progress,
            video,
            "selecting",
            target_index / max(len(targets), 1),
            f"Đã xử lý {target_index}/{len(targets)} mốc",
        )
    if target_mode:
        force_fill_target(
            fallback_candidates,
            output_dir,
            video.stem,
            args,
            reports,
            previous_hash,
            existing_hashes,
            duplicate_buckets,
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
    args: FrameForgeConfig,
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
        "forced_fallback_saved": 0,
        "forced_fallback_reasons": [],
        "force_fill_shortfall": 0,
        "scene_times": [],
        "selected_times": [],
        "scene_confirmations": args.scene_confirmations,
        "smart_scene_detection": True,
    }
    limit = screenshot_limit(args)
    target_mode = bool(args.target_count_after_filter)
    candidate_budget, maximum_candidate_budget = candidate_budget_bounds(args)
    candidate_count = 0
    selected_times: list[float] = []
    fallback_candidates: list[tuple[FrameCandidate, str]] = []
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
        if target_mode and status != "saved":
            fallback_candidates.append((candidate, status))
        return updated_hash

    while True:
        check_cancelled(cancel_event)
        if (target_mode and limit is not None and int(reports["saved"]) >= limit) or (not target_mode and limit is not None and len(selected_times) >= limit) or (candidate_budget is not None and candidate_count >= candidate_budget):
            break
        decode_started = time.perf_counter()
        ok, frame = capture.read()
        record_stage_timing(args.stage_timings, "decode", decode_started)
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
        candidate_count += 1
        record_stage_timing(args.stage_timings, "analysis", analysis_started)
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
                    args.motion_blur_threshold,
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
                    args.motion_blur_threshold,
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
                    args.motion_blur_threshold <= 0
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
                    args.motion_blur_threshold,
                )

        if target_mode and limit is not None and candidate_budget is not None:
            rejected = max(0, candidate_count - int(reports["saved"]))
            candidate_budget = expand_candidate_budget(candidate_budget, maximum_candidate_budget, limit, candidate_count, rejected)
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
                args.motion_blur_threshold,
            )
    previous_hash = flush(current_best, scene_index + 1, previous_hash)
    if target_mode:
        force_fill_target(
            fallback_candidates,
            output_dir,
            video.stem,
            args,
            reports,
            previous_hash,
            existing_hashes,
            duplicate_buckets,
        )
    reports["selected_times"] = selected_times
    emit_progress(on_progress, video, "saving", 1.0, "Đã hoàn tất ghi screenshot")
    return reports


def process_cached_scene_mode(
    capture: cv2.VideoCapture,
    video: Path,
    output_dir: Path,
    args: FrameForgeConfig,
    cached: dict[str, object],
    existing_hashes: set[int],
    duplicate_buckets: dict[str, set[int]] | None = None,
    on_progress: ProgressCallback | None = None,
    cancel_event=None,
) -> dict[str, object]:
    limit = screenshot_limit(args)
    target_mode = bool(args.target_count_after_filter)
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
        "stage_timings": args.stage_timings,
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
        record_stage_timing(args.stage_timings, "decode", decode_started)
        if not ok:
            reports["capture_errors"] = int(reports["capture_errors"]) + 1
            continue
        analysis_started = time.perf_counter()
        candidate = frame_candidate(frame, timestamp, args.analysis_width, requirements)
        record_stage_timing(args.stage_timings, "analysis", analysis_started)
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
    args: FrameForgeConfig,
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
    duplicate_root_value = args.duplicate_root
    duplicate_root = Path(duplicate_root_value) if duplicate_root_value else output_root / ".frameforge_hashes"
    duplicate_root.mkdir(parents=True, exist_ok=True)
    duplicate_path = duplicate_index_path(video, duplicate_root)
    existing_hashes, duplicate_buckets = load_duplicate_index(duplicate_path)
    cache_root_value = args.cache_root
    cache_root = Path(cache_root_value) if cache_root_value else output_root / ".frameforge_cache"
    cache_path: Path | None = None
    cache_key: str | None = None
    cached: dict[str, object] | None = None
    if args.scene_detection:
        cache_root.mkdir(parents=True, exist_ok=True)
        cache_path = scene_cache_path(video, cache_root)
        cache_key = scene_cache_key(video, metadata, args)
        if args.use_scene_cache:
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
    reports["manifest_validation"] = verify_video_manifest(video, output_dir)
    print(
        f"  Kết quả: lưu={reports['saved']}, mờ={reports['rejected_blurry']}, "
        f"trùng={reports['rejected_duplicate']}, lỗi={reports['capture_errors']}"
    )
    return reports


def process_one_video(
    video: Path,
    output_root: Path,
    source_root: Path | None,
    args: FrameForgeConfig,
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
    args: FrameForgeConfig,
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

    requested_workers = args.workers
    if isinstance(requested_workers, str) and requested_workers.lower() == "auto":
        requested_workers = recommend_workers(len(videos))
    worker_count = min(max(1, int(requested_workers)), len(videos))
    retry_count = max(0, int(max_retries))
    extract_worker_request = args.extract_workers or 1
    extract_worker_count = adaptive_extract_workers(worker_count, extract_worker_request)
    runtime_args = copy.copy(args)
    runtime_args.extract_workers = extract_worker_count
    runtime_args.video_workers = worker_count
    runtime_args.extract_min_targets = max(1, int(args.extract_min_targets))
    results: dict[int, dict[str, object]] = {}
    checkpoint_file = checkpoint_path(output_root, args)
    run_signature = str(args.queue_run_signature or processing_signature(args))
    checkpoint = load_checkpoint(checkpoint_file)
    completed_checkpoint = checkpoint.get("completed", {}) if args.resume and checkpoint.get("run_signature") == run_signature else {}
    if not isinstance(completed_checkpoint, dict):
        completed_checkpoint = {}
    save_checkpoint(checkpoint_file, run_signature, completed_checkpoint)
    queue_store: PersistentQueueStore | None = None
    queue_job_id: str | None = None
    queue_db_value = args.queue_db
    if queue_db_value:
        queue_store = PersistentQueueStore(Path(queue_db_value))
        queue_job_id = queue_store.open_job(videos, run_signature, resume=bool(args.resume))
        if args.resume:
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
        resource_blocked = False

        def submit_available() -> None:
            nonlocal next_pending, resource_blocked
            while next_pending < len(pending_videos) and len(future_map) < worker_count:
                if pause_event is not None and pause_event.is_set():
                    return
                try:
                    resource_admission_guard(output_root, args)
                except (InsufficientDiskSpace, InsufficientResources) as exc:
                    resource_blocked = True
                    index, video = pending_videos[next_pending]
                    emit_progress(on_progress, video, "resource_wait", 0.0, f"Đang chờ tài nguyên: {exc}")
                    return
                resource_blocked = False
                index, video = pending_videos[next_pending]
                next_pending += 1
                future_map[executor.submit(run_item, index, video)] = (index, video)

        submit_available()
        while future_map or next_pending < len(pending_videos):
            if not future_map:
                # Khi pause hoặc thiếu tài nguyên, không submit thêm item.
                wait_if_paused(pause_event, cancel_event)
                check_cancelled(cancel_event)
                submit_available()
                if resource_blocked:
                    time.sleep(0.5)
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


