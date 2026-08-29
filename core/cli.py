"""FrameForge CLI entry point.

Extracted from video_screenshot_advanced.py.  This module imports from
video_screenshot_advanced (not the other way around) to avoid circular
dependencies.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import shutil
import sys
from pathlib import Path

from core.pipeline import (
    CROP_RATIO_LABELS,
    ENCODE_PROFILE_LABELS,
    InsufficientDiskSpace,
    ProcessingCancelled,
    cleanup_frameforge_cache,
    cleanup_frameforge_temp_dirs,
    find_videos,
    non_negative_float,
    non_negative_int,
    positive_float,
    positive_int,
    recommended_extract_workers,
    recommend_workers,
    threshold_01,
    worker_value,
)
from core.config import FrameForgeConfig
from core.resources import InsufficientResources


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments into a raw ``argparse.Namespace``.

    Callers that need a ``FrameForgeConfig`` should use :func:`build_config`
    instead, which handles the extra CLI-only fields (``input``, ``output``,
    ``recursive``, etc.) and converts them.
    """
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
        help="Ép đủ --max-screenshots nếu có đủ candidate: adaptive budget trước, fallback nới filter cuối và ghi rõ trong report.",
    )
    parser.add_argument("--target-candidate-multiplier", type=positive_int, default=3, help="Candidate ban đầu trên mỗi screenshot mục tiêu.")
    parser.add_argument("--target-candidate-multiplier-max", type=positive_int, default=5, help="Trần adaptive candidate multiplier.")
    parser.add_argument("--repair-manifest", action="store_true", help="Dựng lại danh sách file trong manifest output hiện có.")
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


def build_config(args: argparse.Namespace) -> FrameForgeConfig:
    """Convert a raw ``argparse.Namespace`` into a typed :class:`FrameForgeConfig`.

    This handles the field-name mapping (e.g. ``disk_reserve_mb`` →
    ``disk_reserve_bytes``) and the extra CLI-only fields that live on the
    namespace but are not part of the config dataclass.
    """
    extract_workers = (
        recommended_extract_workers() if args.extract_workers == 0
        else max(1, args.extract_workers)
    )
    return FrameForgeConfig(
        start=args.start,
        end=args.end,
        every=args.every,
        count=args.count,
        max_screenshots=args.max_screenshots,
        target_count_after_filter=args.target_count_after_filter,
        target_candidate_multiplier=args.target_candidate_multiplier,
        target_candidate_multiplier_max=args.target_candidate_multiplier_max,
        repair_manifest=args.repair_manifest,
        min_free_ram_gb=args.min_free_ram_gb,
        scene_detection=args.scene_detection,
        best_frame_per_scene=args.best_frame_per_scene,
        scene_threshold=args.scene_threshold,
        min_scene_gap=args.min_scene_gap,
        flash_return_ratio=args.flash_return_ratio,
        flash_brightness_threshold=args.flash_brightness_threshold,
        scene_confirmations=args.scene_confirmations,
        analysis_width=args.analysis_width,
        analysis_fps=args.analysis_fps,
        workers=args.workers,
        extract_workers=extract_workers,
        extract_min_targets=8,
        min_sharpness=args.min_sharpness,
        motion_blur_threshold=args.motion_blur_threshold,
        duplicate_threshold=args.duplicate_threshold,
        format=args.format,
        quality=args.quality,
        crop_ratio=args.crop_ratio,
        encode_profile=args.encode_profile,
        width=args.width,
        overwrite=args.overwrite,
        retries=args.retries,
        retry_delay=args.retry_delay,
        disk_reserve_bytes=int(args.disk_reserve_mb) * 1024**2,
        use_scene_cache=args.use_scene_cache,
        cross_run_duplicates=args.cross_run_duplicates,
        cross_run_duplicate_threshold=args.duplicate_threshold,
        resume=args.resume,
        checkpoint_path=args.checkpoint,
        cache_root=args.cache_dir,
        duplicate_root=args.duplicate_index_dir,
        queue_db=args.queue_db or args.output / ".frameforge_queue.sqlite3",
    )


def _import_process_videos():
    """Lazy-import process_videos to avoid cv2 dependency at module load time."""
    from video_screenshot_advanced import process_videos
    return process_videos


def main() -> int:
    mp.freeze_support()
    args = parse_args()
    config = build_config(args)
    cleanup_frameforge_temp_dirs(
        older_than_seconds=int(args.temp_cleanup_hours) * 60 * 60,
        max_total_bytes=int(args.temp_quota_mb) * 1024**2,
    )
    cleanup_frameforge_cache(
        args.cache_dir or args.output / ".frameforge_cache",
        max_total_bytes=int(args.cache_quota_mb) * 1024**2,
    )
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
        process_videos = _import_process_videos()
        reports = process_videos(
            videos,
            args.output,
            source_root,
            config,
            on_complete,
            on_progress,
            max_retries=config.retries,
            retry_delay_seconds=config.retry_delay,
        )
    except ProcessingCancelled as exc:
        print(str(exc), file=sys.stderr)
        return 130
    except (InsufficientDiskSpace, InsufficientResources) as exc:
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
