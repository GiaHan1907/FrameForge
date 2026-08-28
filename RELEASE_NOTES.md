# FrameForge Windows Release Notes

# FrameForge v0.1.27

## UI/UX: Validation, queue dashboard và resource visibility

Bổ sung validation ngay trong wizard 4 bước. FrameForge kiểm tra nguồn video, thư mục output, khoảng thời gian, số screenshot, kích thước phân tích và FPS trước khi bật nút **Bắt đầu xử lý**. Các cấu hình có rủi ro shortfall hoặc dùng nhiều worker nhưng chưa đặt RAM reserve được hiển thị dưới dạng cảnh báo sớm.

Summary card mới được ghim khi cuộn trang, hiển thị nhanh số video, mode chọn frame, định dạng/crop output và trạng thái cấu hình. Người dùng không cần quay lại đầu trang để kiểm tra các thông số quan trọng trước khi chạy queue.

Khi queue đang chạy, dashboard tổng quan hiển thị tổng video, đang chạy, đang chờ, hoàn tất, lỗi và đã hủy cùng progress tổng. Resource meter hiển thị RAM khả dụng, disk còn trống, RSS của FrameForge và các ngưỡng admission đang áp dụng. Trạng thái `resource_wait` được giải thích rõ là đang chờ tài nguyên, không phải video bị lỗi.

Các lỗi queue hiện có diagnostic action để tải file `frameforge-diagnostic.json` chứa version và lỗi rút gọn. Diagnostic không bao gồm cookie hoặc thông tin đăng nhập, giúp người dùng dễ gửi thông tin hỗ trợ mà không phải sao chép thủ công từ màn hình.

Thêm regression assertions cho các thành phần UI v0.1.27; toàn bộ test suite và compile check tiếp tục được chạy trước khi release.

# FrameForge v0.1.26

## P0: Adaptive target, manifest safety và resource back-pressure

Target count sau filter nay có candidate budget adaptive: bắt đầu theo `target_candidate_multiplier`, tăng khi tỷ lệ reject cao và dừng ở `target_candidate_multiplier_max`. Report phân biệt candidate đã xét, ảnh đã lưu, các nhóm bị loại và shortfall.

Engine bổ sung `verify_video_manifest()` và CLI `--repair-manifest` để phát hiện file output thiếu/thừa sau crash và dựng lại danh sách file bằng atomic JSON write. Resume queue trong Streamlit kiểm tra run signature trước khi cho tiếp tục; nếu cấu hình hiện tại khác queue cũ, nút resume bị khóa để tránh dùng sai cache/checkpoint.

Bounded scheduler kiểm tra RAM/disk trước mỗi item mới và chuyển item sang trạng thái chờ tài nguyên khi dưới ngưỡng, không admit thêm video cho đến khi tài nguyên hồi phục hoặc người dùng cancel. Preview có nút phân tích nhanh scene thật ở độ phân giải thấp, tách biệt với timestamp preview ước tính.

# FrameForge v0.1.25

## Target count, manifest và resource guard

Bổ sung chế độ **Cố gắng đủ số ảnh sau khi lọc** cho scene/every mode. Engine xét thêm candidate trong budget tối đa gấp 3 lần mục tiêu để bù ảnh bị loại bởi sharpness, motion blur hoặc duplicate, đồng thời báo cáo rõ `target_screenshots`, `saved`, `shortfall` và `shortfall_reasons`.

Mỗi video tạo `.frameforge_manifest.json`; screenshot được encode vào file tạm rồi rename atomically trước khi ghi nhận thành công. Resource guard kiểm tra dung lượng output ước tính và RAM khả dụng. Streamlit hiển thị preview phân bố timestamp dự kiến và shortfall diagnostics theo từng video. Thêm regression tests cho target count, manifest, atomic output, resource guard và preview.

# FrameForge v0.1.24

## Chọn số screenshot cho mỗi video

Streamlit bổ sung widget **Số screenshot mỗi video** với giới hạn 1–1000. Best frame per scene và Scene detection dùng giá trị này làm số ảnh tối đa; Mỗi N giây dùng làm giới hạn timestamp; Đúng N frame dùng làm số frame chính xác. CLI hỗ trợ `--max-screenshots N`, trong khi `--count N` tiếp tục giữ semantics cũ.

