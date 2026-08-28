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
ROLLBACK_PENDING_FILE_NAME = "rollback_pending.json"
CHANNEL_FILE_NAME = "update_channel.json"
DEFAULT_BETA_MANIFEST_URL = "https://github.com/GiaHan1907/FrameForge/releases/latest/download/latest-beta.json"


def _hidden_windows_process_kwargs() -> dict[str, object]:
    """Ẩn console của process con trên Windows; không truyền cờ này trên POSIX."""
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
SUPPORTED_CHANNELS = {"stable", "beta"}


@dataclass
class AppUpdateStatus:
    current_version: str
    latest_version: str | None
    checked: bool
    available: bool
    downloaded: bool
    installer_path: str | None
    message: str
    channel: str = "stable"
    release_notes: str | None = None
    release_notes_url: str | None = None
    rollback_version: str | None = None
    rollback_available: bool = False


def _atomic_write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


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


def _channel_path() -> Path:
    return app_data_dir() / CHANNEL_FILE_NAME


def normalize_channel(value: str | None) -> str:
    normalized = str(value or "stable").strip().lower()
    return normalized if normalized in SUPPORTED_CHANNELS else "stable"


def get_update_channel() -> str:
    configured = os.environ.get("FRAMEFORGE_UPDATE_CHANNEL")
    if configured:
        return normalize_channel(configured)
    value = _read_json(_channel_path())
    return normalize_channel(str(value.get("channel")) if value else "stable")


def set_update_channel(channel: str) -> str:
    normalized = normalize_channel(channel)
    _atomic_write_json(_channel_path(), {"version": 1, "channel": normalized, "updated_at": time.time()})
    return normalized


def _manifest_url(channel: str | None = None) -> str:
    override = os.environ.get("FRAMEFORGE_UPDATE_MANIFEST_URL")
    if override:
        return override.strip()
    return DEFAULT_BETA_MANIFEST_URL if normalize_channel(channel or get_update_channel()) == "beta" else DEFAULT_MANIFEST_URL


def _validate_manifest(manifest: dict[str, object], channel: str) -> dict[str, object]:
    if manifest.get("schema") != 1:
        raise ValueError("Manifest có schema không được hỗ trợ.")
    if manifest.get("app") != "FrameForge":
        raise ValueError("Manifest không thuộc ứng dụng FrameForge.")
    latest = str(manifest.get("version") or "")
    installer_url = str(manifest.get("installer_url") or "")
    sha256 = str(manifest.get("sha256") or "")
    installer_name = Path(str(manifest.get("installer") or "FrameForge-Setup.exe")).name
    if not re.fullmatch(r"\d+\.\d+\.\d+", latest):
        raise ValueError("Manifest có version không hợp lệ.")
    if installer_name != f"FrameForge-Setup-{latest}.exe":
        raise ValueError("Tên installer không khớp version trong manifest.")
    if not installer_url.lower().startswith("https://"):
        raise ValueError("Manifest có installer URL không dùng HTTPS.")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        raise ValueError("Manifest có SHA-256 không hợp lệ.")
    release_tag = manifest.get("release_tag")
    if release_tag is not None and release_tag != f"v{latest}":
        raise ValueError("release_tag không khớp version trong manifest.")
    raw_channel = str(manifest.get("channel") or channel).strip().lower()
    if raw_channel not in SUPPORTED_CHANNELS or raw_channel != normalize_channel(channel):
        raise ValueError("Manifest channel không khớp kênh đang chọn.")
    manifest_channel = raw_channel
    signature_status = str(manifest.get("signature_status") or "unsigned").strip().lower()
    if signature_status not in {"signed", "unsigned"}:
        raise ValueError("signature_status không hợp lệ.")
    signer_subject = str(manifest.get("signer_subject") or "") or None
    if signature_status == "signed" and not signer_subject:
        raise ValueError("Manifest signed phải có signer_subject.")
    release_notes_url = str(manifest.get("release_notes_url") or "") or None
    if release_notes_url and not release_notes_url.lower().startswith("https://"):
        raise ValueError("release_notes_url phải dùng HTTPS.")
    rollback = manifest.get("rollback")
    if rollback is not None:
        if not isinstance(rollback, dict):
            raise ValueError("Rollback metadata không hợp lệ.")
        rollback_version = str(rollback.get("version") or "")
        rollback_url = str(rollback.get("installer_url") or "")
        rollback_sha = str(rollback.get("sha256") or "")
        if not re.fullmatch(r"\d+\.\d+\.\d+", rollback_version):
            raise ValueError("Rollback version không hợp lệ.")
        if not rollback_url.lower().startswith("https://") or not re.fullmatch(r"[0-9a-fA-F]{64}", rollback_sha):
            raise ValueError("Rollback URL hoặc SHA-256 không hợp lệ.")
    return {
        "version": latest,
        "installer_url": installer_url,
        "sha256": sha256.lower(),
        "installer": installer_name,
        "channel": manifest_channel,
        "signature_status": signature_status,
        "signer_subject": signer_subject,
        "release_notes": str(manifest.get("release_notes") or "")[:12000] or None,
        "release_notes_url": release_notes_url,
        "rollback": rollback if isinstance(rollback, dict) else None,
    }


