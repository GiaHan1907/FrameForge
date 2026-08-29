"""Pure cv2/numpy helper functions for image analysis.

These functions perform frame quality analysis (sharpness, motion blur,
perceptual hashing) and have no file I/O or Streamlit dependencies.
"""

from __future__ import annotations

import math

import cv2
import numpy as np


def laplacian_variance(gray: np.ndarray) -> float:
    """Compute Laplacian variance as a sharpness metric."""
    if min(gray.shape) < 3:
        return 0.0
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def motion_blur_score(gray: np.ndarray) -> float:
    """Estimate motion blur in [0, 1]; higher means more motion blur risk.

    Motion blur typically concentrates gradient energy in one direction
    and suppresses high-frequency detail.  This is a fast heuristic for
    frame filtering, not an absolute motion velocity estimator.
    """
    if min(gray.shape) < 8:
        return 0.0
    gray_float = gray.astype(np.float32) / 255.0
    grad_x = cv2.Scharr(gray_float, cv2.CV_32F, 1, 0)
    grad_y = cv2.Scharr(gray_float, cv2.CV_32F, 0, 1)
    energy_x = float(np.mean(np.abs(grad_x)))
    energy_y = float(np.mean(np.abs(grad_y)))
    directional_imbalance = abs(energy_x - energy_y) / (energy_x + energy_y + 1e-6)

    grad_energy = float(np.mean(np.sqrt(grad_x * grad_x + grad_y * grad_y)))
    lap_energy = float(np.var(cv2.Laplacian(gray_float, cv2.CV_32F)))
    detail_ratio = math.sqrt(max(lap_energy, 0.0)) / (
        math.sqrt(max(lap_energy, 0.0)) + grad_energy + 1e-6
    )
    detail_deficit = 1.0 - min(1.0, detail_ratio * 3.0)

    score = 0.62 * directional_imbalance + 0.38 * detail_deficit
    return float(min(1.0, max(0.0, score)))


def dhash(gray: np.ndarray) -> int:
    """Compute a 64-bit difference hash for perceptual deduplication."""
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    differences = small[:, 1:] > small[:, :-1]
    hash_value = 0
    for bit in differences.flatten():
        hash_value = (hash_value << 1) | int(bool(bit))
    return hash_value


def hamming_distance(left: int, right: int) -> int:
    """Compute Hamming distance between two hash values."""
    return (left ^ right).bit_count()
