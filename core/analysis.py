"""Pure cv2/numpy analysis functions for frame evaluation and scene detection.

These functions have no file I/O or Streamlit dependencies — they operate
on numpy arrays returned by OpenCV.  They are independently testable with
synthetic data (no real video file needed).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from core.cv2_helpers import dhash, laplacian_variance, motion_blur_score

# ---------------------------------------------------------------------------
# Constants (duplicated from core.pipeline to avoid circular imports)
# ---------------------------------------------------------------------------
REFERENCE_ANALYSIS_WIDTH: int = 640

CROP_RATIO_VALUES: dict[str, float] = {
    "16:9": 16 / 9,
    "9:16": 9 / 16,
    "4:5": 4 / 5,
    "1:1": 1.0,
}


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------
@dataclass
class FrameCandidate:
    """Aggregated per-frame metrics used for best-frame selection."""

    frame: np.ndarray = field(repr=False)
    timestamp: float = 0.0
    sharpness: float = 0.0
    motion_blur_score: float = 0.0
    hash_value: int = 0
    brightness: float = 0.0
    gray: np.ndarray = field(default_factory=lambda: np.empty((0, 0), dtype=np.uint8), repr=False)
    histogram: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=np.float32), repr=False)


# ---------------------------------------------------------------------------
# Video probing
# ---------------------------------------------------------------------------
def probe_video(video: Path) -> dict[str, float | int]:
    """Open a video with OpenCV and return basic metadata.

    Raises ``RuntimeError`` if the video cannot be opened or has no valid
    duration.
    """
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV không mở được video: {video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    capture.release()
    if not math.isfinite(fps) or fps <= 0:
        fps = 30.0
    duration = frame_count / fps if frame_count > 0 else 0.0
    if duration <= 0:
        raise RuntimeError("Video không có thời lượng hợp lệ.")
    return {
        "fps": fps,
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "duration": duration,
    }


# ---------------------------------------------------------------------------
# Resize helpers
# ---------------------------------------------------------------------------
def resized_for_analysis(frame: np.ndarray, analysis_width: int) -> np.ndarray:
    """Resize *frame* so that its width is at most *analysis_width*."""
    height, width = frame.shape[:2]
    target_width = min(width, analysis_width)
    if target_width == width:
        return frame
    target_height = max(1, round(height * target_width / width))
    return cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)


def resize_for_analysis(frame: np.ndarray, analysis_width: int) -> np.ndarray:
    """Resize and convert to grayscale — convenience for scene-detection."""
    return cv2.cvtColor(resized_for_analysis(frame, analysis_width), cv2.COLOR_BGR2GRAY)


# ---------------------------------------------------------------------------
# Histogram
# ---------------------------------------------------------------------------
def color_histogram(frame: np.ndarray, analysis_width: int) -> np.ndarray:
    """Compute a compact HSV colour histogram for perceptual comparison."""
    small = resized_for_analysis(frame, analysis_width)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    histogram = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256])
    histogram = cv2.normalize(histogram, histogram).flatten()
    return histogram.astype(np.float32)


# ---------------------------------------------------------------------------
# Frame candidate construction
# ---------------------------------------------------------------------------
def frame_candidate(
    frame: np.ndarray,
    timestamp: float,
    analysis_width: int,
    requirements: "MetricRequirements | None" = None,
) -> FrameCandidate:
    """Build a :class:`FrameCandidate` with the requested quality metrics.

    *requirements* controls which metrics are computed; ``None`` means
    compute all of them.
    """
    from core.pipeline import MetricRequirements  # lazy to avoid circular

    requirements = requirements or MetricRequirements(True, True, True, True)
    small = resized_for_analysis(frame, analysis_width)
    need_gray = (
        requirements.need_sharpness
        or requirements.need_motion_blur
        or requirements.need_hash
        or requirements.need_histogram
    )
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if need_gray else np.empty((0, 0), dtype=np.uint8)
    raw_sharpness = laplacian_variance(gray) if requirements.need_sharpness else 0.0
    blur_score = motion_blur_score(gray) if requirements.need_motion_blur else 0.0
    histogram = np.empty((0,), dtype=np.float32)
    if requirements.need_histogram:
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        histogram = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256])
        histogram = cv2.normalize(histogram, histogram).flatten().astype(np.float32)
    width_scale = (REFERENCE_ANALYSIS_WIDTH / max(gray.shape[1], 1)) ** 2 if need_gray else 1.0
    normalized_sharpness = raw_sharpness * width_scale
    return FrameCandidate(
        frame=frame.copy(),
        timestamp=timestamp,
        sharpness=normalized_sharpness,
        motion_blur_score=blur_score,
        hash_value=dhash(gray) if requirements.need_hash else 0,
        brightness=float(np.mean(gray)) / 255.0 if need_gray else 0.0,
        gray=gray,
        histogram=histogram,
    )


# ---------------------------------------------------------------------------
# Scene-detection difference metrics
# ---------------------------------------------------------------------------
def normalized_difference(left: np.ndarray, right: np.ndarray) -> float:
    """Mean absolute pixel difference normalised to [0, 1]."""
    return float(np.mean(cv2.absdiff(left, right))) / 255.0


def histogram_difference(left: np.ndarray, right: np.ndarray) -> float:
    """Histogram correlation distance mapped to [0, 1].

    Correlation is robust to small illumination changes.
    """
    correlation = float(cv2.compareHist(left, right, cv2.HISTCMP_CORREL))
    return min(1.0, max(0.0, (1.0 - correlation) / 2.0))


def smart_scene_difference(
    gray: np.ndarray,
    histogram: np.ndarray,
    previous_gray: np.ndarray | None,
    previous_histogram: np.ndarray | None,
) -> float:
    """Weighted combination of pixel and histogram differences."""
    if previous_gray is None or previous_histogram is None:
        return 0.0
    pixel_difference = normalized_difference(gray, previous_gray)
    color_difference = histogram_difference(histogram, previous_histogram)
    return 0.70 * pixel_difference + 0.30 * color_difference


# ---------------------------------------------------------------------------
# Frame comparison
# ---------------------------------------------------------------------------
def better_frame(
    current: FrameCandidate | None,
    candidate: FrameCandidate,
    choose_best: bool = True,
    motion_threshold: float = 0.0,
) -> FrameCandidate:
    """Select the better frame between *current* and *candidate*."""
    if current is None:
        return candidate
    if motion_threshold > 0:
        candidate_ok = candidate.motion_blur_score <= motion_threshold
        current_ok = current.motion_blur_score <= motion_threshold
        if candidate_ok and not current_ok:
            return candidate
        if not candidate_ok and current_ok:
            return current
    if not choose_best:
        return current
    if candidate.sharpness > current.sharpness:
        return candidate
    return current


# ---------------------------------------------------------------------------
# Crop
# ---------------------------------------------------------------------------
def crop_to_aspect_ratio(
    frame: np.ndarray,
    crop_ratio: str | None,
) -> np.ndarray:
    """Centre-crop *frame* to the target aspect ratio.

    Returns the original frame if *crop_ratio* is ``None``, empty, or
    ``"Khong crop"``.
    """
    if crop_ratio is None or str(crop_ratio).strip() in ("", "none", "Khong crop", "Không crop"):
        return frame
    target_ratio = CROP_RATIO_VALUES.get(str(crop_ratio))
    if target_ratio is None:
        raise ValueError(f"Tỉ lệ crop không hợp lệ: {crop_ratio}")
    height, width = frame.shape[:2]
    if height <= 0 or width <= 0:
        return frame
    current_ratio = width / height
    if abs(current_ratio - target_ratio) < 1e-6:
        return frame
    if current_ratio > target_ratio:
        cropped_width = max(1, min(width, round(height * target_ratio)))
        left = max(0, (width - cropped_width) // 2)
        return frame[:, left : left + cropped_width]
    cropped_height = max(1, min(height, round(width / target_ratio)))
    top = max(0, (height - cropped_height) // 2)
    return frame[top : top + cropped_height, :]
