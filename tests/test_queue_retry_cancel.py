from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import video_screenshot_advanced as engine


class QueueRetryCancelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root_context = tempfile.TemporaryDirectory()
        self.root = Path(self.root_context.name)
        self.videos = [self.root / "one.mp4", self.root / "two.mp4"]
        for video in self.videos:
            video.write_bytes(b"test video")
        self.args = SimpleNamespace(workers=1, disk_reserve_bytes=0)

    def tearDown(self) -> None:
        self.root_context.cleanup()

    def test_retry_is_applied_per_video_and_preserves_order(self) -> None:
        attempts: dict[str, int] = {}
        progress: list[tuple[str, str]] = []

        def fake_process(video, output_root, source_root, args, on_progress=None, cancel_event=None):
            attempts[video.name] = attempts.get(video.name, 0) + 1
            if video.name == "one.mp4" and attempts[video.name] == 1:
                raise RuntimeError("temporary failure")
            return {"video": str(video), "saved": 1}

        with patch.object(engine, "process_one_video", side_effect=fake_process):
            reports = engine.process_videos(
                self.videos,
                self.root / "output",
                None,
                self.args,
                on_progress=lambda video, phase, fraction, message: progress.append((video.name, phase)),
                max_retries=1,
                retry_delay_seconds=0,
            )

        self.assertEqual([Path(item["video"]).name for item in reports], ["one.mp4", "two.mp4"])
        self.assertEqual(attempts, {"one.mp4": 2, "two.mp4": 1})
        self.assertEqual(reports[0]["attempts"], 2)
        self.assertEqual(reports[1]["attempts"], 1)
        self.assertIn(("one.mp4", "retrying"), progress)

    def test_cancel_before_queue_stops_without_processing(self) -> None:
        cancel_event = threading.Event()
        cancel_event.set()
        with patch.object(engine, "process_one_video") as process_mock:
            with self.assertRaises(engine.ProcessingCancelled):
                engine.process_videos(
                    self.videos,
                    self.root / "output",
                    None,
                    self.args,
                    cancel_event=cancel_event,
                )
        process_mock.assert_not_called()

    def test_cancel_during_worker_propagates_processing_cancelled(self) -> None:
        cancel_event = threading.Event()

        def fake_process(video, output_root, source_root, args, on_progress=None, cancel_event=None):
            on_progress(video, "analyzing", 0.25, "processing")
            engine.check_cancelled(cancel_event)
            return {"video": str(video), "saved": 1}

        def request_cancel(video, phase, fraction, message):
            if phase == "analyzing":
                cancel_event.set()

        with patch.object(engine, "process_one_video", side_effect=fake_process):
            with self.assertRaises(engine.ProcessingCancelled):
                engine.process_videos(
                    [self.videos[0]],
                    self.root / "output",
                    None,
                    self.args,
                    on_progress=request_cancel,
                    cancel_event=cancel_event,
                )

    def test_disk_guard_and_stale_temp_cleanup(self) -> None:
        with self.assertRaises(engine.InsufficientDiskSpace):
            engine.ensure_free_disk_space(self.root, reserve_bytes=10**30)

        stale = self.root / "video_screenshot_web_stale"
        stale.mkdir()
        old = time.time() - 3600
        os.utime(stale, (old, old))
        self.assertEqual(engine.cleanup_frameforge_temp_dirs(self.root, older_than_seconds=60), 1)
        self.assertFalse(stale.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
