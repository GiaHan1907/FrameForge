"""cv2-dependent tests for Streamlit app functions.

These tests require cv2/numpy to create test videos and verify
frame processing behavior.
"""

from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]


def _has_cv2():
    return cv2 is not None and np is not None


@unittest.skipUnless(
    _has_cv2(),
    "cv2/numpy not installed; skipping cv2-dependent Streamlit tests",
)
class StreamlitCv2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_crop_overlay_function_behavior(self) -> None:
        function = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "preview_crop_overlay"
        )
        namespace = {
            "CROP_RATIO_VALUES": {"Kh\u00f4ng crop": None, "9:16": 9 / 16},
            "Path": Path,
            "cv2": cv2,
            "np": np,
            "tempfile": tempfile,
        }
        exec(
            compile(
                ast.Module(body=[function], type_ignores=[]),
                "streamlit_app.py",
                "exec",
            ),
            namespace,
        )
        with tempfile.TemporaryDirectory() as temporary:
            video_path = Path(temporary) / "preview.mp4"
            writer = cv2.VideoWriter(
                str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 8.0, (160, 90)
            )
            self.assertTrue(writer.isOpened())
            try:
                for index in range(3):
                    writer.write(np.full((90, 160, 3), 50 + index * 30, dtype=np.uint8))
            finally:
                writer.release()
            overlay = namespace["preview_crop_overlay"](video_path, "9:16")
            self.assertIsNotNone(overlay)
            self.assertTrue(bytes(overlay).startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
