"""Shared HTTPS download and SHA-256 verification utilities.

Consolidates the ``_download_verified()`` function that was duplicated
between ``app_update.py`` and ``updater.py``.  Both callers now import
``download_verified`` from this module.
"""

from __future__ import annotations

import hashlib
import re
import urllib.request
from pathlib import Path


def download_verified(
    url: str,
    expected_sha256: str,
    destination: Path,
    *,
    timeout: float = 60.0,
    user_agent: str = "FrameForge/1.0",
    validate_https: bool = True,
    validate_sha256_format: bool = True,
) -> None:
    """Download *url* to *destination*, verifying SHA-256 digest.

    Parameters
    ----------
    url:
        HTTPS URL to download.
    expected_sha256:
        Lowercase or mixed-case 64-char hex SHA-256 digest.
    destination:
        Target file path (overwritten on success, deleted on mismatch).
    timeout:
        Socket timeout in seconds.
    user_agent:
        ``User-Agent`` header value.
    validate_https:
        If ``True`` (default), raise ``ValueError`` when *url* is not HTTPS.
    validate_sha256_format:
        If ``True`` (default), raise ``ValueError`` when *expected_sha256*
        is not exactly 64 hex characters.
    """
    if validate_https and not url.lower().startswith("https://"):
        raise ValueError("URL phải dùng HTTPS.")
    if validate_sha256_format and not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise ValueError("Manifest có SHA-256 không hợp lệ.")

    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=timeout) as response, destination.open("wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            output.write(chunk)

    actual = digest.hexdigest().lower()
    if actual != expected_sha256.lower():
        destination.unlink(missing_ok=True)
        raise ValueError(f"SHA-256 không khớp: nhận {actual}, mong đợi {expected_sha256}.")
