# Hướng dẫn sử dụng FrameForge

## 1. Tổng quan

FrameForge là công cụ cắt screenshot từ video với giao diện Streamlit. Công cụ hỗ trợ xem trước video, tự nhận diện thay đổi cảnh, chọn frame sắc nét nhất trong từng scene, loại frame mờ/trùng và xử lý nhiều video song song.

Pipeline bên trong mỗi video đọc tuần tự một lần. Khi có nhiều video, các video độc lập được phân phối cho nhiều worker để tận dụng CPU mà không làm thay đổi thứ tự báo cáo.

## 2. Build bản Windows EXE

Việc build cần thực hiện trên Windows. Giải nén package vào một thư mục mới, sau đó mở CMD trong thư mục chứa `build_windows.bat`.

Xóa các thư mục build cũ nếu có:

```bat
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
```

Build:

```bat
build_windows.bat
```

File kết quả mặc định:

```text
dist\VideoScreenshotFilter\VideoScreenshotFilter.exe
```

Bản mặc định được cấu hình **onedir** và windowed, nên khi double-click `dist\VideoScreenshotFilter\VideoScreenshotFilter.exe` sẽ không hiện cửa sổ CMD. Launcher tự chờ Streamlit sẵn sàng tại `http://localhost:8501`, sau đó mở trình duyệt. Nếu cần one-file, đặt `BUILD_MODE=onefile`; đây là profile full dự phòng.

## 3. Sử dụng giao diện Web

Double-click `VideoScreenshotFilter.exe`. Nếu trình duyệt không tự mở, truy cập thủ công:

```text
http://127.0.0.1:8501
```

Trong sidebar, chọn một hoặc nhiều video. Khu vực **Xem trước video** sẽ xuất hiện sau khi upload; chọn video trong danh sách để phát trực tiếp trước khi cắt.

### Chế độ chọn frame

| Chế độ | Hành vi |
|---|---|
| Best frame per scene | Phát hiện scene và giữ frame sắc nét nhất trong mỗi scene. Đây là chế độ nên dùng mặc định. |
| Scene detection | Phát hiện scene và giữ frame đầu của mỗi scene. |
| Mỗi N giây | Lấy frame theo khoảng thời gian cố định. |
| Đúng N frame | Phân bố đều đúng số lượng frame trong khoảng thời gian đã chọn. |

Sau khi chọn cấu hình, bấm **Bắt đầu xử lý**. Ứng dụng tạo một job nền và hiển thị progress tổng thể cùng progress riêng cho từng video. Các giai đoạn gồm `queued`, `preparing`, `analyzing`, `selecting`, `saving` và `completed`; bounded scheduler chỉ cấp tối đa số item bằng số worker hiệu dụng. Khi video lỗi, queue sẽ tự retry theo số lần đã chọn trước khi chuyển sang video tiếp theo.

Trong lúc xử lý, khu vực **Queue theo video** hiển thị card riêng cho từng file với trạng thái, phần trăm, message, số lần thử, số ảnh đã lưu, FPS, ETA và RAM. Bấm **Tạm dừng** để đặt pause event; pause chỉ có hiệu lực tại ranh giới video/retry và không cắt video đang chạy giữa một frame. Khi `Video xử lý song song` lớn hơn 1, các video đã được submit cho worker có thể tiếp tục đến checkpoint gần nhất; nếu cần pause tuần tự rõ ràng, đặt giá trị bằng 1. Bấm **Tiếp tục** để mở lại item còn chờ.

Bấm **Hủy xử lý** để dừng an toàn. FrameForge kiểm tra yêu cầu hủy giữa các checkpoint, giải phóng `VideoCapture` và giữ lại các screenshot đã ghi trước đó. Job đang chạy sẽ khóa nút bắt đầu mới để tránh tạo hai queue cùng lúc. Sau khi job kết thúc, **Thử lại mục thất bại** chạy lại toàn bộ report lỗi còn file nguồn; nút **Retry item này** chỉ chạy một item lỗi. Nếu file upload tạm đã bị xóa hoặc di chuyển, cần chọn lại video trước khi retry.

Sau khi từng video hoàn tất, file input tạm của video đó được xóa ngay; khi cả job hoàn tất hoặc gặp lỗi, work directory còn lại cũng được dọn. Nếu bạn bấm **Hủy xử lý**, work directory và checkpoint vẫn được giữ để có thể resume. Khi đóng browser trên bản EXE desktop, FrameForge chờ một khoảng reconnect ngắn, hủy job đang chạy, đóng executor, dọn work directory rồi dừng Streamlit. Chạy `streamlit run` thủ công không tự tắt server khi browser đóng.

Trước khi chạy, ứng dụng kiểm tra dung lượng trống tại thư mục screenshot. Trường **Vùng đệm dung lượng tối thiểu** mặc định là 512 MB; nếu không đủ vùng đệm, job sẽ không bắt đầu. Các work directory tạm của phiên trước có tiền tố `video_screenshot_web_` và cũ hơn 24 giờ sẽ được dọn tự động. Report JSON được ghi trực tiếp trong thư mục run để không bị mất khi thư mục tạm được dọn.

Khu vực **Tải video công khai** dùng layout hai tầng: URL ở vùng rộng phía trên, chất lượng ở cột bên cạnh, còn giới hạn playlist, số lần retry và nút **Tải queue** nằm trên cùng một hàng bên dưới. Toàn bộ giao diện dùng dark mode thống nhất cho nền, card, ô nhập, select, bảng timeline và nút thao tác.

### Preset cấu hình và telemetry

Ở đầu sidebar, chọn **Preset cấu hình** trước khi tinh chỉnh chi tiết. `Nhanh` giảm kích thước/FPS phân tích để xử lý nhanh; `Cân bằng` là mặc định; `Chất lượng cao` ưu tiên phân tích và chất lượng ảnh; `Video dọc / TikTok` dùng các kích thước phù hợp nội dung dọc. Preset chỉ điền giá trị khởi đầu, bạn vẫn có thể sửa bất kỳ trường nào sau đó.

