from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

PYPI_JSON_URL = "https://pypi.org/pypi/yt-dlp/json"
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
UPDATE_DIR_NAME = "yt_dlp_updates"
POINTER_NAME = "current.json"


@dataclass
class UpdateStatus:
    current_version: str
    latest_version: str | None
    checked: bool
    updated: bool
    activated_version: str | None
    message: str


def app_data_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    directory = root / "VideoScreenshotFilter"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _version_key(value: str | None) -> tuple[int, ...]:
    if not value:
        return (0,)
    numbers = re.findall(r"\d+", str(value))
    return tuple(int(number) for number in numbers) or (0,)


def _current_version() -> str:
    try:
        import yt_dlp
        version = getattr(yt_dlp, "__version__", None)
        if version:
            return str(version)
        from yt_dlp.version import __version__
        return str(__version__)
    except Exception:
        return "unknown"


def _update_root() -> Path:
    root = app_data_dir() / UPDATE_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _read_pointer() -> dict[str, object] | None:
    path = _update_root() / POINTER_NAME
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def activate_yt_dlp_override() -> str | None:
    """Chèn override đã xác thực vào sys.path trước khi import yt_dlp."""
    pointer = _read_pointer()
    if not pointer:
        return None
    version = str(pointer.get("version") or "")
    package_dir = Path(str(pointer.get("package_dir") or ""))
    marker = package_dir / "yt_dlp" / "__init__.py"
    if not version or not marker.exists():
        return None
    path_value = str(package_dir)
    if path_value not in sys.path:
        sys.path.insert(0, path_value)
    return version


def _fetch_json(url: str, timeout: float = 8.0) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "FrameForge-yt-dlp-updater/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("PyPI metadata không có định dạng object.")
    return value


def latest_yt_dlp_metadata(timeout: float = 8.0) -> tuple[str, dict[str, object]]:
    metadata = _fetch_json(PYPI_JSON_URL, timeout=timeout)
    info = metadata.get("info")
    if not isinstance(info, dict) or not info.get("version"):
        raise ValueError("Không đọc được phiên bản yt-dlp từ PyPI.")
    version = str(info["version"])
    return version, metadata


def _choose_pure_wheel(metadata: dict[str, object], version: str) -> tuple[str, str]:
    releases = metadata.get("releases")
    if not isinstance(releases, dict):
        raise ValueError("PyPI metadata không có danh sách release.")
    files = releases.get(version)
    if not isinstance(files, list):
        raise ValueError(f"Không có file release cho yt-dlp {version}.")
    for item in files:
        if not isinstance(item, dict):
            continue
        filename = str(item.get("filename") or "")
        digest = item.get("digests")
        sha256 = digest.get("sha256") if isinstance(digest, dict) else None
        if filename.endswith("-py3-none-any.whl") and isinstance(sha256, str) and len(sha256) == 64:
            url = str(item.get("url") or "")
            if url:
                return url, sha256
    raise ValueError("Không tìm thấy wheel py3-none-any có SHA-256.")


def _download_verified(url: str, expected_sha256: str, destination: Path, timeout: float = 30.0) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "FrameForge-yt-dlp-updater/1.0"})
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


def _install_wheel(version: str, wheel_path: Path) -> Path:
    root = _update_root()
    staging = Path(tempfile.mkdtemp(prefix=f"yt_dlp_{version}_", dir=root))
    try:
        with zipfile.ZipFile(wheel_path) as archive:
            names = archive.namelist()
            if not any(name.startswith("yt_dlp/") and name.endswith("__init__.py") for name in names):
                raise ValueError("Wheel không chứa package yt_dlp hợp lệ.")
            staging_root = staging.resolve()
            for name in names:
                target = (staging / name).resolve()
                if target != staging_root and staging_root not in target.parents:
                    raise ValueError("Wheel chứa đường dẫn không an toàn.")
            archive.extractall(staging)
        package_marker = staging / "yt_dlp" / "__init__.py"
        if not package_marker.exists():
            raise ValueError("Package yt_dlp không được giải nén đúng cấu trúc.")
        target = root / version
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
        return target
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _write_pointer(version: str, package_dir: Path, sha256: str) -> None:
    root = _update_root()
    pointer = root / POINTER_NAME
    temporary = root / f"{POINTER_NAME}.tmp"
    payload = {
        "version": version,
        "package_dir": str(package_dir),
        "sha256": sha256,
    }
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, pointer)


def maybe_update_yt_dlp(force: bool = False, timeout: float = 8.0) -> UpdateStatus:
    activated = activate_yt_dlp_override()
    current = _current_version()
    state_file = app_data_dir() / "yt_dlp_update_check.json"
    if not force and state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            checked_at = float(state.get("checked_at", 0))
            if (os.path.getmtime(state_file) + CHECK_INTERVAL_SECONDS) > __import__("time").time():
                return UpdateStatus(current, state.get("latest_version"), False, False, activated, "Đã kiểm tra gần đây.")
        except (OSError, ValueError, TypeError):
            pass
    if os.environ.get("FRAMEFORGE_AUTO_UPDATE", "1").lower() in {"0", "false", "no", "off"}:
        return UpdateStatus(current, None, False, False, activated, "Auto-update đang tắt.")
    try:
        latest, metadata = latest_yt_dlp_metadata(timeout=timeout)
        state_file.write_text(json.dumps({"checked_at": __import__("time").time(), "latest_version": latest}), encoding="utf-8")
        if _version_key(latest) <= _version_key(current):
            return UpdateStatus(current, latest, True, False, activated, "yt-dlp đã là phiên bản mới nhất.")
        url, sha256 = _choose_pure_wheel(metadata, latest)
        root = _update_root()
        with tempfile.NamedTemporaryFile(prefix="yt_dlp_", suffix=".whl", dir=root, delete=False) as temporary:
            wheel_path = Path(temporary.name)
        try:
            _download_verified(url, sha256, wheel_path, timeout=max(timeout, 30.0))
            installed = _install_wheel(latest, wheel_path)
            _write_pointer(latest, installed, sha256)
        finally:
            wheel_path.unlink(missing_ok=True)
        return UpdateStatus(current, latest, True, True, latest, "Đã tải và xác minh bản cập nhật; sẽ áp dụng từ lần chạy kế tiếp.")
    except (OSError, ValueError, urllib.error.URLError, TimeoutError) as exc:
        return UpdateStatus(current, None, True, False, activated, f"Không cập nhật yt-dlp: {exc}")


def initialize_yt_dlp(auto_update: bool = True) -> UpdateStatus:
    activated = activate_yt_dlp_override()
    current = _current_version()
    if not auto_update:
        return UpdateStatus(current, None, False, False, activated, "Auto-update đang tắt.")
    return maybe_update_yt_dlp()
