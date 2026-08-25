FrameForge embedded FFmpeg
===========================

Đặt ffmpeg.exe và ffprobe.exe của Windows x86_64 static build tại thư mục này.

Cách chuẩn bị tự động từ thư mục gốc package:

  powershell -ExecutionPolicy Bypass -File .\prepare_ffmpeg_windows.ps1

Script sẽ tải archive theo URL đã ghim trong script, giải nén, lấy hai executable,
chép license/readme nếu có và ghi BUILD_METADATA.txt gồm URL cùng SHA-256.

Trước khi phát hành, hãy kiểm tra license/configure của archive. FFmpeg mặc định
là LGPL 2.1+ nhưng build có thành phần GPL/nonfree có thể thay đổi nghĩa vụ phân phối.
Không xóa license, source hoặc thông tin build của binary đã dùng.

PyInstaller spec nhúng hai executable vào _MEIPASS/vendor/ffmpeg. Runtime sẽ ưu tiên
đường dẫn này trước PATH, và health check hiển thị source=embedded.

Không commit binary vào Git nếu policy repository không cho phép. Khi phân phối ZIP
hoặc EXE, đính kèm thông báo license phù hợp và giữ lại BUILD_METADATA.txt.