Scene cache tăng version và đưa giới hạn screenshot vào cache key để thay đổi số lượng không dùng nhầm timestamp của cấu hình trước. Regression test xác nhận fixed mode không tạo vượt giới hạn và UI/CLI có đầy đủ option.

# FrameForge v0.1.23

## SQLite state machine và crash-safe queue resume

`persistent_queue.py` được nâng cấp lên schema v0.1.23 theo migration additive từ schema v0.1.22. Database cũ được giữ nguyên report/status, sau đó backfill `item_id` ổn định, `source_position`, phase/progress/message, heartbeat và thời gian bắt đầu/kết thúc. Migration chạy tự động khi mở store và có schema metadata để nhận biết phiên bản.

Queue item có state transition được kiểm soát cho `queued`, `running`, `retrying`, `completed`, `failed`, `cancelled` và `interrupted`. Khi mở lại queue sau khi process bị dừng bất thường, item đang `running` hoặc `retrying` được đánh dấu `interrupted`; `resume_job()` đưa chúng về `queued` mà không đổi stable item ID. Retry theo `item_id` không bị lệch khi xử lý một subset.

Store bổ sung heartbeat/progress API, phát hiện job stale, retry item/retry failed và đóng connection idempotent. Integration test dùng subprocess thật và `os._exit()` để mô phỏng crash sau khi SQLite đã commit, rồi xác minh reopen/resume, stable IDs, migration legacy và hoàn tất toàn bộ queue.

# FrameForge v0.1.22

## Bounded queue, điều khiển đáng tin cậy và preview hai panel

Engine queue nhiều video nay dùng bounded scheduler: chỉ submit số item tối đa bằng số video worker hiệu dụng, không còn submit toàn bộ future ngay từ đầu. Khi pause được bật, scheduler không cấp thêm item queued; các item đang chạy hoàn tất tại checkpoint an toàn rồi queue chờ resume. Cancel trong lúc pause hoặc retry backoff được kiểm tra định kỳ và không phải chờ hết toàn bộ thời gian backoff.

Retry vẫn được thực hiện theo từng video, giữ thứ tự report, SQLite/checkpoint và exponential backoff. Các test tích hợp mới kiểm tra giới hạn submit, pause/resume, cancel trước queue, cancel khi worker chạy, cancel trong backoff, retry từng video và SQLite resume. Retry item/retry failed trong UI chỉ cho phép khi job không còn chạy và nguồn video còn tồn tại.

Preview Streamlit được bố trí thành hai panel cạnh nhau: **Video gốc** và **Crop overlay** theo ratio đang chọn. Frame overlay chỉ dùng để minh họa vùng giữ lại, file nguồn không bị thay đổi. Queue UX dùng accordion cho từng video, tự mở item đang chạy/lỗi, có bộ lọc riêng cho `Retrying`, summary trạng thái và hiển thị attempts, saved, FPS, ETA, RAM cùng chẩn đoán lỗi.

Downloader vẫn chỉ xử lý URL công khai được phép; không bổ sung cookie, login, DRM bypass hoặc PAT. Packaging và release gates tiếp tục giữ nguyên nguyên tắc phải compile, full test, workflow validator, packaged smoke và checksum public trước khi tag.

# FrameForge v0.1.21

## Tích hợp queue per-video vào Streamlit chính

Module `queue_per_video.py` được tích hợp vào giao diện Streamlit qua `_ProcessingQueueAdapter`, dùng lại engine `process_videos`, SQLite queue, JSON checkpoint, retry exponential backoff và lifecycle cleanup hiện có. Giao diện live hiển thị card cho từng video với trạng thái `queued`, `running`, `retrying`, `paused`, `completed` hoặc `failed`, cùng attempts, số ảnh đã lưu, FPS, ETA, RAM, mã lỗi và gợi ý.

Các nút **Tạm dừng**, **Tiếp tục**, **Hủy xử lý**, **Thử lại mục thất bại** và **Retry item này** đã nối vào job hiện tại. Retry chỉ nhận report lỗi có file nguồn còn tồn tại; cancel giữ checkpoint/work directory theo flow resume hiện có. Pause an toàn ở ranh giới item/retry và không dừng giữa frame. Với nhiều video worker, các video đã submit có thể tiếp tục đến checkpoint gần nhất; chế độ `Video xử lý song song = 1` cho semantics pause tuần tự rõ ràng hơn.

