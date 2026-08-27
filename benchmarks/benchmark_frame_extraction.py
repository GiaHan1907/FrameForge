from __future__ import annotations

import argparse
import contextlib
import csv
import ctypes
import io
import json
import os
try:
    import resource
except ImportError:  # Windows
    resource = None
import shutil
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import video_screenshot_advanced as engine  # noqa: E402


def rss_bytes() -> int:
    if sys.platform == "win32":
        class Counters(ctypes.Structure):
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
        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        return int(counters.WorkingSetSize)
    if resource is None:
        return 0
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1024 if sys.platform != "darwin" else 1))


def make_synthetic_video(path: Path, frames: int, width: int, height: int, fps: float) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError("Không tạo được video synthetic cho benchmark")
    try:
        for index in range(frames):
            frame = (index * 7) % 255
            image = __import__("numpy").full((height, width, 3), frame, dtype="uint8")
            cv2.putText(image, f"Frame {index}", (32, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255 - frame, 255, 255), 2)
            writer.write(image)
    finally:
        writer.release()


def make_args(work: Path, workers: int, frames: int, encode_profile: str) -> SimpleNamespace:
    return SimpleNamespace(
        start=0.0, end=None, every=None, count=frames,
        scene_detection=False, best_frame_per_scene=False,
        scene_threshold=0.30, min_scene_gap=0.5,
        flash_return_ratio=0.55, flash_brightness_threshold=0.18,
        scene_confirmations=2, analysis_width=320, analysis_fps=4.0,
        min_sharpness=0.0, motion_blur_threshold=0.0,
        duplicate_threshold=0, cross_run_duplicate_threshold=0,
        cross_run_duplicates=False, format="jpg", quality=85,
        width=640, overwrite=True, workers=1, extract_workers=workers,
        encode_profile=encode_profile, stage_timings=engine.new_stage_timings(),
        extract_min_targets=1, disk_reserve_bytes=0,
        use_scene_cache=False, cache_root=work / "cache",
        duplicate_root=work / "duplicates", checkpoint_path=None,
        resume=False, queue_db=None,
    )


def run_case(video: Path, work: Path, workers: int, frames: int, encode_profile: str) -> dict[str, object]:
    output = work / f"workers_{workers}"
    output.mkdir(parents=True, exist_ok=True)
    args = make_args(work, workers, frames, encode_profile)
    before = rss_bytes()
    started = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        report = engine.process_video(video, output, None, args)
    elapsed = time.perf_counter() - started
    after = rss_bytes()
    timings = report.get("stage_timings") or {}
    return {
        "workers": workers,
        "elapsed_seconds": round(elapsed, 6),
        "frames_requested": frames,
        "frames_saved": int(report.get("saved", 0)),
        "throughput_frames_per_second": round(frames / max(elapsed, 1e-9), 3),
        "rss_before_bytes": before,
        "rss_after_bytes": after,
        "rss_delta_bytes": max(0, after - before),
        "extraction_mode": report.get("extraction_mode", "sequential"),
        "encode_profile": encode_profile,
        "decode_ms": float(timings.get("decode_ms", 0.0)),
        "analysis_ms": float(timings.get("analysis_ms", 0.0)),
        "encode_ms": float(timings.get("encode_ms", 0.0)),
        "write_ms": float(timings.get("write_ms", 0.0)),
        "decode_count": int(timings.get("decode_count", 0)),
        "analysis_count": int(timings.get("analysis_count", 0)),
        "encode_count": int(timings.get("encode_count", 0)),
        "write_count": int(timings.get("write_count", 0)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark FrameForge frame extraction speed and RSS memory.")
    parser.add_argument("--video", type=Path, default=None, help="Video input; omit to generate a synthetic MP4.")
    parser.add_argument("--frames", type=int, default=60, help="Number of evenly spaced frames.")
    parser.add_argument("--workers", default="1,2,4", help="Comma-separated extraction worker counts.")
    parser.add_argument("--output", type=Path, default=Path("benchmark_results.json"))
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    parser.add_argument("--encode-profile", choices=("Nhanh", "Chất lượng cao"), default="Chất lượng cao")
    args = parser.parse_args()
    if args.frames < 8:
        parser.error("--frames must be at least 8 to exercise multiprocessing")
    worker_counts = sorted({max(1, int(value.strip())) for value in args.workers.split(",") if value.strip()})
    if not worker_counts:
        parser.error("--workers must contain at least one positive integer")
    temporary = tempfile.TemporaryDirectory(prefix="frameforge_benchmark_")
    root = Path(temporary.name)
    try:
        video = args.video
        if video is None:
            video = root / "synthetic.mp4"
            make_synthetic_video(video, args.frames, args.width, args.height, 12.0)
        if not video.is_file():
            raise FileNotFoundError(video)
        work = root / "runs"
        results = [run_case(video, work, workers, args.frames, args.encode_profile) for workers in worker_counts]
        baseline = next((item for item in results if item["workers"] == 1), results[0])
        baseline_time = float(baseline["elapsed_seconds"])
        for item in results:
            item["speedup_vs_baseline"] = round(baseline_time / max(float(item["elapsed_seconds"]), 1e-9), 3)
        payload = {
            "schema": 1,
            "video": str(video),
            "frames": args.frames,
            "platform": sys.platform,
            "cpu_count": os.cpu_count(),
            "encode_profile": args.encode_profile,
            "results": results,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        csv_path = args.output.with_suffix(".csv")
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    finally:
        temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
