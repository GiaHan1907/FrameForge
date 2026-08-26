from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_update


class AppUpdateChannelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.payload = b"installer payload"
        self.sha256 = hashlib.sha256(self.payload).hexdigest()
        self.manifest = {
            "schema": 1,
            "app": "FrameForge",
            "channel": "stable",
            "version": "0.1.6",
            "release_tag": "v0.1.6",
            "installer": "FrameForge-Setup-0.1.6.exe",
            "sha256": self.sha256,
            "installer_url": "https://github.com/GiaHan1907/FrameForge/releases/download/v0.1.6/FrameForge-Setup-0.1.6.exe",
            "signature_status": "unsigned",
            "release_notes": "# FrameForge 0.1.6\nCache and timeline improvements.",
            "release_notes_url": "https://github.com/GiaHan1907/FrameForge/releases/tag/v0.1.6",
            "rollback": {
                "version": "0.1.5",
                "sha256": "a" * 64,
                "installer_url": "https://github.com/GiaHan1907/FrameForge/releases/download/v0.1.5/FrameForge-Setup-0.1.5.exe",
            },
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_channel_manifest_and_rollback_contract(self) -> None:
        normalized = app_update._validate_manifest(self.manifest, "stable")
        self.assertEqual(normalized["channel"], "stable")
        self.assertEqual(normalized["version"], "0.1.6")
        self.assertEqual(normalized["rollback"]["version"], "0.1.5")
        with self.assertRaises(ValueError):
            app_update._validate_manifest({**self.manifest, "channel": "beta"}, "stable")
        with self.assertRaises(ValueError):
            app_update._validate_manifest({**self.manifest, "signature_status": "signed", "signer_subject": ""}, "stable")

    def test_maybe_update_preserves_release_notes_and_channel(self) -> None:
        state_path = self.root / "state.json"
        update_root = self.root / "updates"
        with patch.dict("os.environ", {"FRAMEFORGE_APP_VERSION": "0.1.0", "FRAMEFORGE_UPDATE_CHANNEL": "stable"}, clear=False), patch.object(
            app_update, "_fetch_json", return_value=self.manifest
        ), patch.object(app_update, "_state_path", return_value=state_path), patch.object(
            app_update, "_update_root", return_value=update_root
        ), patch.object(app_update, "app_data_dir", return_value=self.root):
            status = app_update.maybe_update_app(force=True, timeout=1.0, download=False)
        self.assertTrue(status.available)
        self.assertEqual(status.channel, "stable")
        self.assertIn("Cache and timeline", status.release_notes or "")
        self.assertEqual(status.rollback_version, "0.1.5")
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["channel"], "stable")
        self.assertEqual(saved["release_notes_url"], self.manifest["release_notes_url"])

    def test_rollback_pending_rejects_path_escape_and_tampering(self) -> None:
        update_root = self.root / "updates"
        update_root.mkdir()
        outside = self.root / "outside.exe"
        outside.write_bytes(self.payload)
        pending_path = update_root / app_update.ROLLBACK_PENDING_FILE_NAME
        pending_path.write_text(
            json.dumps({"version": "0.1.5", "installer_path": str(outside), "sha256": self.sha256}),
            encoding="utf-8",
        )
        with patch.object(app_update, "_update_root", return_value=update_root):
            self.assertIsNone(app_update._read_rollback_pending())
        self.assertTrue(outside.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
