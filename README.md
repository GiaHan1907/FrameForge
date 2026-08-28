# FrameForge

FrameForge là ứng dụng Streamlit và CLI dùng để trích xuất screenshot từ video, phát hiện scene, lọc frame mờ/trùng và xử lý queue nhiều video trên Windows, Linux và macOS.

## Tính năng chính

| Nhóm | Tính năng |
|---|---|
| Trích xuất frame | Best frame per scene, mỗi N giây hoặc đúng N frame |
| Scene detection | Phát hiện scene change, chống flash và preview scene thật |
| Lọc chất lượng | Sharpness chuẩn hóa, motion blur, duplicate detection bằng dHash |
| Crop/đầu ra | Tỉ lệ `16:9`, `9:16`, `4:5`, `1:1`, encode profile nhanh/chất lượng cao |
| Queue | SQLite persistence, pause/resume/cancel/retry, checkpoint và crash recovery |
| Downloader | Hỗ trợ URL công khai qua yt-dlp, retry exponential backoff và staging an toàn |
| Desktop | Installer Inno Setup, auto-update, FFmpeg nhúng, silent console và auto-shutdown |

## Ba bản cập nhật gần nhất

### v0.1.32 — Desktop auto-shutdown watchdog

Khi browser session cuối cùng đóng trên bản desktop, watchdog hủy job an toàn, dừng Streamlit và kết thúc đúng `VideoScreenshotFilter.exe` cùng process con bằng `taskkill /PID /T /F`. PID guard ngăn kill nhầm process khác; lệnh kill chạy với `CREATE_NO_WINDOW`. Bổ sung unit test watchdog và script build `build_installer_v0132.bat`.

### v0.1.31 — Silent Windows runtime

PowerShell Authenticode check và FFmpeg health check chạy ẩn console bằng `CREATE_NO_WINDOW`. Inno Setup tạo shortcut trực tiếp tới EXE windowed. Thêm smoke test kiểm tra PE GUI subsystem, shortcut target, `WorkingDir`, silent launch và Process Monitor startup capture.

### v0.1.30 — Accessibility và responsive UI

Bổ sung focus-visible, keyboard guidance, reduced motion, status live region và responsive layout cho preview/queue. Visual regression contract, browser smoke và full regression suite được cập nhật.

Xem chi tiết tại [GitHub Releases](https://github.com/GiaHan1907/FrameForge/releases).

## Chạy từ source

Cần Python 3.12 và FFmpeg/ffprobe nếu không dùng binary nhúng.

```bash
pip install -r requirements_full.txt
streamlit run streamlit_app.py
```

Trên Windows:

```bat
run_windows.bat
```

Ứng dụng mở tại `http://localhost:8501`. Để chạy bản desktop đã đóng gói, mở trực tiếp `VideoScreenshotFilter.exe` hoặc shortcut từ installer; không dùng file `.bat` nếu muốn ẩn hoàn toàn cửa sổ CMD.

## Build installer Windows

Build bản v0.1.32 trên máy Windows:

```bat
build_installer_v0132.bat
```

Build v0.1.31:

```bat
build_installer_v0131.bat
```

Installer được tạo trong thư mục `installer` với tên tương ứng. Workflow GitHub Actions `.github/workflows/build.yml` có thể chạy manual trên Windows 2022, build PyInstaller onedir, Inno Setup, test suite, checksum và upload artifact.

## Smoke test và debug

Kiểm tra installer, shortcut, PE subsystem và silent launch:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\tests\windows_installer_smoke.ps1 -InstallerPath .\installer\FrameForge-Setup-0.1.32.exe
```

Theo dõi process con lúc khởi động bằng Microsoft Process Monitor:

```powershell
.\tests\process_monitor_startup.ps1 `
  -ProcmonPath 'C:\Tools\Procmon64.exe' `
  -ExecutablePath "$env:LOCALAPPDATA\Programs\FrameForge\VideoScreenshotFilter.exe" `
  -CaptureSeconds 20
```

Launcher log nằm tại:

```text
%LOCALAPPDATA%\VideoScreenshotFilter\launcher_error.log
```

Kiểm tra log một lần hoặc theo dõi liên tục:

```powershell
.\check_launcher_log.ps1
.\check_launcher_log.ps1 -Watch
```

Khi đóng web trên bản desktop, có thể xác nhận process đã dừng bằng:

```powershell
Get-Process VideoScreenshotFilter -ErrorAction SilentlyContinue
```

## Cấu trúc quan trọng

| File | Vai trò |
|---|---|
| `streamlit_app.py` | Giao diện Streamlit, preview, queue dashboard và watchdog |
| `video_screenshot_advanced.py` | Engine scene detection, filtering, adaptive target và manifest |
| `persistent_queue.py` | SQLite queue state machine và migration |
| `video_downloader.py` | Downloader yt-dlp và FFmpeg health check |
| `windows_launcher.py` | Launcher desktop, browser auto-open và lifecycle |
| `FrameForge.iss` | Cấu hình Inno Setup |
| `build_installer_v0132.bat` | Build installer v0.1.32 |
| `.github/workflows/build.yml` | Windows CI build và artifact upload |

## Lưu ý dữ liệu

Không xóa SQLite queue, checkpoint, manifest hoặc output khi nâng cấp. Khi resume queue, giữ cấu hình tương ứng để `run_signature` khớp. Sao lưu dữ liệu trước khi cài bản mới và không mở cùng một queue bằng hai phiên bản FrameForge đồng thời.

## Kiểm thử

Chạy full test suite từ thư mục project:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

Bản desktop dùng `console=False`; các script `.bat` vẫn mở console vì chúng dành cho development/build. Nếu EXE vẫn chớp terminal, kiểm tra launcher log và Process Monitor capture trước khi chia sẻ báo cáo lỗi.
