# FrameForge — Auto-update và tối ưu kích thước Setup

## 1. Trạng thái hiện tại

FrameForge hiện có hai cơ chế độc lập. `updater.py` cập nhật riêng yt-dlp; `app_update.py` kiểm tra manifest ứng dụng qua HTTPS, so sánh SemVer, tải Setup vào thư mục dữ liệu của user, xác minh SHA-256 và mở Setup khi người dùng xác nhận trong Streamlit. Đây là **user-confirmed update**, chưa phải silent update hoàn toàn.

Workflow `.github/workflows/windows-release.yml` tạo `latest.json` khi build. Khi chạy từ tag `v1.2.3`, manifest chứa version, tên Setup, URL release asset và SHA-256. GitHub hỗ trợ endpoint release/latest và release assets qua REST/API chính thức [1] [2].

## 2. Điều kiện để auto-update từ GitHub Release hoạt động

Repository private không thể làm nguồn tải công khai cho EXE nếu ứng dụng không có cơ chế xác thực. Không nhúng Personal Access Token vào EXE. Có ba lựa chọn:

| Approach | Tradeoffs | Cost | Setup Complexity |
|---|---|---|---|
| Public release feed trong repository hiện tại | Đơn giản nhất; source cũng có thể bị công khai nếu dùng cùng repo | GitHub repository public không mất phí cơ bản | Thấp |
| Giữ source private, tạo repository public riêng cho release assets | Giữ source private; cần đổi workflow để publish Setup/manifest sang repo public | GitHub public repository không mất phí cơ bản | Trung bình |
| Dùng update server/private distribution có token hoặc signed URL | Kiểm soát truy cập tốt; cần backend, auth, rotation và monitoring | Có chi phí vận hành tùy dịch vụ | Cao |

Với bản phát hành cho một hoặc nhiều máy Windows không yêu cầu bảo mật source, lựa chọn đầu tiên đơn giản nhất. Nếu cần giữ source private, lựa chọn thứ hai phù hợp hơn.

Sau khi có **public release feed**, đặt biến môi trường trên máy Windows:

```bat
setx FRAMEFORGE_UPDATE_MANIFEST_URL "https://github.com/GiaHan1907/FrameForge/releases/latest/download/latest.json"
setx FRAMEFORGE_APP_UPDATE "1"
```

Đóng và mở lại FrameForge sau khi chạy `setx`. Không cần đặt `FRAMEFORGE_AUTO_UPDATE=1`; biến đó chỉ điều khiển updater yt-dlp.

Khi có bản mới, ứng dụng kiểm tra tối đa một lần mỗi 24 giờ. Nếu version trong `latest.json` lớn hơn version đang chạy, giao diện hiển thị nút **Tải và xác minh Setup mới**. Sau khi SHA-256 khớp, nút **Mở Setup để cài bản cập nhật** xuất hiện. Nên đóng FrameForge trước khi hoàn tất trình cài đặt để tránh file đang chạy bị khóa.

## 3. Phát hành version mới

```bash
git checkout main
git pull origin main
git tag -a v1.0.0 -m "FrameForge 1.0.0"
git push origin v1.0.0
```

Tag phải dùng dạng `vMAJOR.MINOR.PATCH`, ví dụ `v1.0.0`. Workflow sẽ build profile minimal, tạo Setup, sinh `latest.json`, `SHA256SUMS.txt`, rồi tạo GitHub Release. Không nên tái sử dụng tag đã phát hành; nếu cần sửa, tăng lên `v1.0.1`.

## 4. Phân tích Setup 147 MB

Setup `FrameForge-Setup-0.0.6.exe` có kích thước khoảng **147.45 MB**. Đây là archive đã nén bởi Inno Setup; kích thước installed payload trong report là khoảng **459.47 MiB**, vì vậy không thể trừ trực tiếp từng file installed khỏi 147 MB. Các file lớn nhất trong Windows dist là:

