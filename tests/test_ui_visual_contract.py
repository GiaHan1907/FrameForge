from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UIVisualContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        cls.css = (ROOT / "ui" / "styles.css").read_text(encoding="utf-8") if (ROOT / "ui" / "styles.css").exists() else ""

    def test_accessibility_focus_and_touch_contract(self):
        combined = self.source + self.css
        self.assertIn(":focus-visible", combined)
        self.assertIn("min-height: 40px", combined)
        self.assertIn('aria-live="polite"', self.source)
        self.assertIn("prefers-reduced-motion", combined)

    def test_responsive_breakpoints_contract(self):
        combined = self.source + self.css
        self.assertIn("@media (max-width: 900px)", combined)
        self.assertIn("@media (max-width: 640px)", combined)
        self.assertIn(".sticky-summary { position: static; }", combined)
        self.assertIn(".timeline-legend { flex-wrap: wrap; }", combined)

    def test_preview_and_v0129_contracts_remain_present(self):
        for marker in ("Preview workspace", "Frame gallery", "Lịch sử job", "Xuất cấu hình JSON", "Queue dashboard"):
            self.assertIn(marker, self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
