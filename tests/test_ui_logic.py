"""Tests for ui/logic.py — pure functions extracted from streamlit_app.py.

These tests verify that each extracted function works correctly without
requiring Streamlit, cv2, or any other heavy dependency.
"""

from __future__ import annotations

import io
import json
import tempfile
import time
import zipfile
from pathlib import Path
from unittest.mock import patch

import unittest

from ui.logic import (
    _pause_processing_job,
    _resume_processing_job,
    append_job_history,
    build_preview_timestamps,
    format_eta,
    frameforge_user_data_root,
    job_history_path,
    make_download_zip,
    make_zip,
    normalize_output_dir,
    parse_progress_units,
    personal_presets_path,
    progress_telemetry,
    read_json_list,
)


# ── format_eta ─────────────────────────────────────────────────────────


class FormatEtaTests(unittest.TestCase):
    def test_none(self):
        self.assertEqual(format_eta(None), "\u2014")

    def test_negative(self):
        self.assertEqual(format_eta(-5.0), "\u2014")

    def test_zero(self):
        self.assertEqual(format_eta(0.0), "0s")

    def test_seconds_only(self):
        self.assertEqual(format_eta(45.0), "45s")

    def test_minutes_and_seconds(self):
        self.assertEqual(format_eta(90.0), "1p 30s")

    def test_hours(self):
        self.assertEqual(format_eta(3661.0), "1g 01p")

    def test_nan(self):
        self.assertEqual(format_eta(float("nan")), "\u2014")

    def test_inf(self):
        self.assertEqual(format_eta(float("inf")), "\u2014")


# ── parse_progress_units ───────────────────────────────────────────────


class ParseProgressUnitsTests(unittest.TestCase):
    def test_vietnamese(self):
        self.assertEqual(parse_progress_units("3/10 m\u1ed1c"), (3, 10))

    def test_english(self):
        self.assertEqual(parse_progress_units("5/20 frame"), (5, 20))

    def test_no_match(self):
        self.assertIsNone(parse_progress_units("no numbers here"))

    def test_spaces(self):
        self.assertEqual(parse_progress_units("7 / 15 m\u1ed1c"), (7, 15))


# ── progress_telemetry ─────────────────────────────────────────────────


class ProgressTelemetryTests(unittest.TestCase):
    def test_basic(self):
        item = {"units_done": 5, "units_total": 10, "started_at": time.monotonic() - 1.0}
        result = progress_telemetry(item)
        self.assertEqual(result["done"], 5)
        self.assertEqual(result["total"], 10)
        self.assertIsNotNone(result["fps"])
        self.assertGreater(result["fps"], 0)

    def test_no_start(self):
        item = {"units_done": 0, "units_total": 0, "started_at": 0.0}
        result = progress_telemetry(item)
        self.assertIsNone(result["fps"])
        self.assertIsNone(result["eta"])

    def test_defaults(self):
        item = {}
        result = progress_telemetry(item)
        self.assertEqual(result["done"], 0)
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["rss"], 0)


# ── build_preview_timestamps ───────────────────────────────────────────


class BuildPreviewTimestampsTests(unittest.TestCase):
    def test_count_mode(self):
        ts = build_preview_timestamps(100.0, "\u0110\u00fang N frame", 0, 100, None, 5, 32)
        self.assertEqual(len(ts), 5)
        self.assertAlmostEqual(ts[0], 0.0, places=1)
        self.assertAlmostEqual(ts[-1], 99.9, places=0)

    def test_single_frame(self):
        ts = build_preview_timestamps(100.0, "\u0110\u00fang N frame", 0, 100, None, 1, 32)
        self.assertEqual(len(ts), 1)
        self.assertAlmostEqual(ts[0], 50.0, places=0)

    def test_interval_mode(self):
        # Ép đủ (mặc định): max_screenshots là mục tiêu → bù lên 32 mốc đều.
        ts = build_preview_timestamps(100.0, "M\u1ed7i N gi\u00e2y", 0, 100, 10.0, 10, 32)
        self.assertEqual(len(ts), 32)
        self.assertAlmostEqual(ts[0], 0.0, places=1)

    def test_interval_mode_no_fill_long_video(self):
        # Tắt ép đủ trên video dài: giữ mốc theo every (10 mốc cho 100s/10s).
        ts = build_preview_timestamps(100.0, "M\u1ed7i N gi\u00e2y", 0, 100, 10.0, 10, 32, fill_to_maximum=False)
        self.assertEqual(len(ts), 10)
        self.assertAlmostEqual(ts[0], 0.0, places=1)
        self.assertAlmostEqual(ts[1], 10.0, places=1)

    def test_interval_mode_short_video_fills_to_maximum(self):
        # Video 3s + every 5s chỉ có 1 mốc; ép đủ phải bù lên 6 mốc đều
        # (khớp engine khi target_count_after_filter=True).
        ts = build_preview_timestamps(3.0, "M\u1ed7i N gi\u00e2y", 0, None, 5.0, 1, 6)
        self.assertEqual(len(ts), 6)
        self.assertAlmostEqual(ts[0], 0.0, places=1)
        self.assertAlmostEqual(ts[-1], 2.9, places=0)

    def test_interval_mode_no_fill_keeps_sparse_ticks(self):
        # Tắt ép đủ: giữ nguyên hành vi cũ (1 mốc cho video ngắn).
        ts = build_preview_timestamps(3.0, "M\u1ed7i N gi\u00e2y", 0, None, 5.0, 1, 6, fill_to_maximum=False)
        self.assertEqual(len(ts), 1)
        self.assertAlmostEqual(ts[0], 0.0, places=1)

    def test_empty_range(self):
        ts = build_preview_timestamps(100.0, "\u0110\u00fang N frame", 50, 50, None, 5, 32)
        self.assertEqual(ts, [])

    def test_scene_mode(self):
        ts = build_preview_timestamps(100.0, "Scene detection", 0, 100, 5.0, 10, 5)
        self.assertLessEqual(len(ts), 5)

    def test_none_duration(self):
        ts = build_preview_timestamps(100.0, "\u0110\u00fang N frame", 0, 100, 5.0, 3, 32)
        self.assertEqual(len(ts), 3)


