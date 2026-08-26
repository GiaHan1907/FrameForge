from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StreamlitDirectoryStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
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
