#!/usr/bin/env python3
"""Benchmark tốc độ xử lý video đơn luồng và đa luồng.

Benchmark xử lý cùng một bộ video ở hai chế độ:
- workers=1: baseline đơn luồng
- workers=N: xử lý nhiều video độc lập song song

Kết quả ghi ra JSON và CSV để dễ so sánh.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import shutil
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from video_screenshot_advanced import find_videos, process_videos, recommend_workers


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("giá trị phải lớn hơn 0")
    return number


def make_args(options: argparse.Namespace, workers: int) -> SimpleNamespace:
    return SimpleNamespace(
        start=0.0,
        end=None,
        every=float(options.every),
        count=None,
        scene_detection=True,
        best_frame_per_scene=True,
        scene_threshold=0.30,
        min_scene_gap=0.5,
        flash_return_ratio=0.55,
        flash_brightness_threshold=0.18,
        scene_confirmations=2,
        analysis_width=int(options.analysis_width),
        analysis_fps=float(options.analysis_fps),
        min_sharpness=0.0,
        duplicate_threshold=0,
        format="jpg",
        quality=90,
        width=None,
        overwrite=True,
        workers=workers,
    )


def run_once(
    videos: list[Path],
    source_root: Path | None,
    options: argparse.Namespace,
    workers: int,
) -> tuple[float, list[dict[str, object]]]:
    output_dir = Path(tempfile.mkdtemp(prefix=f"benchmark_w{workers}_"))
    args = make_args(options, workers)
    stdout = io.StringIO()
    stderr = io.StringIO()
    started = time.perf_counter()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            reports = process_videos(videos, output_dir, source_root, args)
        elapsed = time.perf_counter() - started
        return elapsed, reports
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark đơn luồng và đa luồng cho video screenshot.")
    parser.add_argument("input", type=Path, help="Một video hoặc thư mục video.")
    parser.add_argument("-o", "--output", type=Path, default=Path("benchmark_results"), help="Thư mục kết quả benchmark.")
    parser.add_argument("--multi-workers", type=positive_int, default=None, help="Số worker đa luồng; mặc định tự đề xuất theo CPU/RAM.")
    parser.add_argument("--every", type=float, default=1.0, help="Khoảng cách frame dùng trong benchmark, tính bằng giây.")
    parser.add_argument("--analysis-width", type=positive_int, default=640, help="Chiều rộng phân tích.")
    parser.add_argument("--analysis-fps", type=float, default=8.0, help="FPS phân tích scene.")
    parser.add_argument("--repetitions", type=positive_int, default=1, help="Số lần lặp mỗi chế độ.")
    args = parser.parse_args()

    videos = find_videos(args.input, recursive=True)
    if len(videos) < 2:
        print("Cảnh báo: cần ít nhất 2 video để đo lợi ích đa luồng; với 1 video, cả hai chế độ sẽ hiệu dụng 1 worker.")
    if not videos:
        print("Không tìm thấy video phù hợp.")
        return 1

    multi_workers = args.multi_workers or recommend_workers(len(videos))
    multi_workers = max(1, min(multi_workers, len(videos)))
    source_root = args.input if args.input.is_dir() else None
    modes = [("single", 1), ("multi", multi_workers)]
    rows: list[dict[str, object]] = []

    print(f"Benchmark {len(videos)} video | single=1 worker | multi={multi_workers} worker")
    for mode, workers in modes:
        for repetition in range(1, args.repetitions + 1):
            elapsed, reports = run_once(videos, source_root, args, workers)
            saved = sum(int(report.get("saved", 0)) for report in reports)
            rows.append(
                {
                    "mode": mode,
                    "workers": workers,
                    "repetition": repetition,
                    "seconds": round(elapsed, 4),
                    "videos": len(videos),
                    "saved": saved,
                    "throughput_videos_per_second": round(len(videos) / elapsed, 4) if elapsed else None,
                }
            )
            print(f"  {mode:6s} run {repetition}: {elapsed:.3f}s | saved={saved}")

    single_seconds = sum(float(row["seconds"]) for row in rows if row["mode"] == "single") / args.repetitions
    multi_seconds = sum(float(row["seconds"]) for row in rows if row["mode"] == "multi") / args.repetitions
    summary = {
        "video_count": len(videos),
        "single_workers": 1,
        "multi_workers": multi_workers,
        "single_seconds_avg": round(single_seconds, 4),
        "multi_seconds_avg": round(multi_seconds, 4),
        "speedup": round(single_seconds / multi_seconds, 4) if multi_seconds else None,
        "parallel_efficiency": round((single_seconds / multi_seconds) / multi_workers, 4) if multi_seconds and multi_workers else None,
        "results": rows,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "benchmark_results.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (args.output / "benchmark_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSpeedup: {summary['speedup']}x")
    print(f"Kết quả: {args.output / 'benchmark_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