Trong khi xử lý, ba thẻ telemetry hiển thị **FPS**, **ETA** và **RAM process**. FPS là số đơn vị tiến độ đã hoàn thành chia cho thời gian chạy; ETA là thời gian còn lại ước tính tuyến tính khi đã biết tổng số frame/mốc; RAM process là RSS của process FrameForge. Đây không phải tổng RAM máy hoặc tổng RSS của các process con. Khi engine chưa gửi được `frame x/y` hoặc `mốc x/y`, FPS/ETA có thể hiển thị trạng thái chờ thay vì một con số thiếu tin cậy.

## 4. Tinh chỉnh scene detection

`Độ nhạy thay đổi cảnh` thấp hơn sẽ nhạy hơn và thường tạo nhiều scene hơn. `Khoảng cách tối thiểu giữa scene` giúp tránh tạo quá nhiều scene trong các đoạn chuyển tiếp nhanh. Cơ chế chống flash kiểm tra xem frame sau thay đổi có quay lại cảnh cũ hay không.

Giá trị khởi đầu khuyến nghị:

```text
Scene threshold: 0.30
Minimum scene gap: 0.5 giây
Flash return ratio: 0.55
Flash brightness threshold: 0.18
```

Nếu video có nhiều hiệu ứng sáng hoặc flash, tăng độ ổn định bằng cách tăng `minimum scene gap` hoặc giảm độ nhạy scene. Nếu video có chuyển cảnh rất nhanh, giảm minimum gap và tăng FPS phân tích.

## 5. Tốc độ và đa luồng

`Chiều rộng phân tích` là kích thước dùng để phân tích scene, độ nét và dHash; ảnh lưu ra vẫn có thể dùng chiều rộng đầu ra riêng. Giá trị 640 px phù hợp cho phần lớn video. Dùng 320 px khi ưu tiên tốc độ, hoặc 960–1280 px khi cần phân tích cảnh có chi tiết nhỏ.

`FPS phân tích scene` quyết định số frame/giây được kiểm tra. Dùng 8 FPS cho video thông thường và 15–24 FPS cho video có chuyển cảnh nhanh.

`Video xử lý song song` chỉ áp dụng giữa các video độc lập. Một worker phù hợp khi xử lý một video hoặc máy có ít RAM. Hai đến ba worker là điểm bắt đầu an toàn khi xử lý nhiều video. Video 4K hoặc nhiều video dài có thể cần giảm worker để tránh đầy RAM.

## 6. Lọc chất lượng

Ngưỡng độ nét đã được chuẩn hóa về chiều rộng tham chiếu 640 px. Đặt `Ngưỡng độ nét tối thiểu` bằng 0 để tắt lọc mờ. Giá trị 100 là điểm bắt đầu hợp lý; tăng giá trị nếu muốn giữ ít frame nhưng sắc nét hơn.

`Ngưỡng trùng dHash` càng lớn thì bộ lọc càng mạnh và loại nhiều frame tương tự hơn. Giá trị 6 phù hợp cho phần lớn nội dung. Đặt bằng 0 để tắt lọc trùng.

## 7. CLI nâng cao

Có thể chạy trực tiếp không cần giao diện:

```bash
python video_screenshot_advanced.py ./videos \
  --workers 3 \
  --best-frame-per-scene \
  --scene-threshold 0.30 \
  --min-scene-gap 0.5 \
  --analysis-width 640 \
  --analysis-fps 8 \
  --min-sharpness 100 \
  --duplicate-threshold 6 \
  --format jpg \
  --quality 95 \
  --output ./screenshots_filtered \
  --report ./screenshots_filtered/report.json \
  --retries 2 \
  --retry-delay 1 \
  --disk-reserve-mb 512 \
  --temp-cleanup-hours 24 \
  --extract-workers 0 \
  --cache-dir ./frameforge_cache \
  --duplicate-index-dir ./frameforge_duplicate_index
```

Các tùy chọn chính:

| Tùy chọn | Ý nghĩa |
|---|---|
| `--workers N` | Số video xử lý song song. |
| `--best-frame-per-scene` | Chọn frame sắc nét nhất trong từng scene. |
| `--scene-detection` | Chọn frame đầu của từng scene. |
| `--every N` | Lấy frame sau mỗi N giây. |
| `--count N` | Lấy đúng N frame phân bố đều. |
| `--analysis-width N` | Chiều rộng phân tích nhanh. |
| `--analysis-fps N` | FPS dùng để phân tích scene. |
| `--min-sharpness N` | Ngưỡng loại frame mờ. |
| `--duplicate-threshold N` | Ngưỡng khoảng cách dHash để loại frame trùng. |
| `--report FILE` | Ghi báo cáo JSON. |
| `--retries N` | Retry từng video tối đa N lần nếu gặp lỗi tạm thời. |
| `--retry-delay N` | Số giây chờ giữa các lần retry. |
| `--disk-reserve-mb N` | Vùng đệm dung lượng trống tối thiểu trước khi xử lý. |
| `--temp-cleanup-hours N` | Dọn work directory tạm cũ hơn N giờ khi khởi động CLI. |
| `--temp-quota-mb N` | Giới hạn tổng work directory tạm cũ; mặc định 2048 MB, `0` để tắt quota. |
| `--cache-quota-mb N` | Giới hạn scene cache cũ; mặc định 1024 MB, `0` để tắt quota. |
| `--extract-workers N` | Số process trích frame cho fixed/count mode; `0` tự chọn tối đa 4, `1` chạy tuần tự. Adaptive worker còn xét thời lượng và số timestamp: clip ngắn/ít mốc thường giữ 1 process, job dài/nhiều mốc mới mở thêm process trong giới hạn CPU/RAM và số video worker. |
| `--resume` | Tiếp tục queue từ checkpoint của output run hiện tại. |
| `--checkpoint FILE` | Đường dẫn checkpoint JSON tùy chỉnh. |
| `--cache-dir DIR` | Cache timestamp scene để dùng lại giữa các lần chạy. |
| `--no-scene-cache` | Tắt việc đọc/ghi scene cache. |
| `--duplicate-index-dir DIR` | Nơi lưu dHash index dùng phát hiện duplicate giữa các lần chạy. |
| `--no-cross-run-duplicates` | Tắt lọc duplicate với các lần chạy trước. |

