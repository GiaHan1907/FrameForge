# FrameForge Windows Release Notes

# FrameForge v0.1.11

## Sửa lỗi thiếu module trong Windows installer

Bản vá bổ sung `persistent_queue.py` và `timeline_utils.py` vào cả ba PyInstaller spec: onedir, minimal và one-file. Workflow Windows hiện kiểm tra trực tiếp các module runtime trong thư mục package trước khi chạy packaged smoke test, tránh phát hành installer thiếu file Python cần thiết. Người dùng đang gặp `ModuleNotFoundError: No module named 'persistent_queue'` nên cài bản v0.1.11 thay cho v0.1.10.

# FrameForge v0.1.10

## Tối ưu dHash index và quản lý dung lượng tạm

DHash index được nâng từ định dạng v1 chỉ chứa danh sách hash sang định dạng v2 có thêm bucket theo từng byte. Với threshold phổ biến không vượt quá 6, FrameForge chỉ cần kiểm tra các hash trong bucket liên quan thay vì quét toàn bộ index. Index v1 vẫn được đọc tương thích và tự chuyển sang v2 khi ghi lại.

CLI bổ sung quota cho work directory tạm và scene cache. Work directory cũ nhất được dọn khi vượt quota; scene cache chỉ xóa JSON cũ hơn 7 ngày, giúp bảo vệ cache mới và tránh làm mất lợi ích resume nhanh. Streamlit áp dụng cùng quota mặc định cho thư mục cache/temp của người dùng.

# FrameForge v0.1.9

## Tối ưu adaptive worker và queue bền vững

Bản nâng cấp này giới hạn số process trích frame theo số video worker chạy đồng thời, CPU và RAM khả dụng để tránh oversubscription trên máy nhiều lõi. Báo cáo JSON và giao diện Streamlit hiện hiển thị số video worker, số extraction worker được cấu hình và số worker adaptive thực tế cho từng video.

SQLite queue được đóng sạch khi hủy xử lý trong single-worker mode và vẫn giữ trạng thái `cancelled` cho toàn bộ item còn lại, giúp lần mở lại sau không gặp database connection treo hoặc trạng thái queue không nhất quán. Bộ test mới kiểm tra adaptive budget, resume report từ SQLite và cancel lifecycle thực tế qua `process_videos()`.

## Phạm vi bản cập nhật

Bản cập nhật mới bổ sung scene cache, checkpoint resume, duplicate detection giữa các lần chạy và timeline tương tác với zoom/bộ lọc scene. Updater ứng dụng hỗ trợ stable/beta channel, release notes trong UI và rollback installer có xác minh SHA-256.

Bản cập nhật này hoàn thiện hướng phát hành **PyInstaller onedir + FFmpeg/ffprobe nhúng + updater yt-dlp riêng**. Giao diện timeline đã bỏ `st.table` và chuyển sang HTML/CSS thuần, nhờ đó profile minimal không cần Pandas hoặc PyArrow. Các chức năng cốt lõi của FrameForge vẫn được giữ: preview video, tải URL công khai được phép bằng yt-dlp, queue/playlist, scene detection, chống flash, lọc motion blur, dHash, Best frame per scene, worker tự động và benchmark.

## Profile và số đo

| Profile | Linux onedir trước FFmpeg Windows | Trạng thái smoke test |
|---|---:|---|
| Full | 622.06 MiB | Streamlit HTTP 200 |
| Minimal | 324.10 MiB | Streamlit HTTP 200, không thấy lỗi import/runtime |

Các số liệu trên là phép đo artifact Linux cùng mã nguồn. Cặp FFmpeg static Windows tham khảo có tổng khoảng **218.01 MiB**, do đó installed size dưới 200 MB **không khả thi** nếu vẫn giữ Streamlit, OpenCV và FFmpeg offline đầy đủ. Installer Inno Setup có thể giảm kích thước tải xuống nhờ LZMA2, nhưng không làm giảm dung lượng thư mục đã cài.

## Cách build trên Windows

Build onedir minimal:

```bat
set BUILD_PROFILE=minimal
set BUILD_MODE=onedir
build_windows.bat
```

Build onedir full:

```bat
set BUILD_PROFILE=full
set BUILD_MODE=onedir
build_windows.bat
```

