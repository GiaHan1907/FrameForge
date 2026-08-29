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
            '("core/pipeline.py", "core")',
            '("core/resources.py", "core")',
            '("core/targets.py", "core")',
            '("core/manifest.py", "core")',
            '("core/errors.py", "core")',
            '("core/cv2_helpers.py", "core")',
            '("core/analysis.py", "core")',
            '("core/checkpoint.py", "core")',
            '("core/workers.py", "core")',
            '("core/cleanup.py", "core")',
            '("ui/logic.py", "ui")',
            '("ui/processing.py", "ui")',
            '("ui/session.py", "ui")',
            '("ui/wizard.py", "ui")',
            '("ui/preview.py", "ui")',
            '("ui/preview_section.py", "ui")',
            '("ui/presets.py", "ui")',
            '("ui/desktop.py", "ui")',
            '("ui/queue_ui.py", "ui")',
            '("ui/dashboard.py", "ui")',
            '("ui/processing_view.py", "ui")',
            '("ui/sidebar.py", "ui")',
            '("ui/timeline.py", "ui")',
            '("ui/widgets.py", "ui")',
            '("ui/styles.css", "ui")',
            '("frameforge/__init__.py", "frameforge")',
            '("frameforge/__main__.py", "frameforge")',
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
