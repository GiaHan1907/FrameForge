from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

import video_screenshot_advanced as engine
from timeline_utils import build_timeline_entries, filter_timeline_entries


class CacheCheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.video = Path("/home/ubuntu/scene_test/two_scenes.mp4")
        if not self.video.exists():
            self.skipTest("scene test video is not available")
        self.context = tempfile.TemporaryDirectory()
        self.root = Path(self.context.name)
        self.args = SimpleNamespace(
            workers=1,
            start=0.0,
            end=None,
            scene_detection=True,
            best_frame_per_scene=True,
            scene_threshold=0.30,
            min_scene_gap=0.5,
            flash_return_ratio=0.55,
            flash_brightness_threshold=0.18,
            scene_confirmations=2,
            analysis_width=320,
            analysis_fps=4.0,
            min_sharpness=0.0,
            motion_blur_threshold=0.0,
            duplicate_threshold=6,
            cross_run_duplicate_threshold=6,
            cross_run_duplicates=True,
            format="jpg",
            quality=90,
            width=None,
            overwrite=True,
            disk_reserve_bytes=0,
            use_scene_cache=True,
            cache_root=self.root / "cache",
            duplicate_root=self.root / "duplicates",
            checkpoint_path=None,
            resume=False,
        )

    def tearDown(self) -> None:
        self.context.cleanup()

    def test_crop_ratios_and_resize_preserve_aspect(self) -> None:
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        expected_shapes = {
            "16:9": (100, 178),
            "9:16": (100, 56),
            "4:5": (100, 80),
            "1:1": (100, 100),
        }
        for ratio, (expected_height, expected_width) in expected_shapes.items():
            cropped = engine.crop_to_aspect_ratio(frame, ratio)
            self.assertEqual(cropped.shape[:2], (expected_height, expected_width))
            self.assertAlmostEqual(cropped.shape[1] / cropped.shape[0], engine.CROP_RATIO_VALUES[ratio], delta=0.02)
        self.assertIs(engine.crop_to_aspect_ratio(frame, "Không crop"), frame)
        with self.assertRaises(ValueError):
            engine.crop_to_aspect_ratio(frame, "3:2")

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "cropped.jpg"
            engine.save_image(frame, output, "jpg", 90, 100, "9:16")
            with Image.open(output) as image:
                self.assertEqual(image.size, (56, 100))
                self.assertAlmostEqual(image.size[0] / image.size[1], 9 / 16, delta=0.02)

    def test_conditional_metrics_skip_disabled_work(self) -> None:
        frame = np.full((80, 120, 3), 96, dtype=np.uint8)
        requirements = engine.MetricRequirements(False, False, False, False)
        candidate = engine.frame_candidate(frame, 0.0, 64, requirements)
        self.assertEqual(candidate.sharpness, 0.0)
        self.assertEqual(candidate.motion_blur_score, 0.0)
        self.assertEqual(candidate.hash_value, 0)
        self.assertEqual(candidate.brightness, 0.0)
        self.assertEqual(candidate.gray.size, 0)
        self.assertEqual(candidate.histogram.size, 0)

        full = engine.frame_candidate(frame, 0.0, 64, engine.MetricRequirements(True, True, True, True))
        self.assertGreater(full.gray.size, 0)
        self.assertEqual(full.histogram.size, 128)

    def test_encode_profiles_and_stage_timings(self) -> None:
        frame = np.zeros((80, 120, 3), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fast = root / "fast.jpg"
            high = root / "high.jpg"
            engine.save_image(frame, fast, "jpg", 90, None, encode_profile="Nhanh")
            engine.save_image(frame, high, "jpg", 90, None, encode_profile="Chất lượng cao")
            self.assertTrue(fast.exists())
            self.assertTrue(high.exists())
            with self.assertRaises(ValueError):
                engine.save_image(frame, root / "invalid.jpg", "jpg", 90, None, encode_profile="invalid")

            args = copy.copy(self.args)
            args.scene_detection = False
            args.best_frame_per_scene = False
            args.count = 1
            args.every = None
            args.encode_profile = "Nhanh"
            args.stage_timings = engine.new_stage_timings()
            report = engine.process_video(self.video, root / "timed", None, args)
            self.assertGreaterEqual(report["stage_timings"]["decode_count"], 1)
            self.assertEqual(report["stage_timings"]["analysis_count"], 1)
            self.assertEqual(report["stage_timings"]["encode_count"], 1)
            self.assertEqual(report["stage_timings"]["write_count"], 1)
            self.assertGreaterEqual(report["stage_timings"]["decode_ms"], 0.0)

    def test_max_screenshots_limits_fixed_mode(self) -> None:
        args = copy.copy(self.args)
        args.scene_detection = False
        args.best_frame_per_scene = False
        args.count = None
        args.every = 0.1
        args.max_screenshots = 3
        args.duplicate_threshold = 0
        args.cross_run_duplicates = False
        args.cross_run_duplicate_threshold = 0
        args.min_sharpness = 0.0
        args.motion_blur_threshold = 0.0
        output = self.root / "limited"
        report = engine.process_video(self.video, output, None, args)
        self.assertEqual(int(report["requested"]), 3)
        self.assertLessEqual(int(report["saved"]), 3)
        self.assertLessEqual(len(list(output.rglob("*.jpg"))), 3)

    def test_target_count_manifest_and_shortfall_diagnostics(self) -> None:
        args = copy.copy(self.args)
        args.scene_detection = False
        args.best_frame_per_scene = False
        args.count = None
        args.every = 0.1
        args.max_screenshots = 3
        args.target_count_after_filter = True
        args.target_candidate_multiplier = 3
        args.duplicate_threshold = 0
        args.cross_run_duplicates = False
        args.cross_run_duplicate_threshold = 0
        args.min_sharpness = 0.0
        args.motion_blur_threshold = 0.0
        args.disk_reserve_bytes = 0
        args.min_free_ram_gb = 0.0
        output = self.root / "targeted"
        report = engine.process_video(self.video, output, None, args)
        self.assertEqual(int(report["target_screenshots"]), 3)
        self.assertEqual(int(report["shortfall"]), 0)
        self.assertTrue(Path(str(report["manifest_path"])).is_file())
        manifest = json.loads(Path(str(report["manifest_path"])).read_text(encoding="utf-8"))
        self.assertEqual(manifest["report"]["saved"], 3)
        self.assertEqual(manifest["config"]["target_count_after_filter"], True)

    def test_adaptive_candidate_budget_expands_with_rejections(self) -> None:
        args = copy.copy(self.args)
        args.max_screenshots = 2
        args.target_count_after_filter = True
        args.target_candidate_multiplier = 3
        args.target_candidate_multiplier_max = 5
        initial, maximum = engine.candidate_budget_bounds(args)
        self.assertEqual((initial, maximum), (6, 10))
        self.assertEqual(engine.expand_candidate_budget(initial, maximum, 2, 6, 3), 9)
        self.assertEqual(engine.expand_candidate_budget(10, maximum, 2, 10, 10), 10)

    def test_manifest_verify_detects_missing_and_repairs_file_list(self) -> None:
        args = copy.copy(self.args)
        args.scene_detection = False
        args.best_frame_per_scene = False
        args.count = 2
        args.every = None
        args.max_screenshots = 0
        args.min_sharpness = 0.0
        args.motion_blur_threshold = 0.0
        output = self.root / "manifest-verify"
        report = engine.process_video(self.video, output, None, args)
        manifest = Path(str(report["manifest_path"]))
        manifest_dir = manifest.parent
        self.assertEqual(engine.verify_video_manifest(self.video, manifest_dir)["status"], "valid")
        image = next(manifest_dir.glob("*.jpg"))
        image.unlink()
        mismatch = engine.verify_video_manifest(self.video, manifest_dir)
        self.assertEqual(mismatch["status"], "mismatch")
        self.assertIn(image.name, mismatch["missing_files"])
        repaired = engine.verify_video_manifest(self.video, manifest_dir, repair=True)
        self.assertEqual(repaired["status"], "repaired")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertNotIn(image.name, payload["files"])

    def test_resource_admission_guard_rejects_low_ram(self) -> None:
        args = copy.copy(self.args)
        args.disk_reserve_bytes = 0
        args.min_free_ram_gb = 4.0
        with patch.object(engine, "available_ram_gb", return_value=1.0):
            with self.assertRaises(engine.InsufficientResources):
                engine.resource_admission_guard(self.root / "admission", args)

    def test_resource_guard_rejects_insufficient_ram_threshold(self) -> None:
        args = copy.copy(self.args)
        args.format = "jpg"
        args.count = 1
        args.max_screenshots = 1
        args.min_free_ram_gb = 10_000.0
        with self.assertRaises(engine.InsufficientResources):
            engine.resource_guard(self.root / "resource", 1.0, args)

    def test_scene_cache_hit_and_cross_run_duplicate_rejection(self) -> None:
        first_output = self.root / "first"
        second_output = self.root / "second"
        first = engine.process_video(self.video, first_output, None, self.args)
        self.assertFalse(first["cache_hit"])
        self.assertTrue(Path(first["scene_cache_path"]).exists())
        self.assertGreaterEqual(int(first["saved"]), 1)

        second = engine.process_video(self.video, second_output, None, self.args)
        self.assertTrue(second["cache_hit"])
        self.assertGreaterEqual(int(second["rejected_duplicate_cross_run"]), 1)
        duplicate_index = engine.duplicate_index_path(self.video, self.args.duplicate_root)
        self.assertTrue(duplicate_index.exists())
        self.assertEqual(len(list(second_output.rglob("*.jpg"))), 0)

    def test_timeline_build_and_filters(self) -> None:
        reports = [
            {
                "video": "/videos/alpha.mp4",
                "scene_times": [1.0, 5.0],
                "selected_times": [1.2, 4.8],
                "cache_hit": True,
            },
            {
                "video": "/videos/beta.mp4",
                "scene_times": [2.5],
                "selected_times": [2.5],
            },
        ]
        entries = build_timeline_entries(reports)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]["representative_seconds"], 1.2)
        self.assertTrue(entries[0]["cache_hit"])
        alpha = filter_timeline_entries(entries, video_name="alpha.mp4")
        self.assertEqual(len(alpha), 2)
        late = filter_timeline_entries(entries, query="scene 2", min_seconds=4.0, max_seconds=6.0)
        self.assertEqual([(item["video"], item["scene"]) for item in late], [("alpha.mp4", 2)])

    def test_fixed_mode_multiprocessing_extraction(self) -> None:
        args = copy.copy(self.args)
        args.scene_detection = False
        args.best_frame_per_scene = False
        args.count = 200
        args.every = None
        args.extract_workers = 2
        args.extract_min_targets = 1
        args.duplicate_threshold = 0
        args.cross_run_duplicates = False
        args.cross_run_duplicate_threshold = 0
        output = self.root / "multiprocess"
        with patch.object(engine.os, "cpu_count", return_value=8), patch.object(
            engine, "available_memory_gb", return_value=16.0
        ):
            report = engine.process_video(self.video, output, None, args)
        self.assertEqual(report["extraction_mode"], "multiprocessing")
        self.assertEqual(report["extraction_workers"], 2)
        self.assertEqual(int(report["requested"]), 200)
        self.assertGreaterEqual(int(report["saved"]), 1)
        self.assertEqual(len(list(output.rglob("*.jpg"))), int(report["saved"]))

    def test_duplicate_bucket_index_is_backward_compatible(self) -> None:
        index_path = self.root / "duplicate.json"
        original = 0x0123456789ABCDEF
        near = original ^ 1
        index_path.write_text(json.dumps({"version": 1, "hashes": [original]}), encoding="utf-8")
        hashes, buckets = engine.load_duplicate_index(index_path)
        self.assertEqual(hashes, {original})
        self.assertTrue(set(engine._dhash_bucket_keys(original)).intersection(engine._dhash_bucket_keys(near)))
        engine.save_duplicate_hashes(index_path, hashes, buckets)
        stored = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(stored["version"], 2)
        self.assertIn(str(original), {str(item) for item in stored["hashes"]})
        self.assertTrue(stored["buckets"])
        stored["buckets"] = {}
        index_path.write_text(json.dumps(stored), encoding="utf-8")
        rebuilt_hashes, rebuilt_buckets = engine.load_duplicate_index(index_path)
        self.assertEqual(rebuilt_hashes, {original})
        self.assertTrue(rebuilt_buckets)

    def test_checkpoint_resume_skips_completed_video(self) -> None:
        videos = [self.root / "one.mp4", self.root / "two.mp4"]
        for video in videos:
            video.write_bytes(b"placeholder")
        args = SimpleNamespace(workers=1, checkpoint_path=self.root / "checkpoint.json", resume=False)
        calls: list[str] = []

        def fake_process(video, output_root, source_root, args, on_progress=None, cancel_event=None):
            calls.append(video.name)
            return {"video": str(video), "saved": 1}

        with patch.object(engine, "process_one_video", side_effect=fake_process):
            engine.process_videos(videos, self.root / "output", None, args)
            args.resume = True
            resumed = engine.process_videos(videos, self.root / "output", None, args)

        self.assertEqual(calls, ["one.mp4", "two.mp4"])
        self.assertEqual([Path(item["video"]).name for item in resumed], ["one.mp4", "two.mp4"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
