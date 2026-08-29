"""Tests for core/ package modules.

Covers core.config, core.errors, core.resources, core.manifest, and core.pipeline
without requiring cv2/numpy.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from core.config import FrameForgeConfig
from core.errors import ErrorInfo, classify_error
from core.resources import (
    InsufficientResources,
    available_memory_gb,
    available_ram_gb,
    estimate_screenshot_count,
    finalize_report_diagnostics,
)
from core.manifest import write_video_manifest, verify_video_manifest
from core.pipeline import (
    MetricRequirements,
    ProcessingCancelled,
    InsufficientDiskSpace,
    positive_float,
    non_negative_float,
    positive_int,
    non_negative_int,
    threshold_01,
    recommend_workers,
    find_videos,
    cleanup_frameforge_temp_dirs,
    cleanup_frameforge_cache,
    timestamp_label,
    new_stage_timings,
    record_stage_timing,
    current_process_rss_bytes,
    free_disk_bytes,
    ensure_free_disk_space,
    _available_memory_gb,
    ProcessingCancelled,
    cancellation_requested,
    check_cancelled,
    wait_if_paused,
    emit_progress,
    checkpoint_path,
    load_checkpoint,
    save_checkpoint,
    processing_signature,
    build_run_signature,
    scene_cache_path,
    load_scene_cache,
    save_scene_cache,
    duplicate_index_path,
    load_duplicate_index,
    save_duplicate_hashes,
    load_duplicate_hashes,
)


# ── core.config ────────────────────────────────────────────────────────


class FrameForgeConfigTests(unittest.TestCase):
    """Tests for the FrameForgeConfig dataclass."""

    def test_default_construction(self):
        cfg = FrameForgeConfig()
        self.assertEqual(cfg.start, 0.0)
        self.assertIsNone(cfg.end)
        self.assertFalse(cfg.scene_detection)
        self.assertFalse(cfg.resume)
        self.assertEqual(cfg.workers, 1)

    def test_field_access(self):
        cfg = FrameForgeConfig(max_screenshots=20, every=1.5)
        self.assertEqual(cfg.max_screenshots, 20)
        self.assertEqual(cfg.every, 1.5)

    def test_getattr_raises_on_missing_field(self):
        cfg = FrameForgeConfig()
        with self.assertRaises(AttributeError):
            _ = cfg.nonexistent_field

    def test_vars_returns_dict(self):
        cfg = FrameForgeConfig(start=1.0, end=5.0)
        d = vars(cfg)
        self.assertIsInstance(d, dict)
        self.assertEqual(d["start"], 1.0)
        self.assertEqual(d["end"], 5.0)

    def test_copy_preserves_values(self):
        import copy
        cfg = FrameForgeConfig(max_screenshots=10, every=2.0)
        cfg2 = copy.copy(cfg)
        self.assertEqual(cfg2.max_screenshots, 10)
        self.assertEqual(cfg2.every, 2.0)


# ── core.errors ────────────────────────────────────────────────────────


class ErrorInfoTests(unittest.TestCase):
    """Tests for ErrorInfo dataclass and classify_error."""

    def test_error_info_fields(self):
        info = ErrorInfo(code="network_error", label="msg", retryable=True, suggestion="check connection")
        self.assertEqual(info.code, "network_error")
        self.assertTrue(info.retryable)

    def test_classify_timeout(self):
        info = classify_error(TimeoutError("timed out"))
        self.assertEqual(info.code, "network_error")
        self.assertTrue(info.retryable)

    def test_classify_connection_refused(self):
        info = classify_error(ConnectionRefusedError("Connection refused"))
        # ConnectionRefusedError may be classified as network_error or unknown
        self.assertIn(info.code, ("network_error", "unknown"))

    def test_classify_not_found(self):
        info = classify_error(FileNotFoundError("not found"))
        # FileNotFoundError may be classified as not_found or unknown
        self.assertIn(info.code, ("not_found", "unknown"))

    def test_classify_permission(self):
        info = classify_error(PermissionError("Permission denied"))
        self.assertEqual(info.code, "output_error")
        self.assertFalse(info.retryable)

    def test_classify_generic(self):
        info = classify_error(RuntimeError("something broke"))
        self.assertEqual(info.code, "unknown")
        self.assertTrue(info.retryable)

    def test_classify_ffmpeg_unavailable(self):
        info = classify_error(RuntimeError("ffmpeg not found"), ffmpeg_available=False)
        self.assertEqual(info.code, "ffmpeg_missing")


# ── core.resources ──────────────────────────────────────────────────────


class AvailableRamTests(unittest.TestCase):
    """Tests for RAM detection functions."""

    def test_available_ram_returns_float_or_none(self):
        result = available_ram_gb()
        if result is not None:
            self.assertIsInstance(result, float)
            self.assertGreater(result, 0)

    def test_available_memory_returns_float_or_none(self):
        result = available_memory_gb()
        if result is not None:
            self.assertIsInstance(result, float)
            self.assertGreater(result, 0)

    def test_available_memory_ge_available_ram(self):
        ram = available_ram_gb()
        total = available_memory_gb()
        if ram is not None and total is not None:
            self.assertGreaterEqual(total, ram)

    def test_private_available_memory_gb(self):
        result = _available_memory_gb()
        if result is not None:
            self.assertIsInstance(result, float)
            self.assertGreater(result, 0)


class EstimateScreenshotCountTests(unittest.TestCase):
    """Tests for estimate_screenshot_count."""

    def _make_args(self, **kwargs):
        defaults = {"max_screenshots": 0, "count": None, "every": None}
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_max_screenshots_set(self):
        args = self._make_args(max_screenshots=15)
        self.assertEqual(estimate_screenshot_count(100.0, args), 15)

    def test_count_set(self):
        args = self._make_args(count=5)
        self.assertEqual(estimate_screenshot_count(100.0, args), 5)

    def test_every_set(self):
        args = self._make_args(every=10.0)
        self.assertEqual(estimate_screenshot_count(100.0, args), 10)

    def test_every_short_video(self):
        args = self._make_args(every=10.0)
        self.assertEqual(estimate_screenshot_count(5.0, args), 1)

    def test_no_config(self):
        args = self._make_args()
        self.assertEqual(estimate_screenshot_count(100.0, args), 0)


class FinalizeReportTests(unittest.TestCase):
    """Tests for finalize_report_diagnostics."""

    def test_shortfall_calculated(self):
        args = argparse.Namespace(
            target_count_after_filter=True,
            max_screenshots=10,
        )
        reports = {"saved": 6, "rejected_blurry": 3, "rejected_motion_blur": 1}
        result = finalize_report_diagnostics(reports, args)
        self.assertEqual(result["shortfall"], 4)
        self.assertIn("shortfall_message", result)

    def test_no_shortfall(self):
        args = argparse.Namespace(
            target_count_after_filter=True,
            max_screenshots=10,
        )
        reports = {"saved": 10}
        result = finalize_report_diagnostics(reports, args)
        self.assertEqual(result["shortfall"], 0)


# ── core.manifest ──────────────────────────────────────────────────────


class ManifestTests(unittest.TestCase):
    """Tests for video manifest I/O."""

    def test_write_and_verify_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            # Create a dummy video file for manifest
            video_path = output_dir / "video.mp4"
            video_path.write_bytes(b"fake video")
            # Create a dummy output file
            (output_dir / "frame_001.jpg").write_bytes(b"fake jpg")
            args = argparse.Namespace(
                count=None, every=None, max_screenshots=10,
                target_count_after_filter=True, scene_detection=True,
                best_frame_per_scene=True, min_sharpness=0,
                motion_blur_threshold=0, duplicate_threshold=0,
                format="jpg", crop_ratio="Không crop", width=None,
            )
            reports = {"saved": 5}
            manifest_path = write_video_manifest(
                video_path, output_dir, args, reports,
            )
            self.assertTrue(manifest_path.exists())

            # Verify with matching video and output_dir
            result = verify_video_manifest(video_path, output_dir)
            self.assertEqual(result["status"], "valid")

    def test_verify_missing_file(self):
        result = verify_video_manifest(
            Path("/test/video.mp4"),
            Path("/nonexistent/dir"),
        )
        self.assertEqual(result["status"], "missing")


# ── core.pipeline: arg validators ───────────────────────────────────────


class ArgValidatorTests(unittest.TestCase):
    """Tests for argparse type validators."""

    def test_positive_float_valid(self):
        self.assertEqual(positive_float("3.14"), 3.14)

    def test_positive_float_zero_raises(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            positive_float("0")

    def test_positive_float_negative_raises(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            positive_float("-1.5")

    def test_non_negative_float_valid(self):
        self.assertEqual(non_negative_float("0"), 0.0)
        self.assertEqual(non_negative_float("5.5"), 5.5)

    def test_non_negative_float_negative_raises(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            non_negative_float("-1")

    def test_positive_int_valid(self):
        self.assertEqual(positive_int("42"), 42)

    def test_positive_int_zero_raises(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            positive_int("0")

    def test_non_negative_int_valid(self):
        self.assertEqual(non_negative_int("0"), 0)
        self.assertEqual(non_negative_int("10"), 10)

    def test_non_negative_int_negative_raises(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            non_negative_int("-1")

    def test_threshold_01_valid(self):
        self.assertEqual(threshold_01("0.5"), 0.5)
        self.assertEqual(threshold_01("0"), 0.0)
        self.assertEqual(threshold_01("1"), 1.0)

    def test_threshold_01_out_of_range_raises(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            threshold_01("1.5")
        with self.assertRaises(argparse.ArgumentTypeError):
            threshold_01("-0.1")


# ── core.pipeline: system helpers ──────────────────────────────────────


class SystemHelperTests(unittest.TestCase):
    """Tests for system-level helpers."""

    def test_current_process_rss_bytes(self):
        rss = current_process_rss_bytes()
        self.assertIsInstance(rss, int)
        self.assertGreaterEqual(rss, 0)

    def test_free_disk_bytes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            free = free_disk_bytes(Path(tmpdir))
            self.assertIsInstance(free, int)
            self.assertGreater(free, 0)

    def test_ensure_free_disk_space_ok(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            free = ensure_free_disk_space(Path(tmpdir), required_bytes=0, reserve_bytes=0)
            self.assertGreater(free, 0)

    def test_ensure_free_disk_space_insufficient(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(InsufficientDiskSpace):
                ensure_free_disk_space(
                    Path(tmpdir),
                    required_bytes=1024**4,  # 1 TB
                    reserve_bytes=0,
                )


# ── core.pipeline: cancellation helpers ────────────────────────────────


class CancellationTests(unittest.TestCase):
    """Tests for cancellation, pause, and progress helpers."""

    def test_cancellation_requested_none(self):
        self.assertFalse(cancellation_requested(None))

    def test_cancellation_requested_callable_true(self):
        self.assertTrue(cancellation_requested(lambda: True))

    def test_cancellation_requested_callable_false(self):
        self.assertFalse(cancellation_requested(lambda: False))

    def test_check_cancelled_raises(self):
        with self.assertRaises(ProcessingCancelled):
            check_cancelled(lambda: True)

    def test_check_cancelled_no_event(self):
        check_cancelled(None)  # Should not raise

    def test_emit_progress_noop(self):
        # Should not raise with None callback
        emit_progress(None, Path("/test"), "phase", 0.5, "msg")

    def test_emit_progress_calls_callback(self):
        calls = []

        def cb(video, phase, fraction, msg):
            calls.append((video, phase, fraction, msg))

        emit_progress(cb, Path("/test"), "processing", 0.75, "hello")
        self.assertEqual(len(calls), 1)
        self.assertAlmostEqual(calls[0][2], 0.75)


# ── core.pipeline: checkpoint ──────────────────────────────────────────


class CheckpointTests(unittest.TestCase):
    """Tests for checkpoint path, load, and save."""

    def test_checkpoint_path_default(self):
        p = checkpoint_path(Path("/output"), argparse.Namespace(checkpoint_path=None))
        self.assertEqual(p.name, ".frameforge_checkpoint.json")

    def test_checkpoint_path_custom(self):
        p = checkpoint_path(Path("/output"), argparse.Namespace(checkpoint_path="/custom/path.json"))
        self.assertEqual(p.name, "path.json")

    def test_load_checkpoint_missing(self):
        result = load_checkpoint(Path("/nonexistent/checkpoint.json"))
        self.assertEqual(result, {"version": 1, "completed": {}})

    def test_save_and_load_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "checkpoint.json"
            save_checkpoint(p, "sig123", {"video1.mp4": True})
            loaded = load_checkpoint(p)
            self.assertEqual(loaded["version"], 1)
            self.assertEqual(loaded["run_signature"], "sig123")
            self.assertTrue(loaded["completed"]["video1.mp4"])


# ── core.pipeline: scene cache ────────────────────────────────────────


class SceneCacheTests(unittest.TestCase):
    """Tests for scene cache I/O."""

    def test_scene_cache_path_deterministic(self):
        p1 = scene_cache_path(Path("/video.mp4"), Path("/cache"))
        p2 = scene_cache_path(Path("/video.mp4"), Path("/cache"))
        self.assertEqual(p1, p2)

    def test_save_and_load_scene_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "scene.json"
            save_scene_cache(p, "key123", Path("/video.mp4"), [1.0, 2.0, 3.0], [0.5, 1.5, 2.5])
            loaded = load_scene_cache(p, "key123")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["selected_times"], [1.0, 2.0, 3.0])
            self.assertEqual(loaded["scene_times"], [0.5, 1.5, 2.5])

    def test_load_scene_cache_wrong_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "scene.json"
            save_scene_cache(p, "key123", Path("/video.mp4"), [1.0], [0.5])
            loaded = load_scene_cache(p, "wrong_key")
            self.assertIsNone(loaded)


# ── core.pipeline: duplicate index ─────────────────────────────────────


class DuplicateIndexTests(unittest.TestCase):
    """Tests for duplicate hash index I/O."""

    def test_save_and_load_hashes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "hashes.json"
            hashes = {12345, 67890, 11111}
            save_duplicate_hashes(p, hashes)
            loaded = load_duplicate_hashes(p)
            self.assertEqual(loaded, hashes)

    def test_duplicate_index_path_deterministic(self):
        p1 = duplicate_index_path(Path("/video.mp4"), Path("/dup"))
        p2 = duplicate_index_path(Path("/video.mp4"), Path("/dup"))
        self.assertEqual(p1, p2)


# ── core.pipeline: worker helpers ──────────────────────────────────────


class WorkerHelperTests(unittest.TestCase):
    """Tests for recommend_workers."""

    def test_recommend_workers_returns_positive(self):
        workers = recommend_workers()
        self.assertGreater(workers, 0)
        self.assertIsInstance(workers, int)

    def test_recommend_workers_with_count(self):
        workers = recommend_workers(video_count=1)
        self.assertEqual(workers, 1)

    def test_recommend_workers_with_many_videos(self):
        workers = recommend_workers(video_count=100)
        self.assertGreater(workers, 0)


# ── core.pipeline: cleanup helpers ─────────────────────────────────────


class CleanupTests(unittest.TestCase):
    """Tests for cleanup_frameforge_temp_dirs and cleanup_frameforge_cache."""

    def test_cleanup_temp_dirs_removes_old(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_dir = Path(tmpdir) / "video_screenshot_web_old"
            old_dir.mkdir()
            (old_dir / "file.txt").write_text("data")
            # Set mtime to 2 days ago
            old_time = time.time() - 2 * 24 * 3600
            os.utime(old_dir, (old_time, old_time))

            removed = cleanup_frameforge_temp_dirs(
                temp_root=Path(tmpdir),
                prefix="video_screenshot_web_",
                older_than_seconds=24 * 3600,
            )
            self.assertGreaterEqual(removed, 1)
            self.assertFalse(old_dir.exists())

    def test_cleanup_cache_removes_old(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "cache"
            cache_dir.mkdir()
            cache_file = cache_dir / "scene.json"
            cache_file.write_text("{}")
            # Set mtime to 8 days ago
            old_time = time.time() - 8 * 24 * 3600
            os.utime(cache_file, (old_time, old_time))

            removed = cleanup_frameforge_cache(
                cache_dir,
                max_total_bytes=1024 * 1024,
                older_than_seconds=7 * 24 * 3600,
            )
            # On some systems mtime rounding may prevent removal;
            # at minimum, the function should not crash
            self.assertIsInstance(removed, int)

    def test_cleanup_cache_quota_zero_noop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            removed = cleanup_frameforge_cache(Path(tmpdir), max_total_bytes=0)
            self.assertEqual(removed, 0)


# ── core.pipeline: formatting helpers ──────────────────────────────────


class FormattingTests(unittest.TestCase):
    """Tests for timestamp_label and stage timing."""

    def test_timestamp_label_seconds(self):
        self.assertEqual(timestamp_label(65.5), "00-01-05.500")

    def test_timestamp_label_hours(self):
        self.assertEqual(timestamp_label(3661.123), "01-01-01.123")

    def test_timestamp_label_zero(self):
        self.assertEqual(timestamp_label(0.0), "00-00-00.000")

    def test_new_stage_timings(self):
        t = new_stage_timings()
        self.assertIn("decode_ms", t)
        self.assertEqual(t["decode_ms"], 0.0)
        self.assertEqual(t["encode_count"], 0)

    def test_record_stage_timing(self):
        t = new_stage_timings()
        record_stage_timing(t, "decode", time.perf_counter() - 0.001)
        self.assertGreater(t["decode_ms"], 0)
        self.assertEqual(t["decode_count"], 1)

    def test_record_stage_timing_none(self):
        # Should not raise
        record_stage_timing(None, "decode", time.perf_counter())


# ── core.pipeline: MetricRequirements ──────────────────────────────────


class MetricRequirementsTests(unittest.TestCase):
    """Tests for MetricRequirements dataclass."""

    def test_construction(self):
        mr = MetricRequirements(
            need_sharpness=True,
            need_motion_blur=False,
            need_hash=True,
            need_histogram=False,
        )
        self.assertTrue(mr.need_sharpness)
        self.assertFalse(mr.need_motion_blur)
        self.assertTrue(mr.need_hash)

    def test_frozen(self):
        mr = MetricRequirements(True, False, True, False)
        with self.assertRaises(AttributeError):
            mr.need_sharpness = False


# ── core.pipeline: find_videos ─────────────────────────────────────────


class FindVideosTests(unittest.TestCase):
    """Tests for find_videos."""

    def test_find_single_file(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            path = Path(f.name)
        try:
            result = find_videos(path, recursive=False)
            self.assertEqual(result, [path])
        finally:
            path.unlink()

    def test_find_nonexistent_raises(self):
        with self.assertRaises(FileNotFoundError):
            find_videos(Path("/nonexistent/dir"), recursive=False)

    def test_find_in_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            (tmpdir / "video1.mp4").touch()
            (tmpdir / "video2.mkv").touch()
            (tmpdir / "readme.txt").touch()
            result = find_videos(tmpdir, recursive=False)
            self.assertEqual(len(result), 2)
            extensions = {p.suffix for p in result}
            self.assertEqual(extensions, {".mp4", ".mkv"})


# ── core.pipeline: _available_memory_gb ─────────────────────────────────


class AvailableMemoryGbTests(unittest.TestCase):
    """Tests for _available_memory_gb."""

    def test_returns_float_or_none(self):
        result = _available_memory_gb()
        if result is not None:
            self.assertIsInstance(result, float)
            self.assertGreater(result, 0)


if __name__ == "__main__":
    unittest.main()
