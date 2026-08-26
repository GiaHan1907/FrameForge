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
