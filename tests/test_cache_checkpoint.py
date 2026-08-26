from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import video_screenshot_advanced as engine


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
