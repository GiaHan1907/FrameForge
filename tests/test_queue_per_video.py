from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from queue_per_video import (
    QueueStatus,
    VideoQueueController,
    classify_error,
)


class QueueSampleTests(unittest.TestCase):
    def make_videos(self, directory: str) -> list[Path]:
        root = Path(directory)
        videos = [root / "one.mp4", root / "two.mp4"]
        for video in videos:
            video.write_bytes(b"sample")
        return videos

    def test_classifier(self) -> None:
        self.assertEqual(classify_error(RuntimeError("HTTP 429 too many requests")).code, "rate_limited")
        self.assertTrue(classify_error(RuntimeError("connection reset by peer")).retryable)
        self.assertFalse(classify_error(RuntimeError("requested format is not available")).retryable)

    def test_pause_resume_and_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calls: list[str] = []
            started = threading.Event()
            release = threading.Event()

            def processor(video, callback, cancel_event):
                calls.append(video.name)
                started.set()
                if video.name == "one.mp4":
                    release.wait(1.0)
                return {"saved": 1}

            controller = VideoQueueController(self.make_videos(directory), processor)
            controller.start()
            self.assertTrue(started.wait(1.0))
            controller.pause()
            self.assertTrue(controller.is_paused)
            release.set()
            time.sleep(0.2)
            self.assertEqual(calls, ["one.mp4"])
            controller.resume()
            controller.wait(2.0)
            self.assertEqual(calls, ["one.mp4", "two.mp4"])
            self.assertEqual(controller.snapshot()["status"], "completed")

    def test_cancel_while_paused_unblocks_queue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            started = threading.Event()
            release = threading.Event()

            def processor(video, callback, cancel_event):
                started.set()
                release.wait(1.0)
                return {"saved": 0}

            controller = VideoQueueController(self.make_videos(directory), processor)
            controller.start()
            self.assertTrue(started.wait(1.0))
            controller.pause()
            release.set()
            time.sleep(0.1)
            controller.cancel()
            controller.wait(2.0)
            state = controller.snapshot()
            self.assertEqual(state["status"], "cancelled")
            self.assertEqual(state["cancelled"], 1)

    def test_retry_backoff_and_retry_failed_item(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calls = {"one.mp4": 0, "two.mp4": 0}

            def processor(video, callback, cancel_event):
                calls[video.name] += 1
                if video.name == "one.mp4" and calls[video.name] == 1:
                    raise RuntimeError("connection reset by peer")
                if video.name == "two.mp4":
                    raise RuntimeError("requested format is not available")
                return {"saved": 3}

            controller = VideoQueueController(
                self.make_videos(directory),
                processor,
                max_retries=1,
                base_retry_delay=0.01,
            )
            with patch("queue_per_video.time.sleep", wraps=time.sleep) as sleep_mock:
                controller.start()
                controller.wait(2.0)
            state = controller.snapshot()
            self.assertEqual(calls, {"one.mp4": 2, "two.mp4": 1})
            self.assertEqual(state["items"][0]["status"], QueueStatus.COMPLETED.value)
            self.assertEqual(state["items"][1]["status"], QueueStatus.FAILED.value)
            self.assertGreaterEqual(sleep_mock.call_count, 1)
            controller.retry_item(1)
            controller.wait(2.0)
            self.assertEqual(controller.snapshot()["items"][1]["attempts"], 1)


if __name__ == "__main__":
    unittest.main()
