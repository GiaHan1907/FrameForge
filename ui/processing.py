"""Processing lifecycle functions extracted from streamlit_app.py.

These functions manage the background processing job (start, poll, complete)
and accept a ``session: dict`` parameter (the Streamlit ``st.session_state``
dict) instead of reading globals directly.  This makes them testable without
a Streamlit runtime.

``_render_processing_job`` stays in ``streamlit_app.py`` because it is
heavily coupled to Streamlit widgets and the ``@st.fragment`` decorator.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from core.config import FrameForgeConfig
from core.pipeline import (
    InsufficientDiskSpace,
    ProcessingCancelled,
    current_process_rss_bytes,
)
from core.resources import InsufficientResources
from ui.desktop import finish_processing_job
from ui.logic import append_job_history, parse_progress_units


def start_processing_job(
    session: dict[str, Any],
    args: FrameForgeConfig,
    input_paths: list[Path],
    output_dir: Path,
    work_dir: Path,
) -> None:
    """Create a background processing job and store it in *session*.

    Parameters
    ----------
    session:
        Mutable dict (typically ``st.session_state``).  The job is stored
        under key ``"processing_job"``.
    args:
        FrameForgeConfig for this processing run.
    input_paths:
        List of video files to process.
    output_dir:
        Where to write screenshots and reports.
    work_dir:
        Temporary work directory (cleaned up after processing).
    """
    # Lazy import to avoid pulling in cv2 at module load time.
    from video_screenshot_advanced import process_videos

    args.queue_db = Path(
        str(getattr(args, "queue_db", "") or output_dir / ".frameforge_queue.sqlite3")
    )
    cancel_event = threading.Event()
    pause_event = threading.Event()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="frameforge-ui")
    progress_state = {
        str(path): {
            "phase": "queued",
            "fraction": 0.0,
            "message": "Đang xếp hàng",
            "started_at": time.monotonic(),
            "units_done": 0,
            "units_total": 0,
            "rss_bytes": current_process_rss_bytes(),
        }
        for path in input_paths
    }
    completed = {"count": 0}

    def on_progress(video: Path, phase: str, fraction: float, message: str) -> None:
        key = str(video)
        state = progress_state.setdefault(
            key,
            {"started_at": time.monotonic(), "units_done": 0, "units_total": 0},
        )
        state.update(
            {
                "phase": phase,
                "fraction": fraction,
                "message": message,
                "rss_bytes": current_process_rss_bytes(),
            }
        )
        units = parse_progress_units(message)
        if units is not None:
            state["units_done"], state["units_total"] = units

    def on_complete(video: Path, report: dict[str, object]) -> None:
        completed["count"] += 1
        if "error" not in report:
            try:
                input_root = work_dir.resolve() / "input"
                resolved_video = video.resolve()
                if resolved_video.is_relative_to(input_root):
                    resolved_video.unlink(missing_ok=True)
            except OSError:
                pass
        state = progress_state.setdefault(
            str(video), {"started_at": time.monotonic()}
        )
        state.update(
            {
                "phase": "completed" if "error" not in report else "error",
                "fraction": 1.0,
                "message": (
                    f"Đã hoàn tất · lưu {report.get('saved', 0)} ảnh"
                    if "error" not in report
                    else str(report.get("error"))
                ),
                "rss_bytes": current_process_rss_bytes(),
                "attempts": int(report.get("attempts", 1) or 1),
                "saved": int(report.get("saved", 0) or 0),
            }
        )
        if report.get("requested") is not None:
            state["units_done"] = int(report.get("requested", 0) or 0)
            state["units_total"] = int(report.get("requested", 0) or 0)

    future = executor.submit(
        process_videos,
        input_paths,
        output_dir,
        None,
        args,
        on_complete,
        on_progress,
        cancel_event,
        args.retries,
        args.retry_delay,
        pause_event,
    )
    job: dict[str, Any] = {
        "status": "running",
        "future": future,
        "executor": executor,
        "cancel_event": cancel_event,
        "pause_event": pause_event,
        "progress": progress_state,
        "completed": completed,
        "input_paths": input_paths,
        "output_dir": output_dir,
        "work_dir": work_dir,
        "args": args,
        "reports": None,
        "error": None,
        "cleaned": False,
    }
    session["processing_job"] = job
    shutdown_state = session.get("_frameforge_shutdown_state")
    if isinstance(shutdown_state, dict):
        shutdown_state["job"] = job


def poll_processing_job(session: dict[str, Any]) -> dict[str, Any] | None:
    """Check if the background job is done and update *session* accordingly.

    Returns the job dict (or ``None`` if no active job).
    """
    job = session.get("processing_job")
    if not isinstance(job, dict) or job.get("status") not in {"running", "paused"}:
        return job if isinstance(job, dict) else None

    future = job.get("future")
    if future is None or not future.done():
        return job

    try:
        reports = future.result()
        output_dir = Path(str(job["output_dir"]))
        report_path = output_dir / "report.json"
        report_path.write_text(
            json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        job["reports"] = reports
        job["report_path"] = report_path
        job["status"] = "completed"
        job["message"] = "Đã xử lý xong queue."
        append_job_history(job)
    except ProcessingCancelled as exc:
        job["status"] = "cancelled"
        job["error"] = str(exc)
        job["message"] = (
            "Đã hủy xử lý; checkpoint và các screenshot đã ghi trước đó "
            "vẫn được giữ lại để tiếp tục."
        )
    except (InsufficientDiskSpace, InsufficientResources) as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        job["message"] = str(exc)
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        job["message"] = f"Không thể xử lý queue: {exc}"

    has_failures = any(
        isinstance(item, dict) and "error" in item
        for item in (job.get("reports") or [])
    )
    finish_processing_job(
        job,
        keep_work_dir=str(job.get("status")) == "cancelled" or has_failures,
    )
    return job
