"""Target generation logic for screenshot extraction.

Pure functions that determine how many screenshots and candidates to
extract per video.  No cv2/numpy dependency — these can be tested
and used independently of the video processing pipeline.
"""

from __future__ import annotations

from core.config import FrameForgeConfig


def screenshot_limit(args: FrameForgeConfig) -> int | None:
    """Return the maximum number of screenshots per video; ``None`` means unlimited."""
    raw = args.max_screenshots
    try:
        value = int(raw or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else None


def candidate_limit(args: FrameForgeConfig) -> int | None:
    """Return the initial candidate budget for a video.

    When ``target_count_after_filter`` is enabled, the budget is multiplied
    by ``target_candidate_multiplier`` to give the filter more candidates
    to choose from.
    """
    limit = screenshot_limit(args)
    if limit is None:
        return None
    if args.target_count_after_filter:
        multiplier = max(1, int(args.target_candidate_multiplier or 3))
        return limit * multiplier
    return limit


def candidate_budget_bounds(args: FrameForgeConfig) -> tuple[int | None, int | None]:
    """Return ``(initial, maximum)`` candidate budget bounds.

    The initial budget is used for the first extraction pass.  The maximum
    budget is the upper bound for adaptive expansion when too many candidates
    are rejected.
    """
    initial = candidate_limit(args)
    target = screenshot_limit(args)
    if initial is None or target is None or not args.target_count_after_filter:
        return initial, initial
    maximum_multiplier = max(
        int(args.target_candidate_multiplier or 3),
        int(args.target_candidate_multiplier_max or 5),
    )
    return initial, target * maximum_multiplier


def expand_candidate_budget(
    current: int | None,
    maximum: int | None,
    target: int | None,
    considered: int,
    rejected: int,
) -> int | None:
    """Expand the candidate budget if rejection rate is too high.

    Returns the (possibly expanded) budget, or *current* if no expansion
    is needed or possible.
    """
    if current is None or maximum is None or target is None or current >= maximum:
        return current
    if considered < current or considered <= 0 or rejected <= 0:
        return current
    if rejected / max(considered, 1) < 0.25:
        return current
    return min(maximum, current + max(target, current // 2))
