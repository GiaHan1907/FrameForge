from __future__ import annotations

import ast
import math
import re
import tempfile
import time
from types import SimpleNamespace

import cv2
import numpy as np
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StreamlitDirectoryStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.queue_source = (ROOT / "queue_per_video.py").read_text(encoding="utf-8")
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
        self.assertIn("with st.container(border=True):", self.source)
        self.assertIn("download_input_col, quality_col = st.columns([2.35, 1.0], gap=\"large\")", self.source)
        self.assertIn("limit_col, retry_col, action_col = st.columns([1.0, 1.0, 1.35], gap=\"medium\")", self.source)
        self.assertIn("--canvas: #0b1220", self.source)
        self.assertIn("--surface: #151d2d", self.source)
        self.assertIn(".download-action-spacer", self.source)

    def test_video_preview_is_compact_and_timestamp_lookup_is_supported(self) -> None:
        self.assertIn("max-width: 560px !important", self.source)
        self.assertIn("aspect-ratio: 16 / 9", self.source)
        self.assertIn("width=560", self.source)
        self.assertIn('pattern = f"*{timestamp_label(nearest)}.*"', self.source)

    def test_downloader_error_categories_and_backoff_are_present(self) -> None:
        self.assertIn('--max-screenshots', (ROOT / 'video_screenshot_advanced.py').read_text(encoding='utf-8'))
        self.assertIn('DownloadFailure', self.source)
        self.assertIn('download_error_hook', self.source)
        self.assertIn('state == "retrying"', self.source)
        self.assertIn('retry_delay_seconds=1.0', self.source)
        self.assertIn('error_code', self.source)

    def test_presets_and_progress_telemetry_are_present(self) -> None:
        self.assertIn('PRESET_CONFIGS = {', self.source)
        for name in ('Nhanh', 'Cân bằng', 'Chất lượng cao', 'Video dọc / TikTok'):
            self.assertIn(f'"{name}"', self.source)
        self.assertIn('on_change=apply_selected_preset', self.source)
        self.assertIn('st.session_state.setdefault("preset_choice", "Cân bằng")', self.source)
        self.assertIn('CROP_RATIO_LABELS', self.source)
        self.assertIn('key="crop_ratio"', self.source)
        self.assertIn('Tỉ lệ crop screenshot', self.source)
        self.assertIn('Số screenshot mỗi video', self.source)
        self.assertIn('max_screenshots=int(max_screenshots)', self.source)
        self.assertIn('crop_ratio=crop_ratio', self.source)
        self.assertIn('ENCODE_PROFILE_LABELS', self.source)
        self.assertIn('key="encode_profile"', self.source)
        self.assertIn('encode_profile=encode_profile', self.source)
        self.assertIn('def parse_progress_units', self.source)
        self.assertIn('def progress_telemetry', self.source)
        self.assertIn('"fps": telemetry["fps"]', self.source)
        self.assertIn('"eta": telemetry["eta"]', self.source)
        self.assertIn('"rss": telemetry["rss"]', self.source)
        self.assertIn('fps_label', self.queue_source)
        self.assertIn('eta_label', self.queue_source)
        self.assertIn('ram_label', self.queue_source)
        self.assertIn('WIZARD_STEPS', self.source)
        self.assertIn('wizard_step', self.source)
        self.assertIn('preview_crop_overlay', self.source)
        self.assertIn('preview_col, crop_preview_col = st.columns(2', self.source)
        self.assertIn('st.markdown("**Video gốc**")', self.source)
        self.assertIn('**Crop overlay · {crop_ratio}**', self.source)
        self.assertIn('"Tạm dừng"', self.queue_source)
        self.assertIn('"Tiếp tục"', self.queue_source)
        self.assertIn('Thử lại', self.queue_source)
        self.assertIn('Queue theo video', self.source)
        self.assertIn('from queue_per_video import classify_error, render_queue_per_video', self.source)
        self.assertIn('class _ProcessingQueueAdapter', self.source)
        self.assertIn('render_queue_per_video(_ProcessingQueueAdapter(job)', self.source)
        self.assertIn('with st.expander(', self.queue_source)
        self.assertIn('"Retrying"', self.queue_source)
        self.assertIn('DownloadFailure', self.source)
        self.assertIn('download_error_hook', self.source)
        self.assertIn('state == "retrying"', self.source)

    def test_crop_overlay_function_behavior(self) -> None:
        function = next(
            node for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "preview_crop_overlay"
        )
        namespace = {
            "CROP_RATIO_VALUES": {"Không crop": None, "9:16": 9 / 16},
            "Path": Path,
            "cv2": cv2,
            "np": np,
            "tempfile": tempfile,
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), "streamlit_app.py", "exec"), namespace)
        with tempfile.TemporaryDirectory() as temporary:
            video_path = Path(temporary) / "preview.mp4"
            writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 8.0, (160, 90))
            self.assertTrue(writer.isOpened())
            try:
                for index in range(3):
                    writer.write(np.full((90, 160, 3), 50 + index * 30, dtype=np.uint8))
            finally:
                writer.release()
            overlay = namespace["preview_crop_overlay"](video_path, "9:16")
            self.assertIsNotNone(overlay)
            self.assertTrue(bytes(overlay).startswith(b"\x89PNG"))

    def test_progress_parser_and_telemetry_behavior(self) -> None:
        functions = [
            node
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name in {"parse_progress_units", "progress_telemetry"}
        ]
        namespace = {"math": math, "re": re, "time": time}
        exec(compile(ast.Module(body=functions, type_ignores=[]), "streamlit_app.py", "exec"), namespace)
        parse_progress_units = namespace["parse_progress_units"]
        progress_telemetry = namespace["progress_telemetry"]
        self.assertEqual(parse_progress_units("Đã xử lý 7/20 mốc"), (7, 20))
        self.assertEqual(parse_progress_units("Đã xử lý 9/20 frame"), (9, 20))
        self.assertIsNone(parse_progress_units("Đang chuẩn bị"))
        telemetry = progress_telemetry(
            {"units_done": 5, "units_total": 10, "started_at": time.monotonic() - 1.0, "rss_bytes": 1234}
        )
        self.assertEqual(telemetry["done"], 5)
        self.assertEqual(telemetry["total"], 10)
        self.assertEqual(telemetry["rss"], 1234)
        self.assertIsNotNone(telemetry["fps"])
        self.assertGreaterEqual(float(telemetry["eta"]), 0.0)

    def test_desktop_lifecycle_shutdown_is_guarded(self) -> None:
        launcher = (ROOT / "windows_launcher.py").read_text(encoding="utf-8")
        self.assertIn('FRAMEFORGE_DESKTOP_LIFECYCLE', launcher)
        self.assertIn('FRAMEFORGE_NO_BROWSER', launcher)
        self.assertIn('FRAMEFORGE_DESKTOP_LIFECYCLE', self.source)
        self.assertIn('runtime.stop()', self.source)
        self.assertIn('atexit.register(cleanup_at_exit)', self.source)

    def test_completed_video_temp_input_is_removed(self) -> None:
        self.assertIn('input_root = work_dir.resolve() / "input"', self.source)
        self.assertIn('resolved_video.is_relative_to(input_root)', self.source)
        self.assertIn('resolved_video.unlink(missing_ok=True)', self.source)
        self.assertIn('if "error" not in report:', self.source)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
