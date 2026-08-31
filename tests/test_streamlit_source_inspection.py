"""Source code inspection tests for Streamlit app.

These tests verify that the Streamlit app source code contains expected
patterns, functions, and UI elements.  They use AST parsing and string
matching — no cv2, numpy, or Streamlit runtime needed.
"""

from __future__ import annotations

import ast
import math
import re
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class StreamlitSourceInspectionTests(unittest.TestCase):
    """Tests that inspect streamlit_app.py source code via AST/string matching."""

    def setUp(self) -> None:
        self.source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.css_source = (ROOT / "ui" / "styles.css").read_text(encoding="utf-8") if (ROOT / "ui" / "styles.css").exists() else ""
        self.queue_source = (ROOT / "queue_per_video.py").read_text(encoding="utf-8")
        # Include all ui/ module sources for assertions that check functions
        # extracted from streamlit_app.py into ui/logic.py, ui/presets.py, etc.
        ui_sources = []
        for name in ("logic.py", "presets.py", "preview.py", "desktop.py", "queue_ui.py", "download_section.py"):
            p = ROOT / "ui" / name
            if p.exists():
                ui_sources.append(p.read_text(encoding="utf-8"))
        self.all_source = self.source + self.css_source + "\n".join(ui_sources)
        self.tree = ast.parse(self.source)

    def test_directory_buttons_use_callback(self) -> None:
        buttons = [
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "st"
            and node.func.attr == "button"
        ]
        by_key = {}
        for button in buttons:
            for keyword in button.keywords:
                if keyword.arg == "key" and isinstance(keyword.value, ast.Constant):
                    by_key[keyword.value.value] = button
        for key in ("choose_video_dir", "choose_screenshot_dir"):
            self.assertIn(key, by_key)
            keyword_names = {keyword.arg for keyword in by_key[key].keywords}
            self.assertIn("on_click", keyword_names)
            self.assertIn("args", keyword_names)

    def test_downloader_uses_dark_responsive_panel(self) -> None:
        self.assertIn("with st.container(border=True):", self.all_source)
        self.assertIn(
            'download_input_col, quality_col = st.columns([2.35, 1.0], gap="large")',
            self.all_source,
        )
        self.assertIn("--canvas: #", self.all_source)
        self.assertIn("--surface: #", self.all_source)
        self.assertIn(".download-action-spacer", self.all_source)

    def test_video_preview_is_compact_and_timestamp_lookup_is_supported(self) -> None:
        self.assertIn("max-width: 560px !important", self.all_source)
        self.assertIn("aspect-ratio: 16 / 9", self.all_source)
        preview_section_source = (ROOT / "ui" / "preview_section.py").read_text(encoding="utf-8")
        self.assertIn("width=560", preview_section_source)
        timeline_source = (ROOT / "ui" / "timeline.py").read_text(encoding="utf-8")
        self.assertIn('pattern = f"*{timestamp_label(nearest)}.*"', timeline_source)

    def test_downloader_error_categories_and_backoff_are_present(self) -> None:
        cli_source = (ROOT / "core" / "cli.py").read_text(encoding="utf-8")
        self.assertIn("--max-screenshots", cli_source)
        self.assertIn("DownloadFailure", self.all_source)
        self.assertIn("download_error_hook", self.all_source)
        self.assertIn('state == "retrying"', self.all_source)
        self.assertIn("retry_delay_seconds=1.0", self.all_source)
        self.assertIn("error_code", self.all_source)

    def test_presets_and_progress_telemetry_are_present(self) -> None:
        self.assertIn("PRESET_CONFIGS = {", self.source)
        for name in ("Nhanh", "C\u00e2n b\u1eb1ng", "Ch\u1ea5t l\u01b0\u1ee3ng cao"):
            self.assertIn(f'"{name}"', self.source)
        self.assertIn("apply_selected_preset", self.all_source)
        self.assertIn('CROP_RATIO_LABELS', self.all_source)
        self.assertIn("def validate_ui_configuration", self.source)
        dashboard_source = (ROOT / "ui" / "dashboard.py").read_text(encoding="utf-8")
        self.assertIn("def render_queue_dashboard", dashboard_source)
        self.assertIn("def render_resource_meter", dashboard_source)
        self.assertIn("def error_actions", dashboard_source)
        self.assertIn("PERSONAL_PRESET_KEYS", self.all_source)
        self.assertIn("def save_personal_preset", self.all_source)
        self.assertIn("def append_job_history", self.all_source)
        self.assertIn("def export_ui_config", self.all_source)
        self.assertIn("def import_ui_config", self.all_source)
        self.assertIn("def parse_progress_units", self.all_source)
        self.assertIn("def progress_telemetry", self.all_source)
        self.assertIn('"fps": telemetry["fps"]', self.all_source)
        self.assertIn('"eta": telemetry["eta"]', self.all_source)
        self.assertIn('"rss": telemetry["rss"]', self.all_source)
        self.assertIn("WIZARD_STEPS", self.source)
        self.assertIn("def preview_frame_at", self.all_source)
        preview_section_source = (ROOT / "ui" / "preview_section.py").read_text(encoding="utf-8")
        self.assertIn("def preview_scene_timeline", preview_section_source)
        processing_view_source = (ROOT / "ui" / "processing_view.py").read_text(encoding="utf-8")
        self.assertIn("Queue theo video", processing_view_source)
        self.assertIn(
            "from queue_per_video import render_queue_per_video",
            self.source,
        )
        self.assertIn("from persistent_queue import PersistentQueueStore", self.source)
        self.assertIn("find_recoverable_queue_jobs", self.source)
        self.assertIn("Ti\u1ebfp t\u1ee5c queue \u0111\u00e3 gi\u00e1n \u0111o\u1ea1n", self.source)
        self.assertIn("DownloadFailure", self.all_source)
        self.assertIn("download_error_hook", self.all_source)

    def test_desktop_lifecycle_shutdown_is_guarded(self) -> None:
        launcher = (ROOT / "windows_launcher.py").read_text(encoding="utf-8")
        self.assertIn("FRAMEFORGE_DESKTOP_LIFECYCLE", launcher)
        self.assertIn("FRAMEFORGE_NO_BROWSER", launcher)
        desktop_source = (ROOT / "ui" / "desktop.py").read_text(encoding="utf-8") if (ROOT / "ui" / "desktop.py").exists() else self.source
        self.assertIn("runtime.stop()", desktop_source)
        # atexit.register lives in streamlit_app.py (desktop lifecycle setup)
        self.assertIn("atexit.register", self.source)

    def test_completed_video_temp_input_is_removed(self) -> None:
        processing_source = (ROOT / "ui" / "processing.py").read_text(encoding="utf-8")
        self.assertIn('input_root = work_dir.resolve() / "input"', processing_source)
        self.assertIn("resolved_video.is_relative_to(input_root)", processing_source)
        self.assertIn("resolved_video.unlink(missing_ok=True)", processing_source)
        self.assertIn('if "error" not in report:', processing_source)

    def test_widget_keys_are_not_assigned_directly(self) -> None:
        forbidden = {"video_dir_text", "screenshot_dir_text"}
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Subscript):
                    continue
                if not isinstance(target.value, ast.Attribute):
                    continue
                if not isinstance(target.value.value, ast.Name):
                    continue
                if target.value.value.id != "st" or target.value.attr != "session_state":
                    continue
                key = target.slice
                if isinstance(key, ast.Constant) and key.value in forbidden:
                    self.fail(f"direct assignment to widget key remains: {key.value}")

    def test_progress_parser_and_telemetry_behavior(self) -> None:
        """Test parse_progress_units and progress_telemetry via import."""
        from ui.logic import parse_progress_units, progress_telemetry
        self.assertEqual(parse_progress_units("\u0110\u00e3 x\u1eed l\u00fd 7/20 m\u1ed1c"), (7, 20))
        self.assertEqual(parse_progress_units("\u0110\u00e3 x\u1eed l\u00fd 9/20 frame"), (9, 20))
        self.assertIsNone(parse_progress_units("\u0110ang chu\u1ea9n b\u1ecb"))
        telemetry = progress_telemetry({
            "units_done": 5,
            "units_total": 10,
            "started_at": time.monotonic() - 1.0,
            "rss_bytes": 1234,
        })
        self.assertEqual(telemetry["done"], 5)
        self.assertEqual(telemetry["total"], 10)
        self.assertEqual(telemetry["rss"], 1234)
        self.assertIsNotNone(telemetry["fps"])
        self.assertGreaterEqual(float(telemetry["eta"]), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
