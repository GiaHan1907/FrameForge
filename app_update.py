from __future__ import annotations

import hashlib
import json
import os
import subprocess
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MANIFEST_URL = "https://github.com/GiaHan1907/FrameForge/releases/latest/download/latest.json"
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
APP_UPDATE_DIR_NAME = "app_updates"
STATE_FILE_NAME = "app_update_check.json"
PENDING_FILE_NAME = "pending.json"


@dataclass
class AppUpdateStatus:
    current_version: str
    latest_version: str | None
    checked: bool
    available: bool
    downloaded: bool
    installer_path: str | None
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


def current_app_version() -> str:
    explicit = os.environ.get("FRAMEFORGE_APP_VERSION")
    if explicit:
        return explicit.strip()
    roots = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(str(meipass)))
    roots.append(Path(__file__).resolve().parent)
    for root in roots:
        version_file = root / "frameforge_version.txt"
        try:
            value = version_file.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if re.fullmatch(r"\d+\.\d+\.\d+", value):
            return value
    return "0.0.0"


def _update_root() -> Path:
    root = app_data_dir() / APP_UPDATE_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _state_path() -> Path:
    return app_data_dir() / STATE_FILE_NAME


def _fetch_json(url: str, timeout: float = 10.0) -> dict[str, object]:
    if not url.lower().startswith("https://"):
        raise ValueError("Update manifest phải dùng HTTPS.")
    request = urllib.request.Request(url, headers={"User-Agent": "FrameForge-App-Updater/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    value = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Update manifest không có định dạng object.")
    return value


def _manifest_url() -> str:
    return os.environ.get("FRAMEFORGE_UPDATE_MANIFEST_URL", DEFAULT_MANIFEST_URL).strip()


def _download_verified(url: str, expected_sha256: str, destination: Path, timeout: float = 60.0) -> None:
    if not url.lower().startswith("https://"):
        raise ValueError("Installer URL phải dùng HTTPS.")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise ValueError("Manifest có SHA-256 không hợp lệ.")
    request = urllib.request.Request(url, headers={"User-Agent": "FrameForge-App-Updater/1.0"})
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


def _read_pending() -> dict[str, object] | None:
    path = _update_root() / PENDING_FILE_NAME
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def read_app_update_status() -> AppUpdateStatus:
    pending = _read_pending()
    current = current_app_version()
    pending_path = _update_root() / PENDING_FILE_NAME
    if pending:
        path = Path(str(pending.get("installer_path") or ""))
        version = str(pending.get("version") or "")
        sha256 = str(pending.get("sha256") or "")
        if version and _version_key(version) <= _version_key(current):
            # Bản cập nhật đã được cài đặt; không nhắc lại Setup cũ.
            pending_path.unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            pending = None
        elif version and path.is_file() and re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
            return AppUpdateStatus(current, version, True, True, True, str(path), "Đã tải Setup mới và chờ người dùng cài đặt.")
    try:
        state = json.loads(_state_path().read_text(encoding="utf-8"))
        return AppUpdateStatus(
            current,
            str(state.get("latest_version")) if state.get("latest_version") else None,
            False,
            bool(state.get("available")),
            False,
            None,
            str(state.get("message") or "Chưa kiểm tra cập nhật."),
        )
    except (OSError, ValueError, TypeError):
        return AppUpdateStatus(current, None, False, False, False, None, "Chưa kiểm tra cập nhật.")


def maybe_update_app(force: bool = False, timeout: float = 10.0, download: bool = True) -> AppUpdateStatus:
    current = current_app_version()
    if os.environ.get("FRAMEFORGE_APP_UPDATE", "1").lower() in {"0", "false", "no", "off"}:
        return AppUpdateStatus(current, None, False, False, False, None, "Auto-update ứng dụng đang tắt.")

    existing = read_app_update_status()
    if existing.downloaded and existing.installer_path:
        return existing

    state_path = _state_path()
    if not force and state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            checked_at = float(state.get("checked_at", 0))
            if checked_at + CHECK_INTERVAL_SECONDS > time.time():
                return AppUpdateStatus(current, state.get("latest_version"), False, bool(state.get("available")), False, None, "Đã kiểm tra cập nhật gần đây.")
        except (OSError, ValueError, TypeError):
            pass

    manifest_url = _manifest_url()
    if not manifest_url:
        return AppUpdateStatus(current, None, False, False, False, None, "Chưa cấu hình update feed công khai cho ứng dụng.")
    try:
        manifest = _fetch_json(manifest_url, timeout=timeout)
        latest = str(manifest.get("version") or "")
        installer_url = str(manifest.get("installer_url") or "")
        sha256 = str(manifest.get("sha256") or "")
        installer_name = Path(str(manifest.get("installer") or "FrameForge-Setup.exe")).name
        if not re.fullmatch(r"\d+\.\d+\.\d+", latest):
            raise ValueError("Manifest có version không hợp lệ.")
        if not installer_name.lower().endswith(".exe"):
            raise ValueError("Manifest không trỏ tới installer .exe.")
        available = _version_key(latest) > _version_key(current)
        state = {
            "checked_at": time.time(),
            "latest_version": latest,
            "available": available,
            "message": "Có bản cập nhật mới." if available else "Ứng dụng đã là phiên bản mới nhất.",
        }
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        if not available:
            return AppUpdateStatus(current, latest, True, False, False, None, str(state["message"]))
        if not download:
            return AppUpdateStatus(current, latest, True, True, False, None, "Có bản cập nhật mới. Nhấn Cập nhật ngay để tải và cài đặt.")

        update_root = _update_root()
        target = update_root / installer_name
        with tempfile.NamedTemporaryFile(prefix="FrameForge-Setup-", suffix=".tmp", dir=update_root, delete=False) as temporary:
            temporary_path = Path(temporary.name)
        try:
            _download_verified(installer_url, sha256, temporary_path, timeout=max(timeout, 60.0))
            if target.exists():
                target.unlink()
            temporary_path.replace(target)
        finally:
            temporary_path.unlink(missing_ok=True)
        pending = {"version": latest, "installer_path": str(target), "sha256": sha256.lower()}
        (update_root / PENDING_FILE_NAME).write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
        return AppUpdateStatus(current, latest, True, True, True, str(target), "Đã tải và xác minh Setup mới; hãy bấm cài đặt khi sẵn sàng.")
    except (OSError, ValueError, urllib.error.URLError, TimeoutError) as exc:
        message = f"Không kiểm tra được bản cập nhật ứng dụng: {exc}"
        state_path.write_text(json.dumps({"checked_at": time.time(), "available": False, "message": message}, ensure_ascii=False, indent=2), encoding="utf-8")
        return AppUpdateStatus(current, None, True, False, False, None, message)


def initialize_app_update() -> AppUpdateStatus:
    # Startup chỉ kiểm tra manifest; không tự tải/chạy EXE từ Internet.
    return maybe_update_app(download=False)


def update_app_now(timeout: float = 10.0) -> AppUpdateStatus:
    """Tải, xác minh và mở Setup mới trong một thao tác người dùng."""
    status = maybe_update_app(force=True, timeout=timeout, download=True)
    if status.downloaded and status.installer_path and launch_pending_installer():
        return AppUpdateStatus(
            status.current_version,
            status.latest_version,
            status.checked,
            status.available,
            True,
            status.installer_path,
            "Đã xác minh và mở Setup mới. Hãy hoàn tất trình cài đặt rồi khởi động lại FrameForge.",
        )
    if status.downloaded:
        return AppUpdateStatus(
            status.current_version,
            status.latest_version,
            status.checked,
            status.available,
            True,
            status.installer_path,
            "Đã tải và xác minh Setup mới nhưng chưa thể mở trình cài đặt.",
        )
    return status


def launch_pending_installer() -> bool:
    pending = _read_pending()
    if not pending:
        return False
    path = Path(str(pending.get("installer_path") or ""))
    if not path.is_file():
        return False
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen([str(path)])
    return True
