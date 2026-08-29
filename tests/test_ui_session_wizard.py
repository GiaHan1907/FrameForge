"""Tests for ui/session.py and ui/wizard.py.

These tests verify the widget session-state mapping and the refactored
wizard functions **without** requiring a Streamlit runtime.
"""

from __future__ import annotations

import unittest

from ui.session import WIDGET_KEYS
from ui.wizard import build_args, validate_ui_configuration, wizard_summary


class WidgetKeysMappingTests(unittest.TestCase):
    """Test the WIDGET_KEYS mapping in ui/session.py."""

    def test_all_expected_keys_are_present(self) -> None:
        expected = {
            "start", "end", "limit_end", "every", "mode_label",
            "max_screenshots", "target_count_after_filter",
            "scene_threshold", "min_scene_gap", "flash_return_ratio",
            "flash_brightness_threshold", "scene_confirmations",
            "worker_choice", "analysis_width", "min_free_ram_gb",
            "analysis_fps", "extract_worker_choice",
            "min_sharpness", "duplicate_threshold", "motion_blur_threshold",
            "encode_profile", "image_format", "crop_ratio", "quality",
            "width", "overwrite", "retry_count", "retry_delay",
            "disk_reserve_mb", "use_scene_cache", "cross_run_duplicates",
            "uploaded_files", "video_dir_text", "screenshot_dir_text",
            "download_urls_text", "download_quality",
            "wizard_step", "preview_name",
        }
        self.assertTrue(expected.issubset(set(WIDGET_KEYS)))

    def test_mapping_is_string_to_string(self) -> None:
        for var, key in WIDGET_KEYS.items():
            self.assertIsInstance(var, str)
            self.assertIsInstance(key, str)


class BuildArgsTests(unittest.TestCase):
    """Test build_args() with a plain dict — no Streamlit needed."""

    def _make_defaults(self) -> dict:
        return {
            "start": 0, "end": 60.0, "limit_end": False, "every": None,
            "mode_label": "Best frame per scene",
            "max_screenshots": 20, "target_count_after_filter": True,
            "scene_threshold": 0.30, "min_scene_gap": 0.5,
            "flash_return_ratio": 0.55, "flash_brightness_threshold": 0.18,
            "scene_confirmations": 2,
            "analysis_width": 640, "analysis_fps": 1.0,
            "extract_worker_choice": "Auto (khuyến nghị)",
            "worker_choice": "Auto (khuyến nghị)",
            "min_sharpness": 0.0, "motion_blur_threshold": 0.3,
            "duplicate_threshold": 0, "image_format": "jpg",
            "quality": 95, "crop_ratio": None,
            "encode_profile": "Chất lượng cao",
            "width": 0, "overwrite": False,
            "retry_count": 3, "retry_delay": 2.0,
            "disk_reserve_mb": 500, "use_scene_cache": True,
            "cross_run_duplicates": False,
        }

    def test_returns_frame_forge_config(self) -> None:
        from core.config import FrameForgeConfig
        w = self._make_defaults()
        config = build_args(w)
        self.assertIsInstance(config, FrameForgeConfig)

    def test_start_and_end(self) -> None:
        w = self._make_defaults()
        w["start"] = 10.0
        w["end"] = 30.0
        w["limit_end"] = True
        config = build_args(w)
        self.assertAlmostEqual(config.start, 10.0)
        self.assertAlmostEqual(config.end, 30.0)

    def test_limit_end_false_sets_end_none(self) -> None:
        w = self._make_defaults()
        w["limit_end"] = False
        config = build_args(w)
        self.assertIsNone(config.end)

    def test_every_mode(self) -> None:
        w = self._make_defaults()
        w["mode_label"] = "Mỗi N giây"
        w["every"] = 5.0
        config = build_args(w)
        self.assertAlmostEqual(config.every, 5.0)
        self.assertFalse(config.scene_detection)

    def test_scene_detection_mode(self) -> None:
        w = self._make_defaults()
        w["mode_label"] = "Scene detection"
        config = build_args(w)
        self.assertTrue(config.scene_detection)
        self.assertFalse(config.best_frame_per_scene)

    def test_best_frame_per_scene_mode(self) -> None:
        w = self._make_defaults()
        w["mode_label"] = "Best frame per scene"
        config = build_args(w)
        self.assertTrue(config.scene_detection)
        self.assertTrue(config.best_frame_per_scene)

    def test_worker_auto(self) -> None:
        w = self._make_defaults()
        w["worker_choice"] = "Auto (khuyến nghị)"
        config = build_args(w)
        self.assertEqual(config.workers, "auto")

    def test_worker_explicit(self) -> None:
        w = self._make_defaults()
        w["worker_choice"] = 2
        config = build_args(w)
        self.assertEqual(config.workers, 2)

    def test_disk_reserve_bytes(self) -> None:
        w = self._make_defaults()
        w["disk_reserve_mb"] = 1000
        config = build_args(w)
        self.assertEqual(config.disk_reserve_bytes, 1000 * 1024**2)

    def test_extract_workers_auto(self) -> None:
        w = self._make_defaults()
        w["extract_worker_choice"] = "Auto (khuyến nghị)"
        config = build_args(w)
        self.assertGreater(config.extract_workers, 0)

    def test_extract_workers_explicit(self) -> None:
        w = self._make_defaults()
        w["extract_worker_choice"] = "3"
        config = build_args(w)
        self.assertEqual(config.extract_workers, 3)

    def test_empty_widgets_uses_defaults(self) -> None:
        config = build_args({})
        self.assertEqual(config.max_screenshots, 20)
        self.assertEqual(config.analysis_width, 640)


