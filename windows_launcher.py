from __future__ import annotations

import os
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


HOST = "localhost"
PORT = 8501
URL = f"http://{HOST}:{PORT}"


def write_failure_log(error: BaseException) -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "VideoScreenshotFilter"
    base.mkdir(parents=True, exist_ok=True)
    log_path = base / "launcher_error.log"
    log_path.write_text(
        "VideoScreenshotFilter launcher error\n\n" + traceback.format_exc(),
        encoding="utf-8",
    )
    return log_path


def show_failure_message(error: BaseException, log_path: Path) -> None:
    message = (
        "VideoScreenshotFilter không thể khởi động.\n\n"
        f"{type(error).__name__}: {error}\n\n"
        f"Log: {log_path}"
    )
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, "VideoScreenshotFilter", 0x10)
            return
        except Exception:
            pass
    print(message, file=sys.stderr)


def open_browser_when_ready(url: str, timeout: float = 45.0) -> None:
    """Mở trình duyệt sau khi endpoint Streamlit phản hồi."""
    if os.environ.get("FRAMEFORGE_NO_BROWSER", "").lower() in {"1", "true", "yes", "on"}:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                if 200 <= response.status < 500:
                    webbrowser.open_new_tab(url)
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.5)


def main() -> None:
    # PyInstaller one-file giải nén data vào _MEIPASS; khi chạy source dùng thư mục hiện tại.
    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    app_path = base_dir / "streamlit_app.py"
    if str(base_dir) not in sys.path:
        sys.path.insert(0, str(base_dir))
    if not app_path.exists():
        raise FileNotFoundError(f"Không tìm thấy Streamlit app: {app_path}")

    # Kích hoạt bản yt-dlp đã xác minh từ lần trước và kiểm tra bản mới tối đa mỗi 24 giờ.
    # FRAMEFORGE_AUTO_UPDATE=0 cho phép người dùng tắt hoàn toàn updater.
    try:
        from updater import initialize_yt_dlp
        update_status = initialize_yt_dlp(
            auto_update=os.environ.get("FRAMEFORGE_AUTO_UPDATE", "1").lower() not in {"0", "false", "no", "off"}
        )
        update_log_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "VideoScreenshotFilter"
        update_log_dir.mkdir(parents=True, exist_ok=True)
        (update_log_dir / "yt_dlp_update.log").write_text(
            f"current={update_status.current_version}\n"
            f"latest={update_status.latest_version}\n"
            f"updated={update_status.updated}\n"
            f"activated={update_status.activated_version}\n"
            f"message={update_status.message}\n",
            encoding="utf-8",
        )
    except Exception as update_error:
        # Updater không được phép làm app không khởi động; chỉ ghi log để chẩn đoán.
        update_log_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "VideoScreenshotFilter"
        update_log_dir.mkdir(parents=True, exist_ok=True)
        (update_log_dir / "yt_dlp_update.log").write_text(
            f"updater_error={type(update_error).__name__}: {update_error}\n",
            encoding="utf-8",
        )

    # Không đặt server.port: Streamlit trong PyInstaller có thể nhận diện development mode.
    # Server mặc định dùng cổng 8501; thread bên dưới chỉ mở browser sau khi server sẵn sàng.
    os.environ["FRAMEFORGE_DESKTOP_LIFECYCLE"] = "1"
    os.environ["FRAMEFORGE_DESKTOP_PID"] = str(os.getpid())
    os.environ["STREAMLIT_GLOBAL_DEVELOPMENTMODE"] = "false"
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    os.environ["STREAMLIT_SERVER_ADDRESS"] = HOST

    threading.Thread(target=open_browser_when_ready, args=(URL,), daemon=True).start()

    import streamlit.config as st_config
    # Trong PyInstaller, __file__ của Streamlit nằm trong _MEIPASS nên
    # Streamlit tự suy ra developmentMode=True. Ép false trước khi parse CLI.
    st_config.set_option("global.developmentMode", False)

    from streamlit.web import cli as stcli

    sys.argv = [
        "streamlit",
        "run",
        str(app_path),
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
        "--global.developmentMode=false",
    ]
    raise SystemExit(stcli.main())


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        log_path = write_failure_log(error)
        show_failure_message(error, log_path)
        raise SystemExit(1)
