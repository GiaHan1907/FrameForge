from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UIVisualContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")

    def test_accessibility_focus_and_touch_contract(self):
        self.assertIn(":focus-visible", self.source)
        self.assertIn("min-height: 40px", self.source)
        self.assertIn('aria-live="polite"', self.source)
        self.assertIn("prefers-reduced-motion", self.source)

    def test_responsive_breakpoints_contract(self):
        self.assertIn("@media (max-width: 900px)", self.source)
        self.assertIn("@media (max-width: 640px)", self.source)
        self.assertIn(".sticky-summary { position: static; }", self.source)
        self.assertIn(".timeline-legend { flex-wrap: wrap; }", self.source)

    def test_preview_and_v0129_contracts_remain_present(self):
        for marker in ("Preview workspace", "Frame gallery", "Lịch sử job", "Xuất cấu hình JSON", "Queue dashboard"):
            self.assertIn(marker, self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
