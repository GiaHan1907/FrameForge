"""Queue UI adapter and render functions.

Provides _ProcessingQueueAdapter for queue visualization and
render_resource_meter / render_queue_dashboard for status display.
"""

from __future__ import annotations

import streamlit as st

from core.pipeline import progress_telemetry, timestamp_label, current_process_rss_bytes
from core.utils import format_bytes
from core.resources import available_ram_gb
from core.errors import classify_error
from ui.logic import format_eta


class ProcessingQueueAdapter:
    """Adapter to use the per-video queue renderer with the current processing job."""

    def __init__(self, job: dict[str, object]) -> None:
        self.job = job

    def snapshot(self) -> dict[str, object]:
        status = str(self.job.get("status", "running"))
        paused = status == "paused"
        progress = self.job.get("progress") or {}
        reports = self.job.get("reports") or []
        input_paths = list(self.job.get("input_paths", []))
        items: list[dict[str, object]] = []
        for position, path in enumerate(input_paths):
            state = progress.get(str(path), {})
            report = (
                reports[position]
                if position < len(reports) and isinstance(reports[position], dict)
                else {}
            )
            phase = str(state.get("phase", "queued"))
            fraction = float(state.get("fraction", 0.0) or 0.0)
            if "error" in report or phase in {"error", "failed"}:
                item_status = "failed"
            elif fraction >= 1.0 or phase == "completed":
                item_status = "completed"
            elif phase == "retrying":
                item_status = "retrying"
            elif phase == "queued":
                item_status = "paused" if paused else "queued"
            else:
                item_status = "running"
            telemetry = progress_telemetry(state)
            error_info = (
                classify_error(RuntimeError(str(report.get("error", ""))))
                if report.get("error")
                else None
            )
            items.append({
                "position": position,
                "video_path": str(path),
                "status": item_status,
                "fraction": max(0.0, min(1.0, fraction)),
                "message": str(state.get("message", "\u0110ang ch\u1edd")),
                "attempts": int(
                    state.get("attempts", report.get("attempts", 0)) or 0
                ),
                "error_code": report.get("error_code") or (
                    error_info.code if error_info else None
                ),
                "error": report.get("error"),
                "suggestion": report.get("suggestion") or (
                    error_info.suggestion if error_info else None
                ),
                "saved": int(state.get("saved", report.get("saved", 0)) or 0),
                "fps": telemetry["fps"],
                "eta": telemetry["eta"],
                "rss": telemetry["rss"],
            })
        return {
            "status": status,
            "running": status in {"running", "paused"},
            "paused": paused,
            "total": len(items),
            "completed": sum(1 for i in items if i["status"] == "completed"),
            "failed": sum(1 for i in items if i["status"] == "failed"),
            "items": items,
        }

    def _pause_note(self) -> str:
        return (
            "T\u1ea1m d\u1eebng — video hi\u1ec7n t\u1ea1i ho\u00e0n t\u1eaft r\u1ed3i "
            "s\u1ebd ch\u1edd ti\u1ebfp t\u1ee5c."
        )

    def pause(self) -> None:
        pause_event = self.job.get("pause_event")
        if pause_event is not None:
            pause_event.set()
        self.job["status"] = "paused"
        self.job["message"] = self._pause_note()

    def resume(self) -> None:
        pause_event = self.job.get("pause_event")
        if pause_event is not None:
            pause_event.clear()
        self.job["status"] = "running"
        self.job["message"] = "\u0110\u00e3 ti\u1ebfp t\u1ee5c queue."

    def cancel(self) -> None:
        cancel_event = self.job.get("cancel_event")
        if cancel_event is not None:
            cancel_event.set()
        self.job["status"] = "cancelling"
        self.job["message"] = "\u0110ang h\u1ee7y..."

    def retry_failed(self, positions: set[int] | None = None) -> int:
        from ui.logic import _pause_processing_job  # noqa: avoid circular

        reports = self.job.get("reports") or []
        failed: list[int] = []
        for pos, report in enumerate(reports):
            if positions is not None and pos not in positions:
                continue
            if isinstance(report, dict) and "error" in report:
                failed.append(pos)
        if not failed:
            return 0
        # Delegate to the main app's retry function via the job dict
        self.job["_retry_positions"] = set(failed)
        return len(failed)

    def retry_item(self, position: int) -> None:
        self.retry_failed({position})