def _sha256_file(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest().lower()


def _authenticode_valid(path: Path) -> bool:
    """Kiểm tra chữ ký Authenticode bằng PowerShell khi chạy trên Windows."""
    if sys.platform != "win32":
        return False
    escaped = str(path).replace("'", "''")
    command = f"(Get-AuthenticodeSignature -LiteralPath '{escaped}').Status"
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            **_hidden_windows_process_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip().lower() == "valid"


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
    if not isinstance(value, dict):
        return None
    installer_path = Path(str(value.get("installer_path") or ""))
    update_root = _update_root().resolve()
    try:
        installer_path.resolve().relative_to(update_root)
    except ValueError:
        path.unlink(missing_ok=True)
        return None
    return value


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
        elif (
            version
            and path.is_file()
            and re.fullmatch(r"[0-9a-fA-F]{64}", sha256)
            and _sha256_file(path) == sha256.lower()
            and (str(pending.get("signature_status") or "unsigned").lower() != "signed" or _authenticode_valid(path))
        ):
            return AppUpdateStatus(
                current, version, True, True, True, str(path), "Đã tải Setup mới và chờ người dùng cài đặt.",
                normalize_channel(str(pending.get("channel") or get_update_channel())),
                str(pending.get("release_notes") or "") or None,
                str(pending.get("release_notes_url") or "") or None,
            )
        elif pending:
            # Không mở lại file pending đã bị sửa, thiếu hoặc có metadata hỏng.
            pending_path.unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            pending = None
    try:
        state = json.loads(_state_path().read_text(encoding="utf-8"))
        rollback = state.get("rollback") if isinstance(state.get("rollback"), dict) else None
        return AppUpdateStatus(
            current,
            str(state.get("latest_version")) if state.get("latest_version") else None,
            False,
            bool(state.get("available")),
            False,
            None,
            str(state.get("message") or "Chưa kiểm tra cập nhật."),
            normalize_channel(str(state.get("channel") or get_update_channel())),
            str(state.get("release_notes") or "") or None,
            str(state.get("release_notes_url") or "") or None,
            str(rollback.get("version")) if rollback else None,
            bool(rollback),
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
                rollback = state.get("rollback") if isinstance(state.get("rollback"), dict) else None
                return AppUpdateStatus(
                    current, state.get("latest_version"), False, bool(state.get("available")), False, None,
                    "Đã kiểm tra cập nhật gần đây.", normalize_channel(str(state.get("channel") or get_update_channel())),
                    str(state.get("release_notes") or "") or None, str(state.get("release_notes_url") or "") or None,
                    str(rollback.get("version")) if rollback else None, bool(rollback),
                )
        except (OSError, ValueError, TypeError):
            pass

    channel = get_update_channel()
    manifest_url = _manifest_url(channel)
    if not manifest_url:
        return AppUpdateStatus(current, None, False, False, False, None, "Chưa cấu hình update feed công khai cho ứng dụng.", channel=channel)
    try:
        manifest = _fetch_json(manifest_url, timeout=timeout)
        normalized = _validate_manifest(manifest, channel)
        latest = str(normalized["version"])
        installer_url = str(normalized["installer_url"])
        sha256 = str(normalized["sha256"])
        installer_name = str(normalized["installer"])
        available = _version_key(latest) > _version_key(current)
        rollback = normalized.get("rollback") if isinstance(normalized.get("rollback"), dict) else None
        state = {
            "checked_at": time.time(),
            "latest_version": latest,
            "available": available,
            "channel": channel,
            "signature_status": normalized.get("signature_status", "unsigned"),
            "signer_subject": normalized.get("signer_subject"),
            "release_notes": normalized.get("release_notes"),
            "release_notes_url": normalized.get("release_notes_url"),
            "rollback": rollback,
            "message": "Có bản cập nhật mới." if available else "Ứng dụng đã là phiên bản mới nhất.",
        }
        _atomic_write_json(state_path, state)
        if not available:
            return AppUpdateStatus(current, latest, True, False, False, None, str(state["message"]), channel, normalized.get("release_notes"), normalized.get("release_notes_url"), str(rollback.get("version")) if rollback else None, bool(rollback))
        if not download:
            return AppUpdateStatus(current, latest, True, True, False, None, "Có bản cập nhật mới. Nhấn Cập nhật ngay để tải và cài đặt.", channel, normalized.get("release_notes"), normalized.get("release_notes_url"), str(rollback.get("version")) if rollback else None, bool(rollback))

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
        pending = {
            "version": latest,
            "installer_path": str(target),
            "sha256": sha256.lower(),
            "channel": channel,
            "signature_status": normalized.get("signature_status", "unsigned"),
            "signer_subject": normalized.get("signer_subject"),
            "release_notes": normalized.get("release_notes"),
            "release_notes_url": normalized.get("release_notes_url"),
        }
        _atomic_write_json(update_root / PENDING_FILE_NAME, pending)
        return AppUpdateStatus(current, latest, True, True, True, str(target), "Đã tải và xác minh Setup mới; hãy bấm cài đặt khi sẵn sàng.", channel, normalized.get("release_notes"), normalized.get("release_notes_url"), str(rollback.get("version")) if rollback else None, bool(rollback))
    except (OSError, ValueError, urllib.error.URLError, TimeoutError) as exc:
        message = f"Không kiểm tra được bản cập nhật ứng dụng: {exc}"
        _atomic_write_json(state_path, {"checked_at": time.time(), "available": False, "channel": channel if 'channel' in locals() else get_update_channel(), "message": message})
        return AppUpdateStatus(current, None, True, False, False, None, message)


def _rollback_pending_path() -> Path:
    return _update_root() / ROLLBACK_PENDING_FILE_NAME


def _read_rollback_pending() -> dict[str, object] | None:
    value = _read_json(_rollback_pending_path())
    if not value:
        return None
    path = Path(str(value.get("installer_path") or ""))
    sha256 = str(value.get("sha256") or "")
    update_root = _update_root().resolve()
    try:
        path.resolve().relative_to(update_root)
    except ValueError:
        _rollback_pending_path().unlink(missing_ok=True)
        return None
    signature_status = str(value.get("signature_status") or "unsigned").lower()
    if not path.is_file() or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256) or _sha256_file(path) != sha256.lower() or (signature_status == "signed" and not _authenticode_valid(path)):
        _rollback_pending_path().unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        return None
    return value


def rollback_app_now(timeout: float = 10.0) -> AppUpdateStatus:
    """Tải và xác minh bản rollback được workflow ghi trong manifest."""
    status = maybe_update_app(force=True, timeout=timeout, download=False)
    state = _read_json(_state_path()) or {}
    rollback = state.get("rollback") if isinstance(state.get("rollback"), dict) else None
    if not rollback:
        return AppUpdateStatus(
            status.current_version, status.latest_version, status.checked, status.available, False, None,
            "Manifest không cung cấp bản rollback an toàn.", status.channel, status.release_notes,
            status.release_notes_url, None, False,
        )
    version = str(rollback.get("version") or "")
    url = str(rollback.get("installer_url") or "")
    sha256 = str(rollback.get("sha256") or "").lower()
    signature_status = str(rollback.get("signature_status") or "unsigned").lower()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or not url.lower().startswith("https://") or not re.fullmatch(r"[0-9a-f]{64}", sha256) or signature_status not in {"signed", "unsigned"}:
        return AppUpdateStatus(
            status.current_version, status.latest_version, status.checked, status.available, False, None,
            "Metadata rollback không hợp lệ.", status.channel, status.release_notes, status.release_notes_url,
            None, False,
        )
    existing = _read_rollback_pending()
    if existing and str(existing.get("version")) == version:
        return AppUpdateStatus(
            status.current_version, status.latest_version, status.checked, status.available, True,
            str(existing.get("installer_path")), "Đã tải và xác minh bản rollback; hãy bấm mở installer.",
            status.channel, status.release_notes, status.release_notes_url, version, True,
        )
    update_root = _update_root()
    update_root.mkdir(parents=True, exist_ok=True)
    target = update_root / f"FrameForge-Setup-{version}.exe"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="FrameForge-Rollback-", suffix=".tmp", dir=update_root, delete=False) as temporary:
            temporary_path = Path(temporary.name)
        _download_verified(url, sha256, temporary_path, timeout=max(timeout, 60.0))
        target.unlink(missing_ok=True)
        temporary_path.replace(target)
        _atomic_write_json(_rollback_pending_path(), {
            "version": version,
            "installer_path": str(target),
            "sha256": sha256,
            "signature_status": signature_status,
            "signer_subject": rollback.get("signer_subject"),
        })
        return AppUpdateStatus(
            status.current_version, status.latest_version, status.checked, status.available, True, str(target),
            "Đã tải và xác minh bản rollback; hãy bấm mở installer.", status.channel, status.release_notes,
            status.release_notes_url, version, True,
        )
    except (OSError, ValueError, urllib.error.URLError, TimeoutError) as exc:
        return AppUpdateStatus(
            status.current_version, status.latest_version, status.checked, status.available, False, None,
            f"Không thể tải rollback: {exc}", status.channel, status.release_notes, status.release_notes_url,
            version, True,
        )
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def launch_rollback_installer() -> bool:
    pending = _read_rollback_pending()
    if not pending:
        return False
    path = Path(str(pending.get("installer_path") or ""))
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen([str(path)])
    return True


def initialize_app_update() -> AppUpdateStatus:
    # Mỗi lần mở app đều kiểm tra manifest; không tự tải/chạy EXE từ Internet.
    if os.environ.get("FRAMEFORGE_APP_UPDATE_STARTUP", "1").lower() in {"0", "false", "no", "off"}:
        return AppUpdateStatus(
            current_app_version(), None, False, False, False, None, "Kiểm tra cập nhật lúc khởi động đang tắt."
        )
    return maybe_update_app(force=True, timeout=5.0, download=False)


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
    sha256 = str(pending.get("sha256") or "")
    if not path.is_file() or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256) or _sha256_file(path) != sha256.lower():
        _update_root().joinpath(PENDING_FILE_NAME).unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        return False
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen([str(path)])
    return True