## 8. Cache, checkpoint và duplicate giữa các lần chạy

Khi chạy scene detection, FrameForge lưu cache JSON theo **đường dẫn, kích thước, thời gian sửa đổi và cấu hình phân tích** của video. Nếu video hoặc các tham số scene thay đổi, cache cũ sẽ tự bị bỏ qua. Cache chỉ lưu timestamp đã chọn và scene marker, không lưu toàn bộ frame nên có kích thước nhỏ.

Để tiếp tục một queue bị hủy, giữ nguyên thư mục output run và chạy lại với `--resume` cùng `--checkpoint` cũ:

```bash
python video_screenshot_advanced.py ./videos \
  --best-frame-per-scene \
  --output ./screenshots_filtered \
  --checkpoint ./screenshots_filtered/.frameforge_checkpoint.json \
  --resume
```

Checkpoint được ghi atomically sau mỗi video hoàn tất. Khi resume, FrameForge chỉ bỏ qua video đã hoàn tất với cùng processing signature; nếu thay đổi cấu hình xử lý, checkpoint sẽ được coi là không tương thích và queue sẽ chạy lại an toàn.

Report sau khi hoàn tất có thêm `video_workers`, `configured_extract_workers` và `adaptive_extract_workers`, giúp kiểm tra số worker thực tế thay vì chỉ nhìn cấu hình ban đầu. Khi hủy queue single-worker, toàn bộ item còn lại được ghi trạng thái `cancelled` vào SQLite và kết nối database được đóng sạch.

Từ v0.1.7, queue còn được lưu bền vững trong SQLite tại `<output>/.frameforge_queue.sqlite3`. Database ghi trạng thái từng video (`queued`, `running`, `retrying`, `completed`, `failed`, `cancelled`), số lần thử, lỗi cuối cùng và report JSON. JSON checkpoint vẫn được giữ để tương thích ngược và làm file resume dễ kiểm tra. CLI có thể đổi vị trí bằng `--queue-db FILE`; Streamlit tự dùng database trong thư mục output. Khi ứng dụng bị đóng sau khi một video hoàn tất, lần resume sau sẽ đọc cả SQLite và checkpoint để bỏ qua video đó.

DHash index trong `--duplicate-index-dir` giúp loại frame gần giống đã lưu ở những lần chạy trước. Từ v0.1.10, index ghi thêm bucket theo từng byte dHash để giảm số phép so sánh khi threshold không vượt quá 6. Index cũ v1 chỉ có trường `hashes` vẫn được đọc và tự nâng cấp khi ghi lại; vì vậy người dùng không cần xóa index cũ. Đặt `--duplicate-threshold 0` hoặc dùng `--no-cross-run-duplicates` nếu muốn mỗi lần chạy luôn tạo output độc lập.

CLI xóa work directory tạm cũ nhất khi vượt `--temp-quota-mb`, sau khi đã áp dụng `--temp-cleanup-hours`. Scene cache chỉ xóa file JSON cũ hơn 7 ngày khi vượt `--cache-quota-mb`; cache đang mới sẽ được giữ lại để tránh làm mất lợi ích resume nhanh.

## 9. Timeline tương tác

Sau khi queue hoàn tất, Web UI hiển thị scene markers và bảng timestamp. Khu vực **Timeline tương tác** cho phép chọn một video/scene, điều chỉnh mốc preview bằng slider và xem frame gần nhất trong thư mục output. Screenshot mới có tên dạng `HH-MM-SS.mmm.jpg` hoặc `.webp`; tên cũ có tiền tố video vẫn được tìm thấy nhờ pattern tương thích. Với video chỉ có một scene, frame đại diện vẫn được hiển thị như một marker.

## 10. Kết quả và báo cáo

Ảnh được lưu trong thư mục output theo từng video. Báo cáo JSON gồm số frame yêu cầu, số frame đã lưu, số frame bị loại vì mờ/trùng, lỗi đọc frame, metadata video và danh sách timestamp của scene.

Trong Web UI, nút tải ZIP chứa toàn bộ ảnh và `report.json`. Có thể tải report JSON riêng để xử lý tiếp bằng chương trình khác.

## 11. Khắc phục sự cố

Nếu chạy EXE mà không thấy giao diện, trước hết kiểm tra:

```text
http://127.0.0.1:8501
```

Nếu vẫn không được, xem log tại:

```text
%LOCALAPPDATA%\VideoScreenshotFilter\launcher_error.log
```

Nếu cổng 8501 đang bị một phiên bản cũ chiếm dụng, đóng các tiến trình cũ rồi chạy lại:

```bat
taskkill /IM VideoScreenshotFilter.exe /F
```

Nếu browser không phát được preview, hãy đổi video sang MP4/H.264. Đây là giới hạn codec của trình duyệt, không phải lỗi cắt screenshot.

Từ v0.1.16, mỗi URL và mỗi lần retry tải video vào staging riêng `.frameforge_download_*`, rồi mới chuyển file hoàn tất sang thư mục lưu video. Cách này tránh việc file cũ cùng video khiến yt-dlp bỏ qua download và FrameForge báo nhầm `yt-dlp không tạo được file video đầu ra`. Staging được dọn tự động sau cả thành công và lỗi.

## v0.1.23 — SQLite state machine và resume sau crash

Khi mở queue database được tạo từ v0.1.22, FrameForge tự chạy migration additive lên schema v0.1.23. Report, checkpoint và trạng thái cũ được giữ lại; hệ thống bổ sung `item_id` ổn định, `source_position`, phase/progress, heartbeat và timestamps. Không cần xóa file SQLite hoặc tạo database mới.

Nếu ứng dụng bị đóng hoặc crash, item đang `running` hoặc `retrying` sẽ được đánh dấu `interrupted` khi queue được mở lại. Chọn **Resume** để đưa các item này về `queued`; stable item ID không thay đổi và video đã hoàn tất không bị chạy lại. Nếu muốn chạy lại một item lỗi, dùng stable item ID nội bộ của queue; không dựa vào số thứ tự sau khi lọc subset.

