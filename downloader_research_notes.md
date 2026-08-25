# Ghi chú nghiên cứu downloader

- yt-dlp có danh sách extractor/site hỗ trợ chính thức trong `supportedsites.md`; danh sách thay đổi theo phiên bản nên package cần cập nhật định kỳ.
- Tài liệu chính thức của yt-dlp mô tả lựa chọn format bằng biểu thức `-f`, trong đó có thể ưu tiên video/audio tốt nhất và fallback format kết hợp.
- Khi video và audio nằm ở stream riêng, yt-dlp cần FFmpeg để ghép thành file đầu ra.
- Ứng dụng chỉ nên xử lý URL công khai, không nhận cookie/login và không cố vượt DRM hoặc nội dung riêng tư.
- Cần hiển thị rõ trách nhiệm của người dùng về quyền sử dụng và điều khoản nền tảng.
- Nguồn: https://github.com/yt-dlp/yt-dlp ; https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md ; https://ffmpeg.org/documentation.html
