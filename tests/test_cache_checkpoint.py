from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
        args.count = 8
        args.every = None
        args.extract_workers = 2
        args.extract_min_targets = 1
        args.duplicate_threshold = 0
        args.cross_run_duplicates = False
        args.cross_run_duplicate_threshold = 0
        output = self.root / "multiprocess"
        report = engine.process_video(self.video, output, None, args)
        self.assertEqual(report["extraction_mode"], "multiprocessing")
        self.assertEqual(report["extraction_workers"], 2)
        self.assertEqual(int(report["requested"]), 8)
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