Cả ba PyInstaller spec đều nhúng `queue_per_video.py`; workflow Windows compile và kiểm tra runtime module này trước packaged smoke test. Downloader vẫn chỉ xử lý URL công khai được phép, không bổ sung cookie, login, DRM bypass hoặc PAT.

# FrameForge v0.1.20

## Wizard UI, crop overlay và queue per-video

Giao diện chính bổ sung wizard bốn bước `Nguồn`, `Chọn frame`, `Chất lượng` và `Đầu ra`, cùng summary card cho cấu hình hiện tại trước khi chạy.

Preview video hiển thị crop overlay theo ratio đã chọn. Vùng sáng có viền xanh là phần giữ lại, vùng tối là phần bị crop; overlay dùng frame đầu để minh họa và không thay đổi file nguồn.

Queue xử lý hiển thị trạng thái per-video. Người dùng có thể tạm dừng queue ở ranh giới video, tiếp tục queue, hủy xử lý để giữ checkpoint và thử lại các mục thất bại có file nguồn còn tồn tại. Video đang chạy không bị cắt giữa chừng khi tạm dừng.

# FrameForge v0.1.19

## Tối ưu pipeline ảnh và benchmark theo công đoạn

Pipeline tạo ảnh phân tích nhỏ một lần cho mỗi frame và dùng chung cho grayscale, sharpness, motion blur, dHash và histogram. Các metric không cần thiết được bỏ qua dựa trên cấu hình; job không lọc chất lượng, không duplicate và không scene detection sẽ tránh các phép tính tương ứng.

Bổ sung hai encode profile: `Nhanh` giảm chi phí tối ưu encode cho JPEG/WebP/PNG, còn `Chất lượng cao` giữ tùy chọn tối ưu hiện tại. Profile có trong Streamlit, preset, CLI `--encode-profile` và benchmark.

Benchmark xuất riêng thời gian và số lần thực hiện của `decode`, `analysis`, `encode` và `write` qua các trường `*_ms` và `*_count`. Với multiprocessing, decode được tính tại bước đọc frame tạm trong process cha.

# FrameForge v0.1.18

## Phân loại lỗi downloader và exponential backoff

Downloader yt-dlp phân loại lỗi theo các mã `access_denied`, `rate_limited`, `ffmpeg_missing`, `format_unavailable`, `output_error`, `network_error` và `unknown`. Mỗi lỗi có nhãn tiếng Việt, thông tin retryable và gợi ý xử lý cụ thể.

Lỗi mạng tạm thời và giới hạn tần suất được retry với exponential backoff theo chu kỳ `1s`, `2s`, `4s`... và giới hạn chờ tối đa 60 giây. Lỗi URL cần đăng nhập, không có format, thiếu FFmpeg hoặc không ghi được output sẽ dừng retry sớm vì thử lại không khắc phục được nguyên nhân. Progress hook phát sự kiện `retrying` gồm mã lỗi, lần thử kế tiếp và thời gian chờ.

Queue hỗ trợ `error_hook` per-URL; một URL thất bại không làm mất các video đã tải thành công và cho phép tiếp tục xử lý các URL còn lại. Phạm vi downloader vẫn chỉ là nội dung công khai mà người dùng có quyền sử dụng, không dùng cookie, đăng nhập, bypass DRM hoặc truy cập riêng tư.

# FrameForge v0.1.17

## Crop screenshot theo tỉ lệ

Bổ sung lựa chọn `Không crop`, `16:9`, `9:16`, `4:5` và `1:1` trong nhóm Đầu ra của Streamlit. Crop được thực hiện ở chính giữa khung hình, không kéo giãn nội dung, sau đó mới áp dụng giới hạn chiều rộng đầu ra. Preset `Video dọc / TikTok` tự chọn `9:16`; các preset khác mặc định giữ nguyên toàn bộ khung hình.

CLI cũng hỗ trợ `--crop-ratio` với các giá trị trên. Nếu không truyền tham số, hành vi mặc định vẫn là `Không crop` để bảo toàn tương thích với các job cũ.

# FrameForge v0.1.16

## Sửa lỗi Facebook Reel không nhận diện file output

