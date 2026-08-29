"""cv2-dependent preview functions extracted from streamlit_app.py.

These functions handle video frame extraction and preview rendering.
They require cv2/numpy but have no Streamlit (st.) dependencies.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import cv2
import numpy as np

from core.pipeline import CROP_RATIO_VALUES


def preview_video_duration(source: object) -> float | None:
    """Extract video duration in seconds from a file or uploaded file object."""
    temporary_path: Path | None = None
    try:
        if hasattr(source, "getvalue"):
            temporary = tempfile.NamedTemporaryFile(
                prefix="frameforge_duration_", suffix=".mp4", delete=False
            )
            temporary.write(source.getvalue())
            temporary.close()
            temporary_path = Path(temporary.name)
            video_path = temporary_path
        else:
            video_path = Path(str(source))
        capture = cv2.VideoCapture(str(video_path))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        capture.release()
        if fps > 0 and frames > 0:
            return frames / fps
    except (OSError, TypeError, ValueError):
        return None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return None


def quick_scene_preview(
    source: object,
    threshold: float,
    start: float,
    end: float | None,
    analysis_fps: float,
    maximum: int = 32,
) -> list[float]:
    """Detect scene change markers using lightweight frame differencing."""
    temporary_path: Path | None = None
    if isinstance(source, Path):
        video_path = source
    else:
        data = source.getvalue() if hasattr(source, "getvalue") else b""
        with tempfile.NamedTemporaryFile(
            prefix="frameforge_preview_", suffix=".mp4", delete=False
        ) as handle:
            handle.write(data)
            temporary_path = Path(handle.name)
        video_path = temporary_path
    capture = cv2.VideoCapture(str(video_path))
    try:
        fps = max(float(capture.get(cv2.CAP_PROP_FPS) or analysis_fps or 4.0), 1.0)
        duration = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0) / fps
        actual_end = duration if end is None else min(float(end), duration)
        interval = 1.0 / max(float(analysis_fps), 1.0)
        next_sample = max(0.0, float(start))
        previous: np.ndarray | None = None
        markers: list[float] = []
        while next_sample <= actual_end and len(markers) < maximum:
            capture.set(cv2.CAP_PROP_POS_MSEC, next_sample * 1000.0)
            ok, frame = capture.read()
            if not ok:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
            if previous is not None:
                difference = float(np.mean(cv2.absdiff(previous, gray))) / 255.0
                if difference >= float(threshold):
                    markers.append(round(next_sample, 3))
            previous = gray
            next_sample += interval
        return markers
    finally:
        capture.release()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def preview_crop_overlay(source: object, crop_ratio: str) -> bytes | None:
    """Extract first frame and overlay crop region for UI preview."""
    temporary_path: Path | None = None
    try:
        if hasattr(source, "getvalue"):
            temporary = tempfile.NamedTemporaryFile(
                prefix="frameforge_preview_", suffix=".mp4", delete=False
            )
            temporary.write(source.getvalue())
            temporary.close()
            temporary_path = Path(temporary.name)
            video_path = temporary_path
        else:
            video_path = Path(str(source))
        capture = cv2.VideoCapture(str(video_path))
        ok, frame = capture.read()
        capture.release()
        if not ok or frame is None:
            return None
        target_ratio = CROP_RATIO_VALUES.get(str(crop_ratio))
        if target_ratio is None:
            target_ratio = frame.shape[1] / max(frame.shape[0], 1)
        height, width = frame.shape[:2]
        current_ratio = width / max(height, 1)
        if current_ratio > target_ratio:
            kept_width = max(1, min(width, round(height * target_ratio)))
            left = max(0, (width - kept_width) // 2)
            top, right, bottom = 0, left + kept_width, height
        else:
            kept_height = max(1, min(height, round(width / target_ratio)))
            top = max(0, (height - kept_height) // 2)
            left, right, bottom = 0, width, top + kept_height
        original = frame.copy()
        shaded = cv2.addWeighted(frame, 0.38, np.zeros_like(frame), 0.62, 0)
        shaded[top:bottom, left:right] = original[top:bottom, left:right]
        cv2.rectangle(
            shaded, (left, top), (max(left + 1, right - 1), max(top + 1, bottom - 1)),
            (91, 214, 164), 4,
        )
        cv2.putText(
            shaded, str(crop_ratio),
            (max(12, left + 12), max(28, top + 28)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (91, 214, 164), 2, cv2.LINE_AA,
        )
        preview = cv2.resize(
            shaded,
            (min(720, width), max(1, round(height * min(720, width) / width))),
            interpolation=cv2.INTER_AREA,
        )
        success, encoded = cv2.imencode(".png", preview)
        return encoded.tobytes() if success else None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def preview_frame_at(
    source: object, timestamp: float, crop_ratio: str = "Kh\u00f4ng crop"
) -> bytes | None:
    """Read a single frame at timestamp and apply crop ratio."""
    temporary_path: Path | None = None
    try:
        if hasattr(source, "getvalue"):
            with tempfile.NamedTemporaryFile(
                prefix="frameforge_gallery_", suffix=".mp4", delete=False
            ) as handle:
                handle.write(source.getvalue())
                temporary_path = Path(handle.name)
            video_path = temporary_path
        else:
            video_path = Path(str(source))
        capture = cv2.VideoCapture(str(video_path))
        capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(timestamp)) * 1000.0)
        ok, frame = capture.read()
        capture.release()
        if not ok or frame is None:
            return None
        target_ratio = CROP_RATIO_VALUES.get(str(crop_ratio))
        if target_ratio is not None:
            height, width = frame.shape[:2]
            if width / max(height, 1) > target_ratio:
                kept_width = max(1, min(width, round(height * target_ratio)))
                left = max(0, (width - kept_width) // 2)
                frame = frame[:, left : left + kept_width]
            else:
                kept_height = max(1, min(height, round(width / target_ratio)))
                top = max(0, (height - kept_height) // 2)
                frame = frame[top : top + kept_height, :]
        frame = cv2.resize(
            frame,
            (min(720, frame.shape[1]), max(1, round(frame.shape[0] * min(720, frame.shape[1]) / frame.shape[1]))),
            interpolation=cv2.INTER_AREA,
        )
        success, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        return encoded.tobytes() if success else None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