class ValidateUiConfigurationTests(unittest.TestCase):
    """Test validate_ui_configuration() with a plain dict."""

    def _make_valid(self) -> dict:
        return {
            "start": 0, "end": 60.0, "limit_end": True,
            "max_screenshots": 20, "analysis_fps": 1.0,
            "analysis_width": 640, "min_sharpness": 10.0,
            "min_free_ram_gb": 0.5, "worker_choice": 2,
        }

    def test_valid_config_has_no_errors(self) -> None:
        result = validate_ui_configuration(
            self._make_valid(), source_count=1, screenshot_dir="/tmp/out"
        )
        self.assertEqual(result["errors"], [])

    def test_no_source_video(self) -> None:
        result = validate_ui_configuration(
            self._make_valid(), source_count=0, screenshot_dir="/tmp/out"
        )
        self.assertTrue(any("video" in e for e in result["errors"]))

    def test_no_screenshot_dir(self) -> None:
        result = validate_ui_configuration(
            self._make_valid(), source_count=1, screenshot_dir=""
        )
        self.assertTrue(any("thư mục" in e for e in result["errors"]))

    def test_start_negative(self) -> None:
        w = self._make_valid()
        w["start"] = -5
        result = validate_ui_configuration(w, source_count=1, screenshot_dir="/tmp")
        self.assertTrue(any("nhỏ hơn 0" in e for e in result["errors"]))

    def test_end_before_start(self) -> None:
        w = self._make_valid()
        w["start"] = 10
        w["end"] = 5
        w["limit_end"] = True
        result = validate_ui_configuration(w, source_count=1, screenshot_dir="/tmp")
        self.assertTrue(any("lớn hơn" in e for e in result["errors"]))

    def test_max_screenshots_zero(self) -> None:
        w = self._make_valid()
        w["max_screenshots"] = 0
        result = validate_ui_configuration(w, source_count=1, screenshot_dir="/tmp")
        # max_screenshots=0 < 1 triggers error
        self.assertTrue(len(result["errors"]) > 0)

    def test_high_sharpness_warning(self) -> None:
        w = self._make_valid()
        w["min_sharpness"] = 500
        result = validate_ui_configuration(w, source_count=1, screenshot_dir="/tmp")
        self.assertTrue(any("sharpness" in wr for wr in result["warnings"]))

    def test_worker_no_ram_warning(self) -> None:
        w = self._make_valid()
        w["min_free_ram_gb"] = 0
        w["worker_choice"] = 3
        result = validate_ui_configuration(
            w, source_count=1, screenshot_dir="/tmp", workers_value=3
        )
        self.assertTrue(any("RAM" in wr for wr in result["warnings"]))


class WizardSummaryTests(unittest.TestCase):
    """Test wizard_summary() with a plain dict."""

    def test_returns_all_keys(self) -> None:
        result = wizard_summary({}, source_count=3)
        for key in ("Nguồn", "Chọn frame", "Chất lượng", "Đầu ra"):
            self.assertIn(key, result)

    def test_source_count(self) -> None:
        result = wizard_summary({}, source_count=5)
        self.assertEqual(result["Nguồn"], "5 video")

    def test_format_label(self) -> None:
        result = wizard_summary({"image_format": "png"})
        self.assertIn("PNG", result["Đầu ra"])

    def test_crop_label(self) -> None:
        result = wizard_summary({"crop_ratio": "16:9"})
        self.assertIn("16:9", result["Đầu ra"])

    def test_crop_none_label(self) -> None:
        result = wizard_summary({"crop_ratio": "Không crop"})
        self.assertIn("Giữ nguyên", result["Đầu ra"])

    def test_mode_label(self) -> None:
        result = wizard_summary({"mode_label": "Scene detection"})
        self.assertEqual(result["Chọn frame"], "Scene detection")


if __name__ == "__main__":
    unittest.main(verbosity=2)
