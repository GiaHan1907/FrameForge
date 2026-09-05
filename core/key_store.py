"""Persistent, encrypted storage for third-party API keys.

Pexels / Pixabay / Unsplash keys were previously available only through
``FRAMEFORGE_*`` environment variables or a per-session UI input.  This
module adds optional on-disk storage that is encrypted at rest:

* Windows (the packaged app's platform): keys are encrypted with DPAPI
  (``CryptProtectData`` / ``CryptUnprotectData`` via ctypes - no extra
  dependency) and written as base64 blobs to a JSON file.  Only the same
  Windows user on the same machine can decrypt them.
* Other platforms: keys are stored in a JSON file with owner-only
  permissions (best effort; no OS keychain integration).

This module also owns the key-resolution rule used by both the engine
(``core/google_images.py``) and the UI (``ui/image_search_inline.py``):
explicit argument > ``FRAMEFORGE_*`` environment variable > stored value.
See ``resolve_api_key()``.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import app_config

STORAGE_FILENAME = "api_keys.json"
_STORAGE_SCHEMA = 1
_ENCRYPTED_ALGO = "dpapi-v1"
_PLAINTEXT_ALGO = "plaintext"

# source name -> environment variable checked before the persistent store.
# Single source of truth: engine and UI both go through resolve_api_key().
ENV_NAMES = {
    "pexels": "FRAMEFORGE_PEXELS_API_KEY",
    "pixabay": "FRAMEFORGE_PIXABAY_API_KEY",
    "unsplash": "FRAMEFORGE_UNSPLASH_ACCESS_KEY",
    "openverse": "FRAMEFORGE_OPENVERSE_TOKEN",
}

_DEFAULT_STORE: "ApiKeyStore | None" = None  # set lazily by default_store()


@dataclass(frozen=True)
class KeyResolution:
    """How a source's API key was resolved (see resolve_api_key).

    Carries everything callers need to act on the SAME rule instead of
    re-deriving it: the effective key, where it came from, the env var name
    (when origin == "env"), and the stored value (when one exists).
    """

    value: str
    origin: str  # "explicit" | "env" | "store" | "none"
    env_name: str = ""
    stored: str = ""

    @property
    def from_env(self) -> bool:
        return self.origin == "env"


def resolve_api_key(
    source: str,
    explicit: str | None = None,
    store: "ApiKeyStore | None" = None,
) -> KeyResolution:
    """Resolve a source's API key: explicit argument > env var > stored value.

    Single owner of the precedence rule (``ApiKeyStore.resolve`` delegates
    here).  ``store`` defaults to the app-wide ``default_store()`` and is
    only consulted when neither an explicit nor an env-var key applies - so
    callers that already hold a store (or want a hermetic one) pass it
    explicitly and the rule is pointed at exactly one store, never two.
    """
    source = (source or "").strip().lower()
    explicit_value = (explicit or "").strip()
    if explicit_value:
        return KeyResolution(value=explicit_value, origin="explicit")
    env_name = ENV_NAMES.get(source, "")
    if env_name:
        env_value = os.environ.get(env_name, "").strip()
        if env_value:
            return KeyResolution(value=env_value, origin="env", env_name=env_name)
    store = store or default_store()
    stored_value = store.get(source)
    if stored_value:
        return KeyResolution(value=stored_value, origin="store", stored=stored_value)
    return KeyResolution(value="", origin="none")


def default_store() -> "ApiKeyStore":
    """The app-wide store, rooted at the standard config directory."""
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = ApiKeyStore(app_config.app_config_dir())
    return _DEFAULT_STORE


# ---------------------------------------------------------------------------
# DPAPI (Windows only, via ctypes - no extra dependency)
# ---------------------------------------------------------------------------

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    def _dpapi_protect(plain: bytes) -> bytes:
        """Encrypt bytes with DPAPI (CryptProtectData), tied to user + machine."""
        buffer = ctypes.create_string_buffer(plain)
        blob_in = _DATA_BLOB(len(plain), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        blob_out = _DATA_BLOB()
        if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        ):
            raise OSError(f"DPAPI CryptProtectData failed (error {ctypes.get_last_error()})")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)

    def _dpapi_unprotect(blob: bytes) -> bytes:
        """Decrypt a DPAPI blob (CryptUnprotectData)."""
        buffer = ctypes.create_string_buffer(blob)
        blob_in = _DATA_BLOB(len(blob), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        blob_out = _DATA_BLOB()
        if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        ):
            raise OSError(f"DPAPI CryptUnprotectData failed (error {ctypes.get_last_error()})")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class ApiKeyStore:
    """Encrypted-at-rest key store, one JSON file per app install.

    ``base_dir`` is the config directory (defaults to ``app_config``'s
    standard location).  Each stored key is a small dict:

    * ``{"algo": "dpapi-v1", "data": "<base64>"}`` on Windows
    * ``{"algo": "plaintext", "data": "<value>"}`` elsewhere (file is 0600)

    Reading never raises for corrupt/undecryptable entries - it returns
    "" so a broken blob cannot crash a search.  Writing raises on I/O or
    encryption failure so callers can surface the problem.
    """

    def __init__(self, base_dir: str | Path | None = None):
        self._path = Path(base_dir or app_config.app_config_dir()) / STORAGE_FILENAME

    # -- public API ---------------------------------------------------------

    def get(self, source: str) -> str:
        """Return the stored key for ``source``, or "" when absent/unreadable."""
        source = source.strip().lower()
        entry = self._load().get(source)
        if not isinstance(entry, dict):
            return ""
        algo = entry.get("algo")
        data = entry.get("data", "")
        try:
            if algo == _ENCRYPTED_ALGO:
                blob = base64.b64decode(data)
                return _dpapi_unprotect(blob).decode("utf-8")
            if algo == _PLAINTEXT_ALGO:
                return str(data)
        except Exception:
            return ""
        return ""

    def set(self, source: str, value: str) -> None:
        """Store a key (encrypted on Windows).  Empty value deletes it."""
        source = source.strip().lower()
        value = (value or "").strip()
        entries = self._load()
        if not value:
            entries.pop(source, None)
        else:
            entries[source] = self._encrypt_entry(value)
        self._write(entries)

    def delete(self, source: str) -> None:
        """Remove a stored key (no-op when none is stored)."""
        source = source.strip().lower()
        entries = self._load()
        if source in entries:
            del entries[source]
            self._write(entries)

    def resolve(self, source: str, explicit: str | None = None) -> KeyResolution:
        """Resolve a source's API key against THIS store (see resolve_api_key).

        Convenience delegate that pins the rule to this store, so callers
        (e.g. ui/logic.search_key_rows) read stored state through exactly one
        store instead of the process-global default.
        """
        return resolve_api_key(source, explicit, store=self)

    # -- internals ----------------------------------------------------------

    def _encrypt_entry(self, value: str) -> dict[str, str]:
        if sys.platform == "win32":
            try:
                blob = _dpapi_protect(value.encode("utf-8"))
                return {
                    "algo": _ENCRYPTED_ALGO,
                    "data": base64.b64encode(blob).decode("ascii"),
                }
            except OSError:
                # DPAPI unusable (rare) - fall back to the plaintext entry
                pass
        return {"algo": _PLAINTEXT_ALGO, "data": value}

    def _load(self) -> dict[str, Any]:
        try:
            payload: Any = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(payload, dict) or payload.get("v") != _STORAGE_SCHEMA:
            return {}
        entries = payload.get("keys")
        return entries if isinstance(entries, dict) else {}

    def _write(self, entries: dict[str, Any]) -> None:
        if not entries:
            self._path.unlink(missing_ok=True)
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"v": _STORAGE_SCHEMA, "keys": entries}
        fd, temporary_name = tempfile.mkstemp(prefix="api_keys-", suffix=".tmp", dir=self._path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            temporary.replace(self._path)
            try:
                os.chmod(self._path, 0o600)
            except OSError:
                pass  # Windows ACLs already restrict access to the user
        finally:
            temporary.unlink(missing_ok=True)