"""Typed configuration for FrameForge processing pipeline.

Replaces the untyped ``SimpleNamespace`` / ``argparse.Namespace`` that was
previously passed around as ``args``.  Every field has a sensible default so
that callers can construct an instance with only the fields they care about.

The dataclass is a **drop-in replacement** for ``SimpleNamespace``:

* ``vars(cfg)`` works (returns ``__dict__``).
* ``copy.copy(cfg)`` works.
* ``getattr(cfg, "field", default)`` works — but now typos raise
  ``AttributeError`` instead of silently falling back to the default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FrameForgeConfig:
    """All processing parameters for a FrameForge run."""

    # ── Time range / extraction mode ──────────────────────────────────
    start: float = 0.0
    end: float | None = None
    every: float | None = None
    count: int | None = None
    max_screenshots: int = 20

    # ── Target count after filtering ──────────────────────────────────
    target_count_after_filter: bool = True
    target_candidate_multiplier: int = 3
    target_candidate_multiplier_max: int = 5

    # ── Manifest ──────────────────────────────────────────────────────
    repair_manifest: bool = False

    # ── Resource guards ───────────────────────────────────────────────
    min_free_ram_gb: float = 0.0

    # ── Scene detection ───────────────────────────────────────────────
    scene_detection: bool = False
    best_frame_per_scene: bool = False
    scene_threshold: float = 0.30
    min_scene_gap: float = 0.5
    flash_return_ratio: float = 0.55
    flash_brightness_threshold: float = 0.18
    scene_confirmations: int = 2
    analysis_width: int = 640
    analysis_fps: float = 8.0

    # ── Workers ───────────────────────────────────────────────────────
    workers: int | str = 1
    extract_workers: int = 0
    extract_min_targets: int = 8
    video_workers: int | None = None          # set at runtime

    # ── Quality filters ───────────────────────────────────────────────
    min_sharpness: float = 100.0
    motion_blur_threshold: float = 0.30
    duplicate_threshold: int = 6

    # ── Output format ─────────────────────────────────────────────────
    format: str = "jpg"
    quality: int = 95
    crop_ratio: str = "Không crop"
    encode_profile: str = "Chất lượng cao"
    width: int | None = None
    overwrite: bool = False

    # ── Retry / queue ─────────────────────────────────────────────────
    retries: int = 2
    retry_delay: float = 1.0
    disk_reserve_bytes: int = 512 * 1024**2
    use_scene_cache: bool = True
    cross_run_duplicates: bool = True
    cross_run_duplicate_threshold: int = 6

    # ── Checkpoint / resume ───────────────────────────────────────────
    resume: bool = False
    checkpoint_path: Path | None = None
    cache_root: Path | None = None
    duplicate_root: Path | None = None
    queue_db: Path | None = None
    queue_run_signature: str | None = None    # set at runtime

    # ── Runtime-only (set by process_videos, not by UI) ──────────────
    stage_timings: dict[str, float | int] | None = None
