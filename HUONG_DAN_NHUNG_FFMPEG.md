# Hướng dẫn nhúng FFmpeg vào FrameForge EXE

## Mục tiêu

Sau khi thực hiện các bước dưới đây, người dùng cuối chỉ cần chạy `VideoScreenshotFilter.exe`; ứng dụng sẽ tự tìm `ffmpeg.exe` và `ffprobe.exe` đã được nhúng trong bundle. Người dùng cuối không cần cài FFmpeg vào Windows hoặc sửa biến môi trường `PATH`.

## 1. Layout cần có trước khi build

Từ thư mục gốc của package, tạo layout:

```text
video_screenshot_app/
├── streamlit_app.py
├── video_screenshot_advanced.py
├── video_downloader.py
├── windows_launcher.py
├── video_screenshot_filter.spec
├── build_windows.bat
├── prepare_ffmpeg_windows.ps1
└── vendor/
    └── ffmpeg/
        ├── ffmpeg.exe
        ├── ffprobe.exe
        ├── LICENSE hoặc COPYING
        ├── README*             (nếu archive cung cấp)
        └── BUILD_METADATA.txt
```

Hai file bắt buộc là `ffmpeg.exe` và `ffprobe.exe`. Các file license, README và metadata không tham gia chạy nhưng nên được giữ lại trong package phân phối.

## 2. Chọn binary Windows

Ứng dụng này cần binary Windows x86_64 nếu máy đích là Windows 64-bit. Ưu tiên bản **static** vì thường ít phụ thuộc DLL bên ngoài hơn bản shared. Package có sẵn script PowerShell tham chiếu tới một release LGPL x86_64 cụ thể của BtbN/FFmpeg-Builds.

Không nên dùng URL `latest` cho quy trình phát hành chính thức nếu cần reproducible build. Hãy thay URL bằng release/tag đã kiểm tra, lưu checksum và giữ lại source/configuration/license tương ứng.

## 3. Chuẩn bị tự động bằng PowerShell

Mở PowerShell tại thư mục package và chạy:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\prepare_ffmpeg_windows.ps1
```

Script sẽ tải archive, giải nén tạm, tìm `ffmpeg.exe` và `ffprobe.exe`, chép vào `vendor\ffmpeg`, sao chép các file license/readme phù hợp và tạo `BUILD_METADATA.txt` chứa URL, thời điểm và SHA-256.

Nếu muốn dùng archive nội bộ hoặc release đã ghim, truyền URL riêng:

```powershell
.\prepare_ffmpeg_windows.ps1 `
  -ArchiveUrl "https://server-noi-bo.example/ffmpeg-win64-lgpl.zip"
```

Không chạy binary hoặc script tải từ nguồn chưa kiểm tra. Hãy xác minh checksum và nguồn phát hành trước khi đưa vào sản phẩm.

## 4. Cấu hình PyInstaller

`video_screenshot_filter.spec` thực hiện ba việc:

| Thành phần | Cấu hình |
|---|---|
| Runtime Python | Nhúng Streamlit, OpenCV, NumPy, Pandas, Pillow và yt-dlp. |
| FFmpeg | Đưa `vendor/ffmpeg/ffmpeg.exe` và `ffprobe.exe` vào `_MEIPASS/vendor/ffmpeg`. |
| Metadata/license | Đưa các file `.txt` trong `vendor/ffmpeg` vào cùng thư mục runtime. |
| Cửa sổ | `console=False` để không hiện CMD. |
| Độ ổn định | `upx=False` để không nén lại binary FFmpeg. |

Launcher tìm FFmpeg theo thứ tự:

```text
_MEIPASS/vendor/ffmpeg/ffmpeg.exe
vendor/ffmpeg/ffmpeg.exe khi chạy source
ffmpeg.exe trong PATH như fallback
```

Sau khi tìm thấy, downloader truyền thư mục chứa binary cho yt-dlp qua `ffmpeg_location`.

## 5. Build EXE

Chạy:

```bat
build_windows.bat
```

Script sẽ tạo virtual environment, cài requirements và PyInstaller, chuẩn bị FFmpeg nếu chưa có, kiểm tra hai executable rồi build:

```text
dist\VideoScreenshotFilter\VideoScreenshotFilter.exe
```

