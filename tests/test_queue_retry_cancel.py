from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    import video_screenshot_advanced as engine
except ImportError:
    engine = None  # type: ignore[assignment]

from persistent_queue import PersistentQueueStore


def _has_engine():
    return engine is not None


@unittest.skipUnless(
    _has_engine(),
    "video_screenshot_advanced (cv2) not installed; skipping queue retry tests",
)
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

    def test_bounded_scheduler_does_not_submit_pending_items_while_paused(self) -> None:
        pause_event = threading.Event()
        paused_after_first = threading.Event()
        calls: list[str] = []
        submitted = 0
        submitted_lock = threading.Lock()
        real_executor = engine.ThreadPoolExecutor

        class SpyExecutor:
            def __init__(self, max_workers, thread_name_prefix):
                self.inner = real_executor(max_workers=max_workers, thread_name_prefix=thread_name_prefix)

            def __enter__(self):
                self.inner.__enter__()
                return self

            def __exit__(self, *args):
                return self.inner.__exit__(*args)

            def submit(self, *args, **kwargs):
                nonlocal submitted
                with submitted_lock:
                    submitted += 1
                return self.inner.submit(*args, **kwargs)

        videos = self.videos + [self.root / "three.mp4", self.root / "four.mp4"]
        for video in videos[2:]:
            video.write_bytes(b"test video")
        args = SimpleNamespace(workers=2, extract_workers=1, disk_reserve_bytes=0)

        def fake_process(video, output_root, source_root, args, on_progress=None, cancel_event=None):
            calls.append(video.name)
            return {"video": str(video), "saved": 1}

        def on_complete(video, report):
            if not paused_after_first.is_set():
                paused_after_first.set()
                pause_event.set()

        result: list[dict[str, object]] = []

        def run_queue() -> None:
            with patch.object(engine, "process_one_video", side_effect=fake_process), patch.object(
                engine, "ThreadPoolExecutor", SpyExecutor
            ):
                result.extend(
                    engine.process_videos(
                        videos,
                        self.root / "bounded-output",
                        None,
                        args,
                        on_complete=on_complete,
                        pause_event=pause_event,
                    )
                )

        worker = threading.Thread(target=run_queue)
        worker.start()
        self.assertTrue(paused_after_first.wait(5.0))
        time.sleep(0.1)
        with submitted_lock:
            self.assertEqual(submitted, 2)
        self.assertLessEqual(len(calls), 2)
        pause_event.clear()
        worker.join(timeout=3.0)
        self.assertFalse(worker.is_alive())
        self.assertEqual(submitted, 4)
        self.assertEqual(calls, [video.name for video in videos])
        self.assertEqual([Path(item["video"]).name for item in result], [video.name for video in videos])

    def test_pause_blocks_next_video_until_resumed(self) -> None:
        pause_event = threading.Event()
        pause_event.set()
        calls: list[str] = []
        result: list[dict[str, object]] = []

        def fake_process(video, output_root, source_root, args, on_progress=None, cancel_event=None):
            calls.append(video.name)
            return {"video": str(video), "saved": 1}

        def run_queue() -> None:
            with patch.object(engine, "process_one_video", side_effect=fake_process):
                result.extend(
                    engine.process_videos(
                        self.videos[:1], self.root / "pause-output", None, self.args,
                        max_retries=0, retry_delay_seconds=0, pause_event=pause_event,
                    )
                )

        worker = threading.Thread(target=run_queue)
        worker.start()
        # Wait for worker to reach the pause point — CI can be slow
        time.sleep(0.5)
        self.assertEqual(calls, [])
        pause_event.clear()
        worker.join(timeout=5.0)
        self.assertFalse(worker.is_alive())
        self.assertEqual(calls, ["one.mp4"])
        self.assertEqual(result[0]["saved"], 1)

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

    def test_cancel_interrupts_retry_backoff(self) -> None:
        cancel_event = threading.Event()
        retry_started = threading.Event()
        result: list[BaseException] = []

        def fake_process(video, output_root, source_root, args, on_progress=None, cancel_event=None):
            raise RuntimeError("temporary failure")

        def on_progress(video, phase, fraction, message):
            if phase == "retrying":
                retry_started.set()
                cancel_event.set()

        def run_queue() -> None:
            try:
                with patch.object(engine, "process_one_video", side_effect=fake_process):
                    engine.process_videos(
                        [self.videos[0]],
                        self.root / "backoff-output",
                        None,
                        self.args,
                        on_progress=on_progress,
                        cancel_event=cancel_event,
                        max_retries=2,
                        retry_delay_seconds=30,
                    )
            except BaseException as exc:  # noqa: BLE001 - assertion boundary
                result.append(exc)

        worker = threading.Thread(target=run_queue)
        worker.start()
        self.assertTrue(retry_started.wait(5.0))
        worker.join(timeout=2.0)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], engine.ProcessingCancelled)

    def test_adaptive_extract_workers_caps_nested_parallelism(self) -> None:
        from core import workers as _workers
        with patch.object(_workers.os, "cpu_count", return_value=8), patch.object(_workers, "_available_memory_gb", return_value=16.0):
            self.assertEqual(engine.adaptive_extract_workers(1, 4, target_count=4), 1)
            self.assertEqual(engine.adaptive_extract_workers(1, 4, target_count=8), 3)
            self.assertEqual(engine.adaptive_extract_workers(4, 4, target_count=8), 2)
            self.assertEqual(engine.adaptive_extract_workers(8, 4, target_count=8), 1)

    def test_adaptive_extract_workers_uses_duration_and_target_count(self) -> None:
        from core import workers as _workers
        with patch.object(_workers.os, "cpu_count", return_value=8), patch.object(_workers, "_available_memory_gb", return_value=32.0):
            self.assertEqual(
                engine.adaptive_extract_workers(1, 4, target_count=64, duration_seconds=12),
                1,
            )
            self.assertEqual(
                engine.adaptive_extract_workers(1, 4, target_count=200, duration_seconds=120),
                2,
            )
            self.assertEqual(
                engine.adaptive_extract_workers(1, 4, target_count=600, duration_seconds=600),
                4,
            )

    def test_sqlite_queue_resume_completed_reports(self) -> None:
        queue_db = self.root / "queue.sqlite3"
        checkpoint = self.root / "checkpoint.json"
        args = SimpleNamespace(
            workers=1,
            extract_workers=4,
            extract_min_targets=8,
            queue_db=queue_db,
            checkpoint_path=checkpoint,
            resume=False,
            disk_reserve_bytes=0,
        )
        calls: list[str] = []

        def fake_process(video, output_root, source_root, args, on_progress=None, cancel_event=None):
            calls.append(video.name)
            return {"video": str(video), "saved": 1}

        with patch.object(engine, "process_one_video", side_effect=fake_process):
            first = engine.process_videos(self.videos, self.root / "output", None, args)
            args.resume = True
            resumed = engine.process_videos(self.videos, self.root / "output", None, args)

        self.assertEqual(calls, ["one.mp4", "two.mp4"])
        self.assertEqual([item["saved"] for item in first], [1, 1])
        self.assertEqual([item["saved"] for item in resumed], [1, 1])
        with PersistentQueueStore(queue_db) as store:
            job_id = store.open_job(self.videos, engine.processing_signature(args), resume=True)
            self.assertEqual([item.status for item in store.snapshot(job_id)], ["completed", "completed"])

    def test_sqlite_queue_cancel_marks_all_items_and_closes(self) -> None:
        queue_db = self.root / "cancel.sqlite3"
        args = SimpleNamespace(
            workers=1,
            extract_workers=1,
            extract_min_targets=8,
            queue_db=queue_db,
            checkpoint_path=self.root / "cancel-checkpoint.json",
            resume=False,
            disk_reserve_bytes=0,
        )
        cancel_event = threading.Event()

        def fake_process(video, output_root, source_root, args, on_progress=None, cancel_event=None):
            cancel_event.set()
            engine.check_cancelled(cancel_event)
            return {"video": str(video), "saved": 1}

        with patch.object(engine, "process_one_video", side_effect=fake_process):
            with self.assertRaises(engine.ProcessingCancelled):
                engine.process_videos(self.videos, self.root / "cancel-output", None, args, cancel_event=cancel_event)

        with PersistentQueueStore(queue_db) as store:
            job_id = store.open_job(self.videos, engine.processing_signature(args), resume=True)
            self.assertEqual([item.status for item in store.snapshot(job_id)], ["cancelled", "cancelled"])

    def test_disk_guard_and_stale_temp_cleanup(self) -> None:
        with self.assertRaises(engine.InsufficientDiskSpace):
            engine.ensure_free_disk_space(self.root, reserve_bytes=10**30)

        stale = self.root / "video_screenshot_web_stale"
        stale.mkdir()
        old = time.time() - 3600
        os.utime(stale, (old, old))
        self.assertEqual(engine.cleanup_frameforge_temp_dirs(self.root, older_than_seconds=60), 1)
        self.assertFalse(stale.exists())

        old_one = self.root / "video_screenshot_web_old_one"
        old_two = self.root / "video_screenshot_web_old_two"
        old_one.mkdir()
        old_two.mkdir()
        (old_one / "payload.bin").write_bytes(b"12345678")
        (old_two / "payload.bin").write_bytes(b"abcdefgh")
        old_timestamp = time.time() - 3600
        os.utime(old_one, (old_timestamp - 10, old_timestamp - 10))
        os.utime(old_two, (old_timestamp, old_timestamp))
        removed = engine.cleanup_frameforge_temp_dirs(self.root, older_than_seconds=60, max_total_bytes=8)
        self.assertEqual(removed, 1)
        self.assertFalse(old_one.exists())
        self.assertTrue(old_two.exists())

        cache = self.root / "cache"
        cache.mkdir()
        old_cache = cache / "old.scene-cache.json"
        new_cache = cache / "new.scene-cache.json"
        old_cache.write_bytes(b"old-cache")
        new_cache.write_bytes(b"new-cache")
        os.utime(old_cache, (old_timestamp - 10, old_timestamp - 10))
        os.utime(new_cache, None)
        removed_cache = engine.cleanup_frameforge_cache(cache, max_total_bytes=8, older_than_seconds=60)
        self.assertEqual(removed_cache, 1)
        self.assertFalse(old_cache.exists())
        self.assertTrue(new_cache.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