| Thành phần | Installed size | Nhận xét |
|---|---:|---|
| `ffmpeg.exe` | 109.10 MiB | Cần cho merge/download chất lượng cao. |
| `ffprobe.exe` | 108.91 MiB | Hiện chủ yếu dùng cho health/status; chưa thấy đường dẫn xử lý cốt lõi bắt buộc phải gọi nó. |
| `cv2.pyd` | 81.87 MiB | Cần cho scene detection, motion blur và xử lý frame. |
| OpenCV FFmpeg backend | 29.45 MiB | Có thể ảnh hưởng đọc video nếu xóa trực tiếp. |
| OpenBLAS của NumPy | 19.55 MiB | Native dependency của NumPy/OpenCV. |
| PyInstaller executable | 16.23 MiB | Khó giảm đáng kể. |
| Pillow AVIF extension | 7.53 MiB | Có thể thử loại nếu chỉ xuất JPEG/PNG, cần regression test. |
| Streamlit Plotly JS | 4.45 MiB | Static asset của Streamlit; xóa thủ công có thể phá frontend. |

## 5. Tối ưu nên thử theo thứ tự

### A. Tách `ffprobe.exe` thành tùy chọn

Đây là ứng viên an toàn nhất cần benchmark. Code hiện tại coi `ffprobe` là tùy chọn khi `ffmpeg` tồn tại và `ready_for_merge` chỉ phụ thuộc vào FFmpeg. Nếu kiểm thử đầy đủ cho downloader, health check, playlist, merge và preview đều đạt, có thể bỏ `ffprobe.exe` khỏi profile minimal. Mức giảm installed payload lý thuyết khoảng **108.91 MiB**; mức giảm Setup thực tế phải build lại để đo vì Inno Setup còn nén các file khác nhau.

### B. Tách FFmpeg khỏi Setup và tự tải ở lần đầu

Đây là phương án giảm lớn nhất: Setup không nhúng cặp FFmpeg static, ứng dụng tự tải archive đã ghim version qua HTTPS, xác minh SHA-256 và giải nén vào `%LOCALAPPDATA%`. Người dùng không phải cài thủ công, nhưng lần chạy đầu cần mạng, phải hiển thị license/source/checksum và phải xử lý retry/offline. Phương án này thay đổi trải nghiệm “offline installer”, nên nên làm thành profile riêng.

### C. Custom FFmpeg

Có thể giảm binary bằng cách giới hạn codec/container, nhưng downloader Facebook/TikTok/Pinterest có thể trả nhiều codec và video/audio tách riêng. Đây là hướng có rủi ro cao hơn; phải kiểm thử nhiều định dạng và rà lại license. Không nên xóa DLL codec trực tiếp khỏi `dist`.

### D. Custom OpenCV

`cv2.pyd` khoảng 81.87 MiB và backend media khoảng 29.45 MiB. Build OpenCV custom có thể giảm đáng kể, nhưng dễ gặp lỗi ABI, DLL, codec và `VideoCapture`. Chỉ nên làm sau khi có test matrix video cố định.

### E. Prune frontend/static và codec tùy chọn

Có thể thử loại Pillow AVIF extension và một số static asset không dùng, nhưng lợi ích nhỏ hơn FFmpeg/OpenCV. Mỗi lần prune phải build lại, smoke-test HTTP 200 và test UI upload/preview/download/scene timeline.

### F. Các tối ưu đã gần đạt giới hạn

Inno Setup đã dùng LZMA2/max và solid compression. Exclude source map/PDB/log/temp cũng đã có. UPX/strip chỉ có thể giảm thêm một phần nhỏ và có nguy cơ false positive antivirus hoặc lỗi native; không nên dùng cho FFmpeg/OpenCV nếu chưa có test trên Windows sạch.

## 6. Kết luận

Nếu vẫn giữ yêu cầu **Setup offline, không cần người dùng cài FFmpeg, Streamlit và OpenCV đầy đủ**, mốc 147 MB đã khá tốt và phần còn giảm đáng kể nhất là thử bỏ `ffprobe.exe`. Nếu mục tiêu là dưới 100 MB, gần như phải tách FFmpeg thành gói tải lần đầu hoặc chấp nhận dùng FFmpeg hệ thống.

### References

[1]: https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases "GitHub — About releases"

[2]: https://docs.github.com/en/rest/releases/releases "GitHub REST API — Releases"

[3]: https://docs.github.com/en/rest/releases/assets "GitHub REST API — Release assets"

[4]: https://docs.github.com/en/actions/reference/security/secure-use "GitHub Actions — Secure use reference"