Nếu muốn build offline, hãy chuẩn bị sẵn `vendor\ffmpeg\ffmpeg.exe` và `vendor\ffmpeg\ffprobe.exe`, đồng thời giữ wheel/cache Python cần thiết trong môi trường build. Script không tải FFmpeg tại runtime của người dùng cuối; việc tải chỉ diễn ra ở bước build nếu thiếu binary.

## 6. Kiểm tra trước khi phát hành

Trên máy build, chạy:

```bat
vendor\ffmpeg\ffmpeg.exe -version
vendor\ffmpeg\ffprobe.exe -version
certutil -hashfile vendor\ffmpeg\ffmpeg.exe SHA256
certutil -hashfile vendor\ffmpeg\ffprobe.exe SHA256
```

Sau đó chạy EXE và kiểm tra trong giao diện khu vực **Tải video công khai**. Health check phải hiển thị tương tự:

```text
FFmpeg sẵn sàng (nhúng trong bundle)
source=embedded
```

Thử một format cần ghép video/audio, rồi dùng `ffprobe.exe` nhúng để xác minh file đầu ra:

```bat
vendor\ffmpeg\ffprobe.exe -hide_banner output.mp4
```

Kiểm tra thêm trên một máy Windows sạch không có FFmpeg trong `PATH`. Nếu EXE vẫn ghép video/audio được và health check báo `embedded`, việc nhúng đã hoạt động.

## 7. Xử lý lỗi thường gặp

| Hiện tượng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| Health check báo `PATH` | Spec không nhúng được binary hoặc binary không nằm trong `vendor/ffmpeg`. | Xóa `build`/`dist`, chạy lại bước chuẩn bị và build sạch. |
| `ffmpeg.exe` không chạy | Sai kiến trúc, file hỏng hoặc thiếu DLL của shared build. | Dùng Windows x86_64 static build và kiểm tra trực tiếp bằng `-version`. |
| yt-dlp không ghép stream | Không có `ffmpeg.exe` nhúng, format không khả dụng hoặc lỗi codec. | Xem health check và log; thử format thấp hơn. |
| EXE quá lớn | FFmpeg static và các thư viện Python được nhúng. | Đây là đánh đổi của one-file; có thể dùng shared build nhưng phải nhúng DLL đầy đủ. |
| Windows Defender cảnh báo | One-file PyInstaller tự giải nén vào thư mục tạm và binary bên thứ ba có thể bị quét. | Ký code, giữ checksum, dùng nguồn binary tin cậy và phân phối license/metadata. |

## 8. License và phân phối

FFmpeg cho biết mã nguồn chính yếu theo LGPL 2.1+ nhưng có phần tùy chọn theo GPL; nếu build chứa các phần GPL, phạm vi nghĩa vụ sẽ thay đổi. Trang pháp lý chính thức của FFmpeg không phải tư vấn pháp lý, vì vậy cần kiểm tra chính xác cấu hình của binary được chọn [1].

Khi phân phối, không xóa license/copyright, checksum, source/configuration information hoặc metadata của build. Nếu chọn một binary LGPL, hãy xác minh binary thực tế không bật các phần GPL/nonfree ngoài ý muốn. Đồng thời kiểm tra nghĩa vụ codec/patent tại thị trường phân phối.

### Tài liệu tham khảo

[1]: https://www.ffmpeg.org/legal.html "FFmpeg License and Legal Considerations"
[2]: https://ffmpeg.org/download.html "FFmpeg Download"
[3]: https://github.com/BtbN/FFmpeg-Builds/releases "BtbN FFmpeg Builds Releases"
[4]: https://pyinstaller.org/en/stable/spec-files.html "PyInstaller Spec Files"

## 9. Profile onedir và dung lượng thực tế

Profile onedir là lựa chọn cân bằng về khởi động, cập nhật và chẩn đoán, nhưng tổng dung lượng thư mục không nhất thiết nhỏ hơn onefile. Trong build thử nghiệm Linux của package hiện tại, thư mục onedir có kích thước khoảng **622.06 MiB** khi chưa nhúng binary FFmpeg Windows; riêng `_internal` khoảng 608 MiB. Các thành phần lớn gồm PyArrow, OpenCV, cv2, Pandas, Streamlit, NumPy và yt-dlp.

Vì vậy, hãy đo bằng `build_size_report.json` sau khi build Windows thay vì suy ra từ kích thước file EXE. Onedir thuận tiện để cập nhật yt-dlp và thay thế riêng `vendor\ffmpeg`, nhưng cần phát hành toàn bộ thư mục cùng các DLL đi kèm.
