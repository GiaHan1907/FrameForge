from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackagingSpecTests(unittest.TestCase):
    def test_all_specs_embed_runtime_source_modules(self) -> None:
        required = [
            '("persistent_queue.py", ".")',
            '("timeline_utils.py", ".")',
            '("core/__init__.py", "core")',
            '("core/utils.py", "core")',
            '("core/config.py", "core")',
            '("ui/styles.css", "ui")',
        ]
        for spec_name in (
            "video_screenshot_filter.spec",
            "video_screenshot_filter_minimal.spec",
            "video_screenshot_filter_onedir.spec",
        ):
            content = (ROOT / spec_name).read_text(encoding="utf-8")
            for marker in required:
                self.assertIn(marker, content, f"{marker} missing from {spec_name}")

    def test_windows_workflow_checks_runtime_modules(self) -> None:
        content = (ROOT / ".github" / "workflows" / "windows-release.yml").read_text(encoding="utf-8")
        self.assertIn('"persistent_queue.py"', content)
        self.assertIn('"timeline_utils.py"', content)
        self.assertIn("Required runtime module was not packaged", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
