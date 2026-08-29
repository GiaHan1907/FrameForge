"""Desktop lifecycle management for FrameForge.

Functions for process tree termination, shutdown coordination, and
session watchdog.  These are used by the desktop launcher to ensure
clean shutdown when the browser tab is closed.
"""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path


def terminate_desktop_process_tree() -> None:
    """Kill the current desktop process and all children on Windows."""
    if sys.platform != "win32":
        return
    expected_pid = os.environ.get("FRAMEFORGE_DESKTOP_PID", "")
    if expected_pid and expected_pid != str(os.getpid()):
        return
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        subprocess.Popen(
            ["taskkill.exe", "/PID", str(os.getpid()), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def finish_processing_job(
    job: dict[str, object], keep_work_dir: bool = False, wait: bool = False
) -> None:
    """Clean up a processing job's work directory and executor."""
    if job.get("cleaned") and not keep_work_dir:
        return
    work_dir = Path(str(job["work_dir"]))
    if not keep_work_dir:
        shutil.rmtree(work_dir, ignore_errors=True)
        job["cleaned"] = True
    else:
        job["resumable"] = work_dir.exists()
    executor = job.get("executor")
    if executor is not None:
        executor.shutdown(wait=wait, cancel_futures=True)
        job["executor"] = None


def shutdown_processing_job(job: dict[str, object]) -> None:
    """Cancel background job and clean up when desktop session closes."""
    cancel_event = job.get("cancel_event")
    if cancel_event is not None:
        cancel_event.set()
    future = job.get("future")
    if future is not None and not future.done():
        try:
            future.result(timeout=45.0)
        except Exception:
            pass
    finish_processing_job(job, keep_work_dir=False, wait=True)


def desktop_session_watchdog(session_id: str, state: dict[str, object]) -> None:
    """Stop packaged Streamlit when no browser session is active."""
    try:
        from streamlit.runtime import get_instance

        runtime = get_instance()
    except Exception:
        return
    was_active = False
    while True:
        try:
            active = runtime.is_active_session(session_id)
        except Exception:
            return
        if active:
            was_active = True
        elif was_active:
            time.sleep(3.0)
            try:
                if runtime.is_active_session(session_id):
                    continue
            except Exception:
                return
            state["shutdown_requested"] = True
            job = state.get("job")
            if isinstance(job, dict):
                shutdown_processing_job(job)
            try:
                runtime.stop()
            except Exception:
                pass
            threading.Thread(
                target=terminate_desktop_process_tree,
                name="frameforge-process-tree-terminator",
                daemon=True,
            ).start()
            return
        time.sleep(2.0)
