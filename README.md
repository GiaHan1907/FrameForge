# Video Screenshot Filter — Optimized Streamlit Package

## Chuẩn bị phát hành v0.1.31

v0.1.31 tập trung vào silent Windows runtime và chẩn đoán launcher. EXE release dùng PyInstaller `console=False`; PowerShell Authenticode check và FFmpeg health check dùng `CREATE_NO_WINDOW` trên Windows để tránh cửa sổ console chớp tắt. Inno Setup tạo shortcut trực tiếp tới `VideoScreenshotFilter.exe` với `WorkingDir` là thư mục cài đặt.

Bản build tự động có thể chạy từ GitHub Actions workflow `.github/workflows/build.yml` bằng **Actions → FrameForge Windows Installer Build → Run workflow**, chọn version `0.1.31` và profile `full` hoặc `minimal`. Workflow chạy Windows 2022, build PyInstaller onedir, tạo Inno Setup installer, chạy test suite, kiểm tra PE GUI subsystem, sinh SHA-256/metadata và upload artifact. Workflow này chỉ tạo artifact; việc publish GitHub Release vẫn cần release workflow sau khi kiểm tra artifact.

Script build local tương ứng là `build_installer_v0131.bat`. Script sẽ build lại từ source hiện tại, kiểm tra FFmpeg/ffprobe nhúng và yêu cầu artifact cuối là `installer\\FrameForge-Setup-0.1.31.exe`.

## Smoke test Windows và Process Monitor

Kiểm tra installer, shortcut và PE subsystem bằng PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\\tests\\windows_installer_smoke.ps1 -InstallerPath .\\installer\\FrameForge-Setup-0.1.31.exe
```

Chỉ kiểm tra shortcut/EXE đã cài mà không cài lại:

```powershell
.\\tests\\windows_installer_smoke.ps1 -SkipInstall
```

Khi cần bắt chi tiết process con lúc startup, tải [Process Monitor của Microsoft Sysinternals](https://learn.microsoft.com/sysinternals/downloads/procmon), rồi chạy:

```powershell
.\\tests\\process_monitor_startup.ps1 `
  -ProcmonPath 'C:\\Tools\\Procmon64.exe' `
  -ExecutablePath "$env:LOCALAPPDATA\\Programs\\FrameForge\\VideoScreenshotFilter.exe" `
  -CaptureSeconds 20
```

Script tạo file `.pml`, CSV export nếu Procmon hỗ trợ, và snapshot process tree tại Desktop `FrameForge-Procmon`. Trong Procmon, lọc `Operation = Process Create`, kiểm tra `Process Name`, `Parent PID` và command line. Không gửi PML/CSV công khai trước khi xóa path local, tên tài khoản hoặc tham số nhạy cảm.

Launcher log nằm tại `%LOCALAPPDATA%\\VideoScreenshotFilter\\launcher_error.log`. Có thể kiểm tra nhanh bằng `check_launcher_log.ps1` hoặc theo dõi liên tục bằng `-Watch`.


## Chọn số screenshot cho mỗi video

Trong sidebar, nhập **Số screenshot mỗi video** từ 1 đến 1000. Với **Best frame per scene** và **Scene detection**, đây là số ảnh tối đa; số thực tế có thể thấp hơn nếu video có ít scene hoặc frame bị loại bởi bộ lọc mờ/trùng. Với **Mỗi N giây**, đây là giới hạn trên của số mốc được lấy. Với **Đúng N frame**, giá trị này là số frame chính xác được phân bố đều trong khoảng thời gian đã chọn.

CLI cũng hỗ trợ `--max-screenshots N` cho scene/every mode; `--count N` vẫn giữ semantics cũ là lấy đúng N frame. Khi đổi số lượng trong scene mode, cache scene được invalidated bằng cache key mới để không dùng nhầm danh sách timestamp cũ.

## Ghi chú v0.1.26

P0 v0.1.26 nâng cấp target count bằng candidate budget adaptive: budget bắt đầu theo `target_candidate_multiplier`, tăng khi tỷ lệ frame bị loại cao và dừng ở `target_candidate_multiplier_max`. Report phân biệt candidate đã xét, ảnh đã lưu, nhóm bị loại và shortfall; không chạy vô hạn khi video không đủ frame hợp lệ.

Engine có `verify_video_manifest()` và CLI `--repair-manifest` để phát hiện file output thiếu/thừa sau crash và dựng lại danh sách file bằng atomic JSON write. Resume queue trên Streamlit kiểm tra run signature trước khi cho tiếp tục; khi config hiện tại khác queue cũ, nút resume bị khóa để tránh dùng sai checkpoint hoặc cache.

Bounded scheduler kiểm tra RAM/disk trước mỗi item mới. Khi tài nguyên dưới ngưỡng, queue chuyển sang `resource_wait` và không admit thêm video cho tới khi tài nguyên hồi phục hoặc người dùng cancel. Preview có nút **Phân tích nhanh scene thật**, dùng decode độ phân giải thấp và hiển thị marker scene thực tế tách biệt với timestamp ước tính.

## Ghi chú v0.1.25

FrameForge bổ sung chế độ **Cố gắng đủ số ảnh sau khi lọc**. Với scene/every mode, engine xét thêm candidate trong budget giới hạn để bù ảnh bị loại bởi sharpness, motion blur hoặc duplicate. Report phân biệt `target_screenshots`, `saved`, `shortfall` và `shortfall_reasons`; nếu không đủ ảnh, giao diện nêu rõ lý do.

Mỗi video có `.frameforge_manifest.json` ghi cấu hình an toàn, danh sách file và report. Ảnh được encode vào file tạm rồi rename atomically trước khi report ghi nhận là đã lưu. Resource guard kiểm tra dung lượng ước tính và RAM khả dụng trước khi bắt đầu video. Preview hiển thị các timestamp dự kiến theo mode; scene preview là ước tính, không thay thế scene detection thật.

## Ghi chú v0.1.23

SQLite queue nay dùng state machine có schema version và migration additive từ v0.1.22. Khi mở database cũ, FrameForge tự bổ sung stable `item_id`, `source_position`, phase/progress, heartbeat và timestamps mà không xóa report cũ. Item đang `running` hoặc `retrying` khi ứng dụng dừng bất thường được đánh dấu `interrupted`; resume đưa item về queue mà không đổi định danh.

Retry item dùng stable ID thay vì vị trí hiển thị, tránh lệch mapping khi retry subset. Store có heartbeat/progress, phát hiện job stale, retry failed và đóng connection idempotent. Integration test dùng subprocess và `os._exit()` để mô phỏng crash thật, sau đó reopen/resume và hoàn tất lại queue.

## Ghi chú v0.1.22

Queue nhiều video nay dùng **bounded scheduler**: số item được submit đồng thời không vượt quá số video worker hiệu dụng. Pause không cấp thêm item queued; các video đang chạy kết thúc tại checkpoint an toàn. Cancel có thể ngắt khi queue đang pause hoặc đang retry backoff thay vì chờ hết delay.

Preview được chia thành hai panel cạnh nhau: **Video gốc** và **Crop overlay** theo tỉ lệ đang chọn. Queue per-video dùng accordion, tự mở item đang chạy/lỗi, có filter `Retrying`, summary trạng thái và telemetry attempts, saved, FPS, ETA, RAM. Retry vẫn giữ SQLite/checkpoint và chỉ chạy nguồn video còn tồn tại.

