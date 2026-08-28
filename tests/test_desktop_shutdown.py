import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


class DesktopShutdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_terminate_desktop_process_tree"
        )
        namespace = {"os": os, "sys": sys, "subprocess": subprocess}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "streamlit_app.py", "exec"), namespace)
        cls.terminate = namespace["_terminate_desktop_process_tree"]

    def test_non_windows_does_not_spawn_taskkill(self):
        original_platform = sys.platform
        original_popen = subprocess.Popen
        try:
            sys.platform = "linux"
            subprocess.Popen = Mock()
            type(self).terminate()
            subprocess.Popen.assert_not_called()
        finally:
            sys.platform = original_platform
            subprocess.Popen = original_popen

    def test_windows_kills_current_tree_without_console(self):
        original_platform = sys.platform
        original_popen = subprocess.Popen
        original_pid = os.getpid
        try:
            sys.platform = "win32"
            os.environ.pop("FRAMEFORGE_DESKTOP_PID", None)
            os.getpid = lambda: 4321
            subprocess.Popen = Mock()
            type(self).terminate()
            subprocess.Popen.assert_called_once()
            args, kwargs = subprocess.Popen.call_args
            self.assertEqual(args[0], ["taskkill.exe", "/PID", "4321", "/T", "/F"])
            self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
            self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
            self.assertEqual(kwargs["creationflags"], 0x08000000)
        finally:
            sys.platform = original_platform
            os.getpid = original_pid
            subprocess.Popen = original_popen
            os.environ.pop("FRAMEFORGE_DESKTOP_PID", None)

    def test_windows_pid_guard_prevents_killing_other_process(self):
        original_platform = sys.platform
        original_popen = subprocess.Popen
        original_pid = os.getpid
        try:
            sys.platform = "win32"
            os.environ["FRAMEFORGE_DESKTOP_PID"] = "9999"
            os.getpid = lambda: 4321
            subprocess.Popen = Mock()
            type(self).terminate()
            subprocess.Popen.assert_not_called()
        finally:
            sys.platform = original_platform
            os.getpid = original_pid
            subprocess.Popen = original_popen
            os.environ.pop("FRAMEFORGE_DESKTOP_PID", None)


if __name__ == "__main__":
    unittest.main()
