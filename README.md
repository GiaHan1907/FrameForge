# FrameForge

FrameForge là ứng dụng desktop (Streamlit) kèm CLI dùng để trích xuất screenshot từ video, phát hiện scene, lọc frame mờ/trùng, xử lý queue nhiều video và tải video công khai — chạy trên Windows, Linux và macOS. Bản cài Windows được đóng gói bằng PyInstaller + Inno Setup, không cần cài Python hay FFmpeg riêng.

Bản mới nhất: **v0.1.39** — tải tại [GitHub Releases](https://github.com/GiaHan1907/FrameForge/releases).

## Tính năng chính

| Nhóm | Tính năng |
|---|---|
| Trích xuất frame | Best frame per scene, mỗi N giây hoặc đúng N frame |
| Scene detection | Phát hiện scene change, chống flash và preview scene thật |
| Lọc chất lượng | Sharpness chuẩn hóa, motion blur, duplicate detection bằng dHash |
| Crop/đầu ra | Tỉ lệ `16:9`, `9:16`, `4:5`, `1:1`, encode profile nhanh/chất lượng cao |
| Queue | SQLite persistence, pause/resume/cancel/retry, checkpoint và crash recovery |
| Downloader | Tải URL công khai qua yt-dlp (Facebook, TikTok, Pinterest...), retry exponential backoff và staging an toàn |
| Tìm ảnh theo địa điểm | Tìm kiếm ảnh qua DuckDuckGo Images (không cần API key), duyệt kết quả và tải ảnh về máy |
| Preset & lịch sử | Preset cá nhân, xuất/nhập cấu hình JSON, lịch sử job (50 job gần nhất) |
| Cập nhật | Kênh stable/beta, release notes hiển thị trong app, rollback có xác minh SHA-256 |
| Desktop | Installer Inno Setup, FFmpeg nhúng, watchdog tự dừng job khi đóng browser, silent console |

### Giao diện

Giao diện Streamlit được tổ chức thành **3 tab** để không phải cuộn nhiều:

- **⬇️ Tải video công khai** — dán một hoặc nhiều URL, chọn chất lượng, giới hạn playlist, retry.
- **⚙️ Xử lý video** — wizard 4 bước (Nguồn → Chọn frame → Chất lượng → Đầu ra): 4 card tóm tắt + 4 expander cấu hình theo từng bước, preview workspace và nút *Bắt đầu xử lý*.
- **📁 Cài đặt & Lịch sử** — kênh cập nhật + update/rollback, preset cá nhân, lịch sử job.

Các tùy chọn nâng cao (scene detection, hiệu năng, lọc mờ/trùng, retry/cache, form tải video, video player + timeline) nằm trong **expander thu gọn**; toàn bộ cấu hình wizard nằm trong tab ⚙️ Xử lý video, còn sidebar chỉ giữ thương hiệu và nút *Tìm ảnh theo địa điểm* (bật/tắt ngay trong giao diện).

## Ba bản cập nhật gần nhất

### v0.1.39 — Release notes rõ ràng + giao diện gọn thêm

Thêm entry release notes hiển thị trong app; form tải video và panel Cập nhật & kênh gói vào expander thu gọn. Dọn release v0.1.39 lỗi thời để lịch sử phát hành sạch. Xem đầy đủ ở mục *Sửa lỗi ổn định trên bản cài Windows (.exe)* phía dưới trang release.

### v0.1.38 — Redesign giao diện 3 tab

Chia giao diện thành 3 tab thay vì một trang dài; bỏ hero và các card tổng quan trùng lặp; sidebar thu gọn ~một nửa (4 nhóm expander); preview workspace và video player gói trong expander. Widget keys không đổi nên preset và cấu hình đã lưu giữ nguyên.

### v0.1.37 — Loạt fix ổn định cho bản cài .exe

Bảng Lịch sử job chuyển từ `st.dataframe` sang HTML/CSS thuần, loại bỏ phụ thuộc Pandas/PyArrow ở profile minimal (hết lỗi `No module named 'pyarrow'`). Sửa các spec PyInstaller (thiếu trailing comma, thiếu `core/google_images.py`), bổ sung `requests`/`beautifulsoup4` vào requirements, sửa các lỗi thiếu import/NameError khi chạy bản đóng gói, và đưa *Tìm ảnh theo địa điểm* chạy inline thay vì `st.page_link`.

Lịch sử đầy đủ nằm tại [RELEASE_NOTES.md](RELEASE_NOTES.md) (đồng thời là phần *What's new* trong app) và [CHANGELOG.md](CHANGELOG.md). Roadmap đề xuất cũ cho v0.1.33 (đã lưu trữ) tại [ROADMAP_v0.1.33.md](ROADMAP_v0.1.33.md).

## Chạy từ source

Cần Python 3.12 và FFmpeg/ffprobe nếu không dùng binary nhúng.

```bash
pip install -r requirements_full.txt
streamlit run streamlit_app.py
```

Ứng dụng mở tại `http://localhost:8501`. Trên Windows có thể dùng:

```bat
run_windows.bat
```

Chạy headless qua CLI:

```bash
python -m core.cli --help
```

Để chạy bản desktop đã đóng gói, mở trực tiếp `VideoScreenshotFilter.exe` hoặc shortcut từ installer; không dùng file `.bat` nếu muốn ẩn hoàn toàn cửa sổ CMD.

## Build installer Windows

CI là đường phát hành chính: **push tag `vX.Y.Z`** (ví dụ `v0.1.39`) sẽ kích hoạt workflow `.github/workflows/windows-release.yml` — build PyInstaller trên Windows 2022, smoke test HTTP 200, tạo Setup bằng Inno Setup, sinh checksum và **tự tạo/publish GitHub Release** (kênh beta tạo prerelease). Workflow cũ `.github/workflows/build.yml` vẫn hỗ trợ chạy tay theo version/profile.

Build cục bộ trên máy Windows:

```bat
set BUILD_PROFILE=minimal
set BUILD_MODE=onedir
build_windows.bat
```

`BUILD_PROFILE` nhận `minimal` (không đóng gói Pandas/PyArrow — khuyến nghị cho bản cài) hoặc `full`; `BUILD_MODE` mặc định `onedir` (profile minimal chỉ hỗ trợ onedir).

Sau khi build xong, tạo installer:

```bat
set FRAMEFORGE_VERSION=0.1.39
build_installer.bat
```

Kết quả nằm tại `installer\FrameForge-Setup-0.1.39.exe`. `FRAMEFORGE_VERSION` (nếu đặt) ghi đè version mặc định trong `FrameForge.iss`; nếu không đặt, cập nhật `MyAppVersion` trong `FrameForge.iss` trước khi build.

## Smoke test và debug

Kiểm tra installer, shortcut, PE subsystem và silent launch:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\tests\windows_installer_smoke.ps1 -InstallerPath .\installer\FrameForge-Setup-0.1.39.exe
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

| Đường dẫn | Vai trò |
|---|---|
| `streamlit_app.py` | Giao diện chính: layout 3 tab, khởi tạo watchdog/updater, render sidebar |
| `ui/` | Module giao diện: `widgets.py`, `wizard.py`, `sidebar.py`, `download_section.py`, `preview_section.py`, `timeline.py`, `image_search_inline.py`, `logic.py`, `session.py`... |
| `core/` | Logic thuần tách để test: `config.py` (`FrameForgeConfig`), `cli.py`, `pipeline.py`, `analysis.py` + `cv2_helpers.py`, `errors.py`, `manifest.py`, `google_images.py`, `network.py`, `resources.py`, `targets.py`, `utils.py`... |
| `video_screenshot_advanced.py` | Engine xử lý video (scene/fixed mode, trích và lưu ảnh), được gọi từ `core/cli.py` và giao diện |
| `persistent_queue.py` | SQLite queue state machine và migration |
| `video_downloader.py` | Downloader yt-dlp (URL công khai) và FFmpeg health check |
| `windows_launcher.py` | Launcher desktop, browser auto-open và lifecycle |
| `app_update.py`, `updater.py` | Auto-update FrameForge (stable/beta, rollback SHA-256) và updater yt-dlp |
| `FrameForge.iss`, `build_windows.bat`, `build_installer.bat` | Installer Inno Setup và build cục bộ |
| `validate_build.py`, `validate_release_manifest.py` | Kiểm tra gói build và manifest release |
| `.github/workflows/windows-release.yml` | CI build Windows + tự publish release khi push tag `v*` |

## Lưu ý dữ liệu

Không xóa SQLite queue, checkpoint, manifest hoặc output khi nâng cấp. Khi resume queue, giữ cấu hình tương ứng để `run_signature` khớp. Sao lưu dữ liệu trước khi cài bản mới và không mở cùng một queue bằng hai phiên bản FrameForge đồng thời.

## Kiểm thử

Chạy full test suite từ thư mục project:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

Một số test cần OpenCV (`cv2`/`numpy`) và sẽ tự bỏ qua nếu thiếu. Bản desktop dùng `console=False`; các script `.bat` vẫn mở console vì chúng dành cho development/build. Nếu EXE vẫn chớp terminal, kiểm tra launcher log và Process Monitor capture trước khi chia sẻ báo cáo lỗi.