Integration test của bản này mô phỏng process chết đột ngột sau khi SQLite đã commit, mở lại database trong process mới, xác minh hai item active chuyển thành `interrupted`, item thứ ba vẫn `queued`, rồi resume và hoàn tất toàn bộ queue.

## v0.1.22 — Bounded queue, preview hai panel và UX gọn hơn

Khi xử lý nhiều video, FrameForge dùng bounded scheduler: số video được submit đồng thời không vượt quá số `Video xử lý song song` hiệu dụng. Các video còn lại thực sự ở trạng thái chờ, giúp giảm áp lực RAM và tránh tạo quá nhiều future trong một queue lớn.

Khi bấm **Tạm dừng**, scheduler không cấp thêm item queued. Video đang chạy có thể hoàn tất đến checkpoint an toàn; cancel được kiểm tra cả trong lúc queue pause và retry backoff. Bấm **Tiếp tục** để cấp các item còn lại. Với một worker, semantics pause tuần tự rõ ràng nhất; với nhiều worker, các video đã submit vẫn có thể tiếp tục đến checkpoint gần nhất.

Preview hiện có hai panel cạnh nhau: **Video gốc** và **Crop overlay**. Panel crop hiển thị vùng giữ lại theo ratio đã chọn, còn file nguồn chỉ được đọc và không bị sửa. Nếu codec không tạo được frame preview, engine vẫn có thể xử lý video nếu FFmpeg/OpenCV đọc được file.

Queue per-video dùng accordion để giảm chiều dài trang. Item đang chạy, retrying, paused hoặc failed tự mở; bộ lọc có thêm trạng thái `Retrying`; item lỗi hiển thị mã lỗi, gợi ý và nút retry riêng. Retry chỉ có thể thực hiện sau khi job dừng và file nguồn còn tồn tại.

## v0.1.21 — Tích hợp queue per-video

Module `queue_per_video.py` nay được tích hợp vào Streamlit chính qua `_ProcessingQueueAdapter`, nên giao diện queue dùng chung với engine `process_videos` ổn định, SQLite queue và JSON checkpoint hiện có. Module không tự thay thế engine hoặc tạo một lifecycle lưu trữ thứ hai trong Streamlit.

Card per-video có bộ lọc trạng thái, chẩn đoán mã lỗi/gợi ý, attempts, số ảnh đã lưu và telemetry FPS/ETA/RAM. Các thao tác pause, resume, cancel, retry failed và retry item đều có điều kiện an toàn: queue đang chạy không cho retry; retry subset chỉ nhận nguồn còn tồn tại; cancel vẫn giữ checkpoint/work directory để resume theo flow hiện có. Ba PyInstaller spec và bước kiểm tra runtime của Windows CI đều đóng gói/kiểm tra `queue_per_video.py`.

Pause được thiết kế tại ranh giới item. Ở chế độ một video worker, video hiện tại hoàn tất rồi item kế tiếp mới chờ. Ở chế độ nhiều video worker, những video đã submit có thể tiếp tục; đây là giới hạn chủ động để không thay đổi engine đa luồng hiện tại hoặc dừng giữa frame.

## v0.1.20 — Wizard và điều khiển queue

Giao diện chính có wizard bốn bước: `01 · Nguồn`, `02 · Chọn frame`, `03 · Chất lượng` và `04 · Đầu ra`. Summary card bên dưới hiển thị số video, mode, analysis width/FPS, crop ratio, format và encode profile hiện tại trước khi chạy.

Khi đã chọn video, preview hiển thị crop overlay. Vùng sáng có viền xanh là phần sẽ được giữ lại; vùng tối là phần bị crop. Overlay chỉ minh họa frame đầu, còn engine áp dụng ratio đã chọn cho mọi frame được lưu.

Trong lúc xử lý, phần `Queue theo video` hiển thị trạng thái, phần trăm, message, attempts, số ảnh đã lưu, FPS, ETA và RAM cho từng video. **Tạm dừng queue** chỉ có hiệu lực ở ranh giới video/retry và không dừng giữa frame; ở nhiều worker, video đã submit có thể tiếp tục. **Tiếp tục queue** mở lại các video còn chờ. **Hủy xử lý** giữ checkpoint để resume. Sau khi queue kết thúc, retry chỉ chạy các file nguồn còn tồn tại; file upload đã bị xóa hoặc di chuyển cần được chọn lại.

## 12. Profile encode và benchmark hiệu suất ảnh

Trong nhóm **Đầu ra**, trường `Profile encode` có hai lựa chọn. `Nhanh` giảm các bước tối ưu tốn CPU khi ghi JPEG/WebP/PNG, phù hợp khi cần tạo nhiều screenshot hoặc preview nhanh. `Chất lượng cao` dùng các tùy chọn tối ưu hiện tại, phù hợp khi ưu tiên chất lượng và kích thước file. Profile không thay đổi kích thước hoặc tỷ lệ ảnh; nó chỉ thay đổi cách encode file.

CLI hỗ trợ:

```bash
python video_screenshot_advanced.py input.mp4 --count 20 --encode-profile Nhanh
python video_screenshot_advanced.py input.mp4 --count 20 --encode-profile "Chất lượng cao"
```

Benchmark hỗ trợ cùng lựa chọn và xuất các cột `decode_ms`, `analysis_ms`, `encode_ms`, `write_ms` cùng `decode_count`, `analysis_count`, `encode_count`, `write_count`:

```bash
python benchmarks/benchmark_frame_extraction.py --frames 120 --workers 1,2,4 --encode-profile Nhanh --output benchmark_fast.json
python benchmarks/benchmark_frame_extraction.py --frames 120 --workers 1,2,4 --encode-profile "Chất lượng cao" --output benchmark_high.json
```

`decode_ms` là thời gian đọc frame, `analysis_ms` là metric và quyết định frame, `encode_ms` là thời gian mã hóa JPEG/WebP/PNG, còn `write_ms` là thời gian ghi file. Với multiprocessing, decode được đo ở bước đọc frame tạm trong process cha; nên so sánh thêm cột `extraction_mode`, FPS và RSS thay vì chỉ nhìn một counter.

## 13. Chẩn đoán lỗi tải video và retry