Gói này chứa ứng dụng Streamlit và CLI tối ưu để cắt screenshot từ video. Pipeline mới đọc video **tuần tự một lần**, phân tích frame ở độ phân giải thấp hơn và chỉ mã hóa các frame được chọn ở độ phân giải đầu ra.

## Ghi chú v0.1.21

Tích hợp module queue per-video vào Streamlit chính thông qua adapter tương thích với engine `process_videos` hiện có. Giao diện live hiển thị card riêng cho từng video, trạng thái `queued`, `running`, `retrying`, `paused`, `completed` hoặc `failed`, cùng attempts, số ảnh đã lưu, FPS, ETA, RAM, mã lỗi và gợi ý xử lý. Module được nhúng trong cả ba PyInstaller spec và được Windows CI kiểm tra như runtime module. Bounded scheduler và preview hai panel được hoàn thiện trong v0.1.22.

Các nút **Tạm dừng**, **Tiếp tục**, **Hủy xử lý**, **Thử lại mục thất bại** và **Retry item này** dùng lại pause event, cancel event, SQLite/checkpoint và retry/backoff của engine hiện tại; không thay thế lifecycle bền vững đang có. Retry subset chỉ chạy các report lỗi có file nguồn còn tồn tại. Pause an toàn tại ranh giới video/retry, không dừng giữa một frame. Khi cấu hình nhiều video worker, các video đã submit có thể tiếp tục đến checkpoint gần nhất; muốn pause tuần tự rõ ràng nên đặt `Video xử lý song song = 1`.

## Ghi chú v0.1.14

Bản desktop xóa file input tạm sau từng video hoàn tất và dọn work directory ở cuối job. Job bị hủy vẫn giữ checkpoint/work directory để resume. Khi browser đóng trên bản EXE, session watchdog sẽ hủy job đang chạy, đóng executor, dọn dữ liệu tạm và dừng Streamlit; lệnh `streamlit run` thủ công không bật auto-shutdown.

Khu vực tải video công khai dùng panel responsive hai tầng: vùng URL rộng ở phía trên, quality ở cột bên cạnh, và playlist limit/retry/action ở hàng dưới. Preview video dùng khung 16:9 tối đa 560px, tự co theo màn hình. Theme chính được đồng bộ dark mode cho canvas, card, input, select, timeline và cảnh báo. Screenshot mới có tên dạng `HH-MM-SS.mmm.jpg`; video tải xuống có tên dạng `video_YYYYMMDD_HHMMSS.ext` với hậu tố collision khi cần.

## Ghi chú v0.1.20

Giao diện chính có wizard 4 bước: `Nguồn`, `Chọn frame`, `Chất lượng` và `Đầu ra`. Summary card hiển thị số video, mode, analysis width/FPS, crop ratio, format và encode profile để người dùng kiểm tra trước khi chạy.

Preview video có crop overlay theo ratio đã chọn. Vùng sáng có viền xanh là phần được giữ lại, vùng tối là phần bị cắt; overlay dùng frame đầu để minh họa và không thay đổi file nguồn.

Queue hiển thị per-video với trạng thái, phần trăm, message, attempts, số ảnh đã lưu, FPS, ETA, RAM và chẩn đoán lỗi. `Tạm dừng queue` có hiệu lực ở ranh giới video/retry; video đang chạy không bị cắt giữa frame. Với nhiều video worker, các video đã submit có thể tiếp tục đến checkpoint gần nhất. `Tiếp tục queue` mở lại item còn chờ, `Hủy xử lý` giữ checkpoint, còn retry chỉ chạy các file nguồn thất bại vẫn còn tồn tại.

## Ghi chú v0.1.19

Pipeline ảnh nay tạo một ảnh phân tích nhỏ dùng chung cho grayscale, sharpness, motion blur, dHash và histogram. Các metric không cần thiết sẽ không được tính: job không lọc chất lượng hoặc duplicate có thể bỏ qua Laplacian, Scharr, dHash và histogram tương ứng. Điều này giảm xử lý CPU nhưng vẫn giữ đầy đủ metric khi scene detection, best-frame hoặc bộ lọc được bật.

Bổ sung hai profile encode: `Nhanh` tắt các tối ưu encode tốn CPU để ưu tiên tốc độ, còn `Chất lượng cao` giữ JPEG/WebP/PNG tối ưu hóa để ưu tiên kích thước và chất lượng file. Streamlit, preset, CLI `--encode-profile` và benchmark đều hỗ trợ lựa chọn này.

Benchmark giờ xuất `decode_ms`, `analysis_ms`, `encode_ms`, `write_ms` cùng số lần thực hiện tương ứng. Với multiprocessing, decode được đo ở bước đọc frame tạm trong process cha; vì vậy nên đọc các counters cùng `extraction_mode` khi so sánh.

## Ghi chú v0.1.18

Downloader yt-dlp nay phân loại lỗi theo mã `access_denied`, `rate_limited`, `ffmpeg_missing`, `format_unavailable`, `output_error`, `network_error` hoặc `unknown`. Lỗi tạm thời được retry với exponential backoff theo chu kỳ `1s, 2s, 4s...`, giới hạn tối đa 60 giây; lỗi không thể tự khắc phục như URL riêng tư, thiếu format hoặc không có quyền ghi sẽ dừng ngay và hiển thị gợi ý cụ thể. Queue có thể tiếp tục các URL còn lại thông qua callback lỗi per-video.

## Ghi chú v0.1.17

Bổ sung lựa chọn **tỉ lệ crop screenshot**: `Không crop`, `16:9`, `9:16`, `4:5` và `1:1`. Crop được thực hiện ở chính giữa khung hình, giữ nguyên tỉ lệ không kéo giãn, sau đó mới áp dụng chiều rộng đầu ra. Preset `Video dọc / TikTok` tự chọn `9:16`; các preset khác mặc định không crop nhưng người dùng có thể đổi thủ công.

## Ghi chú v0.1.16

Bản vá downloader cô lập từng URL và từng lần retry vào thư mục staging riêng `.frameforge_download_*`, sau đó chỉ chuyển file hoàn tất sang thư mục video đích. Cách này tránh trường hợp yt-dlp thấy file cùng ID đã tồn tại, bỏ qua download và khiến FrameForge hiểu nhầm là không có file output mới. Staging được dọn cả khi thành công, lỗi hoặc retry.

Nếu một Reel cụ thể vẫn không tải được sau bản vá, nguyên nhân có thể nằm ở trạng thái URL, giới hạn/biến động của Facebook hoặc extractor yt-dlp; không được khắc phục bằng cookie, đăng nhập hay vượt DRM. Hãy thử `Tốt nhất`, kiểm tra URL còn mở công khai trong trình duyệt cùng mạng, và cập nhật FrameForge/yt-dlp lên bản mới nhất.

## Ghi chú v0.1.15

Bản này bổ sung **Preset cấu hình** trong sidebar gồm `Nhanh`, `Cân bằng`, `Chất lượng cao` và `Video dọc / TikTok`. Preset chỉ là điểm khởi đầu có thể chỉnh tiếp; khi đổi preset, các trường scene, phân tích, output, retry, cache và extraction được cập nhật đồng bộ mà không ghi trực tiếp vào widget directory.

