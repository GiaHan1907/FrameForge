# FrameForge v0.1.31 — Hướng dẫn cập nhật

> ⚠️ **Tài liệu lưu trữ.** File này ghi chú riêng cho bản **{v}** đã phát hành; bản mới nhất hiện tại là **v0.1.39**. Thông tin hiện hành xem [RELEASE_NOTES.md](RELEASE_NOTES.md) và [CHANGELOG.md](CHANGELOG.md) — nội dung bên dưới chỉ để tham khảo lịch sử.

---


## Tổng quan

FrameForge v0.1.31 chuẩn bị phát hành với bản sửa hiện tượng cửa sổ terminal chớp tắt khi ứng dụng kiểm tra Authenticode hoặc kiểm tra FFmpeg. EXE chính tiếp tục được build bằng PyInstaller `console=False`; các process con PowerShell và FFmpeg được chạy với `CREATE_NO_WINDOW` trên Windows.

## Cài đặt từ bản v0.1.30 trở về trước

Đóng FrameForge và mọi queue đang chạy. Sao lưu thư mục output, SQLite queue, checkpoint và manifest nếu đang có job chưa hoàn tất. Tải `FrameForge-Setup-0.1.31.exe` từ GitHub Release, chạy installer và có thể giữ nguyên thư mục cài đặt hiện tại. Inno Setup sẽ tạo shortcut trỏ trực tiếp tới:

```text
{localappdata}\Programs\FrameForge\VideoScreenshotFilter.exe
```

Shortcut dùng `WorkingDir` là thư mục cài đặt và không gọi qua `.bat`. Sau khi cài, mở bằng shortcut hoặc EXE trực tiếp; không dùng `run_windows.bat` cho bản người dùng cuối vì batch script luôn mở cửa sổ CMD.

## Sau khi cập nhật

Xác nhận version là `0.1.31`, thử mở một video ngắn và chạy quick scene preview hoặc FFmpeg health check. Nếu không còn terminal flash, bản sửa đã hoạt động đúng. Auto-update feed, installer và SHA-256 cần được xác minh trên GitHub Release trước khi phân phối rộng.

Queue/database/config cũ không cần xóa. Khi resume queue, vẫn phải giữ cấu hình để `run_signature` khớp. Không mở cùng một queue bằng hai phiên bản FrameForge cùng lúc.

## Nếu vẫn thấy terminal flash

Trước tiên xác nhận bạn không mở file `.bat`. Nếu flash xuất hiện khi update hoặc health check, kiểm tra đã cài đúng v0.1.31 chưa. Nếu flash vẫn xảy ra, mở log launcher:

```text
%LOCALAPPDATA%\VideoScreenshotFilter\launcher_error.log
```

Có thể dùng script monitor đi kèm:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\check_launcher_log.ps1
```

Theo dõi liên tục:

```powershell
.\check_launcher_log.ps1 -Watch -IntervalSeconds 5
```

## Rollback

Giữ installer v0.1.30 cho đến khi v0.1.31 được kiểm tra xong. Nếu rollback, đóng FrameForge trước, giữ lại diagnostic/report và không xóa queue database hoặc output để có thể điều tra.
