"""Unit tests cho check_docs_stale - chan docs mo ta UI/version cu quay lai."""
from __future__ import annotations

import tempfile
import unittest
import sys
from pathlib import Path


if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from check_docs_stale import (
    CANONICAL_LABELS,
    DEFAULT_FILES,
    ROOT,
    check_canonical,
    scan_files,
    scan_text,
)


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


    def test_flags_short_tab_names(self) -> None:
        findings = scan_text("Mở tab Tải video rồi chuyển sang tab Cài đặt.", "fake.md")
        flagged = " ".join(findings)
        self.assertIn("tab Tải video", flagged)
        self.assertIn("tab Cài đặt", flagged)

    def test_flags_sidebar_group_without_number(self) -> None:
        findings = scan_text("Cấu hình nằm ở nhóm Nguồn video trong sidebar.", "fake.md")
        self.assertTrue(any("nhóm Nguồn video" in f for f in findings))

    def test_all_canonical_labels_present_in_live_docs(self) -> None:
        findings = check_canonical(DEFAULT_FILES, root=ROOT)
        sep = chr(10)
        self.assertEqual([], findings, "Nhãn canonical thiếu trong docs live:" + sep + sep.join(findings))

    def test_canonical_missing_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("Khong co gi o day.", encoding="utf-8")
            findings = check_canonical(["README.md"], root=root)
            self.assertGreaterEqual(len(findings), 1)
            self.assertTrue(findings[0].startswith("CANONICAL:"))

    def test_canonical_registry_is_nonempty_and_unique(self) -> None:
        labels = [label for label, _ in CANONICAL_LABELS]
        self.assertGreaterEqual(len(labels), 20)
        self.assertEqual(len(labels), len(set(labels)), "Nhãn canonical bị trùng")


    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.split())

    def test_canonical_labels_exist_in_code(self) -> None:
        misses = []
        for label, loc in CANONICAL_LABELS:
            file_part = loc.split(":", 1)[0].strip()
            path = ROOT / file_part
            if not path.exists():
                misses.append(label + " -> " + loc + ": file khong ton tai")
                continue
            src = path.read_text(encoding="utf-8")
            if self._normalize(label) not in self._normalize(src):
                misses.append(label + " -> " + loc + ": nhan khong xuat hien trong code")
        sep = chr(10)
        self.assertEqual([], misses, "CANONICAL_LABELS co nhan khong khop code that:" + sep + sep.join(misses))

    def test_canonical_rejects_fabricated_label(self) -> None:
        fabricated = ("Nha hang Pizzeria 66", "streamlit_app.py")
        self.assertNotIn(fabricated, CANONICAL_LABELS, "Fixture trung registry")
        file_part = fabricated[1].split(":", 1)[0].strip()
        src = (ROOT / file_part).read_text(encoding="utf-8")
        self.assertNotIn(self._normalize(fabricated[0]), self._normalize(src))
if __name__ == "__main__":
    unittest.main()