Từ v0.1.18, FrameForge phân loại lỗi tải theo mã để dễ xử lý. `network_error` là lỗi mạng tạm thời và `rate_limited` là nguồn đang giới hạn tần suất; hai nhóm này có thể được retry tự động. `access_denied` là URL cần đăng nhập hoặc không truy cập được, `format_unavailable` là không có format phù hợp, `ffmpeg_missing` là thiếu FFmpeg để ghép video/audio, còn `output_error` là lỗi quyền ghi hoặc dung lượng. Các lỗi không thể tự khắc phục sẽ dừng retry sớm và hiển thị gợi ý.

Retry dùng exponential backoff: với thời gian cơ sở 1 giây, các lần chờ lần lượt là `1s`, `2s`, `4s`, `8s` và tối đa `60s`. Nếu một URL lỗi, queue vẫn tiếp tục các URL còn lại; các video tải thành công trước đó vẫn được giữ trong thư mục đích. Progress bar hiển thị mã lỗi, lần thử tiếp theo và thời gian chờ khi đang backoff.

Khi gặp lỗi, hãy ưu tiên đọc mã trong ngoặc vuông và làm theo gợi ý. Không nên tăng số retry quá cao cho lỗi `access_denied`, `format_unavailable`, `ffmpeg_missing` hoặc `output_error`, vì retry không làm thay đổi nguyên nhân. FrameForge chỉ hỗ trợ URL công khai mà người dùng có quyền sử dụng, không dùng cookie, đăng nhập, bypass DRM hoặc truy cập nội dung riêng tư.

## 13. Chọn tỉ lệ crop screenshot

Trong nhóm **Đầu ra**, trường `Tỉ lệ crop screenshot` có năm lựa chọn: `Không crop`, `16:9`, `9:16`, `4:5` và `1:1`. FrameForge crop chính giữa khung hình, không kéo giãn nội dung, rồi mới áp dụng `Chiều rộng đầu ra`. Vì vậy ảnh không bị méo; phần thừa ở hai bên hoặc phía trên/dưới sẽ được cắt đối xứng.

| Tỉ lệ | Phù hợp với |
|---|---|
| `16:9` | Video ngang, thumbnail và màn hình rộng |
| `9:16` | Video dọc, TikTok, Reels và Shorts |
| `4:5` | Bài đăng feed dọc |
| `1:1` | Ảnh vuông, avatar và thumbnail vuông |
| `Không crop` | Giữ toàn bộ khung hình gốc |

Preset **Video dọc / TikTok** tự chọn `9:16`. Các preset còn lại giữ `Không crop` để không tự động cắt nội dung; bạn có thể chọn tỉ lệ khác sau khi áp dụng preset.

Nếu một Reel vẫn thất bại, hãy kiểm tra URL còn mở công khai trong trình duyệt cùng mạng, thử preset chất lượng `Tốt nhất` và cập nhật FrameForge/yt-dlp. Một số Reel có thể không cung cấp format cho yt-dlp do URL đã bị gỡ, giới hạn khu vực/mạng hoặc thay đổi từ Facebook. FrameForge không hỗ trợ cookie, đăng nhập, bypass DRM hoặc nội dung riêng tư.

## 13. Chọn số worker theo phần cứng

Worker chỉ song song giữa các video độc lập. Số worker không nên vượt quá số video cần xử lý, số lõi CPU hiệu dụng hoặc mức RAM có thể dành cho ứng dụng.

| Cấu hình tham khảo | Video HD/Full HD | Video 4K hoặc file dài |
|---|---:|---:|
| 2 nhân CPU, RAM 8 GB | 1 | 1 |
| 4 nhân CPU, RAM 8–16 GB | 2 | 1–2 |
| 6–8 nhân CPU, RAM 16–32 GB | 3 | 2–3 |
| Trên 8 nhân CPU, RAM từ 32 GB | 4 | 3–4 |

Chế độ `Auto` dùng quy tắc thận trọng dựa trên CPU, RAM và số lượng video. Đây là điểm bắt đầu an toàn, không phải con số tối đa tuyệt đối. Nếu máy bị đầy RAM, quạt chạy liên tục hoặc tốc độ giảm, giảm worker. Nếu CPU còn rảnh, RAM ổn định và có nhiều video chờ, tăng từng bước một rồi đo lại.

Trong thực tế, worker thường có lợi nhất khi có ít nhất hai video. Với một video duy nhất, pipeline vẫn đọc video một lần và chế độ đa luồng không thể chia nhỏ việc đọc cùng video thành nhiều worker độc lập. Với chế độ `Mỗi N giây` hoặc `Đúng N frame` có ít nhất 8 timestamp, `--extract-workers` có thể mở nhiều process để seek/extract theo chunk; process chính vẫn giữ thứ tự timestamp, áp dụng lọc dHash và là nơi duy nhất ghi screenshot. Scene mode tiếp tục decode tuần tự để giữ scene cache và checkpoint nhất quán.

## 13. Adaptive worker và benchmark

FrameForge v0.1.15 có adaptive worker cho hai lớp xử lý. `--workers` điều khiển số video chạy song song, còn `--extract-workers` điều khiển số process seek/trích frame trong fixed/count mode. Khi đặt `--extract-workers 0`, ứng dụng tự chọn tối đa 4 process theo CPU/RAM; quyết định cuối còn xét thời lượng video và số timestamp. Quy tắc thận trọng hiện giữ 1 process cho clip dưới 30 giây với dưới 96 mốc, dưới 90 giây với dưới 160 mốc, và dưới 180 giây với dưới 240 mốc; các job lớn hơn có thể được cấp thêm process theo ngân sách. Khi nhiều video chạy đồng thời, ngân sách extraction trên từng video được hạ xuống để tránh oversubscription. Có thể xem kết quả trong `report.json` qua các trường `extraction_mode`, `extraction_workers`, `video_workers`, `configured_extract_workers` và `adaptive_extract_workers`.

Benchmark CI nằm tại `benchmarks/benchmark_frame_extraction.py`. Script tạo video synthetic nếu không truyền `--video`, chạy các mức worker, đo thời gian, throughput và RSS memory, sau đó ghi JSON/CSV:

```bash
python benchmarks/benchmark_frame_extraction.py \
  --frames 60 \
  --workers 1,2,4 \
  --output benchmark_results.json
```

