"""Durable SQLite state machine for FrameForge video queues.

The v0.1.23 schema remains backward compatible with the v0.1.22 tables.  The
migration is deliberately additive: existing jobs, positions, reports and
statuses are preserved, while stable item IDs and lifecycle telemetry are
backfilled for old rows.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = 2
SCHEMA_VERSION_LABEL = "0.1.23"

ITEM_QUEUED = "queued"
ITEM_RUNNING = "running"
ITEM_RETRYING = "retrying"
ITEM_COMPLETED = "completed"
ITEM_FAILED = "failed"
ITEM_CANCELLED = "cancelled"
ITEM_INTERRUPTED = "interrupted"

TERMINAL_ITEM_STATES = {ITEM_COMPLETED, ITEM_FAILED, ITEM_CANCELLED}
ACTIVE_ITEM_STATES = {ITEM_RUNNING, ITEM_RETRYING}
RESUMABLE_ITEM_STATES = {ITEM_QUEUED, ITEM_INTERRUPTED, ITEM_RETRYING, ITEM_RUNNING}

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    ITEM_QUEUED: {ITEM_RUNNING, ITEM_RETRYING, ITEM_CANCELLED, ITEM_INTERRUPTED, ITEM_FAILED},
    ITEM_RUNNING: {ITEM_RETRYING, ITEM_COMPLETED, ITEM_FAILED, ITEM_CANCELLED, ITEM_INTERRUPTED},
    ITEM_RETRYING: {ITEM_RUNNING, ITEM_FAILED, ITEM_CANCELLED, ITEM_INTERRUPTED},
    ITEM_INTERRUPTED: {ITEM_QUEUED, ITEM_RUNNING, ITEM_CANCELLED},
    ITEM_FAILED: {ITEM_QUEUED, ITEM_RUNNING, ITEM_CANCELLED},
    ITEM_CANCELLED: {ITEM_QUEUED, ITEM_RUNNING},
    ITEM_COMPLETED: {ITEM_QUEUED, ITEM_RUNNING},
}


@dataclass(frozen=True)
class QueueItem:
    job_id: str
    position: int
    video_path: str
    status: str
    attempts: int
    error: str | None
    report: dict[str, object] | None
    item_id: str = ""
    source_position: int = 0
    phase: str = "queued"
    progress: float = 0.0
    message: str | None = None
    error_code: str | None = None
    suggestion: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    updated_at: float | None = None


class PersistentQueueStore:
    """SQLite-backed queue with additive v0.1.22 -> v0.1.23 migration.

    All state changes are serialized by a re-entrant lock and committed in a
    SQLite transaction.  Streamlit or worker code may continue using the
    position-based methods from v0.1.22; new callers can use ``item_id`` for
    retry/resume operations that must survive subset reordering.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._closed = False
        self._connection = sqlite3.connect(
            str(self.path), timeout=30.0, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA busy_timeout = 30000")
        self._initialize()

    @staticmethod
    def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
        return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}

    @staticmethod
    def _stable_item_id(job_id: str, position: int) -> str:
        return uuid.uuid5(
            uuid.NAMESPACE_URL, f"frameforge:{job_id}:{position}"
        ).hex

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
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
                CREATE INDEX IF NOT EXISTS idx_queue_items_state
                    ON queue_items(job_id, status);
                """
            )
            self._migrate_to_v23_locked()

    def _migrate_to_v23_locked(self) -> None:
        """Apply additive migrations and backfill legacy v0.1.22 rows."""
        meta = self._connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        if meta is None:
            self._connection.execute(
                "INSERT INTO schema_meta(key, value) VALUES ('schema_version', '1')"
            )
            current_version = 1
        else:
            try:
                current_version = int(meta["value"])
            except (TypeError, ValueError):
                current_version = 1

        job_columns = self._column_names(self._connection, "jobs")
        job_additions = {
            "schema_version": "INTEGER NOT NULL DEFAULT 2",
            "last_error": "TEXT",
            "finished_at": "REAL",
            "heartbeat_at": "REAL",
        }
        for name, definition in job_additions.items():
            if name not in job_columns:
                self._connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")

        item_columns = self._column_names(self._connection, "queue_items")
        item_additions = {
            "item_id": "TEXT",
            "source_position": "INTEGER",
            "phase": "TEXT NOT NULL DEFAULT 'queued'",
            "progress": "REAL NOT NULL DEFAULT 0.0",
            "message": "TEXT",
            "error_code": "TEXT",
            "suggestion": "TEXT",
            "started_at": "REAL",
            "finished_at": "REAL",
            "last_heartbeat": "REAL",
        }
        for name, definition in item_additions.items():
            if name not in item_columns:
                self._connection.execute(
                    f"ALTER TABLE queue_items ADD COLUMN {name} {definition}"
                )

        # Backfill values without changing any v0.1.22 report or status.
        self._connection.execute(
            "UPDATE queue_items SET source_position = position WHERE source_position IS NULL"
        )
        rows = self._connection.execute(
            "SELECT job_id, position, item_id, status FROM queue_items"
        ).fetchall()
        now = time.time()
        for row in rows:
            item_id = row["item_id"] or self._stable_item_id(
                str(row["job_id"]), int(row["position"])
            )
            self._connection.execute(
                """
                UPDATE queue_items
                SET item_id = ?,
                    phase = COALESCE(NULLIF(phase, ''), status),
                    progress = CASE WHEN status = 'completed' THEN 1.0 ELSE progress END
                WHERE job_id = ? AND position = ?
                """,
                (item_id, row["job_id"], row["position"]),
            )
        self._connection.execute(
            "UPDATE jobs SET schema_version = ?, heartbeat_at = COALESCE(heartbeat_at, updated_at)",
            (SCHEMA_VERSION,),
        )
        self._connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_items_item_id ON queue_items(item_id)"
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_queue_items_source_position ON queue_items(job_id, source_position)"
        )
        self._connection.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self._connection.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('app_version', ?)",
            (SCHEMA_VERSION_LABEL,),
        )
        if current_version < SCHEMA_VERSION:
            self._connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('migrated_at', ?)",
                (str(now),),
            )

    @staticmethod
    def _video_key(videos: Iterable[Path]) -> list[str]:
        return [str(Path(video).resolve()) for video in videos]

    def _reconcile_interrupted_locked(self, job_id: str) -> int:
        now = time.time()
        cursor = self._connection.execute(
            """
            UPDATE queue_items
            SET status = 'interrupted', phase = 'interrupted',
                message = 'Ứng dụng đã dừng trước khi item hoàn tất',
                updated_at = ?, last_heartbeat = ?
            WHERE job_id = ? AND status IN ('running', 'retrying')
            """,
            (now, now, job_id),
        )
        if cursor.rowcount:
            self._connection.execute(
                "UPDATE jobs SET state = 'interrupted', updated_at = ?, heartbeat_at = ? WHERE job_id = ?",
                (now, now, job_id),
            )
        return int(cursor.rowcount)

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
                    job_id = str(candidate["job_id"])
                    rows = self._connection.execute(
                        "SELECT video_path FROM queue_items WHERE job_id = ? ORDER BY source_position, position",
                        (job_id,),
                    ).fetchall()
                    if [row["video_path"] for row in rows] == video_keys:
                        self._reconcile_interrupted_locked(job_id)
                        self._connection.execute(
                            "UPDATE jobs SET state = CASE WHEN EXISTS (SELECT 1 FROM queue_items WHERE job_id = ? AND status = 'interrupted') THEN 'interrupted' ELSE 'resumed' END, updated_at = ?, heartbeat_at = ? WHERE job_id = ?",
                            (job_id, now, now, job_id),
                        )
                        return job_id

            job_id = uuid.uuid4().hex
            self._connection.execute(
                """
                INSERT INTO jobs(
                    job_id, created_at, updated_at, run_signature, state,
                    video_count, schema_version, heartbeat_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, now, now, run_signature, "queued", len(video_keys), SCHEMA_VERSION, now),
            )
            self._connection.executemany(
                """
                INSERT INTO queue_items(
                    job_id, position, video_path, status, attempts, updated_at,
                    item_id, source_position, phase, progress, message, last_heartbeat
                ) VALUES (?, ?, ?, 'queued', 0, ?, ?, ?, 'queued', 0.0, ?, ?)
                """,
                [
                    (
                        job_id,
                        position,
                        video_path,
                        now,
                        self._stable_item_id(job_id, position),
                        position,
                        "Đang chờ scheduler cấp worker",
                        now,
                    )
                    for position, video_path in enumerate(video_keys)
                ],
            )
            return job_id

    def _touch_job(self, job_id: str, state: str | None = None) -> None:
        now = time.time()
        if state is None:
            self._connection.execute(
                "UPDATE jobs SET updated_at = ?, heartbeat_at = ? WHERE job_id = ?",
                (now, now, job_id),
            )
        else:
            self._connection.execute(
                "UPDATE jobs SET state = ?, updated_at = ?, heartbeat_at = ? WHERE job_id = ?",
                (state, now, now, job_id),
            )

    def _item_row_locked(
        self, job_id: str, position: int | None = None, item_id: str | None = None
    ) -> sqlite3.Row | None:
        if item_id is not None:
            return self._connection.execute(
                "SELECT * FROM queue_items WHERE job_id = ? AND item_id = ?",
                (job_id, item_id),
            ).fetchone()
        if position is None:
            raise ValueError("position hoặc item_id là bắt buộc")
        return self._connection.execute(
            "SELECT * FROM queue_items WHERE job_id = ? AND position = ?",
            (job_id, position),
        ).fetchone()

    def _transition_item_locked(
        self,
        job_id: str,
        target_status: str,
        *,
        position: int | None = None,
        item_id: str | None = None,
        attempts: int | None = None,
        error: str | None = None,
        report: dict[str, object] | None = None,
        phase: str | None = None,
        progress: float | None = None,
        message: str | None = None,
        error_code: str | None = None,
        suggestion: str | None = None,
        clear_report: bool = False,
        reset_timing: bool = False,
        force: bool = False,
    ) -> QueueItem:
        row = self._item_row_locked(job_id, position, item_id)
        if row is None:
            raise KeyError(f"Không tìm thấy queue item: {job_id}/{item_id or position}")
        current = str(row["status"])
        if not force and target_status != current and target_status not in _ALLOWED_TRANSITIONS.get(current, set()):
            raise ValueError(f"Transition không hợp lệ: {current} -> {target_status}")
        now = time.time()
        next_attempts = int(row["attempts"] if attempts is None else attempts)
        next_phase = phase or target_status
        next_progress = float(row["progress"] if progress is None else max(0.0, min(1.0, progress)))
        next_message = message if message is not None else row["message"]
        next_error = error[:4000] if error else None
        report_json = (
            json.dumps(report, ensure_ascii=False)
            if report is not None
            else (None if clear_report else row["report_json"])
        )
        started_at = None if reset_timing else row["started_at"]
        if target_status == ITEM_RUNNING and started_at is None:
            started_at = now
        finished_at = now if target_status in TERMINAL_ITEM_STATES else None
        if target_status == ITEM_COMPLETED:
            next_progress = 1.0
            next_message = message or "Hoàn tất"
            next_error = None
        if target_status in {ITEM_QUEUED, ITEM_INTERRUPTED}:
            finished_at = None
        self._connection.execute(
            """
            UPDATE queue_items
            SET status = ?, attempts = ?, error = ?, report_json = ?, updated_at = ?,
                phase = ?, progress = ?, message = ?, error_code = ?, suggestion = ?,
                started_at = ?, finished_at = ?, last_heartbeat = ?
            WHERE job_id = ? AND position = ?
            """,
            (
                target_status,
                next_attempts,
                next_error,
                report_json,
                now,
                next_phase,
                next_progress,
                next_message,
                error_code,
                suggestion,
                started_at,
                finished_at,
                now,
                job_id,
                row["position"],
            ),
        )
        return self._row_to_item(
            self._connection.execute(
                "SELECT * FROM queue_items WHERE job_id = ? AND position = ?",
                (job_id, row["position"]),
            ).fetchone()
        )

    def mark_running(
        self,
        job_id: str,
        position: int,
        attempt: int,
        *,
        item_id: str | None = None,
        phase: str = "preparing",
        progress: float = 0.0,
        message: str | None = None,
    ) -> None:
        with self._lock, self._connection:
            self._transition_item_locked(
                job_id,
                ITEM_RUNNING,
                position=position,
                item_id=item_id,
                attempts=attempt,
                phase=phase,
                progress=progress,
                message=message or "Đang xử lý",
                force=False,
            )
            self._touch_job(job_id, "running")

    def mark_retrying(
        self,
        job_id: str,
        position: int,
        attempt: int,
        error: str,
        *,
        item_id: str | None = None,
        error_code: str | None = None,
        suggestion: str | None = None,
        message: str | None = None,
    ) -> None:
        with self._lock, self._connection:
            self._transition_item_locked(
                job_id,
                ITEM_RETRYING,
                position=position,
                item_id=item_id,
                attempts=attempt,
                error=error,
                phase="retrying",
                message=message or "Chuẩn bị retry",
                error_code=error_code,
                suggestion=suggestion,
            )
            self._touch_job(job_id, "retrying")

    def mark_completed(self, job_id: str, position: int, report: dict[str, object], *, item_id: str | None = None) -> None:
        with self._lock, self._connection:
            self._transition_item_locked(
                job_id,
                ITEM_COMPLETED,
                position=position,
                item_id=item_id,
                attempts=int(report["attempts"]) if "attempts" in report and report["attempts"] is not None else None,
                report=report,
                phase="completed",
                progress=1.0,
                message="Hoàn tất",
            )
            self._touch_job(job_id)

    def mark_failed(
        self,
        job_id: str,
        position: int,
        attempts: int,
        error: str,
        report: dict[str, object],
        *,
        item_id: str | None = None,
        error_code: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        with self._lock, self._connection:
            self._transition_item_locked(
                job_id,
                ITEM_FAILED,
                position=position,
                item_id=item_id,
                attempts=attempts,
                error=error,
                report=report,
                phase="failed",
                message="Xử lý thất bại",
                error_code=error_code,
                suggestion=suggestion,
            )
            self._touch_job(job_id, "failed")

    def mark_cancelled(self, job_id: str, position: int | None = None) -> None:
        with self._lock, self._connection:
            now = time.time()
            if position is not None:
                # Keep the explicit position behavior of v0.1.22.
                sql = (
                    "UPDATE queue_items SET status = 'cancelled', phase = 'cancelled', message = 'Đã hủy', "
                    "updated_at = ?, finished_at = ?, last_heartbeat = ? "
                    "WHERE job_id = ? AND position = ? AND status != 'completed'"
                )
                params: list[object] = [now, now, now, job_id, position]
            else:
                statuses = tuple(RESUMABLE_ITEM_STATES | {ITEM_INTERRUPTED})
                placeholders = ",".join("?" for _ in statuses)
                sql = (
                    f"UPDATE queue_items SET status = 'cancelled', phase = 'cancelled', message = 'Đã hủy', "
                    f"updated_at = ?, finished_at = ?, last_heartbeat = ? "
                    f"WHERE job_id = ? AND status IN ({placeholders})"
                )
                params = [now, now, now, job_id, *statuses]
            self._connection.execute(sql, params)
            self._touch_job(job_id, "cancelled")

    def mark_interrupted(self, job_id: str, position: int | None = None, *, reason: str = "Ứng dụng đã dừng bất thường") -> None:
        with self._lock, self._connection:
            now = time.time()
            if position is None:
                self._connection.execute(
                    "UPDATE queue_items SET status = 'interrupted', phase = 'interrupted', message = ?, updated_at = ?, last_heartbeat = ? WHERE job_id = ? AND status IN ('running', 'retrying')",
                    (reason, now, now, job_id),
                )
            else:
                self._connection.execute(
                    "UPDATE queue_items SET status = 'interrupted', phase = 'interrupted', message = ?, updated_at = ?, last_heartbeat = ? WHERE job_id = ? AND position = ? AND status IN ('running', 'retrying')",
                    (reason, now, now, job_id, position),
                )
            self._touch_job(job_id, "interrupted")

    def resume_job(self, job_id: str) -> int:
        """Move interrupted items back to queued without changing stable IDs."""
        with self._lock, self._connection:
            now = time.time()
            cursor = self._connection.execute(
                """
                UPDATE queue_items
                SET status = 'queued', phase = 'queued', progress = 0.0,
                    message = 'Đã khôi phục; chờ scheduler', error = NULL,
                    error_code = NULL, suggestion = NULL, finished_at = NULL,
                    updated_at = ?, last_heartbeat = ?
                WHERE job_id = ? AND status = 'interrupted'
                """,
                (now, now, job_id),
            )
            self._touch_job(job_id, "resumed")
            return int(cursor.rowcount)

    def retry_item(self, job_id: str, *, item_id: str | None = None, position: int | None = None) -> str:
        """Reset one failed/interrupted/cancelled item and return its stable ID."""
        with self._lock, self._connection:
            row = self._item_row_locked(job_id, position, item_id)
            if row is None:
                raise KeyError(f"Không tìm thấy queue item: {job_id}/{item_id or position}")
            self._transition_item_locked(
                job_id,
                ITEM_QUEUED,
                position=int(row["position"]),
                attempts=0,
                error=None,
                report=None,
                phase="queued",
                progress=0.0,
                message="Đã đưa lại vào queue",
                error_code=None,
                suggestion=None,
                clear_report=True,
                reset_timing=True,
                force=str(row["status"]) in {ITEM_FAILED, ITEM_CANCELLED, ITEM_INTERRUPTED, ITEM_COMPLETED},
            )
            self._touch_job(job_id, "queued")
            return str(row["item_id"])

    def retry_failed(self, job_id: str) -> int:
        with self._lock, self._connection:
            positions = [
                int(row["position"])
                for row in self._connection.execute(
                    "SELECT position FROM queue_items WHERE job_id = ? AND status = 'failed' ORDER BY source_position, position",
                    (job_id,),
                ).fetchall()
            ]
            for position in positions:
                self.retry_item(job_id, position=position)
            return len(positions)

    def update_progress(
        self,
        job_id: str,
        position: int,
        *,
        phase: str,
        progress: float,
        message: str | None = None,
        item_id: str | None = None,
    ) -> None:
        """Persist a lightweight progress heartbeat without changing status."""
        with self._lock, self._connection:
            row = self._item_row_locked(job_id, position, item_id)
            if row is None:
                raise KeyError(f"Không tìm thấy queue item: {job_id}/{item_id or position}")
            now = time.time()
            self._connection.execute(
                """
                UPDATE queue_items
                SET phase = ?, progress = ?, message = COALESCE(?, message),
                    updated_at = ?, last_heartbeat = ?
                WHERE job_id = ? AND position = ?
                """,
                (
                    phase,
                    max(0.0, min(1.0, float(progress))),
                    message,
                    now,
                    now,
                    job_id,
                    row["position"],
                ),
            )
            self._touch_job(job_id)

    def heartbeat(self, job_id: str, position: int | None = None) -> None:
        """Refresh liveness timestamps for a job or one item."""
        with self._lock, self._connection:
            now = time.time()
            if position is None:
                self._connection.execute(
                    "UPDATE jobs SET updated_at = ?, heartbeat_at = ? WHERE job_id = ?",
                    (now, now, job_id),
                )
            else:
                self._connection.execute(
                    "UPDATE queue_items SET updated_at = ?, last_heartbeat = ? WHERE job_id = ? AND position = ?",
                    (now, now, job_id, position),
                )
                self._touch_job(job_id)

    def reconcile_stale_jobs(self, stale_after_seconds: float = 300.0) -> list[str]:
        """Mark active items of old jobs interrupted and return affected jobs."""
        cutoff = time.time() - max(0.0, float(stale_after_seconds))
        with self._lock, self._connection:
            rows = self._connection.execute(
                "SELECT job_id FROM jobs WHERE state IN ('running', 'retrying', 'resumed') AND COALESCE(heartbeat_at, updated_at) < ?",
                (cutoff,),
            ).fetchall()
            affected: list[str] = []
            for row in rows:
                job_id = str(row["job_id"])
                if self._reconcile_interrupted_locked(job_id):
                    affected.append(job_id)
            return affected

    def mark_paused(self, job_id: str) -> None:
        with self._lock, self._connection:
            self._touch_job(job_id, "paused")

    def mark_resumed(self, job_id: str) -> None:
        with self._lock, self._connection:
            self._touch_job(job_id, "resumed")

    def mark_completed_job(self, job_id: str) -> None:
        with self._lock, self._connection:
            self._touch_job(job_id, "completed")

    def list_jobs(self, states: set[str] | None = None) -> list[dict[str, object]]:
        """Liệt kê job theo trạng thái để UI phát hiện queue cần khôi phục."""
        with self._lock:
            if states:
                placeholders = ",".join("?" for _ in states)
                rows = self._connection.execute(
                    f"SELECT * FROM jobs WHERE state IN ({placeholders}) ORDER BY updated_at DESC",
                    tuple(sorted(states)),
                ).fetchall()
            else:
                rows = self._connection.execute("SELECT * FROM jobs ORDER BY updated_at DESC").fetchall()
        return [dict(row) for row in rows]

    def list_recoverable_jobs(self) -> list[dict[str, object]]:
        return self.list_jobs({"running", "paused", "retrying", "interrupted"})

    def job_info(self, job_id: str) -> dict[str, object] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def schema_version(self) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
        return int(row["value"]) if row else 0

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

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> QueueItem:
        try:
            report = json.loads(row["report_json"]) if row["report_json"] else None
        except (TypeError, ValueError):
            report = None
        return QueueItem(
            job_id=str(row["job_id"]),
            position=int(row["position"]),
            video_path=str(row["video_path"]),
            status=str(row["status"]),
            attempts=int(row["attempts"]),
            error=row["error"],
            report=report if isinstance(report, dict) else None,
            item_id=str(row["item_id"] or ""),
            source_position=int(row["source_position"] if row["source_position"] is not None else row["position"]),
            phase=str(row["phase"] or row["status"]),
            progress=float(row["progress"] or 0.0),
            message=row["message"],
            error_code=row["error_code"],
            suggestion=row["suggestion"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            updated_at=row["updated_at"],
        )

    def snapshot(self, job_id: str) -> list[QueueItem]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM queue_items WHERE job_id = ? ORDER BY source_position, position",
                (job_id,),
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def __enter__(self) -> "PersistentQueueStore":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