Build one-file full dự phòng:

```bat
set BUILD_MODE=onefile
build_windows.bat
```

Trước mỗi lần build nên xóa `build` và `dist` cũ. `build_windows.bat` sẽ tạo virtual environment, cài dependency tương ứng, chuẩn bị FFmpeg nhúng nếu thiếu, chạy PyInstaller và tạo `build_size_report.json`.

## Tạo installer

Cài Inno Setup 6 trên Windows, build onedir trước, sau đó chạy:

```bat
build_installer.bat
```

Kết quả có dạng `installer\FrameForge-Setup-1.0.0.exe`. Installer được định nghĩa trong `FrameForge.iss`, đóng gói toàn bộ `dist\VideoScreenshotFilter\*`, tạo shortcut Start Menu và shortcut Desktop tùy chọn, cài theo user vào `%LOCALAPPDATA%\Programs\FrameForge` và đăng ký uninstaller.

## Xác minh trước phát hành

Cần cài thử Setup trên máy Windows không có Python và không có FFmpeg trong PATH. Hãy kiểm tra app tự mở trình duyệt, `http://127.0.0.1:8501` trả về giao diện FrameForge, health check báo `source=embedded`, một URL công khai hợp lệ tải được, format cần ghép audio/video hoạt động, và pipeline Best frame per scene tạo được ảnh/report. Cũng cần đo riêng kích thước thư mục cài đặt và file Setup.

## Giới hạn kiểm thử

Môi trường phát triển hiện tại là Linux và không có Inno Setup, NSIS, Wine hoặc Windows toolchain. Vì vậy chưa thể sinh file Setup `.exe` hoặc xác nhận kích thước Windows cuối cùng trong phiên này. Các script và spec đã được chuẩn bị để chạy trực tiếp trên Windows.

## Phân phối FFmpeg

Giữ lại các file license, readme và `BUILD_METADATA.txt` do `prepare_ffmpeg_windows.ps1` tạo. Trước khi phát hành cần đối chiếu SHA-256, nguồn binary, configure flags và phạm vi license/codec của build FFmpeg đã chọn. Không dùng GPL/nonfree build chỉ vì mục tiêu giảm kích thước khi chưa rà soát nghĩa vụ phân phối.


## GitHub Actions

Workflow mới tại `.github/workflows/windows-release.yml` chạy trên `windows-2022`, chọn profile minimal/full, gọi `build_windows.bat`, smoke-test endpoint HTTP 200 của executable đã đóng gói, cài Inno Setup bằng Chocolatey, tạo Setup, sinh checksum và upload artifact. Push tag dạng `v1.2.3` sẽ tự tạo GitHub Release; chạy thủ công cho phép chọn profile và chỉ publish nếu bật `publish_release`.

Workflow dùng `GITHUB_TOKEN` với `contents: write`. Repository phải cho phép Actions tạo Release. Không commit Personal Access Token hoặc secret nhạy cảm vào YAML. Trước phát hành chính thức nên thay URL FFmpeg alias `latest` bằng asset/version được ghim hoặc truyền qua Repository Variable/Secret.

Kênh `stable` tạo `latest.json` và GitHub Release thông thường. Kênh `beta` tạo prerelease và asset `latest-beta.json`; người dùng chọn kênh trong UI hoặc đặt `FRAMEFORGE_UPDATE_CHANNEL=beta`. Updater chỉ chấp nhận manifest đúng channel, HTTPS và SHA-256 hợp lệ. Stable release mới sẽ ghi metadata rollback tới stable release trước đó nếu asset `latest.json` cũ còn truy cập được.

Để ký installer bằng Authenticode, tạo hai Actions secrets: `WINDOWS_CERTIFICATE_BASE64` chứa file PFX đã mã hóa Base64 và `WINDOWS_CERTIFICATE_PASSWORD` chứa mật khẩu PFX. Workflow sẽ dùng `signtool.exe`, timestamp SHA-256 và kiểm tra `Get-AuthenticodeSignature`. Nếu secrets chưa được cấu hình, build vẫn phát hành nhưng manifest ghi rõ `signature_status=unsigned`; không nên coi bản unsigned là bản phân phối production cuối cùng.
