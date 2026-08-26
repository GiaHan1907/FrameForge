from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class QueueItem:
    job_id: str
    position: int
    video_path: str
    status: str
    attempts: int
    error: str | None
    report: dict[str, object] | None


class PersistentQueueStore:
    """SQLite-backed queue for durable video processing state."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(self.path), timeout=30.0, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA busy_timeout=30000")
        self._initialize()

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    run_signature TEXT NOT NULL,
                    state TEXT NOT NULL,
                    video_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS queue_items (
                    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    video_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    report_json TEXT,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (job_id, position)
                );
                CREATE INDEX IF NOT EXISTS idx_queue_items_state ON queue_items(job_id, status);
                """
            )

    @staticmethod
    def _video_key(videos: Iterable[Path]) -> list[str]:
        return [str(Path(video).resolve()) for video in videos]

    def open_job(self, videos: list[Path], run_signature: str, resume: bool = False) -> str:
        video_keys = self._video_key(videos)
        now = time.time()
        with self._lock, self._connection:
            if resume:
                candidates = self._connection.execute(
                    "SELECT job_id FROM jobs WHERE run_signature = ? ORDER BY updated_at DESC",
                    (run_signature,),
                ).fetchall()
                for candidate in candidates:
                    rows = self._connection.execute(
                        "SELECT video_path FROM queue_items WHERE job_id = ? ORDER BY position",
                        (candidate["job_id"],),
                    ).fetchall()
                    if [row["video_path"] for row in rows] == video_keys:
                        job_id = str(candidate["job_id"])
                        self._connection.execute(
                            "UPDATE queue_items SET status = 'queued', updated_at = ? WHERE job_id = ? AND status = 'running'",
                            (now, job_id),
                        )
                        self._connection.execute(
                            "UPDATE jobs SET state = 'resumed', updated_at = ? WHERE job_id = ?",
                            (now, job_id),
                        )
                        return job_id
            job_id = uuid.uuid4().hex
            self._connection.execute(
                "INSERT INTO jobs(job_id, created_at, updated_at, run_signature, state, video_count) VALUES (?, ?, ?, ?, ?, ?)",
                (job_id, now, now, run_signature, "queued", len(video_keys)),
            )
            self._connection.executemany(
                "INSERT INTO queue_items(job_id, position, video_path, status, attempts, updated_at) VALUES (?, ?, ?, ?, 0, ?)",
                [(job_id, position, video_path, "queued", now) for position, video_path in enumerate(video_keys)],
            )
            return job_id

    def _touch_job(self, job_id: str, state: str | None = None) -> None:
        now = time.time()
        if state is None:
            self._connection.execute("UPDATE jobs SET updated_at = ? WHERE job_id = ?", (now, job_id))
        else:
            self._connection.execute("UPDATE jobs SET state = ?, updated_at = ? WHERE job_id = ?", (state, now, job_id))

    def mark_running(self, job_id: str, position: int, attempt: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE queue_items SET status = 'running', attempts = ?, error = NULL, updated_at = ? WHERE job_id = ? AND position = ?",
                (attempt, time.time(), job_id, position),
            )
            self._touch_job(job_id, "running")

    def mark_retrying(self, job_id: str, position: int, attempt: int, error: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE queue_items SET status = 'retrying', attempts = ?, error = ?, updated_at = ? WHERE job_id = ? AND position = ?",
                (attempt, error[:4000], time.time(), job_id, position),
            )
            self._touch_job(job_id, "running")

    def mark_completed(self, job_id: str, position: int, report: dict[str, object]) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE queue_items SET status = 'completed', error = NULL, report_json = ?, updated_at = ? WHERE job_id = ? AND position = ?",
                (json.dumps(report, ensure_ascii=False), time.time(), job_id, position),
            )
            self._touch_job(job_id)

    def mark_failed(self, job_id: str, position: int, attempts: int, error: str, report: dict[str, object]) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE queue_items SET status = 'failed', attempts = ?, error = ?, report_json = ?, updated_at = ? WHERE job_id = ? AND position = ?",
                (attempts, error[:4000], json.dumps(report, ensure_ascii=False), time.time(), job_id, position),
            )
            self._touch_job(job_id)

    def mark_cancelled(self, job_id: str, position: int | None = None) -> None:
        with self._lock, self._connection:
            now = time.time()
            if position is None:
                self._connection.execute("UPDATE queue_items SET status = 'cancelled', updated_at = ? WHERE job_id = ? AND status IN ('queued', 'running', 'retrying')", (now, job_id))
            else:
                self._connection.execute("UPDATE queue_items SET status = 'cancelled', updated_at = ? WHERE job_id = ? AND position = ?", (now, job_id, position))
            self._touch_job(job_id, "cancelled")

    def mark_completed_job(self, job_id: str) -> None:
        with self._lock, self._connection:
            self._touch_job(job_id, "completed")

    def completed_reports(self, job_id: str) -> dict[str, dict[str, object]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT video_path, report_json FROM queue_items WHERE job_id = ? AND status = 'completed' AND report_json IS NOT NULL",
                (job_id,),
            ).fetchall()
        result: dict[str, dict[str, object]] = {}
        for row in rows:
            try:
                report = json.loads(row["report_json"])
            except (TypeError, ValueError):
                continue
            if isinstance(report, dict):
                result[str(row["video_path"])] = report
        return result

    def snapshot(self, job_id: str) -> list[QueueItem]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT job_id, position, video_path, status, attempts, error, report_json FROM queue_items WHERE job_id = ? ORDER BY position",
                (job_id,),
            ).fetchall()
        items: list[QueueItem] = []
        for row in rows:
            try:
                report = json.loads(row["report_json"]) if row["report_json"] else None
            except (TypeError, ValueError):
                report = None
            items.append(QueueItem(str(row["job_id"]), int(row["position"]), str(row["video_path"]), str(row["status"]), int(row["attempts"]), row["error"], report if isinstance(report, dict) else None))
        return items

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "PersistentQueueStore":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
