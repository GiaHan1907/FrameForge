# Ghi chú updater yt-dlp

PyPI là nguồn package chính thức được yt-dlp README liên kết tới. Trang package hiện hiển thị phiên bản `2026.8.19` tại thời điểm nghiên cứu, nhưng updater không nên hard-code phiên bản này; cần đọc metadata JSON của PyPI qua HTTPS và so sánh bằng packaging.version.

yt-dlp cũng cung cấp release binaries trên GitHub. Bản EXE nhúng PyInstaller nên không tự thay thế chính nó trong lúc đang chạy; updater an toàn hơn là tải một gói patch/standalone đã xác thực vào thư mục tạm, kiểm tra SHA-256 hoặc chữ ký từ manifest tin cậy, rồi dùng helper process thay thế file sau khi ứng dụng đóng.

Không được cài package mới hoặc chạy mã tải về nếu chưa xác minh nguồn, checksum/chữ ký và phiên bản. Nên có opt-in/opt-out, rollback, timeout mạng, cache và nút cập nhật thủ công.

Nguồn:
- https://pypi.org/project/yt-dlp/
- https://github.com/yt-dlp/yt-dlp
- https://pyinstaller.org/en/stable/operating-mode.html
