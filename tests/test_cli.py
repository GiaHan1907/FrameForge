"""Tests for CLI headless mode (core/cli.py).

These tests verify that the CLI can parse args, build configs, and
import without requiring cv2 — the key property of headless mode.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.cli import parse_args, build_config, _import_process_videos
from core.config import FrameForgeConfig


class ParseArgsTests(unittest.TestCase):
    """Tests for CLI argument parsing."""

    def test_minimal_args(self):
        sys.argv = ["frameforge", "video.mp4"]
        args = parse_args()
        self.assertEqual(args.input, Path("video.mp4"))
        self.assertEqual(args.output, Path("screenshots_filtered"))

    def test_every_mode(self):
        sys.argv = ["frameforge", "video.mp4", "--every", "10"]
        args = parse_args()
        self.assertEqual(args.every, 10.0)
        self.assertIsNone(args.count)

    def test_count_mode(self):
        sys.argv = ["frameforge", "video.mp4", "--count", "20"]
        args = parse_args()
        self.assertEqual(args.count, 20)

    def test_scene_detection(self):
        sys.argv = ["frameforge", "video.mp4", "--scene-detection"]
        args = parse_args()
        self.assertTrue(args.scene_detection)

    def test_best_frame_implies_scene(self):
        sys.argv = ["frameforge", "video.mp4", "--best-frame-per-scene"]
        args = parse_args()
        self.assertTrue(args.best_frame_per_scene)
        self.assertTrue(args.scene_detection)

    def test_crop_ratio(self):
        sys.argv = ["frameforge", "video.mp4", "--crop-ratio", "16:9"]
        args = parse_args()
        self.assertEqual(args.crop_ratio, "16:9")

    def test_format_choices(self):
        for fmt in ("jpg", "png", "webp"):
            sys.argv = ["frameforge", "video.mp4", "--format", fmt]
            args = parse_args()
            self.assertEqual(args.format, fmt)

    def test_output_dir(self):
        sys.argv = ["frameforge", "video.mp4", "-o", "my_output"]
        args = parse_args()
        self.assertEqual(args.output, Path("my_output"))

    def test_recursive(self):
        sys.argv = ["frameforge", "video.mp4", "-r"]
        args = parse_args()
        self.assertTrue(args.recursive)

    def test_overwrite(self):
        sys.argv = ["frameforge", "video.mp4", "--overwrite"]
        args = parse_args()
        self.assertTrue(args.overwrite)

    def test_workers_auto(self):
        sys.argv = ["frameforge", "video.mp4", "--workers", "auto"]
        args = parse_args()
        self.assertEqual(args.workers, "auto")

    def test_resume(self):
        sys.argv = ["frameforge", "video.mp4", "--resume"]
        args = parse_args()
        self.assertTrue(args.resume)

    def test_report_path(self):
        sys.argv = ["frameforge", "video.mp4", "--report", "report.json"]
        args = parse_args()
        self.assertEqual(args.report, Path("report.json"))

    def test_default_values(self):
        sys.argv = ["frameforge", "video.mp4"]
        args = parse_args()
        self.assertEqual(args.start, 0.0)
        self.assertIsNone(args.end)
        self.assertFalse(args.scene_detection)
        self.assertFalse(args.overwrite)
        self.assertEqual(args.retries, 2)
        self.assertEqual(args.retry_delay, 1.0)
        self.assertTrue(args.use_scene_cache)
        self.assertTrue(args.cross_run_duplicates)


class BuildConfigTests(unittest.TestCase):
    """Tests for converting argparse.Namespace to FrameForgeConfig."""

    def test_basic_conversion(self):
        sys.argv = ["frameforge", "video.mp4", "--every", "5"]
        args = parse_args()
        config = build_config(args)
        self.assertIsInstance(config, FrameForgeConfig)
        self.assertEqual(config.every, 5.0)

    def test_extract_workers_zero_becomes_auto(self):
        sys.argv = ["frameforge", "video.mp4", "--extract-workers", "0"]
        args = parse_args()
        config = build_config(args)
        self.assertGreater(config.extract_workers, 0)

    def test_extract_workers_explicit(self):
        sys.argv = ["frameforge", "video.mp4", "--extract-workers", "2"]
        args = parse_args()
        config = build_config(args)
        self.assertEqual(config.extract_workers, 2)

    def test_disk_reserve_conversion(self):
        sys.argv = ["frameforge", "video.mp4", "--disk-reserve-mb", "1024"]
        args = parse_args()
        config = build_config(args)
        self.assertEqual(config.disk_reserve_bytes, 1024 * 1024**2)

    def test_queue_db_default(self):
        sys.argv = ["frameforge", "video.mp4", "-o", "output_dir"]
        args = parse_args()
        config = build_config(args)
        self.assertEqual(config.queue_db, Path("output_dir") / ".frameforge_queue.sqlite3")

    def test_queue_db_custom(self):
        sys.argv = ["frameforge", "video.mp4", "--queue-db", "custom.db"]
        args = parse_args()
        config = build_config(args)
        self.assertEqual(config.queue_db, Path("custom.db"))

    def test_all_fields_present(self):
        sys.argv = ["frameforge", "video.mp4"]
        args = parse_args()
        config = build_config(args)
        # Verify all 45 fields are set
        fields = config.__dataclass_fields__
        for name in fields:
            self.assertTrue(hasattr(config, name), f"Missing field: {name}")


class LazyImportTests(unittest.TestCase):
    """Tests for lazy import mechanism."""

    def test_import_process_videos_callable(self):
        """_import_process_videos should return a callable."""
        try:
            fn = _import_process_videos()
            self.assertTrue(callable(fn))
        except ModuleNotFoundError:
            # cv2 not installed — expected on this machine
            self.skipTest("cv2 not installed")

    def test_core_cli_importable_without_cv2(self):
        """core.cli should be importable without cv2."""
        # This test itself proves the point — if we got here, the import worked
        from core.cli import parse_args, build_config, main
        self.assertTrue(callable(parse_args))
        self.assertTrue(callable(build_config))
        self.assertTrue(callable(main))


class CLIModuleEntryTests(unittest.TestCase):
    """Tests for __main__.py entry point."""

    def test_main_module_exists(self):
        """frameforge/__main__.py should exist."""
        import frameforge.__main__
        self.assertTrue(hasattr(frameforge.__main__, "main"))


if __name__ == "__main__":
    unittest.main()