# ── normalize_output_dir ───────────────────────────────────────────────


class NormalizeOutputDirTests(unittest.TestCase):
    def test_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "new_dir"
            result = normalize_output_dir(str(target), Path(tmpdir))
            self.assertTrue(result.exists())
            self.assertTrue(result.is_dir())

    def test_empty_uses_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = normalize_output_dir("", Path(tmpdir))
            self.assertEqual(result, Path(tmpdir).resolve())

    def test_whitespace_uses_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = normalize_output_dir("   ", Path(tmpdir))
            self.assertEqual(result, Path(tmpdir).resolve())


# ── frameforge_user_data_root ──────────────────────────────────────────


class UserDataRootTests(unittest.TestCase):
    def test_returns_path(self):
        result = frameforge_user_data_root()
        self.assertIsInstance(result, Path)

    def test_ends_with_ui(self):
        result = frameforge_user_data_root()
        self.assertEqual(result.name, "ui")


# ── personal_presets_path / job_history_path ───────────────────────────


class PresetPathTests(unittest.TestCase):
    def test_personal_presets(self):
        p = personal_presets_path()
        self.assertTrue(str(p).endswith("presets.json"))

    def test_job_history(self):
        p = job_history_path()
        self.assertTrue(str(p).endswith("job_history.json"))


# ── read_json_list ─────────────────────────────────────────────────────


class ReadJsonListTests(unittest.TestCase):
    def test_valid_list(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([{"a": 1}, {"b": 2}], f)
            path = Path(f.name)
        try:
            result = read_json_list(path)
            self.assertEqual(len(result), 2)
        finally:
            path.unlink()

    def test_not_a_list(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"key": "value"}, f)
            path = Path(f.name)
        try:
            result = read_json_list(path)
            self.assertEqual(result, [])
        finally:
            path.unlink()

    def test_missing_file(self):
        result = read_json_list(Path("/nonexistent/file.json"))
        self.assertEqual(result, [])

    def test_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not json!!!")
            path = Path(f.name)
        try:
            result = read_json_list(path)
            self.assertEqual(result, [])
        finally:
            path.unlink()


# ── make_zip / make_download_zip ───────────────────────────────────────


class ZipTests(unittest.TestCase):
    def test_make_zip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "file1.txt").write_text("hello")
            (tmp / "file2.txt").write_text("world")
            report = tmp / "report.json"
            report.write_text('{"status": "ok"}')
            data = make_zip(tmp, report)
            self.assertIsInstance(data, bytes)
            self.assertGreater(len(data), 0)
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
                self.assertIn("file1.txt", names)
                self.assertIn("report.json", names)

    def test_make_download_zip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "a.mp4").write_bytes(b"fake")
            (tmp / "b.mp4").write_bytes(b"fake2")
            data = make_download_zip([tmp / "a.mp4", tmp / "b.mp4"])
            self.assertIsInstance(data, bytes)
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
                self.assertIn("a.mp4", names)
                self.assertIn("b.mp4", names)

    def test_make_download_zip_skips_missing(self):
        data = make_download_zip([Path("/nonexistent/file.mp4")])
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            self.assertEqual(len(zf.namelist()), 0)


# ── append_job_history ─────────────────────────────────────────────────


class AppendJobHistoryTests(unittest.TestCase):
    def test_appends_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_path = Path(tmpdir) / "job_history.json"
            with patch("ui.logic.job_history_path", return_value=fake_path):
                job = {
                    "status": "completed",
                    "output_dir": "/output",
                    "input_paths": ["/a.mp4", "/b.mp4"],
                    "reports": [{"saved": 5}, {"saved": 3}],
                    "error": None,
                }
                append_job_history(job)
                self.assertTrue(fake_path.exists())
                history = json.loads(fake_path.read_text())
                self.assertEqual(len(history), 1)
                self.assertEqual(history[0]["video_count"], 2)
                self.assertEqual(history[0]["saved"], 8)


# ── _pause_processing_job / _resume_processing_job ─────────────────────


class QueueStateTests(unittest.TestCase):
    def test_pause(self):
        import threading
        event = threading.Event()
        job = {"pause_event": event, "status": "running"}
        _pause_processing_job(job)
        self.assertTrue(event.is_set())
        self.assertEqual(job["status"], "paused")

    def test_resume(self):
        import threading
        event = threading.Event()
        event.set()
        job = {"pause_event": event, "status": "paused"}
        _resume_processing_job(job)
        self.assertFalse(event.is_set())
        self.assertEqual(job["status"], "running")

    def test_pause_no_event(self):
        job = {"status": "running"}
        _pause_processing_job(job)
        self.assertEqual(job["status"], "paused")

    def test_resume_no_event(self):
        job = {"status": "paused"}
        _resume_processing_job(job)
        self.assertEqual(job["status"], "running")


if __name__ == "__main__":
    unittest.main()