GitHub Actions chạy benchmark riêng trên pull request với 24 frame và trên Windows release với 60 frame; kết quả được lưu thành artifact, không được dùng làm ngưỡng cứng vì hiệu năng phụ thuộc codec, CPU, ổ đĩa và runner. Với clip tổng hợp ngắn, việc Auto chọn tuần tự là chủ ý vì chi phí khởi tạo process có thể lớn hơn lợi ích multiprocessing.

## 14. Chạy benchmark cũ

Dùng thư mục có ít nhất hai video để so sánh công bằng:

```bash
python video_screenshot_benchmark.py ./videos \
  --multi-workers 3 \
  --every 1 \
  --analysis-width 640 \
  --analysis-fps 8 \
  --repetitions 2 \
  --output ./benchmark_results
```

Nếu bỏ `--multi-workers`, script tự đề xuất số worker theo CPU/RAM:

```bash
python video_screenshot_benchmark.py ./videos --repetitions 3
```

Kết quả gồm:

```text
benchmark_results/benchmark_results.json
benchmark_results/benchmark_results.csv
```

Các chỉ số quan trọng là `single_seconds_avg`, `multi_seconds_avg`, `speedup` và `parallel_efficiency`. Speedup lớn hơn 1 nghĩa là chế độ đa luồng nhanh hơn trong bài test đó. Không nên so sánh benchmark giữa các máy khác nhau; hãy chạy trên chính máy và bộ video thực tế dự kiến sử dụng.

Để kết quả đáng tin cậy, đóng các ứng dụng nặng, dùng cùng `analysis-width`, `analysis-fps`, bộ lọc và số lần lặp. Lần chạy đầu có thể bị ảnh hưởng bởi cache codec và khởi tạo thư viện, vì vậy nên dùng `--repetitions 3` hoặc cao hơn.

## 14. Scene detection thông minh

Scene detection mới kết hợp sai khác pixel với histogram màu, thay vì chỉ dựa trên một phép đo. Một thay đổi chỉ được xem là scene thật khi khác biệt vượt ngưỡng, frame đủ sắc nét, khoảng cách với scene trước đạt minimum gap và thay đổi được xác nhận qua nhiều frame liên tiếp.

`Số frame xác nhận thay đổi cảnh` mặc định là 2. Tăng lên 3–4 nếu video có rung, flash hoặc hiệu ứng chuyển tiếp nhiều. Giảm xuống 1 nếu cần phản ứng nhanh với hard cut rất ngắn.

Frame ứng viên quá mờ không được dùng để kích hoạt scene mới. Sau khi scene được xác nhận, chế độ **Best frame per scene** vẫn giữ frame sắc nét nhất của scene, đồng thời dHash tiếp tục loại frame gần như trùng trước khi lưu.

Các ngưỡng nên điều chỉnh theo nội dung:

| Nội dung | Scene threshold | Confirmations | Minimum gap |
|---|---:|---:|---:|
| Slide/bài giảng | 0.20–0.30 | 2–3 | 0.5–1.0 giây |
| Video nói chuyện | 0.25–0.40 | 2 | 0.5 giây |
| Video hành động | 0.35–0.55 | 1–2 | 0.2–0.5 giây |
| Video nhiều flash/hiệu ứng | 0.35–0.60 | 3–4 | 0.8–1.5 giây |

## 15. Lọc motion blur

Bộ lọc motion blur phân tích frame thu nhỏ bằng hai tín hiệu: mức tập trung gradient theo một hướng và lượng chi tiết cao tần đo bằng Laplacian so với gradient. Điểm nằm trong khoảng 0–1; điểm càng cao càng có nguy cơ nhòe chuyển động.

Ngưỡng mặc định là `0.30`. Đặt ngưỡng thấp hơn để lọc mạnh hơn, hoặc đặt `0` để tắt. Với video có nhiều đường thẳng, chữ nhỏ hoặc cảnh tự nhiên có cạnh định hướng, nên tăng ngưỡng lên `0.40–0.55` để tránh loại nhầm. Với video hành động có nhiều pan nhanh, bắt đầu từ `0.25–0.35` và kiểm tra preview trước khi dùng hàng loạt.

CLI:

```bash
python video_screenshot_advanced.py video.mp4 \
  --best-frame-per-scene \
  --motion-blur-threshold 0.30 \
  --min-sharpness 100 \
  --duplicate-threshold 6 \
  --output screenshots_filtered
```

Báo cáo có trường `rejected_motion_blur` để biết bao nhiêu frame bị loại riêng vì motion blur. Detector là heuristic nhanh, không phải bộ ước lượng chuyển động tuyệt đối; nên benchmark và xem preview trên loại video thực tế trước khi chọn threshold cố định.

## 16. Tải queue nhiều video và playlist

Trong khu vực **Tải video công khai**, nhập mỗi URL trên một dòng. Có thể trộn URL video đơn và URL playlist trong cùng một queue. Trường **Tối đa mỗi playlist** giới hạn số mục lấy từ từng playlist; tổng số URL trong một lần gọi được giới hạn ở mức an toàn 100 URL. Preview video ở phần dưới dùng khung 16:9 tối đa 560px, tự co trên màn hình hẹp.

Ứng dụng xử lý queue tuần tự, hiển thị progress tải theo file và tự retry từng URL theo trường **Retry tải**. Video tải thành công được đổi tên gọn theo timestamp dạng `video_YYYYMMDD_HHMMSS.ext`; nếu trùng thời điểm, hậu tố số được thêm tự động. Title, URL và playlist index vẫn nằm trong metadata kết quả. Nếu một URL vẫn gặp lỗi sau các lần thử, thông báo sẽ ghi rõ URL và số lần đã thử; các video tải thành công trước đó vẫn được giữ lại để preview hoặc tải ZIP.

Ví dụ queue:

```text
https://www.tiktok.com/...
https://www.facebook.com/...
https://pin.it/...
```

URL phải là URL công khai thuộc Facebook, TikTok hoặc Pinterest. Ứng dụng không hỗ trợ URL riêng tư, nội dung yêu cầu đăng nhập, DRM hoặc kỹ thuật vượt cơ chế bảo vệ.

