# FrameForge v0.1.31

## Silent Windows runtime và installer shortcut hardening

FrameForge v0.1.31 tập trung loại bỏ hiện tượng cửa sổ terminal chớp tắt trong lúc ứng dụng khởi động, kiểm tra cập nhật và kiểm tra FFmpeg.

### Điểm mới

- PowerShell Authenticode check chạy với `CREATE_NO_WINDOW` trên Windows.
- FFmpeg health check chạy với `CREATE_NO_WINDOW` trên Windows.
- EXE chính tiếp tục dùng PyInstaller `console=False`.
- Inno Setup mặc định build đúng version `0.1.31`.
- Start Menu shortcut và Desktop shortcut trỏ trực tiếp đến `VideoScreenshotFilter.exe` trong thư mục cài đặt, với `WorkingDir` đúng là thư mục ứng dụng.
- Installer không gọi `cmd.exe`, `.bat` hoặc một launcher console trung gian.
- Thêm `build_installer_v0131.bat` để build lại sạch từ source, nhúng FFmpeg và kiểm tra installer output.
- Thêm `check_launcher_log.ps1` để phát hiện lỗi mới trong `%LOCALAPPDATA%\VideoScreenshotFilter\launcher_error.log`.
- Thêm `DEBUG_LAUNCHER_LOG.md` và hướng dẫn cập nhật/rollback.

### Tương thích

Bản cập nhật không yêu cầu xóa output, manifest, checkpoint hoặc SQLite queue. Khi resume queue cũ, vẫn cần giữ cấu hình tương ứng để `run_signature` khớp. Config/preset per-user được giữ nguyên.

### Cách cài đặt

Đóng FrameForge trước khi cập nhật. Chạy `FrameForge-Setup-0.1.31.exe` hoặc dùng nút **Cập nhật ngay** trong app. Sau khi cài, mở bằng shortcut hoặc `VideoScreenshotFilter.exe`; không chạy `run_windows.bat` vì đây là script development và sẽ mở CMD theo thiết kế.

### Debug

Nếu ứng dụng không khởi động, launcher không bật console mà hiển thị MessageBox và ghi traceback tại:

```text
%LOCALAPPDATA%\VideoScreenshotFilter\launcher_error.log
```

Có thể kiểm tra log bằng:

```powershell
.\check_launcher_log.ps1
```

Hoặc theo dõi liên tục:

```powershell
.\check_launcher_log.ps1 -Watch
```

### Known limitations

`run_windows.bat`, `build_windows.bat` và các script debug vẫn mở cửa sổ console vì bản chất là batch script. Đây là hành vi dành cho development, không phải hành vi của installer/EXE release. Nếu terminal vẫn chớp khi chạy EXE v0.1.31, cần kiểm tra antivirus/Windows Defender hoặc helper bên thứ ba bằng Process Monitor.