Downloader hiện dùng thư mục staging riêng cho từng URL và từng lần retry, với tên `.frameforge_download_*`. File chỉ được chuyển sang thư mục video đích sau khi yt-dlp hoàn tất; staging luôn được dọn trong cả nhánh thành công, lỗi và retry. Điều này tránh lỗi giả khi thư mục đích đã có file cùng video hoặc yt-dlp bỏ qua file cũ nên snapshot output không thấy file mới.

Đã kiểm thử trực tiếp với Reel công khai `https://www.facebook.com/reel/1629014048842189`: yt-dlp stable `2026.08.19` nhận diện được format và FrameForge tạo file MP4 timestamp khoảng 17.8 MB. Facebook vẫn có thể từ chối hoặc không cung cấp format cho một số Reel theo trạng thái URL, khu vực, mạng hoặc thay đổi extractor; bản vá không dùng cookie, đăng nhập, DRM bypass hay cơ chế truy cập riêng tư.

# FrameForge v0.1.15

## Preset, telemetry và adaptive extraction theo thời lượng

Bổ sung bốn preset cấu hình trong Streamlit: `Nhanh`, `Cân bằng`, `Chất lượng cao` và `Video dọc / TikTok`. Preset điền đồng bộ các tham số scene, kích thước/FPS phân tích, chất lượng ảnh, output, retry, disk reserve, cache và extraction; người dùng vẫn có thể chỉnh từng trường sau khi chọn preset. Preset `Cân bằng` là lựa chọn mặc định.

Trong lúc xử lý, giao diện hiển thị tốc độ progress theo FPS, ETA và RSS RAM của process FrameForge. FPS/ETA chỉ được tính khi progress message có số đơn vị dạng `frame x/y` hoặc `mốc x/y`; trước thời điểm đó giao diện hiển thị trạng thái chờ. RSS là bộ nhớ của process cha, không đại diện cho tổng RSS của child process multiprocessing.

Adaptive extraction worker trong fixed/count mode nay xét đồng thời thời lượng video và số timestamp, bên cạnh CPU, RAM, số video worker và giới hạn `--extract-workers`. Clip ngắn ít mốc ưu tiên chạy tuần tự để tránh overhead spawn; video dài hoặc job nhiều mốc mới mở thêm process trong ngân sách an toàn. Scene detection vẫn decode tuần tự để bảo toàn phân tích scene/cache. Report giữ các trường worker thực tế để kiểm tra quyết định sau khi hoàn tất.

# FrameForge v0.1.14

## Preview gọn và tên file theo timestamp

Preview video trong giao diện được giới hạn ở khung 16:9 tối đa 560px, tự co theo màn hình nhỏ để không lấn át phần điều khiển. Screenshot mới được đặt tên ngắn theo timestamp dạng `HH-MM-SS.mmm.jpg` hoặc `.webp`. Video tải từ queue được đổi tên dạng `video_YYYYMMDD_HHMMSS.ext`; nếu tải nhiều file cùng thời điểm hoặc tên bị trùng, hậu tố số được thêm tự động. Metadata title, URL và playlist index vẫn được lưu trong kết quả tải.

# FrameForge v0.1.13

## Dọn dẹp và giao diện desktop

Work directory tạm giờ được dọn ngay sau khi từng video hoàn tất và tiếp tục được dọn ở cuối job. Dữ liệu của job bị hủy vẫn được giữ lại để resume checkpoint. Bản desktop bật watchdog theo session; khi browser đóng và không còn session hoạt động, job đang chạy được hủy, executor được đóng, work directory được dọn và Streamlit runtime được dừng. Chạy `streamlit run` thủ công không bật hành vi auto-shutdown này.

Khu vực tải video công khai được chuyển sang layout responsive hai tầng với chiều rộng URL lớn hơn, các control giới hạn playlist/retry đồng đều và nút tải queue cùng baseline. Theme chính được đồng bộ dark mode cho canvas, card, input, select, bảng timeline, cảnh báo và nút thao tác.

# FrameForge v0.1.12

## Sửa lỗi chọn thư mục trong Streamlit

Bản vá sửa lỗi `StreamlitAPIException` xảy ra khi nút chọn thư mục cố gắng ghi trực tiếp vào key của `st.text_input` sau khi widget đã được khởi tạo. Hai nút chọn thư mục hiện dùng callback `on_click`, nên đường dẫn video và screenshot được cập nhật an toàn trong session state và vẫn được lưu vào cấu hình người dùng.

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