## 17. Health check FFmpeg

Khi chạy source, ứng dụng kiểm tra `ffmpeg` trong `PATH`. Khi chạy bản Windows được build bằng `build_windows.bat`, ứng dụng ưu tiên `vendor\ffmpeg\ffmpeg.exe` và `ffprobe.exe` đã nhúng; người dùng cuối không phải cài FFmpeg riêng. Nếu cả embedded và PATH đều thiếu, giao diện hiện cảnh báo. Điều này không nhất thiết ngăn tải format đã ghép sẵn, nhưng có thể khiến yt-dlp không ghép được video-only và audio-only thành một file chất lượng cao.

Trên Windows, mở CMD và chạy:

```bat
ffmpeg -version
where ffmpeg
```

Nếu chạy source và không tìm thấy, cài FFmpeg rồi thêm thư mục chứa `ffmpeg.exe` vào biến môi trường `PATH`. Bản EXE onedir/installer đã có FFmpeg nhúng nên không cần bước này. Sau đó đóng và mở lại ứng dụng để health check nhận cấu hình mới.

## 18. Hidden imports của PyInstaller

File `video_screenshot_filter.spec` thu thập `yt_dlp` bằng cả `collect_all` và `collect_submodules`. Khi build EXE trên Windows, cấu hình này giúp nhúng các extractor động. Nếu yt-dlp được nâng cấp, hãy xóa thư mục `build` và `dist`, sau đó chạy lại `build_windows.bat` để tránh dùng cache cũ.

## 19. Auto-updater yt-dlp

Khi mở ứng dụng, FrameForge kiểm tra phiên bản yt-dlp tối đa một lần trong 24 giờ. Nếu có phiên bản mới, updater tải wheel chính thức từ PyPI qua HTTPS, kiểm tra SHA-256 theo metadata PyPI và kiểm tra package có cấu trúc hợp lệ. Bản mới được lưu trong thư mục dữ liệu người dùng và chỉ được kích hoạt khi mở ứng dụng lần kế tiếp.

Updater không thay thế file EXE đang chạy. Cách này tránh khóa file trên Windows và cho phép giữ bản yt-dlp nhúng làm fallback. Nếu tải lỗi, timeout hoặc checksum không khớp, ứng dụng vẫn dùng bản hiện tại.

Để tắt updater:

```bat
set FRAMEFORGE_AUTO_UPDATE=0
VideoScreenshotFilter.exe
```

Log cập nhật:

```text
%LOCALAPPDATA%\VideoScreenshotFilter\yt_dlp_update.log
```

Để quay lại bản yt-dlp nhúng, xóa thư mục `%LOCALAPPDATA%\VideoScreenshotFilter\yt_dlp_updates` rồi mở lại ứng dụng.

> Auto-updater chỉ cập nhật package yt-dlp. Không nên cho updater tự tải và thực thi một EXE mới nếu chưa có manifest tin cậy, checksum/chữ ký số và cơ chế rollback.

## 20. Đo kích thước EXE và giảm dung lượng

Sau khi chạy `build_windows.bat`, file `build_size_report.json` được tạo tự động. Có thể chạy lại thủ công:

```bat
python measure_package_size.py . --json build_size_report.json
```

Hãy chú ý các dòng `vendor_ffmpeg` và `pyinstaller_dist`. FFmpeg static thường là thành phần lớn nhất; các package native như OpenCV và NumPy cũng đóng góp đáng kể. Profile minimal đã loại Pandas và các gói biểu đồ không dùng khỏi bundle.

| Phương án | Mức giảm dự kiến | Đánh đổi |
|---|---:|---|
| Giữ static FFmpeg nhưng chọn build tối giản đúng license | Trung bình | Có thể mất codec/tính năng không cần thiết. |
| Loại hidden import không dùng sau khi test đầy đủ | Nhỏ đến trung bình | Có nguy cơ lỗi extractor hoặc format động. |
| Dùng `onedir` thay `onefile` | Không nhất thiết giảm tổng dung lượng, nhưng giảm thời gian khởi động | Phân phối cả thư mục thay vì một file. |
| Tải FFmpeg ở lần chạy đầu | EXE nhỏ hơn nhiều | Cần mạng, checksum và trải nghiệm cài lần đầu. |
| Tách downloader thành module tùy chọn | Giảm bản cài cơ bản | Không còn mọi tính năng trong một EXE duy nhất. |

Không nên dùng UPX lên FFmpeg hoặc xóa DLL/codec tùy tiện. Mỗi thay đổi phải được kiểm tra lại bằng health check, `ffprobe`, tải format cần dùng và pipeline screenshot.


## 21. Profile minimal

Profile minimal giữ các chức năng cốt lõi gồm giao diện Streamlit, preview, downloader công khai bằng yt-dlp, scene detection, motion blur, dHash, Best frame per scene và xử lý nhiều video. Timeline dùng HTML/CSS thuần thay vì `st.table`, còn spec loại Pandas, PyArrow, PyDeck, Altair, Matplotlib, Plotly, Boto3 và Botocore khỏi bundle khi các thành phần này không được ứng dụng sử dụng.

Build trên Windows:

```bat
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
set BUILD_PROFILE=minimal
set BUILD_MODE=onedir
build_windows.bat
```

Profile full dùng cho trường hợp cần mức tương thích Streamlit rộng hơn:

```bat
set BUILD_PROFILE=full
set BUILD_MODE=onedir
build_windows.bat
```

Số đo Linux tham khảo trước FFmpeg Windows là **622.06 MiB** cho full profile và **324.10 MiB** cho minimal profile. Cặp `ffmpeg.exe`/`ffprobe.exe` static đã chọn khoảng **218.01 MiB**, vì vậy không thể cam kết installed size dưới 200 MB nếu vẫn giữ Streamlit, OpenCV và FFmpeg offline đầy đủ. Installer nén có thể nhỏ hơn dung lượng cài đặt, nhưng hai số đo này không được đánh đồng.

## 22. Tạo installer Setup

Cài **Inno Setup 6** trên Windows. Sau khi build xong thư mục `dist\VideoScreenshotFilter`, chạy:

