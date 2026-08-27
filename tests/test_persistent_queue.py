from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from persistent_queue import PersistentQueueStore


class PersistentQueueTests(unittest.TestCase):
    def test_state_survives_reopen_and_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db_path = root / "queue.sqlite3"
            videos = [root / "one.mp4", root / "two.mp4"]
            with PersistentQueueStore(db_path) as store:
                job_id = store.open_job(videos, "signature-a", resume=False)
                store.mark_running(job_id, 0, 1)
                store.mark_completed(job_id, 0, {"video": str(videos[0]), "saved": 3})
                store.mark_retrying(job_id, 1, 1, "temporary error")
                snapshot = store.snapshot(job_id)
                self.assertEqual([item.status for item in snapshot], ["completed", "retrying"])
                self.assertEqual(snapshot[0].attempts, 1)

            with PersistentQueueStore(db_path) as reopened:
                resumed_id = reopened.open_job(videos, "signature-a", resume=True)
                self.assertEqual(resumed_id, job_id)
                reports = reopened.completed_reports(resumed_id)
                self.assertEqual(reports[str(videos[0].resolve())]["saved"], 3)
                reopened.mark_cancelled(resumed_id)
                self.assertEqual([item.status for item in reopened.snapshot(resumed_id)], ["completed", "cancelled"])

    def test_stable_item_ids_and_retry_by_item_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            videos = [root / "one.mp4", root / "two.mp4"]
            with PersistentQueueStore(root / "queue.sqlite3") as store:
                job_id = store.open_job(videos, "signature-a")
                item = store.snapshot(job_id)[0]
                store.mark_running(job_id, 0, 1, phase="analyzing", progress=0.4)
                store.mark_failed(job_id, 0, 1, "decode error", {"video": str(videos[0])})
                retry_id = store.retry_item(job_id, item_id=item.item_id)
                retried = store.snapshot(job_id)[0]
                self.assertEqual(retry_id, item.item_id)
                self.assertEqual(retried.item_id, item.item_id)
                self.assertEqual(retried.source_position, 0)
                self.assertEqual(retried.status, "queued")
                self.assertEqual(retried.attempts, 0)
                self.assertIsNone(retried.report)

    def test_state_machine_rejects_invalid_transition_and_persists_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "one.mp4"
            with PersistentQueueStore(root / "queue.sqlite3") as store:
                job_id = store.open_job([video], "signature-a")
                with self.assertRaises(ValueError):
                    store.mark_completed(job_id, 0, {"video": str(video)})
                store.mark_running(job_id, 0, 1, phase="analyzing", progress=0.25)
                store.update_progress(job_id, 0, phase="saving", progress=0.75, message="saving")
                store.heartbeat(job_id, 0)
                item = store.snapshot(job_id)[0]
                self.assertEqual(item.status, "running")
                self.assertEqual(item.phase, "saving")
                self.assertAlmostEqual(item.progress, 0.75)
                self.assertEqual(item.message, "saving")
                self.assertIsNotNone(item.updated_at)

    def test_different_signature_creates_new_job(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            videos = [root / "video.mp4"]
            with PersistentQueueStore(root / "queue.sqlite3") as store:
                first = store.open_job(videos, "signature-a")
                second = store.open_job(videos, "signature-b", resume=True)
                self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
