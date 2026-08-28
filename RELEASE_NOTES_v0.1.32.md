# FrameForge v0.1.32

## Desktop auto-shutdown khi đóng web

FrameForge v0.1.32 bổ sung cơ chế tự động dừng tiến trình desktop khi browser session cuối cùng đóng. Mục tiêu là tránh `VideoScreenshotFilter.exe` hoặc process con tiếp tục chạy nền sau khi người dùng đã đóng giao diện web.

### Thay đổi chính

- Watchdog giám sát session desktop và nhận biết khi browser đã đóng thực sự sau khoảng reconnect ngắn.
- Job đang chạy được cancel an toàn trước khi dừng server; checkpoint/work directory được xử lý theo lifecycle hiện tại.
- Streamlit runtime được stop trước khi kết thúc process tree.
- Gọi `taskkill.exe /PID <current_pid> /T /F` để dừng đúng `VideoScreenshotFilter.exe` và process con.
- Lệnh `taskkill.exe` chạy với `CREATE_NO_WINDOW`, không tạo cửa sổ terminal phụ.
- PID guard qua `FRAMEFORGE_DESKTOP_PID` ngăn watchdog kill nhầm process khác.
- Cơ chế chỉ bật từ `windows_launcher.py` với `FRAMEFORGE_DESKTOP_LIFECYCLE=1`; chạy `streamlit run` thủ công không bị ảnh hưởng.
- Inno Setup mặc định đóng gói installer `FrameForge-Setup-0.1.32.exe` và shortcut vẫn trỏ trực tiếp tới EXE windowed.
- Bổ sung unit test kiểm tra non-Windows no-op, Windows taskkill flags và PID mismatch guard.

## Tương thích và migration

Không cần migration database riêng cho tính năng này. SQLite queue, manifest, checkpoint, output và config từ các bản trước được giữ nguyên. Người dùng nên để job dừng tại checkpoint an toàn trước khi đóng web; không nên rút nguồn hoặc kill thủ công giữa lúc đang ghi file.

Bản desktop mới cần được build từ source v0.1.32 để có watchdog. Việc chỉ cập nhật file Streamlit hoặc chạy bản v0.1.31 cũ không kích hoạt tính năng này.

## Cách sử dụng

Cài `FrameForge-Setup-0.1.32.exe`, mở ứng dụng bằng shortcut hoặc `VideoScreenshotFilter.exe`, sau đó đóng browser tab/cửa sổ cuối cùng. Sau thời gian reconnect ngắn, app sẽ cancel job nếu cần, dừng server và kết thúc process desktop.

Có thể xác minh bằng PowerShell:

```powershell
Get-Process VideoScreenshotFilter -ErrorAction SilentlyContinue
```

Nếu không có output, process đã được dừng.

## Kiểm thử

Bản phát hành bao gồm unit test watchdog/process tree, compile check và regression suite. Smoke test Windows kiểm tra PE GUI subsystem, shortcut target, `WorkingDir`, HTTP readiness và không có native window mới trong startup.

## Known limitations

Cơ chế auto-shutdown phụ thuộc việc Streamlit runtime nhận biết browser session cuối cùng đã đóng. Nếu browser crash hoặc mạng bị ngắt bất thường, watchdog có thể cần thời gian reconnect trước khi dừng. Các script `.bat` dành cho build/debug vẫn mở console theo thiết kế; hiện tượng này không đại diện cho EXE installer windowed.

Nếu process vẫn còn sau khi đóng web, kiểm tra `launcher_error.log`, chạy Process Monitor startup capture và xác nhận app được mở bằng EXE v0.1.32 thay vì `.bat`.
