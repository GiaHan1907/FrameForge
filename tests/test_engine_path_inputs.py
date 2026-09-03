from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    import video_screenshot_advanced as engine
except ImportError:
    engine = None  # type: ignore[assignment]


def _has_engine() -> bool:
    return engine is not None


@unittest.skipUnless(
    _has_engine(),
    "video_screenshot_advanced (cv2) not installed; skipping engine path input tests",
)
class EnginePathInputTests(unittest.TestCase):
    """Regression cho fix "'str' object has no attribute 'resolve'".

    session_state["downloaded_paths"] là list[str]; nếu lọt thẳng vào
    process_videos()/process_video() thì video.resolve()/video.name fail.
    Engine phải tự chuẩn hóa str -> Path ở cả entry batch lẫn single-video.
    """

    def setUp(self) -> None:
        self.root_context = tempfile.TemporaryDirectory()
        self.root = Path(self.root_context.name)
        self.video = self.root / "one.mp4"
        self.video.write_bytes(b"test video")
        # Đủ attrs cho process_videos chạy tới vòng lặp item (xem
        # test_queue_retry_cancel.py — pattern đã được chứng minh chạy hermetic).
        self.args = SimpleNamespace(
            workers=1,
            disk_reserve_bytes=0,
            queue_run_signature="",
            extract_workers=1,
            extract_min_targets=8,
            resume=False,
            queue_db=None,
        )

    def tearDown(self) -> None:
        self.root_context.cleanup()

    def test_process_videos_accepts_string_paths(self) -> None:
        seen: list[object] = []

        def fake_process(video, output_root, source_root, args, on_progress=None, cancel_event=None):
            seen.append(video)
            return {"video": str(video), "saved": 1}

        with patch.object(engine, "process_one_video", side_effect=fake_process):
            reports = engine.process_videos(
                [str(self.video), str(self.root / "two.mp4")],
                self.root / "output",
                None,
                self.args,
            )

        # Không AttributeError; item được truyền xuống dưới dạng Path.
        self.assertEqual(len(seen), 2)
        self.assertTrue(all(isinstance(item, Path) for item in seen))
        self.assertEqual([Path(item["video"]).name for item in reports], ["one.mp4", "two.mp4"])

    def test_process_video_accepts_string_path(self) -> None:
        probed: list[object] = []

        def fake_probe(video):
            probed.append(video)
            raise RuntimeError("stop-after-probe")  # chỉ cần chạm tới probe

        with patch.object(engine, "probe_video", side_effect=fake_probe):
            with self.assertRaisesRegex(RuntimeError, "stop-after-probe"):
                engine.process_video(
                    str(self.video),
                    self.root / "output",
                    None,
                    SimpleNamespace(),  # không dùng tới vì probe raise trước
                )

        # Nếu thiếu chuẩn hóa, probe nhận str chứ không phải Path.
        self.assertEqual(len(probed), 1)
        self.assertIsInstance(probed[0], Path)
        self.assertEqual(probed[0], Path(str(self.video)))


if __name__ == "__main__":
    unittest.main()
