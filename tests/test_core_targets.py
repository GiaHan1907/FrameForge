"""Tests for core/targets.py — target generation logic."""

from __future__ import annotations

import unittest

from core.config import FrameForgeConfig
from core.targets import (
    candidate_budget_bounds,
    candidate_limit,
    expand_candidate_budget,
    screenshot_limit,
)


def _config(**overrides) -> FrameForgeConfig:
    """Build a FrameForgeConfig with sensible defaults, overriding specific fields."""
    defaults = dict(
        max_screenshots=20,
        target_count_after_filter=True,
        target_candidate_multiplier=3,
        target_candidate_multiplier_max=5,
    )
    defaults.update(overrides)
    return FrameForgeConfig(**{k: v for k, v in defaults.items() if hasattr(FrameForgeConfig, k)})


class ScreenshotLimitTests(unittest.TestCase):
    def test_positive_value(self) -> None:
        self.assertEqual(screenshot_limit(_config(max_screenshots=15)), 15)

    def test_zero_returns_none(self) -> None:
        self.assertIsNone(screenshot_limit(_config(max_screenshots=0)))

    def test_negative_returns_none(self) -> None:
        self.assertIsNone(screenshot_limit(_config(max_screenshots=-5)))

    def test_none_returns_none(self) -> None:
        self.assertIsNone(screenshot_limit(_config(max_screenshots=0)))

    def test_large_value(self) -> None:
        self.assertEqual(screenshot_limit(_config(max_screenshots=1000)), 1000)


class CandidateLimitTests(unittest.TestCase):
    def test_with_target_filter(self) -> None:
        c = _config(max_screenshots=10, target_count_after_filter=True, target_candidate_multiplier=3)
        self.assertEqual(candidate_limit(c), 30)

    def test_without_target_filter(self) -> None:
        c = _config(max_screenshots=10, target_count_after_filter=False)
        self.assertEqual(candidate_limit(c), 10)

    def test_no_limit(self) -> None:
        c = _config(max_screenshots=0)
        self.assertIsNone(candidate_limit(c))

    def test_multiplier_minimum_1(self) -> None:
        # 0 is falsy → `0 or 3` = 3, then max(1, 3) = 3
        c = _config(max_screenshots=10, target_candidate_multiplier=0)
        self.assertEqual(candidate_limit(c), 30)


class CandidateBudgetBoundsTests(unittest.TestCase):
    def test_with_target_filter(self) -> None:
        c = _config(max_screenshots=10, target_count_after_filter=True, target_candidate_multiplier=3, target_candidate_multiplier_max=5)
        initial, maximum = candidate_budget_bounds(c)
        self.assertEqual(initial, 30)
        self.assertEqual(maximum, 50)

    def test_without_target_filter(self) -> None:
        c = _config(max_screenshots=10, target_count_after_filter=False)
        initial, maximum = candidate_budget_bounds(c)
        self.assertEqual(initial, 10)
        self.assertEqual(maximum, 10)

    def test_no_limit(self) -> None:
        c = _config(max_screenshots=0)
        initial, maximum = candidate_budget_bounds(c)
        self.assertIsNone(initial)
        self.assertIsNone(maximum)


class ExpandCandidateBudgetTests(unittest.TestCase):
    def test_no_expansion_when_at_maximum(self) -> None:
        self.assertEqual(expand_candidate_budget(50, 50, 10, 60, 20), 50)

    def test_no_expansion_when_low_rejection(self) -> None:
        # rejection rate < 25%
        self.assertEqual(expand_candidate_budget(30, 100, 10, 100, 20), 30)

    def test_expansion_when_high_rejection(self) -> None:
        # rejection rate >= 25%
        result = expand_candidate_budget(30, 100, 10, 100, 30)
        self.assertGreater(result, 30)
        self.assertLessEqual(result, 100)

    def test_none_current_returns_none(self) -> None:
        self.assertIsNone(expand_candidate_budget(None, 100, 10, 50, 20))

    def test_none_maximum_returns_current(self) -> None:
        # maximum=None → no expansion possible, return current as-is
        self.assertEqual(expand_candidate_budget(30, None, 10, 50, 20), 30)

    def test_none_target_returns_current(self) -> None:
        # target=None → no expansion possible, return current as-is
        self.assertEqual(expand_candidate_budget(30, 100, None, 50, 20), 30)

    def test_no_expansion_when_considered_too_low(self) -> None:
        self.assertEqual(expand_candidate_budget(30, 100, 10, 20, 10), 30)

    def test_no_expansion_when_rejected_zero(self) -> None:
        self.assertEqual(expand_candidate_budget(30, 100, 10, 50, 0), 30)

    def test_caps_at_maximum(self) -> None:
        result = expand_candidate_budget(90, 100, 50, 200, 100)
        self.assertLessEqual(result, 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
