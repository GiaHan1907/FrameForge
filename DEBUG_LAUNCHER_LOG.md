# Debug cửa sổ terminal và launcher log trên Windows

## Vị trí log

Launcher ghi lỗi khởi động tại:

```text
%LOCALAPPDATA%\VideoScreenshotFilter\launcher_error.log
```

Thông thường đường dẫn đầy đủ là:

```text
C:\Users\<Tên người dùng>\AppData\Local\VideoScreenshotFilter\launcher_error.log
```

Có thể mở nhanh bằng `Win + R`, dán `%LOCALAPPDATA%\VideoScreenshotFilter` rồi nhấn Enter.

## Nội dung log

Khi launcher gặp exception trước hoặc trong lúc khởi động Streamlit, log sẽ chứa tiêu đề, loại exception và traceback Python. Không nên gửi nguyên log công khai nếu log có đường dẫn local hoặc tên tài khoản Windows; hãy kiểm tra và che thông tin cá nhân trước khi chia sẻ.

Để xem log bằng PowerShell:

```powershell
$log = Join-Path $env:LOCALAPPDATA 'VideoScreenshotFilter\launcher_error.log'
Get-Content $log -Tail 120
```

Để theo dõi log khi thử mở lại app:

```powershell
Get-Content "$env:LOCALAPPDATA\VideoScreenshotFilter\launcher_error.log" -Wait
```

Nếu muốn lưu bản sao để gửi hỗ trợ:

```powershell
$src = Join-Path $env:LOCALAPPDATA 'VideoScreenshotFilter\launcher_error.log'
$dst = Join-Path $env:USERPROFILE 'Desktop\frameforge-launcher-error.log'
Copy-Item $src $dst -Force
```

## Chính sách log và lỗi

Log chỉ được tạo hoặc cập nhật khi launcher có lỗi. Việc kiểm tra update/FFmpeg bình thường không cần mở terminal. Nếu app không khởi động được, launcher ưu tiên hiện Windows MessageBox và ghi traceback vào file thay vì yêu cầu người dùng đọc cửa sổ CMD.

Không xóa log trước khi lưu bản sao nếu đang điều tra lỗi. Sau khi đã gửi thông tin cần thiết, có thể xóa file để bắt đầu một phiên debug sạch.

## Các nguồn có thể gây terminal flash

| Thành phần | Có thể tạo console? | Trạng thái v0.1.31 |
|---|---:|---|
| PyInstaller bootloader | Có nếu build console mode | `console=False` trong các spec phát hành |
| PowerShell Authenticode check | Có | Đã thêm `CREATE_NO_WINDOW` |
| FFmpeg health check `-version` | Có | Đã thêm `CREATE_NO_WINDOW` |
| yt-dlp download | Không spawn CLI riêng; dùng thư viện Python | Không có console riêng từ đường này |
| `os.startfile()` mở installer | Không tạo console riêng | Giữ nguyên trên Windows |
| `run_windows.bat` | Có, vì chính nó là batch console | Chỉ dùng cho development/debug |
| `build_windows.bat`/`build_installer.bat` | Có, vì là script build | Không dùng để chạy app sau cài đặt |

## Quy trình chẩn đoán

1. Xác nhận người dùng mở shortcut hoặc `VideoScreenshotFilter.exe`, không mở `.bat`.
2. Xóa hoặc đổi tên `launcher_error.log`, mở app lại và kiểm tra log mới.
3. Nếu terminal chỉ flash lúc khởi động/update, kiểm tra `launcher_error.log` và `yt_dlp_update.log` trong cùng thư mục.
4. Nếu terminal flash lúc kiểm tra FFmpeg hoặc tải video, cập nhật lên installer v0.1.31 vì bản này ẩn process con PowerShell/FFmpeg.
5. Nếu vẫn còn flash, kiểm tra phần mềm antivirus/Windows Defender hoặc một helper bên ngoài bằng Process Monitor; không bật debug console cho bản phát hành.

## Bật debug có kiểm soát

Không nên đổi `console=False` thành `console=True` trên bản phân phối. Khi cần debug, chạy bản source từ PowerShell để giữ traceback trong terminal:

```powershell
cd C:\path\to\FrameForge
python windows_launcher.py
```

Cách này chỉ dùng cho developer/debug. Người dùng cuối nên giữ bản EXE windowed và gửi `launcher_error.log`.
