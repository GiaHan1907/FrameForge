"""Queue per-video mẫu cho FrameForge.

Module này dùng một worker queue tuần tự để pause có ngữ nghĩa rõ ràng:
video đang chạy được hoàn tất, còn item kế tiếp mới chờ. Processor là callable
được tiêm vào nên có thể nối với process_one_video/process_videos hiện tại.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable


class QueueStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class QueueCancelled(RuntimeError):
    """Raised internally when the queue is cancelled."""


@dataclass
class ItemState:
    position: int
    video_path: str
    status: str = QueueStatus.QUEUED.value
    fraction: float = 0.0
    message: str = "Đang chờ"
    attempts: int = 0
    error_code: str | None = None
    error: str | None = None
    suggestion: str | None = None
    saved: int = 0
    started_at: float | None = None
    finished_at: float | None = None
    report: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ErrorInfo:
    code: str
    label: str
    retryable: bool
    suggestion: str


ProgressCallback = Callable[[Path, str, float, str], None]
Processor = Callable[[Path, ProgressCallback, threading.Event], dict[str, Any]]


_ERROR_RULES: tuple[tuple[str, tuple[str, ...], str, bool, str], ...] = (
    (
        "access_denied",
        ("login", "sign in", "private", "permission", "403", "access denied"),
        "URL không công khai hoặc bị từ chối truy cập",
        False,
        "Kiểm tra URL có mở công khai và bạn có quyền sử dụng nội dung.",
    ),
    (
        "rate_limited",
        ("429", "too many requests", "rate limit", "temporarily blocked"),
        "Bị giới hạn tần suất",
        True,
        "Chờ một lúc rồi thử lại; tránh gửi quá nhiều URL cùng lúc.",
    ),
    (
        "ffmpeg_missing",
        ("ffmpeg", "ffprobe"),
        "Thiếu hoặc không gọi được FFmpeg",
        False,
        "Cài FFmpeg hoặc đặt ffmpeg/ffprobe trong PATH rồi thử lại.",
    ),
    (
        "format_unavailable",
        ("requested format", "format is not available", "no video formats", "no formats"),
        "Không có format video phù hợp",
        False,
        "Thử chất lượng khác hoặc kiểm tra Reel/video còn công khai.",
    ),
    (
        "network_error",
        ("timeout", "timed out", "connection reset", "temporary failure", "network", "503", "502"),
        "Lỗi mạng tạm thời",
        True,
        "Kiểm tra kết nối mạng; hệ thống sẽ tự thử lại với thời gian chờ tăng dần.",
    ),
    (
        "output_error",
        ("permission denied", "no space", "disk full", "cannot write", "output"),
        "Không ghi được file output",
        False,
        "Kiểm tra quyền ghi, dung lượng đĩa và thư mục output.",
    ),
)


def classify_error(exc: BaseException) -> ErrorInfo:
    """Phân loại lỗi từ yt-dlp/FFmpeg thành mã ổn định cho UI."""
    text = str(exc).lower()
    for code, needles, label, retryable, suggestion in _ERROR_RULES:
        if any(needle in text for needle in needles):
            return ErrorInfo(code, label, retryable, suggestion)
    return ErrorInfo(
        "unknown",
        "Lỗi không xác định",
        True,
        "Mở chi tiết lỗi, kiểm tra URL/FFmpeg/dung lượng rồi thử lại.",
    )


class VideoQueueController:
    """Queue per-video thread-safe, phù hợp lưu trong st.session_state.

    Pause chỉ tác động tại ranh giới item. Cancel có thể ngắt cả lúc queue đang
    pause hoặc đang backoff. Processor không được tự sửa state của controller.
    """

    def __init__(
        self,
        videos: Iterable[Path],
        processor: Processor,
        *,
        max_retries: int = 2,
        base_retry_delay: float = 1.0,
        max_retry_delay: float = 60.0,
        queue_store: Any | None = None,
        run_signature: str = "frameforge-queue-v1",
    ) -> None:
        self._processor = processor
        self._queue_store = queue_store
        self._run_signature = run_signature
        self._queue_job_id: str | None = None
        self.max_retries = max(0, int(max_retries))
        self.base_retry_delay = max(0.0, float(base_retry_delay))
        self.max_retry_delay = max(self.base_retry_delay, float(max_retry_delay))
        self._items = [ItemState(i, str(Path(video))) for i, video in enumerate(videos)]
        self._lock = threading.RLock()
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._global_status = "idle"
        self._last_error: str | None = None

    @property
    def cancel_event(self) -> threading.Event:
        return self._cancel_event

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def is_paused(self) -> bool:
        with self._lock:
            return self._global_status == "paused"

    def start(self) -> None:
        with self._lock:
            if self._running:
                raise RuntimeError("Queue đang chạy hoặc đang pause.")
            if not any(item.status in {QueueStatus.QUEUED.value, QueueStatus.RETRYING.value} for item in self._items):
                raise RuntimeError("Không còn item queued để chạy.")
            self._cancel_event.clear()
            self._pause_event.clear()
            if self._queue_store is not None:
                self._queue_job_id = self._queue_store.open_job(
                    [Path(item.video_path) for item in self._items],
                    self._run_signature,
                    resume=False,
                )
            self._running = True
            self._global_status = "running"
            self._last_error = None
            self._thread = threading.Thread(target=self._run, name="frameforge-per-video-queue", daemon=True)
            self._thread.start()

    def pause(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._pause_event.set()
            self._global_status = "paused"
            for item in self._items:
                if item.status == QueueStatus.QUEUED.value:
                    item.status = QueueStatus.PAUSED.value
                    item.message = "Đang tạm dừng; chờ tiếp tục"

    def resume(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._pause_event.clear()
            self._global_status = "running"
            for item in self._items:
                if item.status == QueueStatus.PAUSED.value:
                    item.status = QueueStatus.QUEUED.value
                    item.message = "Đã tiếp tục"

    def cancel(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._cancel_event.set()
            self._pause_event.clear()
            self._global_status = "cancelling"

    def retry_item(self, position: int) -> None:
        with self._lock:
            if self._running:
                raise RuntimeError("Không thể retry từng item khi queue đang chạy.")
            item = self._items[position]
            if item.status != QueueStatus.FAILED.value:
                raise ValueError("Chỉ item failed mới có thể retry.")
            if not Path(item.video_path).is_file():
                raise FileNotFoundError(item.video_path)
            self._reset_item(item)
        self.start()

    def retry_failed(self) -> int:
        with self._lock:
            if self._running:
                raise RuntimeError("Hãy chờ queue hiện tại kết thúc trước khi retry failed.")
            retried = 0
            for item in self._items:
                if item.status == QueueStatus.FAILED.value and Path(item.video_path).is_file():
                    self._reset_item(item)
                    retried += 1
            if not retried:
                raise RuntimeError("Không còn file nguồn failed để retry.")
        self.start()
        return retried

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            items = [item.to_dict() for item in self._items]
            total = len(items)
            completed = sum(item["status"] == QueueStatus.COMPLETED.value for item in items)
            failed = sum(item["status"] == QueueStatus.FAILED.value for item in items)
            cancelled = sum(item["status"] == QueueStatus.CANCELLED.value for item in items)
            return {
                "status": self._global_status,
                "running": self._running,
                "paused": self._global_status == "paused",
                "total": total,
                "completed": completed,
                "failed": failed,
                "cancelled": cancelled,
                "fraction": completed / total if total else 1.0,
                "last_error": self._last_error,
                "items": items,
            }

    def wait(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _reset_item(self, item: ItemState) -> None:
        item.status = QueueStatus.QUEUED.value
        item.fraction = 0.0
        item.message = "Đang chờ retry"
        item.attempts = 0
        item.error_code = None
        item.error = None
        item.suggestion = None
        item.saved = 0
        item.started_at = None
        item.finished_at = None
        item.report = None

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise QueueCancelled("Đã hủy queue theo yêu cầu người dùng.")

    def _wait_for_resume(self) -> None:
        while self._pause_event.is_set():
            self._check_cancelled()
            time.sleep(0.15)

    def _wait_backoff(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            self._check_cancelled()
            self._wait_for_resume()
            time.sleep(min(0.15, max(0.01, deadline - time.monotonic())))

    def _persist_running(self, position: int, attempt: int) -> None:
        if self._queue_store is not None and self._queue_job_id is not None:
            self._queue_store.mark_running(self._queue_job_id, position, attempt)

    def _progress(self, position: int, video: Path, phase: str, fraction: float, message: str) -> None:
        with self._lock:
            item = self._items[position]
            item.status = phase
            item.fraction = max(0.0, min(1.0, float(fraction)))
            item.message = message
        # Processor có thể được nối trực tiếp với callback engine nếu cần.

    def _run(self) -> None:
        try:
            for position, item in enumerate(self._items):
                with self._lock:
                    if item.status == QueueStatus.COMPLETED.value:
                        continue
                    if item.status in {QueueStatus.CANCELLED.value, QueueStatus.FAILED.value}:
                        continue
                self._wait_for_resume()
                self._check_cancelled()
                video = Path(item.video_path)
                last_exc: BaseException | None = None
                for attempt in range(self.max_retries + 1):
                    self._wait_for_resume()
                    self._check_cancelled()
                    with self._lock:
                        item.status = QueueStatus.RUNNING.value
                        item.attempts = attempt + 1
                        item.started_at = item.started_at or time.time()
                        item.message = f"Đang xử lý lần {attempt + 1}/{self.max_retries + 1}"
                    self._persist_running(position, attempt + 1)
                    try:
                        def callback(_video: Path, phase: str, fraction: float, message: str) -> None:
                            self._progress(position, video, phase, fraction, message)

                        report = self._processor(video, callback, self._cancel_event)
                        with self._lock:
                            item.status = QueueStatus.COMPLETED.value
                            item.fraction = 1.0
                            item.message = "Hoàn tất"
                            item.finished_at = time.time()
                            item.report = report
                            item.saved = int(report.get("saved", 0)) if isinstance(report, dict) else 0
                        if self._queue_store is not None and self._queue_job_id is not None:
                            self._queue_store.mark_completed(self._queue_job_id, position, report)
                        break
                    except QueueCancelled:
                        raise
                    except Exception as exc:  # noqa: BLE001 - boundary của từng video
                        last_exc = exc
                        info = classify_error(exc)
                        with self._lock:
                            item.error_code = info.code
                            item.error = str(exc)
                            item.suggestion = info.suggestion
                        if self._queue_store is not None and self._queue_job_id is not None:
                            if info.retryable and attempt < self.max_retries:
                                self._queue_store.mark_retrying(self._queue_job_id, position, attempt + 1, str(exc))
                        if not info.retryable or attempt >= self.max_retries:
                            with self._lock:
                                item.status = QueueStatus.FAILED.value
                                item.message = info.label
                                item.finished_at = time.time()
                            if self._queue_store is not None and self._queue_job_id is not None:
                                self._queue_store.mark_failed(
                                    self._queue_job_id,
                                    position,
                                    attempt + 1,
                                    str(exc),
                                    item.to_dict(),
                                )
                            break
                        delay = min(self.max_retry_delay, self.base_retry_delay * (2**attempt))
                        with self._lock:
                            item.status = QueueStatus.RETRYING.value
                            item.message = f"{info.label}; retry sau {delay:g}s"
                        self._wait_backoff(delay)
                else:
                    if last_exc is not None:
                        raise last_exc
        except QueueCancelled as exc:
            with self._lock:
                self._last_error = str(exc)
                for item in self._items:
                    if item.status in {QueueStatus.QUEUED.value, QueueStatus.PAUSED.value, QueueStatus.RETRYING.value, QueueStatus.RUNNING.value}:
                        item.status = QueueStatus.CANCELLED.value
                        item.message = "Đã hủy"
            if self._queue_store is not None and self._queue_job_id is not None:
                if self._cancel_event.is_set():
                    self._queue_store.mark_cancelled(self._queue_job_id)
                else:
                    self._queue_store.mark_completed_job(self._queue_job_id)
        finally:
            if self._queue_store is not None and self._queue_job_id is not None:
                if self._cancel_event.is_set():
                    self._queue_store.mark_cancelled(self._queue_job_id)
                else:
                    self._queue_store.mark_completed_job(self._queue_job_id)
            with self._lock:
                self._running = False
                if self._cancel_event.is_set():
                    self._global_status = "cancelled"
                elif any(item.status == QueueStatus.FAILED.value for item in self._items):
                    self._global_status = "completed_with_errors"
                else:
                    self._global_status = "completed"


def render_queue_per_video(controller: VideoQueueController, *, key_prefix: str = "frameforge_queue") -> None:
    """Renderer Streamlit cho queue; gọi trong fragment 1 giây/lần."""
    import streamlit as st

    state = controller.snapshot()
    st.markdown("#### Queue theo video")
    summary_cols = st.columns(4)
    summary_cols[0].metric("Tổng", state["total"])
    summary_cols[1].metric("Hoàn tất", state["completed"])
    summary_cols[2].metric("Lỗi", state["failed"])
    summary_cols[3].metric("Trạng thái", state["status"])
    if state.get("pause_note"):
        st.caption(str(state["pause_note"]))

    action_cols = st.columns(4)
    with action_cols[0]:
        if state["running"] and not state["paused"]:
            if st.button("Tạm dừng", key=f"{key_prefix}_pause", use_container_width=True):
                controller.pause()
                st.rerun()
        elif state["running"] and state["paused"]:
            if st.button("Tiếp tục", key=f"{key_prefix}_resume", type="primary", use_container_width=True):
                controller.resume()
                st.rerun()
    with action_cols[1]:
        if state["running"] and st.button("Hủy xử lý", key=f"{key_prefix}_cancel", use_container_width=True):
            controller.cancel()
            st.warning("Đang hủy an toàn sau checkpoint gần nhất...")
    with action_cols[2]:
        if not state["running"] and state["failed"]:
            if st.button("Thử lại mục thất bại", key=f"{key_prefix}_retry_failed", type="primary", use_container_width=True):
                controller.retry_failed()
                st.rerun()
    with action_cols[3]:
        filter_value = st.selectbox(
            "Lọc",
            ["Tất cả", "Đang chờ", "Đang chạy", "Hoàn tất", "Thất bại", "Đã hủy"],
            key=f"{key_prefix}_filter",
            label_visibility="collapsed",
        )

    status_labels = {
        "queued": "đang chờ",
        "running": "đang chạy",
        "retrying": "đang retry",
        "paused": "tạm dừng",
        "completed": "hoàn tất",
        "failed": "thất bại",
        "cancelled": "đã hủy",
    }
    filter_map = {
        "Tất cả": None,
        "Đang chờ": {"queued", "retrying"},
        "Đang chạy": {"running", "paused"},
        "Hoàn tất": {"completed"},
        "Thất bại": {"failed"},
        "Đã hủy": {"cancelled"},
    }
    allowed = filter_map[filter_value]
    for item in state["items"]:
        if allowed is not None and item["status"] not in allowed:
            continue
        with st.container(border=True):
            name = Path(item["video_path"]).name
            status_label = status_labels.get(str(item["status"]), str(item["status"]))
            st.markdown(f"**{item['position'] + 1}. {name}** · `{status_label}`")
            st.progress(item["fraction"], text=f"{item['fraction']:.0%} · {item['message']}")
            fps_label = f"{float(item['fps']):.1f} FPS" if item.get("fps") else "FPS —"
            eta_value = item.get("eta")
            eta_label = f"ETA {int(round(float(eta_value)))}s" if eta_value is not None else "ETA —"
            rss_value = int(item.get("rss", 0) or 0)
            ram_label = f"RAM {rss_value / (1024 * 1024):.0f} MB" if rss_value else "RAM —"
            meta_cols = st.columns([1.0, 1.0, 1.0, 1.0, 1.8])
            meta_cols[0].caption(f"Lần thử: {item['attempts']}")
            meta_cols[1].caption(f"Đã lưu: {item['saved']} ảnh")
            meta_cols[2].caption(fps_label)
            meta_cols[3].caption(eta_label)
            meta_cols[4].caption(ram_label if item["status"] != "failed" else f"Mã lỗi: {item['error_code'] or 'unknown'}")
            if item["status"] == "failed":
                st.error(item["error"] or "Lỗi không xác định")
                if item["suggestion"]:
                    st.info(item["suggestion"])
                if not state["running"] and st.button("Retry item này", key=f"{key_prefix}_retry_{item['position']}"):
                    controller.retry_item(int(item["position"]))
                    st.rerun()


# Ví dụ tích hợp vào FrameForge hiện tại:
#
# def frameforge_processor(video, on_progress, cancel_event):
#     return process_one_video(
#         video,
#         output_root,
#         source_root,
#         runtime_args,
#         on_progress,
#         cancel_event,
#     )
#
# if "frameforge_queue_controller" not in st.session_state:
#     st.session_state["frameforge_queue_controller"] = VideoQueueController(
#         input_paths,
#         frameforge_processor,
#         max_retries=int(args.retries),
#         base_retry_delay=float(args.retry_delay),
#     )
# controller = st.session_state["frameforge_queue_controller"]
# if st.button("Bắt đầu xử lý", disabled=controller.is_running):
#     controller.start()
#
# @st.fragment(run_every=1.0)
# def render_live_queue():
#     render_queue_per_video(controller)
# render_live_queue()