Trong lúc xử lý, Web UI hiển thị telemetry theo thời gian thực gồm tốc độ xử lý (FPS), ETA và RAM của process giao diện. FPS/ETA được tính từ các message có số frame hoặc mốc đã hoàn thành; ở giai đoạn chưa có đơn vị đo, UI hiển thị trạng thái chờ thay vì ước đoán không đáng tin. RAM là RSS của process FrameForge, không phải tổng RAM toàn hệ thống hay tổng RSS của các child process.

Adaptive extraction worker nay xét đồng thời **số timestamp yêu cầu, thời lượng video, CPU/RAM và số video worker**. Job ngắn với ít mốc ưu tiên chạy tuần tự để tránh overhead khởi tạo process; job dài hoặc có nhiều mốc mới được cấp thêm extraction process trong giới hạn an toàn. Quy tắc này chỉ áp dụng cho `Mỗi N giây` và `Đúng N frame`; scene mode vẫn decode tuần tự để giữ tính nhất quán của phân tích scene/cache.

## Tính năng

| Tính năng | Mô tả |
|---|---|
| `Best frame per scene` | Chọn frame sắc nét nhất trong từng phân cảnh. |
| Scene detection | Phát hiện thay đổi cảnh bằng sai khác giữa các frame phân tích. |
| Chống flash | Xác nhận thay đổi bằng frame kế tiếp và bỏ thay đổi ngắn quay về cảnh cũ. |
| Sharpness chuẩn hóa | Điểm Laplacian được quy về chuẩn chiều rộng 640 px, dễ dùng giữa nhiều độ phân giải. |
| Phân tích nhanh | `analysis-width` và `analysis-fps` giảm chi phí CPU/RAM. |
| Lọc trùng | dHash 64-bit loại frame gần như giống nhau. |
| Scene timeline | Giao diện HTML/CSS thuần hiển thị mốc scene và bảng timestamp, không cần Pandas/Arrow. |
| Cleanup tạm tự động | Xóa file input tạm sau video hoàn tất và dọn work directory an toàn theo trạng thái job. |
| Desktop lifecycle | Browser đóng sẽ hủy job, đóng executor và dừng server ở bản EXE desktop. |
| Dark responsive downloader | Khu vực tải video công khai cân bằng theo grid hai tầng, phù hợp dark mode và màn hình hẹp. |
| Download staging an toàn | Mỗi URL/retry tải vào staging riêng, tránh output cũ làm yt-dlp bỏ qua file mới và được dọn tự động. |
| Chẩn đoán downloader | Phân loại lỗi theo nguyên nhân, retry exponential backoff cho lỗi tạm thời và giữ queue tiếp tục các URL còn lại. |
| Preset cấu hình | Bốn preset cho tốc độ, cân bằng, chất lượng cao và video dọc; mọi giá trị vẫn có thể tinh chỉnh thủ công. |
| Live telemetry | Hiển thị FPS, ETA và RSS RAM trong lúc xử lý; ETA chỉ xuất hiện khi đã có đơn vị tiến độ hợp lệ. |
| Adaptive worker theo duration | Cấp extraction worker dựa trên thời lượng cùng số timestamp, ngoài CPU/RAM và số video worker. |
| Crop tỉ lệ screenshot | Crop trung tâm theo `16:9`, `9:16`, `4:5`, `1:1` hoặc giữ nguyên; crop trước resize để không méo hình. |
| Conditional image metrics | Chỉ tính sharpness, motion blur, dHash và histogram khi tính năng tương ứng cần dùng. |
| Encode profiles | Chọn `Nhanh` hoặc `Chất lượng cao` cho JPEG/WebP/PNG. |
| Stage timing benchmark | Đo riêng decode, analysis, encode và write theo ms/count. |

## Cấu trúc

| File | Vai trò |
|---|---|
| `streamlit_app.py` | Giao diện Web. |
| `video_screenshot_advanced.py` | Pipeline CLI, scene detection và bộ lọc ảnh. |
| `requirements.txt` | Dependency Python cho profile minimal. |
| `requirements_full.txt` | Dependency mở rộng cho profile full. |
| `video_screenshot_filter_minimal.spec` | Spec onedir giảm dependency UI không dùng. |
| `video_screenshot_filter_onedir.spec` | Spec onedir full. |
| `build_windows.bat` | Build profile full/minimal trên Windows. |
| `FrameForge.iss` | Cấu hình installer Inno Setup. |
| `build_installer.bat` | Biên dịch Setup bằng `ISCC.exe`. |
| `measure_package_size.py` | Đo runtime và liệt kê file lớn nhất. |
| `Dockerfile` | Chạy trong Docker, kèm FFmpeg. |
| `run.sh` | Khởi động Linux/macOS. |
| `run_windows.bat` | Khởi động Windows. |
| `README_video_screenshot_advanced.md` | Tài liệu chi tiết. |

## Chạy trên Linux/macOS

Cần Python 3.10 trở lên và FFmpeg/ffprobe:

```bash
sudo apt update
sudo apt install ffmpeg python3-venv
chmod +x run.sh
./run.sh
```

Ứng dụng mở tại `http://localhost:8501`.

## Chạy bằng Streamlit thủ công

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

Trong Web UI, chọn **Best frame per scene** để giữ một frame sắc nét nhất trong mỗi scene. Timeline sẽ xuất hiện sau khi xử lý xong. Kết quả tải về gồm toàn bộ ảnh và `report.json` trong một file ZIP.

## Chạy CLI tối ưu

```bash
python3 video_screenshot_advanced.py video.mp4 \
  --best-frame-per-scene \
  --scene-threshold 0.30 \
  --min-scene-gap 0.5 \
  --analysis-width 640 \
  --analysis-fps 8 \
  --min-sharpness 100 \
  --duplicate-threshold 6 \
  --output screenshots_by_scene
```

Với video lớn cần lấy nhiều mốc cố định, có thể bật multiprocessing cho bước seek/trích frame:

```bash
python3 video_screenshot_advanced.py video.mp4 \
  --count 120 \
  --extract-workers 4 \
  --output screenshots_fixed
```

Một số tùy chọn hiệu năng:

| Tùy chọn | Ý nghĩa |
|---|---|
| `--analysis-width 640` | Thu nhỏ frame trước khi phân tích. Giảm xuống 320 nếu ưu tiên tốc độ. |
| `--analysis-fps 8` | Chỉ phân tích tối đa 8 frame/giây cho scene. Tăng lên 15–24 nếu cảnh thay đổi rất nhanh. |
| `--width 1280` | Chiều rộng ảnh lưu ra; không ảnh hưởng đến độ phân giải phân tích. |
| `--min-sharpness 100` | Ngưỡng độ nét chuẩn hóa theo chiều rộng tham chiếu 640 px. |
| `--flash-return-ratio 0.55` | Mức tương đồng với cảnh cũ để nhận diện flash. |
| `--flash-brightness-threshold 0.18` | Giới hạn thay đổi độ sáng khi xác nhận flash. |
| `--extract-workers N` | Số process trích frame cho fixed/count mode. `0` tự chọn tối đa 4, `1` chạy tuần tự; adaptive budget còn xét số timestamp, thời lượng, số video worker, CPU và RAM. Job ngắn/ít mốc thường giữ 1 process để tránh overhead. |
| `--queue-db FILE` | SQLite queue bền vững; mặc định là `<output>/.frameforge_queue.sqlite3`. |
| `--temp-quota-mb N` | Quota work directory tạm cũ; mặc định 2048 MB, `0` để tắt quota. |
| `--cache-quota-mb N` | Quota scene cache cũ; mặc định 1024 MB, `0` để tắt. |

