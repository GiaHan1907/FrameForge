"""Unit tests cho check_docs_stale - chan docs mo ta UI/version cu quay lai."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from check_docs_stale import ROOT, DEFAULT_FILES, scan_files, scan_text


class DocsStaleScanTest(unittest.TestCase):
    def test_live_docs_are_clean(self) -> None:
        findings = scan_files(DEFAULT_FILES, root=ROOT)
        sep = chr(10)
        self.assertEqual([], findings, "Docs live dang chua tu khoa UI/version loi thoi:" + sep + sep.join(findings))

    def test_flags_old_wording(self) -> None:
        findings = scan_text("Phần Nơi lưu file ở khu vực chính.", "fake.md")
        self.assertTrue(any("fake.md:1" in f and "Nơi lưu file" in f for f in findings))

    def test_tolerates_corrected_scene_sentence(self) -> None:
        findings = scan_text(
            "Chế độ scene detection **không dùng bộ lọc scene của FFmpeg**: engine tự phân tích bằng OpenCV.",
            "fake.md",
        )
        self.assertEqual([], findings)

    def test_missing_file_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            findings = scan_files(["khong-ton-tai.md"], root=Path(tmp))
            self.assertTrue(any("FILE NOT FOUND" in f for f in findings))


if __name__ == "__main__":
    unittest.main()