```bat
build_installer.bat
```

Script sẽ tự tìm `ISCC.exe`, biên dịch `FrameForge.iss` và tạo `installer\FrameForge-Setup-1.0.0.exe`. Installer đóng gói toàn bộ thư mục onedir, tạo shortcut Start Menu, cho phép tạo shortcut Desktop, có uninstaller và cài mặc định vào `%LOCALAPPDATA%\Programs\FrameForge`. Cách cài theo user giúp updater yt-dlp ghi dữ liệu vào `%LOCALAPPDATA%` mà không cần quyền administrator.

Nếu Inno Setup cài ở vị trí khác, đặt biến `ISCC` trước khi chạy:

```bat
set ISCC=C:\Tools\Inno Setup 6\ISCC.exe
build_installer.bat
```

Không chỉ copy riêng `VideoScreenshotFilter.exe` ra ngoài thư mục onedir. PyInstaller cần `_internal` và các binary vendor đi kèm. Khi gỡ cài đặt, uninstaller xóa chương trình; dữ liệu updater trong `%LOCALAPPDATA%\VideoScreenshotFilter` cũng được dọn theo cấu hình installer, nhưng nên kiểm tra lại nếu muốn giữ cache yt-dlp.

## 23. Checklist phát hành Windows

Trước khi phát hành, hãy build trên Windows trong thư mục sạch, kiểm tra `build_size_report.json`, cài thử Setup trên user không có Python/FFmpeg, mở ứng dụng và xác nhận trình duyệt truy cập `http://127.0.0.1:8501`. Sau đó kiểm tra health check báo FFmpeg `source=embedded`, thử một URL công khai hợp lệ, format cần ghép audio/video và pipeline Best frame per scene. Cuối cùng kiểm tra cả kích thước thư mục cài đặt lẫn kích thước file Setup; file Setup nhỏ hơn không có nghĩa là ứng dụng sau cài chiếm dưới 200 MB.


## 24. Tự động build và tạo Setup bằng GitHub Actions

Workflow `.github/workflows/windows-release.yml` chạy trên Windows runner của GitHub. Nó tự cài Python 3.12, build PyInstaller onedir, cài Inno Setup, chạy `build_installer.bat`, đo kích thước, tạo `SHA256SUMS.txt` và upload file Setup cùng báo cáo build.

Khi push tag theo dạng `v1.2.3`, workflow mặc định build profile `minimal` và tạo GitHub Release. Khi chạy thủ công trong **Actions**, có thể chọn profile `minimal` hoặc `full`. Nếu chạy thủ công từ một tag và muốn tạo Release, bật tùy chọn `publish_release`.

Sau khi workflow hoàn tất, file có thể lấy ở **Actions → workflow run → Artifacts**, hoặc ở **Releases** nếu workflow đã tạo release theo tag. Artifact Actions mặc định chỉ lưu trong thời hạn giới hạn; file trong Release phù hợp hơn để phân phối lâu dài.

Workflow hiện cấp quyền `contents: write` cho `GITHUB_TOKEN` để tạo Release. Repository cần bật GitHub Actions và cho phép workflow tạo/cập nhật Release. Không đặt Personal Access Token trực tiếp trong YAML. Script FFmpeg hiện vẫn dùng URL mặc định trong `prepare_ffmpeg_windows.ps1`; trước khi phát hành chính thức nên thay alias `latest` bằng asset/version đã ghim hoặc truyền URL qua Repository Variable/Secret để build có thể tái lập.


## 25. Auto-update ứng dụng Windows

Updater hiện có hai phần độc lập. Phần cũ cập nhật package yt-dlp; phần mới trong `app_update.py` kiểm tra manifest HTTPS và so sánh phiên bản ở mỗi lần khởi động, sau đó chỉ tải `FrameForge-Setup-*.exe`, xác minh SHA-256 và mở Setup khi người dùng bấm **Cập nhật ngay**. Ứng dụng không tự ghi đè file EXE đang chạy. Có thể tắt riêng kiểm tra startup bằng `FRAMEFORGE_APP_UPDATE_STARTUP=0`.

Workflow GitHub Actions tạo `latest.json` trong mỗi GitHub Release. Để bật kiểm tra cập nhật EXE trên máy người dùng, đặt:

```bat
set FRAMEFORGE_UPDATE_MANIFEST_URL=https://github.com/GiaHan1907/FrameForge/releases/latest/download/latest.json
```

Repository FrameForge hiện là public, nên app có thể đọc manifest và tải asset từ GitHub Release mà không cần Personal Access Token. App đã có URL manifest public mặc định; có thể ghi đè bằng `FRAMEFORGE_UPDATE_MANIFEST_URL` nếu dùng feed khác. Khi có version mới, giao diện hiển thị một nút **Cập nhật ngay** duy nhất.

Có thể tắt updater EXE bằng:

```bat
set FRAMEFORGE_APP_UPDATE=0
```

Biến `FRAMEFORGE_AUTO_UPDATE=0` chỉ tắt updater yt-dlp, không phải updater EXE.


## 26. Chọn nơi lưu video và screenshot

Ngay khi mở ứng dụng, mở phần **Nơi lưu file** ở khu vực chính. Nhập đường dẫn local hoặc bấm **Chọn thư mục video** để chọn nơi lưu video tải xuống, và bấm **Chọn thư mục screenshot** để chọn thư mục gốc cho ảnh đầu ra.

Video tải từ URL công khai sẽ được lưu trực tiếp vào thư mục video. Mỗi lần bấm **Bắt đầu xử lý**, FrameForge tạo thư mục con dạng `FrameForge_YYYYMMDD_HHMMSS` trong thư mục screenshot, lưu ảnh và `report.json` tại đó. Vì vậy không cần tải file ZIP mới xem được kết quả; nút tải ZIP chỉ còn là lựa chọn phụ để chia sẻ kết quả.

Bản Windows đã nhúng native folder picker qua `tkinter`. Nếu đang chạy trên máy chủ không có giao diện đồ họa, nhập đường dẫn thủ công vào ô text. Không nên chọn thư mục bên trong thư mục cài đặt ứng dụng; nên dùng thư mục Documents/Videos riêng của người dùng.