## Scene detection thông thường

Nếu không dùng `--best-frame-per-scene`, có thể dùng:

```bash
python3 video_screenshot_advanced.py video.mp4 \
  --scene-detection \
  --scene-threshold 0.30 \
  --min-scene-gap 0.5
```

Pipeline vẫn đọc video một lần. Chế độ này giữ frame đầu của mỗi scene; chế độ Best frame per scene giữ frame có điểm sharpness cao nhất trong scene đó. Multiprocessing extraction chỉ áp dụng cho fixed/count mode; process chính vẫn giữ thứ tự timestamp, áp dụng lọc và là nơi duy nhất ghi output để tránh race condition. Scene mode tiếp tục decode tuần tự nhằm bảo toàn scene cache.

Từ v0.1.7, queue xử lý screenshot được lưu bền vững bằng SQLite tại `<output>/.frameforge_queue.sqlite3`. Database giữ trạng thái từng video, attempts, lỗi cuối và report để resume sau khi app bị đóng; JSON checkpoint vẫn được giữ để tương thích ngược. Khi hủy ở single-worker mode, các item còn lại được đánh dấu `cancelled` và database được đóng sạch.

Từ v0.1.9, report bổ sung `video_workers`, `configured_extract_workers` và `adaptive_extract_workers`. Khi chạy nhiều video cùng lúc, FrameForge tự hạ số process extraction trên mỗi video để tránh dùng CPU/RAM quá mức; Streamlit cũng hiển thị các giá trị thực tế sau khi hoàn tất. Từ v0.1.15, quyết định này còn xét thời lượng video và số timestamp; vì vậy cùng một cấu hình worker có thể chạy tuần tự trên clip ngắn nhưng dùng multiprocessing trên job dài/nhiều mốc.

Trong Web UI, chọn preset ở đầu sidebar rồi kiểm tra lại các trường đã được điền trước khi xử lý. `Nhanh` giảm chi phí phân tích, `Cân bằng` là mặc định, `Chất lượng cao` ưu tiên phân tích và ảnh đầu ra, còn `Video dọc / TikTok` đặt khung phân tích/output phù hợp nội dung dọc. Preset không thay thế quyền chỉnh thủ công.

Telemetry hiển thị `FPS`, `ETA` và `RAM process`. FPS là số đơn vị progress đã hoàn thành chia cho thời gian chạy; ETA là ước tính tuyến tính còn lại khi có tổng đơn vị; RAM là RSS của process cha. Các chỉ số có thể dao động do seek, codec, bộ lọc chất lượng, multiprocessing và tốc độ ổ đĩa.

Từ v0.1.10, dHash index được ghi theo bucket byte ở định dạng v2 để giảm số hash phải so sánh khi threshold không vượt quá 6. Index định dạng v1 chỉ có mảng `hashes` vẫn được đọc bình thường và tự nâng cấp ở lần ghi kế tiếp. CLI dọn work directory tạm cũ theo tuổi và quota, đồng thời dọn scene cache cũ nhất khi vượt quota.

Benchmark CI nằm tại `benchmarks/benchmark_frame_extraction.py` và đo elapsed time, throughput, RSS memory cho các mức `--workers`. Kết quả được lưu thành artifact trên pull request và Windows release, không áp dụng speedup cố định vì còn phụ thuộc codec, CPU và ổ đĩa.

## Chạy bằng Docker

```bash
docker build -t video-screenshot-filter .
docker run --rm -p 8501:8501 video-screenshot-filter
```

Mở `http://localhost:8501`. Dockerfile tự cài FFmpeg và dependency Python.

## Báo cáo

CLI có thể ghi báo cáo bằng `--report report.json`. Với scene mode, trường `scene_times` chứa các mốc timestamp phát hiện được và `selected_times` chứa frame đại diện đã chọn. Các trường `saved`, `rejected_blurry`, `rejected_duplicate`, `rejected_duplicate_cross_run`, `cache_hit` và `capture_errors` giúp đánh giá chất lượng xử lý.

FrameForge lưu scene cache JSON theo fingerprint của video và cấu hình phân tích. Có thể dùng lại cache bằng `--cache-dir`, tiếp tục queue bằng `--resume --checkpoint FILE`, và dùng `--duplicate-index-dir` để loại các frame gần trùng với những lần chạy trước. Trong Streamlit, phần **Timeline tương tác** cho phép lọc video/scene/khoảng thời gian, zoom vùng timeline, chọn marker, điều chỉnh timestamp và xem preview frame gần nhất.

Updater ứng dụng có hai kênh: `stable` dùng `latest.json`, còn `beta` dùng prerelease asset `latest-beta.json`. Có thể chuyển kênh trong UI hoặc đặt `FRAMEFORGE_UPDATE_CHANNEL=beta`. Release notes được nhúng vào manifest và hiển thị trong expander **Xem release notes**. Stable manifest mới có thể chứa metadata rollback tới release stable trước đó; rollback luôn kiểm tra HTTPS và SHA-256 trước khi mở installer.

## Tham khảo

