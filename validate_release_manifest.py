#!/usr/bin/env python3
"""Validate a FrameForge release manifest against its installer artifact."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: validate_release_manifest.py MANIFEST SETUP TAG", file=sys.stderr)
        return 2

    manifest_path = Path(sys.argv[1])
    setup_path = Path(sys.argv[2])
    tag = sys.argv[3]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict):
        raise ValueError("latest.json must contain an object")
    if manifest.get("schema") != 1 or manifest.get("app") != "FrameForge":
        raise ValueError("Unsupported manifest schema or app name")
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError(f"Release tag must be vMAJOR.MINOR.PATCH: {tag}")
    expected_version = tag[1:]
    if manifest.get("version") != expected_version:
        raise ValueError(f"Manifest version {manifest.get('version')} does not match {expected_version}")
    if manifest.get("release_tag") != tag:
        raise ValueError("Manifest release_tag does not match Git tag")
    channel = str(manifest.get("channel") or "stable").lower()
    if channel not in {"stable", "beta"}:
        raise ValueError("Manifest channel must be stable or beta")
    signature_status = str(manifest.get("signature_status") or "unsigned").lower()
    if signature_status not in {"signed", "unsigned"}:
        raise ValueError("Manifest signature_status must be signed or unsigned")
    if signature_status == "signed" and not str(manifest.get("signer_subject") or ""):
        raise ValueError("Signed manifest must include signer_subject")
    release_notes_url = str(manifest.get("release_notes_url") or "")
    if release_notes_url and not release_notes_url.startswith("https://"):
        raise ValueError("Manifest release_notes_url must use HTTPS")
    rollback = manifest.get("rollback")
    if rollback is not None:
        if not isinstance(rollback, dict):
            raise ValueError("Manifest rollback must be an object")
        if not re.fullmatch(r"\d+\.\d+\.\d+", str(rollback.get("version") or "")):
            raise ValueError("Manifest rollback version is invalid")
        if not str(rollback.get("installer_url") or "").startswith("https://"):
            raise ValueError("Manifest rollback installer_url must use HTTPS")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", str(rollback.get("sha256") or "")):
            raise ValueError("Manifest rollback sha256 is invalid")
    if manifest.get("installer") != setup_path.name:
        raise ValueError("Manifest installer does not match artifact filename")
    installer_url = str(manifest.get("installer_url") or "")
    expected_url = f"https://github.com/GiaHan1907/FrameForge/releases/download/{tag}/{setup_path.name}"
    if installer_url != expected_url:
        raise ValueError(f"Manifest installer_url is not canonical: {installer_url}")
    expected_sha = str(manifest.get("sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ValueError("Manifest sha256 is invalid")
    digest = hashlib.sha256()
    with setup_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_sha = digest.hexdigest().lower()
    if actual_sha != expected_sha:
        raise ValueError(f"Installer SHA-256 mismatch: {actual_sha} != {expected_sha}")
    print(f"Manifest OK: {tag} / {setup_path.name} / {actual_sha}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Manifest validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
