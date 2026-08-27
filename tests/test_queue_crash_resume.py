from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from persistent_queue import (
    ITEM_COMPLETED,
    ITEM_INTERRUPTED,
    ITEM_QUEUED,
    ITEM_RUNNING,
    PersistentQueueStore,
)


CRASH_WORKER = r'''
import os
import sys
from pathlib import Path
from persistent_queue import PersistentQueueStore

root = Path(sys.argv[1])
db_path = root / "queue.sqlite3"
videos = [root / "one.mp4", root / "two.mp4", root / "three.mp4"]
with PersistentQueueStore(db_path) as store:
    job_id = store.open_job(videos, "crash-resume-signature", resume=False)
    store.mark_running(job_id, 0, 1, phase="analyzing", progress=0.42, message="synthetic crash")
    store.mark_running(job_id, 1, 1, phase="saving", progress=0.75, message="synthetic crash")
    print(job_id, flush=True)
    os._exit(23)
'''


class QueueCrashResumeIntegrationTests(unittest.TestCase):
    def test_crash_reconciles_active_items_and_resume_preserves_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            videos = [root / "one.mp4", root / "two.mp4", root / "three.mp4"]
            for video in videos:
                video.write_bytes(b"synthetic input")

            completed = subprocess.run(
                [sys.executable, "-c", CRASH_WORKER, str(root)],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 23, completed.stderr)

            crashed_job_id = completed.stdout.strip().splitlines()[-1]
            self.assertTrue(crashed_job_id)

            with PersistentQueueStore(root / "queue.sqlite3") as store:
                self.assertEqual(
                    [item.status for item in store.snapshot(crashed_job_id)],
                    [ITEM_RUNNING, ITEM_RUNNING, ITEM_QUEUED],
                )
                resumed_id = store.open_job(videos, "crash-resume-signature", resume=True)
                self.assertEqual(resumed_id, crashed_job_id)
                snapshot_after_open = store.snapshot(resumed_id)
                self.assertEqual([item.status for item in snapshot_after_open], [ITEM_INTERRUPTED, ITEM_INTERRUPTED, ITEM_QUEUED])
                original_ids = [item.item_id for item in snapshot_after_open]
                self.assertEqual(len(set(original_ids)), 3)

                self.assertEqual(store.resume_job(resumed_id), 2)
                resumed_snapshot = store.snapshot(resumed_id)
                self.assertEqual([item.status for item in resumed_snapshot], [ITEM_QUEUED, ITEM_QUEUED, ITEM_QUEUED])
                self.assertEqual([item.item_id for item in resumed_snapshot], original_ids)

                store.mark_running(resumed_id, 0, 2, phase="analyzing")
                store.mark_completed(resumed_id, 0, {"video": str(videos[0]), "saved": 2, "attempts": 2})
                store.mark_running(resumed_id, 1, 2, phase="saving")
                store.mark_completed(resumed_id, 1, {"video": str(videos[1]), "saved": 1, "attempts": 2})
                store.mark_running(resumed_id, 2, 1, phase="saving")
                store.mark_completed(resumed_id, 2, {"video": str(videos[2]), "saved": 3, "attempts": 1})
                store.mark_completed_job(resumed_id)

                final_snapshot = store.snapshot(resumed_id)
                self.assertEqual([item.status for item in final_snapshot], [ITEM_COMPLETED] * 3)
                self.assertEqual(store.job_info(resumed_id)["state"], "completed")
                self.assertEqual(store.completed_reports(resumed_id)[str(videos[0].resolve())]["saved"], 2)

    def test_v022_schema_migrates_additively(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db_path = root / "legacy.sqlite3"
            videos = [root / "legacy.mp4"]
            connection = sqlite3.connect(db_path)
            connection.executescript(
                """
                CREATE TABLE jobs (
                    job_id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    run_signature TEXT NOT NULL,
                    state TEXT NOT NULL,
                    video_count INTEGER NOT NULL
                );
                CREATE TABLE queue_items (
                    job_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    video_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    report_json TEXT,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (job_id, position)
                );
                """
            )
            connection.execute(
                "INSERT INTO jobs VALUES ('legacy-job', 1, 1, 'legacy-signature', 'running', 1)"
            )
            connection.execute(
                "INSERT INTO queue_items VALUES ('legacy-job', 0, ?, 'running', 1, NULL, NULL, 1)",
                (str(videos[0].resolve()),),
            )
            connection.commit()
            connection.close()

            with PersistentQueueStore(db_path) as store:
                self.assertEqual(store.schema_version(), 2)
                self.assertEqual(store.open_job(videos, "legacy-signature", resume=True), "legacy-job")
                item = store.snapshot("legacy-job")[0]
                self.assertEqual(item.status, ITEM_INTERRUPTED)
                self.assertTrue(item.item_id)
                self.assertEqual(item.source_position, 0)
                self.assertEqual(store.resume_job("legacy-job"), 1)
                self.assertEqual(store.snapshot("legacy-job")[0].status, ITEM_QUEUED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