1. [OpenCV VideoCapture Documentation](https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html)
2. [Streamlit Documentation](https://docs.streamlit.io/)
3. [FFmpeg Documentation](https://ffmpeg.org/documentation.html)
4. [Docker Documentation](https://docs.docker.com/)

## Build bản Windows `.exe`

Gói này có `windows_launcher.py`, hai spec PyInstaller và `build_windows.bat`. Việc build executable Windows phải thực hiện trên **Windows** để PyInstaller tạo đúng binary Windows. Profile mặc định là **onedir**, gồm một thư mục runtime đầy đủ và khởi động thuận tiện hơn one-file.

Trên máy Windows:

```bat
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
build_windows.bat
```

File kết quả mặc định là:

```text
dist\VideoScreenshotFilter\VideoScreenshotFilter.exe
```

Bản onedir nhúng Python, Streamlit, OpenCV, NumPy, Pillow, yt-dlp và FFmpeg/ffprobe. Người dùng cuối không cần cài FFmpeg bên ngoài. Toàn bộ thư mục `dist\VideoScreenshotFilter` phải được giữ nguyên khi di chuyển hoặc phát hành.

Nếu cần file duy nhất, có thể dùng `set BUILD_MODE=onefile` trước khi chạy build; đây là profile full dự phòng, khởi động chậm hơn và khó chẩn đoán hơn. Trong môi trường Linux hiện tại không có Windows toolchain, Wine hoặc Docker Windows, nên không thể tạo/xác nhận trực tiếp binary `.exe`; các script Windows đã được chuẩn bị sẵn trong package.

## Bản EXE không hiện cửa sổ CMD

`video_screenshot_filter.spec` đã dùng `console=False`, tương đương chế độ `--windowed`/`--noconsole` của PyInstaller. Sau khi build lại bằng `build_windows.bat`, double-click `VideoScreenshotFilter.exe` sẽ không mở cửa sổ CMD.

Launcher chạy Streamlit ở chế độ headless, chờ `http://localhost:8501` phản hồi rồi tự mở tab trình duyệt. Nếu launcher gặp lỗi trước khi server khởi động, không có CMD để xem log; thay vào đó lỗi được ghi tại:

```text
%LOCALAPPDATA%\VideoScreenshotFilter\launcher_error.log
```

Muốn xem log trực tiếp trong CMD khi chẩn đoán, có thể dùng bản debug riêng với cấu hình PyInstaller `console=True`, hoặc chạy source bằng:

```bat
streamlit run streamlit_app.py
```

### Lưu ý sau lỗi `Not Found`

Nếu EXE mở được cổng `8501` nhưng truy cập trang lại hiện `Not Found`, đó là bản build cũ. Launcher mới ép `global.developmentMode=false` bằng API cấu hình nội bộ trước khi chạy Streamlit; sau khi rebuild, log phải hiển thị URL `http://localhost:8501` thay vì `http://localhost:3000`.

Hãy xóa thư mục `build` và `dist` cũ trước khi chạy lại `build_windows.bat`. Không chạy lại EXE cũ trong thư mục `dist` cũ.

## Preview video và xử lý đa luồng

Trong Streamlit, sau khi tải video lên, khu vực **Xem trước video** sẽ xuất hiện. Chọn video trong danh sách để phát trực tiếp trước khi bấm **Bắt đầu xử lý**. Preview dùng chính file đã tải lên và không tạo file trung gian. MP4/H.264 thường có khả năng phát tốt nhất trên trình duyệt; một số codec MKV, TS hoặc AVI có thể cần chuyển đổi sang MP4.

Thanh bên có tùy chọn **Video xử lý song song**. Mỗi worker xử lý một video độc lập, trong khi pipeline bên trong mỗi video vẫn đọc tuần tự một lần. Với một video, nên đặt giá trị 1; với nhiều video, có thể bắt đầu từ 2 hoặc 3. Nếu máy có ít RAM hoặc video 4K, giảm số worker để tránh dùng quá nhiều tài nguyên.

CLI tương ứng:

```bash
python3 video_screenshot_advanced.py ./videos \
  --workers 3 \
  --best-frame-per-scene \
  --analysis-width 640 \
  --analysis-fps 8 \
  --output ./screenshots_filtered
```

Báo cáo JSON vẫn được trả theo đúng thứ tự file đầu vào dù các worker hoàn thành không theo thứ tự. Log trên Web UI hiển thị video nào đã hoàn tất và số ảnh đã lưu.

## Build EXE giao diện mới

Trên Windows, giải nén package vào thư mục mới, xóa `build` và `dist` cũ nếu có, rồi chạy `build_windows.bat`. EXE onedir mới nằm tại `dist\VideoScreenshotFilter\VideoScreenshotFilter.exe`. Bản release dùng `console=False`, tự mở trình duyệt tại `http://localhost:8501`, có preview video, giao diện FrameForge, xử lý đa luồng và FFmpeg nhúng. Nếu app không mở, xem `%LOCALAPPDATA%\VideoScreenshotFilter\launcher_error.log`.

## Tải video công khai từ Facebook, TikTok và Pinterest

Giao diện FrameForge có khu vực **Tải video công khai** ở phía trên. Dán URL `http(s)` của một video công khai, chọn **Tốt nhất**, **1080p**, **720p** hoặc **480p**, rồi bấm **Tải video**. Sau khi tải xong, file được giữ trong phiên làm việc, có thể xem preview và dùng ngay cho pipeline screenshot.

Tính năng này dùng [yt-dlp](https://github.com/yt-dlp/yt-dlp), một bộ tải video hỗ trợ nhiều extractor và có cơ chế chọn format. Ứng dụng chỉ nhận host thuộc Facebook, TikTok, Pinterest, `fb.watch` hoặc `pin.it`; không truyền cookie, không yêu cầu đăng nhập và không cố vượt DRM hoặc nội dung riêng tư.

> Chỉ tải nội dung bạn sở hữu, được chủ sở hữu cho phép hoặc có giấy phép sử dụng phù hợp. Người dùng chịu trách nhiệm tuân thủ điều khoản nền tảng và quyền tác giả đối với URL được nhập.

### FFmpeg và chất lượng cao

Để ghép video và audio riêng thành file MP4 chất lượng cao, cài FFmpeg và bảo đảm `ffmpeg` có trong `PATH`:

```bash
ffmpeg -version
```

Nếu chạy source mà không có FFmpeg, yt-dlp có thể chỉ chọn được format kết hợp sẵn hoặc báo lỗi khi format chất lượng cao yêu cầu ghép stream. Bản Windows đóng gói bằng `build_windows.bat` tự nhúng `ffmpeg.exe` và `ffprobe.exe`, nên người dùng cuối không phải cấu hình `PATH`.

Khi chạy source:

```bash
python -m pip install -r requirements_video_screenshot.txt
streamlit run streamlit_app.py
```

Khi build EXE trên Windows, `yt-dlp` và FFmpeg/ffprobe được nhúng vào PyInstaller. Sau khi tải, bấm **Bắt đầu xử lý** để tạo screenshot; file tải về được đưa vào cùng danh sách với video upload.

### CLI downloader tối giản

Có thể dùng module downloader từ Python:

```python
from pathlib import Path
from video_downloader import download_public_video

result = download_public_video(
    "https://www.tiktok.com/...",
    Path("downloads"),
    quality="1080p hoặc thấp hơn",
)
print(result.path)
```

Module sẽ từ chối URL ngoài ba nền tảng được hỗ trợ và không có API để cung cấp thông tin đăng nhập hoặc vượt qua nội dung bảo vệ.

## Downloader và tài liệu tham khảo

| Thành phần | Vai trò |
|---|---|
| `video_downloader.py` | Kiểm tra host, chọn format và tải video công khai bằng yt-dlp. |
| `requirements_video_screenshot.txt` | Có thêm dependency `yt-dlp`. |
| `video_screenshot_filter.spec` | Nhúng module và hidden imports của yt-dlp vào PyInstaller. |

Tham khảo: [yt-dlp repository](https://github.com/yt-dlp/yt-dlp), [yt-dlp supported sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md), [FFmpeg documentation](https://ffmpeg.org/documentation.html).

## Queue và playlist downloader

Khu vực **Tải video công khai** nhận nhiều URL, mỗi URL trên một dòng. URL đơn tải một video; URL playlist sẽ được mở rộng theo giới hạn **Tối đa mỗi playlist**. Các URL được xử lý tuần tự để giảm tải mạng và tránh ghi đè tên file. Trường **Retry tải** cho phép tự thử lại từng URL khi lỗi mạng tạm thời; các file tải thành công trước đó vẫn được giữ trong phiên làm việc, có thể preview, đưa thẳng vào pipeline screenshot hoặc tải toàn bộ dưới dạng ZIP.

```text
https://www.tiktok.com/...
https://www.facebook.com/...
https://pin.it/...
```

API Python tương ứng là `download_public_videos(urls, output_dir, quality, max_playlist_items=50, max_retries=2, retry_delay_seconds=1.0)`. Queue được giới hạn tối đa 100 URL trong một lần gọi; playlist có giới hạn riêng bằng `max_playlist_items`.

Khi bấm **Bắt đầu xử lý**, FrameForge chạy queue screenshot trong job nền và hiển thị progress tổng thể cùng progress riêng cho từng video. Có thể bấm **Hủy xử lý** để dừng tại checkpoint an toàn; mỗi video lỗi sẽ được retry độc lập trước khi queue chuyển sang item kế tiếp. Ứng dụng kiểm tra vùng đệm dung lượng tại thư mục screenshot trước khi chạy, ghi `report.json` trong thư mục run và tự dọn work directory tạm cũ có tiền tố `video_screenshot_web_`.

## Health check FFmpeg

Ứng dụng tự kiểm tra `ffmpeg` và `ffprobe` trong `PATH` trước khi tải. Nếu thiếu FFmpeg, giao diện cảnh báo rằng các format video/audio tách riêng có thể không ghép được. Dùng lệnh sau để kiểm tra thủ công:

```bash
ffmpeg -version
ffprobe -version
```

`ffmpeg` là thành phần cần thiết khi muốn ghép video và audio thành một file MP4 chất lượng cao; yt-dlp vẫn được nhúng trong Python/EXE nhưng FFmpeg nên được cài riêng trên máy đích.

## Kiểm tra PyInstaller hidden imports

`video_screenshot_filter.spec` vừa dùng `collect_all("yt_dlp")` vừa gọi `collect_submodules("yt_dlp")`. Cấu hình này bao phủ các extractor động của yt-dlp, bao gồm extractor liên quan đến Facebook, TikTok và Pinterest, trong one-file build. Sau mỗi lần nâng cấp yt-dlp, nên build lại EXE sạch bằng cách xóa `build` và `dist`, rồi chạy `build_windows.bat`.

## Nhúng FFmpeg trực tiếp vào file EXE

Bản EXE có thể nhúng sẵn `ffmpeg.exe` và `ffprobe.exe` để người dùng cuối không phải cài FFmpeg bên ngoài. Gói sử dụng layout sau:

```text
vendor\ffmpeg\
  ffmpeg.exe
  ffprobe.exe
  LICENSE hoặc COPYING
  BUILD_METADATA.txt
```

### Cách build tự động trên Windows

Từ thư mục gốc package, mở PowerShell hoặc CMD và chạy:

```powershell
powershell -ExecutionPolicy Bypass -File .\prepare_ffmpeg_windows.ps1
```

Script sẽ tải archive Windows static theo URL đã ghim, giải nén hai executable, chép các file license/readme tìm được và tạo `BUILD_METADATA.txt` gồm URL cùng SHA-256. Sau đó build EXE:

```bat
build_windows.bat
```

`build_windows.bat` cũng tự gọi bước chuẩn bị FFmpeg nếu chưa có `vendor\ffmpeg\ffmpeg.exe`, kiểm tra `ffprobe.exe`, rồi chạy PyInstaller. Với profile onedir, người dùng cuối nhận toàn bộ thư mục `dist\VideoScreenshotFilter`; FFmpeg nằm trong thư mục runtime và được tìm từ `_MEIPASS\vendor\ffmpeg` khi chạy one-file hoặc từ thư mục package khi chạy onedir. Không xóa các file con trong package.

### Cách chọn binary

Nên dùng Windows x86_64 static build tương thích với máy đích và ghim một release cụ thể thay vì dùng URL thay đổi không kiểm soát. Package mẫu đang tham chiếu bản `win64-lgpl`; nếu ứng dụng cần codec hoặc tính năng chỉ có trong GPL build, phải kiểm tra lại toàn bộ nghĩa vụ cấp phép trước khi phân phối. Không dùng bản `nonfree` cho sản phẩm nếu chưa có đánh giá pháp lý phù hợp.

Bản static được ưu tiên vì `ffmpeg.exe` và `ffprobe.exe` ít phụ thuộc DLL bên ngoài hơn bản shared. Bản shared có thể nhỏ hơn nhưng phải nhúng thêm DLL liên quan và kiểm tra PATH/runtime kỹ hơn.

### Cách runtime tìm FFmpeg

Module `video_downloader.py` tìm theo thứ tự:

```text
1. _MEIPASS\vendor\ffmpeg\ffmpeg.exe  (khi chạy EXE one-file)
2. vendor\ffmpeg\ffmpeg.exe           (khi chạy source/package)
3. ffmpeg trong PATH                    (fallback)
```

Health check trả về path, version, `ffmpeg_installed`, `ffprobe_installed`, `ready_for_merge` và `source=embedded` hoặc `source=PATH`. Giao diện sẽ cảnh báo nếu không tìm thấy binary hoặc binary không chạy được.

### Kiểm tra sau khi build

Trước khi phát hành, kiểm tra archive và binary:

```bat
vendor\ffmpeg\ffmpeg.exe -version
vendor\ffmpeg\ffprobe.exe -version
certutil -hashfile vendor\ffmpeg\ffmpeg.exe SHA256
certutil -hashfile vendor\ffmpeg\ffprobe.exe SHA256
```

Sau khi chạy EXE, vào khu vực tải video công khai và xác nhận health check hiển thị `source=embedded`. Thử một format cần ghép video/audio, sau đó kiểm tra file MP4 đầu ra bằng `ffprobe.exe`.

### Giấy phép và file phải giữ lại

FFmpeg nêu rằng mã nguồn chính chủ yếu theo LGPL 2.1+, nhưng một số phần tùy chọn có thể theo GPL; build có thành phần GPL sẽ kéo theo phạm vi giấy phép khác. Trang pháp lý chính thức cũng khuyến nghị xác định chính xác configure flags, source tương ứng, license và thay đổi của binary được phân phối [1]. Vì vậy, không xóa `LICENSE`/`COPYING`, `BUILD_METADATA.txt` hoặc source/configuration information của binary đã chọn.

Nếu phân phối phần mềm cho người khác hoặc dùng trong sản phẩm thương mại, hãy rà soát license và codec/patent obligations với người có chuyên môn. Đây là yêu cầu phân phối phần mềm, không chỉ là thao tác kỹ thuật.

### Nguồn binary và tài liệu

URL mặc định trong `prepare_ffmpeg_windows.ps1` trỏ tới một Windows x86_64 LGPL build cụ thể của BtbN. Đây là nguồn build bên thứ ba, không phải binary do dự án FFmpeg chính thức phát hành; hãy kiểm tra checksum và license của archive trước khi dùng. FFmpeg chính thức cung cấp source code và trang legal/download để đối chiếu [1] [2].

[1]: https://www.ffmpeg.org/legal.html "FFmpeg License and Legal Considerations"
[2]: https://ffmpeg.org/download.html "FFmpeg Download"
[3]: https://github.com/BtbN/FFmpeg-Builds/releases "BtbN FFmpeg Builds Releases"

## Auto-updater yt-dlp

Khi ứng dụng mở, updater kiểm tra metadata PyPI tối đa một lần mỗi 24 giờ. Nếu có phiên bản mới, ứng dụng tải wheel `py3-none-any`, đối chiếu SHA-256 với digest trong metadata HTTPS, kiểm tra cấu trúc package rồi lưu vào `%LOCALAPPDATA%\VideoScreenshotFilter\yt_dlp_updates`. Bản mới không thay thế code đang chạy; nó được kích hoạt ở lần mở ứng dụng kế tiếp. Nếu mạng lỗi hoặc checksum không khớp, updater bỏ qua thay đổi và giữ bản hiện tại.

Có thể tắt updater bằng biến môi trường trước khi chạy:

```bat
set FRAMEFORGE_AUTO_UPDATE=0
VideoScreenshotFilter.exe
```

Log updater nằm tại:

```text
%LOCALAPPDATA%\VideoScreenshotFilter\yt_dlp_update.log
```

Cơ chế này cập nhật package yt-dlp chứ không tự thay thế toàn bộ `VideoScreenshotFilter.exe`. Việc cập nhật toàn bộ ứng dụng nên dùng installer/release có manifest và chữ ký riêng.

## Đo kích thước EXE

Sau build, `build_windows.bat` tự chạy:

```bat
python measure_package_size.py . --json build_size_report.json
```

Báo cáo tách `vendor_ffmpeg`, `pyinstaller_dist`, `pyinstaller_build` và các file Python. Với one-file, kích thước thường tăng mạnh do FFmpeg static và các thư viện native. Dùng số liệu thực tế từ `build_size_report.json` thay vì ước lượng.

Các phương án giảm dung lượng gồm sử dụng build FFmpeg tối giản nhưng vẫn đúng license, loại bỏ package/hidden import không cần thiết sau khi kiểm tra feature, dùng `onedir` thay cho `onefile` nếu ưu tiên kích thước/khởi động, hoặc tách FFmpeg thành download-on-first-run đã xác minh nếu người dùng chấp nhận tải lần đầu. Không nên cắt codec hoặc xóa DLL chỉ để giảm dung lượng nếu chưa kiểm thử toàn bộ format cần hỗ trợ.

### Số đo dung lượng tham khảo

Archive Windows x86_64 LGPL static đã chọn có kích thước khoảng **140.20 MiB**; riêng `ffmpeg.exe` là khoảng **109.10 MiB** và `ffprobe.exe` khoảng **108.91 MiB**, tổng hai binary khoảng **218.01 MiB**. Đây là số đo archive/binary tham khảo; kích thước cài đặt Windows cuối cùng phải được đo sau khi Inno Setup đóng gói.

Các lựa chọn thực tế là giữ static LGPL để đơn giản và ổn định; dùng build FFmpeg tối giản đúng license để giảm codec không cần thiết; dùng `onedir` để giảm thời gian khởi động dù tổng dung lượng có thể không giảm; hoặc tách FFmpeg thành gói tải lần đầu có checksum. Không nên dùng build GPL/nonfree hoặc xóa codec chỉ vì muốn giảm dung lượng nếu chưa rà soát license và test các format mục tiêu.

## Profile phát hành cân bằng: onedir

Profile mặc định của `build_windows.bat` hiện là **onedir**. Chạy:

```bat
build_windows.bat
```

Kết quả:

```text
dist\VideoScreenshotFilter\VideoScreenshotFilter.exe
```

Toàn bộ thư mục `dist\VideoScreenshotFilter` phải được giữ nguyên khi di chuyển hoặc phát hành. FFmpeg/ffprobe nhúng nằm trong thư mục runtime của package; không xóa các thư mục con hoặc DLL đi kèm.

Nếu thực sự cần một file duy nhất, dùng:

```bat
set BUILD_MODE=onefile
build_windows.bat
```

Kết quả khi đó là `dist\VideoScreenshotFilter.exe`, nhưng thời gian khởi động dài hơn và việc cập nhật/chẩn đoán kém thuận tiện hơn so với onedir.

Trong profile onedir, updater yt-dlp lưu bản override tại `%LOCALAPPDATA%\VideoScreenshotFilter\yt_dlp_updates`, không sửa file trong thư mục cài đặt. Vì vậy người dùng không cần quyền admin để cập nhật yt-dlp. Khi phát hành phiên bản FrameForge mới, thay toàn bộ thư mục onedir bằng package mới sau khi kiểm tra checksum/chữ ký.

Trong profile full onedir, build thử nghiệm Linux hiện có tổng kích thước **622.06 MiB** trước khi nhúng FFmpeg Windows. Profile minimal onedir cùng mã nguồn, sau khi loại Pandas/PyArrow/PyDeck/Matplotlib/Plotly Python packages và thay bảng timeline bằng HTML, đo được **324.10 MiB** trước FFmpeg. Thành phần native lớn nhất vẫn là OpenCV/cv2 và NumPy; vì vậy mục tiêu dưới 200 MB không khả thi với Streamlit + OpenCV + FFmpeg static nhúng đầy đủ. Hãy dùng `build_size_report.json` sau build Windows để quyết định dựa trên số đo thực tế.

## Profile minimal và kết quả đo

Profile minimal được chọn khi muốn giảm phần dependency không dùng nhưng vẫn giữ các chức năng cốt lõi: Streamlit UI, preview, downloader yt-dlp, scene detection, motion-blur filter, dHash, Best frame per scene và xử lý đa luồng. Timeline đã chuyển sang HTML/CSS thuần; `requirements.txt` không còn Pandas, còn spec minimal loại thêm PyArrow, PyDeck, Altair, Matplotlib, Plotly, Boto3 và Botocore.

Trên Windows, build profile minimal như sau:

```bat
set BUILD_PROFILE=minimal
set BUILD_MODE=onedir
build_windows.bat
```

Kết quả nằm tại `dist\VideoScreenshotFilter\`. Profile full vẫn là lựa chọn tương thích rộng hơn:

```bat
set BUILD_PROFILE=full
set BUILD_MODE=onedir
build_windows.bat
```

Build thử nghiệm Linux cho cùng mã nguồn đo được khoảng **622.06 MiB** với full profile và **324.10 MiB** với minimal profile, đều chưa nhúng cặp FFmpeg Windows. Đây là số đo tham khảo, không thay thế phép đo trên Windows. Cặp FFmpeg static đã chọn khoảng **218.01 MiB** riêng hai binary, nên tổng installed size dưới 200 MB là không thực tế nếu vẫn giữ Streamlit, OpenCV và FFmpeg offline đầy đủ. Có thể giảm download size nhờ nén installer, nhưng điều đó không biến installed size thành dưới 200 MB.

| Mục tiêu | Profile phù hợp | Đánh đổi |
|---|---|---|
| Offline, đủ tính năng, không cài FFmpeg ngoài | Full onedir + embedded FFmpeg | Dung lượng lớn nhất nhưng ổn định và ít bất ngờ. |
| Giữ tính năng cốt lõi, bỏ dependency UI không dùng | Minimal onedir + embedded FFmpeg | Nhỏ hơn đáng kể; phải regression-test các widget Streamlit sau mỗi lần nâng phiên bản. |
| EXE/download nhỏ nhất | Minimal + FFmpeg tải lần đầu có checksum | Cần mạng ở lần đầu và phải xử lý cache, retry, license/source metadata. |

Không nên xóa DLL OpenCV hoặc codec FFmpeg tùy tiện. Nếu muốn thấp hơn nữa, hướng có cơ sở nhất là thay OpenCV bằng backend nhẹ hơn hoặc tách downloader/FFmpeg thành thành phần tùy chọn, nhưng đó là thay đổi kiến trúc và phải kiểm thử lại toàn bộ scene detection, motion blur, preview và chất lượng output.

## Tạo installer Windows bằng Inno Setup

Installer khuyến nghị là **Inno Setup 6**. File `FrameForge.iss` đóng gói toàn bộ `dist\VideoScreenshotFilter\*`, tạo shortcut Start Menu và shortcut Desktop tùy chọn, cài mặc định vào `%LOCALAPPDATA%\Programs\FrameForge`, thêm uninstaller và cung cấp tùy chọn mở FrameForge sau khi cài. Cách cài theo user giúp updater yt-dlp ghi được vào `%LOCALAPPDATA%` mà không cần quyền administrator.

Sau khi cài Inno Setup 6, mở CMD tại thư mục package và chạy:

```bat
set BUILD_PROFILE=minimal
set BUILD_MODE=onedir
build_windows.bat
build_installer.bat
```

Installer được tạo trong thư mục `installer\` với tên dạng `FrameForge-Setup-1.0.0.exe`. Nếu Inno Setup nằm ở vị trí tùy chỉnh, đặt biến môi trường `ISCC` trỏ tới `ISCC.exe` rồi chạy lại `build_installer.bat`. Inno Setup và Windows compiler không có trong môi trường Linux hiện tại, vì vậy bước biên dịch installer phải được thực hiện và kiểm tra trên Windows.

Sau khi build, nên cài thử trên một user Windows sạch, mở shortcut, xác nhận trình duyệt truy cập được `http://127.0.0.1:8501`, kiểm tra health check báo `source=embedded`, tải một video công khai được phép, thử format cần ghép audio/video và chạy pipeline Best frame per scene. Không phát hành riêng file `.exe` bên trong onedir; phải phân phối installer hoặc toàn bộ thư mục runtime.

## Đo artifact và kiểm tra trước phát hành

Công cụ `measure_package_size.py` hỗ trợ dist path cụ thể và in top thư mục/file lớn nhất:

```bat
python measure_package_size.py . --dist-path dist\VideoScreenshotFilter --top 20 --json build_size_report.json
```

Báo cáo giúp phân biệt `runtime_dist_total` với source/build và tránh cộng đúp symlink trên Linux. Trên Windows, hãy ưu tiên đo cả kích thước thư mục cài đặt sau khi cài và kích thước file Setup sau khi Inno Setup nén. Hai con số này phục vụ hai mục tiêu khác nhau: dung lượng đĩa người dùng và dung lượng tải xuống.


## Tự động build bằng GitHub Actions

Package đã có workflow `.github/workflows/windows-release.yml` chạy trên Windows runner. Workflow cài Python 3.12, cache pip, build PyInstaller onedir, cài Inno Setup, tạo `FrameForge-Setup-<version>.exe`, chạy đo kích thước, tạo SHA-256 và upload Setup cùng report vào GitHub Actions Artifact.

Khi push tag dạng `v1.2.3`, workflow mặc định build profile `minimal` và tự tạo GitHub Release với Setup, `SHA256SUMS.txt` và `build_size_report.json`. Khi chạy thủ công từ tab **Actions**, có thể chọn `minimal` hoặc `full`; nếu muốn tạo Release trong lần chạy thủ công trên một tag, bật `publish_release`.

```text
.github/workflows/windows-release.yml
```

Workflow dùng `GITHUB_TOKEN` với quyền `contents: write` để upload release. Repository cần bật Actions và quyền workflow được phép tạo Release. Không đưa token cá nhân hoặc secret FFmpeg vào file YAML. Nếu muốn dùng URL FFmpeg đã ghim riêng, nên đưa URL vào Repository Variable/Secret và truyền vào `prepare_ffmpeg_windows.ps1`; không nên dựa mãi vào alias `latest` cho bản phát hành reproducible.

Artifacts của workflow có thời hạn lưu mặc định 30 ngày. Release assets là bản phát hành lâu dài hơn theo chính sách repository. Sau khi workflow hoàn tất, vào **Actions → workflow run → Artifacts** để tải bản kiểm thử, hoặc vào **Releases** để tải Setup của tag.


## Auto-update ứng dụng Windows

`updater.py` hiện tiếp tục cập nhật riêng yt-dlp. Module `app_update.py` bổ sung luồng cập nhật ứng dụng an toàn hơn: mỗi lần khởi động đọc manifest HTTPS và so sánh SemVer; chỉ khi người dùng bấm nút **Cập nhật ngay** app mới tải installer, xác minh SHA-256 và mở Setup. Ứng dụng không tự ghi đè executable đang chạy trong nền. Có thể tắt kiểm tra startup bằng `FRAMEFORGE_APP_UPDATE_STARTUP=0`.

Workflow GitHub Actions tạo asset `latest.json` trong mỗi stable release tag và `latest-beta.json` trong beta prerelease. Manifest chứa channel, version, tag, tên Setup, URL tải, SHA-256, signature status, release notes và metadata rollback. Có thể chọn kênh trong UI hoặc cấu hình:

```bat
set FRAMEFORGE_UPDATE_CHANNEL=stable
set FRAMEFORGE_UPDATE_MANIFEST_URL=https://github.com/GiaHan1907/FrameForge/releases/latest/download/latest.json
```

Với beta channel:

```bat
set FRAMEFORGE_UPDATE_CHANNEL=beta
set FRAMEFORGE_UPDATE_MANIFEST_URL=https://github.com/GiaHan1907/FrameForge/releases/latest/download/latest-beta.json
```

Repository FrameForge hiện đã là public, nên có thể dùng trực tiếp GitHub Release làm feed cập nhật công khai mà không cần Personal Access Token. App có URL manifest public mặc định; vẫn có thể ghi đè bằng `FRAMEFORGE_UPDATE_MANIFEST_URL` nếu chuyển sang feed khác.

Quy trình phát hành khuyến nghị là tạo tag SemVer, chờ GitHub Actions build và tạo Release, sau đó kiểm tra manifest, `SHA256SUMS.txt` và Setup asset. Khi manifest có rollback, UI cho phép tải bản stable trước đó, kiểm tra lại SHA-256 và mở installer rollback. Người dùng có thể tắt updater EXE bằng `FRAMEFORGE_APP_UPDATE=0`, hoặc chỉ tắt kiểm tra lúc khởi động bằng `FRAMEFORGE_APP_UPDATE_STARTUP=0`; updater yt-dlp vẫn được điều khiển riêng bằng `FRAMEFORGE_AUTO_UPDATE=0`.

Để ký installer, thêm Actions secrets `WINDOWS_CERTIFICATE_BASE64` và `WINDOWS_CERTIFICATE_PASSWORD`. Secret đầu tiên là file PFX được mã hóa Base64; không commit PFX hoặc password vào repository. Nếu chưa có certificate, workflow vẫn ghi rõ `signature_status=unsigned`; cần cấu hình certificate tin cậy trước khi phân phối production.


## Chọn thư mục lưu file

Ngay sau khi mở app, phần **Nơi lưu file** cho phép nhập đường dẫn hoặc bấm **Chọn thư mục video** và **Chọn thư mục screenshot**. Video tải từ Facebook/TikTok/Pinterest sẽ được lưu trực tiếp vào thư mục video đã chọn. Mỗi lần chạy xử lý screenshot tạo một thư mục con dạng `FrameForge_YYYYMMDD_HHMMSS` trong thư mục screenshot, kèm các ảnh và `report.json`, nên không trộn với kết quả cũ.

Folder picker dùng native dialog của hệ điều hành và được nhúng vào bản PyInstaller qua `tkinter`. Nếu chạy ở môi trường server/headless không có dialog đồ họa, có thể nhập đường dẫn local trực tiếp vào ô text. Các nút tải ZIP trong giao diện vẫn giữ lại như một lựa chọn phụ, nhưng không còn bắt buộc để lấy video hoặc screenshot.
