# Changelog

Lịch sử thay đổi của FrameForge. Các phiên bản tuân theo SemVer; bản mới nhất được đặt ở đầu.

## [Unreleased]

Bản mới nhất đã phát hành: **v0.1.39**. Phần "What's new" hiển thị trong app và các ghi chú theo bản nằm tại [RELEASE_NOTES.md](RELEASE_NOTES.md); roadmap đề xuất cũ cho v0.1.33 đã lưu trữ tại [ROADMAP_v0.1.33.md](ROADMAP_v0.1.33.md).

## [0.1.39] — Release notes rõ ràng và vệ sinh docs

- Bump lên v0.1.39 kèm entry release notes đầy đủ; xóa release/tag v0.1.39 cũ trỏ commit lỗi thời để lịch sử phát hành sạch.
- Nâng `MyAppVersion` mặc định trong `FrameForge.iss` theo version hiện tại để `build_installer.bat` local không tạo Setup sai version.
- Cập nhật README và AI_HANDOVER cho khớp hiện trạng.

## [0.1.38] — Rút gọn giao diện, giảm cuộn tối đa

- Trang chính chuyển sang 3 tab: Xử lý video / Tải video công khai / Cài đặt & Lịch sử; bỏ hero, card tổng quan và step cards.
- Sidebar thu gọn ~một nửa: scene detection nâng cao, hiệu năng, lọc mờ/trùng, retry/cache gói trong 4 expander thu gọn.
- Preview workspace (player + crop + timeline + gallery), form tải video và panel Cập nhật & kênh gói vào expander thu gọn.
- Widget keys giữ nguyên nên preset/autosave không đổi.

## [0.1.37] — Sửa ổn định bản cài Windows (.exe)

- Bảng job history chuyển `st.dataframe` sang HTML/CSS thuần, loại bỏ nhu cầu pyarrow/pandas khỏi profile minimal (hết lỗi `ModuleNotFoundError: No module named 'pyarrow'`).
- Sửa spec PyInstaller: trailing comma thiếu (lỗi `'tuple' object is not callable`), thiếu `core/google_images.py`/`core/pipeline.py` trong datas; bổ sung `requests` + `beautifulsoup4` vào requirements.
- Fix chuỗi lỗi runtime bản cài: thiếu `import streamlit as st`/`Expander` trong `ui/sidebar.py`, `Expander` thiếu field `entries`, biến `count`/`downloaded_paths` chưa gán, `downloaded_paths` là chuỗi cần bọc `Path()`.
- Tìm ảnh theo địa điểm chạy inline trong app (thay `st.page_link` vốn lỗi khi đóng gói); CI tự publish release khi push tag (không còn draft).

## [0.1.36] — Tách core/analysis.py và tối ưu hiệu năng

- Tách 11 hàm phân tích cv2 từ `video_screenshot_advanced.py` vào `core/analysis.py`; tách `_render_processing_job` sang `ui/processing_view.py`.
- Thêm TTL cache cho `_available_memory_gb()`/`current_process_rss_bytes()` và memoize `processing_signature()`.
- Xử lý 12 Web Interface Guidelines issues; thêm `overscroll-behavior: contain`.

## [0.1.35] — Tách module lớn và CLI headless

- Chia `core/pipeline.py` (675 dòng) thành `core/checkpoint.py`/`core/workers.py`/`core/cleanup.py`; tách thêm `core/targets.py`, `core/cv2_helpers.py`, `core/analysis.py`, `core/errors.py`.
- `streamlit_app.py` tách thành 5 module `ui/*`; thay `SimpleNamespace` bằng dataclass `FrameForgeConfig`; chuyển widget globals sang `st.session_state`; xóa duplicate `_ProcessingQueueAdapter`, worker functions và `classify_error`.
- Thêm CLI headless `python -m core.cli` — xử lý video từ terminal không cần Streamlit.

## [0.1.34] — Security hardening and code cleanup

- Thêm path traversal validation cho `_read_pending()` trong app update, chống tampered `pending.json` trỏ ra file ngoài update root.
- Refactor `PersistentQueueStore.mark_cancelled()` bỏ dead code SQL computation bị ghi đè vô ích.
- Cập nhật `frameforge_version.txt` và `FrameForge.iss`sync version 0.1.34.

## [0.1.33] — Ép đủ số screenshot sau filter

- Thêm tùy chọn **Ép đủ số ảnh yêu cầu (fallback cuối)**: nếu sau vòng filter chính vẫn thiếu target do mờ/motion blur/duplicate, engine dùng lại candidate bị loại theo thứ tự ưu tiên; không tạo frame giả, không decode thừa.
- Report/manifest ghi nhận `forced_fallback_saved`, `forced_fallback_reasons`, `force_fill_shortfall`; thêm suffix `_fallback_0001_1` khi trùng tên để không ghi đè output cũ.
- Chi tiết: [RELEASE_NOTES_v0.1.33.md](RELEASE_NOTES_v0.1.33.md).

## [0.1.32] — Desktop auto-shutdown watchdog

- Thêm watchdog nhận biết khi browser session desktop cuối cùng đóng.
- Hủy job đang chạy an toàn, giữ checkpoint theo lifecycle hiện tại và dọn work directory phù hợp.
- Dừng Streamlit runtime, sau đó kết thúc đúng `VideoScreenshotFilter.exe` cùng process con bằng `taskkill.exe /PID /T /F`.
- Chạy `taskkill.exe` với `CREATE_NO_WINDOW` để không tạo terminal phụ.
- Thêm `FRAMEFORGE_DESKTOP_PID` làm PID guard, tránh kill nhầm process khác.
- Giữ nguyên hành vi khi chạy `streamlit run` thủ công; auto-shutdown chỉ bật từ desktop launcher.
- Thêm unit test cho non-Windows no-op, taskkill flags và PID mismatch.
- Cập nhật Inno Setup mặc định và script `build_installer_v0132.bat`.

## [0.1.31] — Silent Windows runtime

- Ẩn console của PowerShell Authenticode check.
- Ẩn console của FFmpeg health check.
- Giữ PyInstaller `console=False` cho EXE release.
- Cập nhật shortcut Inno Setup trỏ trực tiếp tới EXE với `WorkingDir` đúng.
- Thêm smoke test kiểm tra PE GUI subsystem, shortcut target, working directory và silent launch.
- Thêm Process Monitor startup capture để phân tích process con.
- Thêm `check_launcher_log.ps1` và hướng dẫn đọc `launcher_error.log`.
- Thêm workflow build Windows và checksum/metadata artifact.

## [0.1.30] — Accessibility và responsive UI

- Thêm `:focus-visible`, keyboard guidance và trạng thái live region cho các khu vực tương tác.
- Bổ sung reduced-motion handling.
- Cải thiện responsive layout cho preview, queue và các card summary.
- Thêm visual regression contract test cho selector accessibility, breakpoint và live status.
- Cập nhật browser smoke và tài liệu migration.

## [0.1.29] — Preset cá nhân và job history

- Cho phép lưu preset cấu hình cá nhân.
- Thêm job history JSON cho các job gần đây.
- Thêm diagnostic payload JSON có thông tin version và lỗi rút gọn.
- Thêm import/export cấu hình.
- Bảo vệ session state khi import JSON không hợp lệ.

## [0.1.28] — Interactive preview workspace

- Thay preview đơn bằng workspace gồm scene marker timeline, frame gallery và crop preview.
- Đọc frame theo timestamp để xem kết quả thực tế.
- Hiển thị scene marker thật và phân biệt với timestamp ước tính.
- Hỗ trợ chọn timestamp, crop ratio và xem overlay cạnh preview gốc.
- Cập nhật regression test cho layout hai cột và nhãn tương thích.

## [0.1.27] — Validation và queue visibility

- Thêm step validation trước khi chạy job.
- Thêm sticky summary card cho cấu hình quan trọng.
- Thêm queue dashboard tổng quan theo trạng thái.
- Thêm resource meter cho RAM/disk.
- Thêm error actions và diagnostic action theo item.
- Cải thiện hiển thị resource wait, retry và lỗi per-video.

## [0.1.26] — P0 reliability upgrades

- Thêm adaptive target count, tự mở rộng candidate budget khi frame bị loại nhiều.
- Thêm `verify_video_manifest()` và CLI `--repair-manifest` để kiểm tra/sửa manifest sau crash.
- Thêm resume validation bằng `run_signature`.
- Thêm dynamic resource back-pressure và trạng thái `resource_wait`.
- Thêm shortfall diagnostics phân biệt target, candidate, saved và lý do frame bị loại.
- Thêm quick scene preview dùng marker scene thật.
- Bổ sung regression test và tài liệu P0.

## [0.1.25] — Target count và atomic output

- Cố gắng đạt số ảnh mục tiêu sau filter bằng candidate budget giới hạn.
- Thêm `.frameforge_manifest.json` cho từng video.
- Encode vào file tạm rồi rename atomic trước khi ghi nhận output.
- Thêm shortfall diagnostics và resource guard trước khi xử lý.
- Preview hiển thị timestamp dự kiến theo mode.

## [0.1.24] — Số lượng screenshot per-video

- Cho phép chọn số screenshot riêng cho mỗi video.
- Giữ semantics khác nhau giữa scene/every mode và exact-frame mode.
- Cập nhật queue/report để ghi nhận target count từng video.

## [0.1.23] — Crash-resilient persistent queue

- Thêm SQLite state machine có schema version và additive migration từ v0.1.22.
- Thêm stable `item_id`, source position, phase/progress, heartbeat và timestamps.
- Đánh dấu item đang chạy thành `interrupted` sau crash và hỗ trợ resume.
- Retry dùng stable ID thay vì vị trí hiển thị.
- Thêm integration test mô phỏng crash bằng subprocess và `os._exit()`.

## [0.1.22] — Bounded queue và dual preview

- Thêm bounded scheduler giới hạn số video submit đồng thời.
- Pause/cancel/retry hoạt động theo ranh giới video/checkpoint an toàn.
- Thêm preview Video gốc và Crop overlay cạnh nhau.
- Queue per-video hiển thị attempts, saved, FPS, ETA, RAM và lỗi.

## [0.1.21] — Queue per-video controls

- Tích hợp queue per-video vào Streamlit chính.
- Thêm các nút pause, resume, cancel và retry item.
- Hiển thị trạng thái và telemetry riêng cho từng video.
- Đóng gói module queue vào PyInstaller và kiểm tra trên Windows CI.

## [0.1.20] — Wizard và crop overlay

- Thêm wizard bốn bước: Nguồn, Chọn frame, Chất lượng và Đầu ra.
- Thêm summary card cấu hình.
- Thêm crop overlay theo tỉ lệ screenshot.
- Bổ sung mẫu queue controls và preview cạnh nhau.

## [0.1.19] — Conditional metrics và encode profiling

- Dùng ảnh phân tích nhỏ dùng chung cho grayscale, sharpness, motion blur, dHash và histogram.
- Chỉ tính metric khi tính năng tương ứng được bật.
- Thêm encode profile Nhanh và Chất lượng cao.
- Benchmark tách các công đoạn decode, analysis, encode và write.

## [0.1.18] — Downloader error classification

- Phân loại lỗi yt-dlp thành access denied, rate limited, FFmpeg missing, format unavailable, output error, network error và unknown.
- Thêm retry exponential backoff cho lỗi tạm thời.
- Cho queue tiếp tục các URL còn lại qua callback lỗi per-video.

## [0.1.17] — Screenshot crop ratios

- Thêm crop ratio `16:9`, `9:16`, `4:5`, `1:1` và Không crop.
- Crop trung tâm trước resize, không kéo giãn ảnh.
- Preset Video dọc/TikTok mặc định dùng `9:16`.

## [0.1.16] — Downloader staging

- Cô lập từng URL và retry vào thư mục staging riêng.
- Tránh nhầm output cũ với file download mới.
- Dọn staging sau success, error hoặc retry.

## [0.1.15] — Preset và live telemetry

- Thêm preset Nhanh, Cân bằng, Chất lượng cao và Video dọc/TikTok.
- Hiển thị FPS, ETA và RSS RAM trong lúc xử lý.
- Thêm adaptive extraction worker theo duration, timestamp, CPU/RAM và số video worker.

## [0.1.14] — Compact preview và timestamp naming

- Thu nhỏ preview video và dùng layout downloader responsive.
- Đồng bộ dark mode cho downloader.
- Đặt tên screenshot theo `HH-MM-SS.mmm.jpg`.
- Đặt tên video theo timestamp và thêm collision suffix.

## [0.1.13] — Desktop cleanup lifecycle

- Tự động dọn file input tạm và work directory sau job hoàn tất.
- Browser đóng sẽ hủy job, đóng executor và dừng server ở bản desktop.
- Cải thiện dark downloader UI và responsive layout.

## [0.1.12] — Directory picker state fix

- Sửa lỗi Streamlit session state khi chọn lại thư mục video/screenshot.
- Không gán trực tiếp vào widget key sau khi widget đã được khởi tạo.

## [0.1.11] — Windows package modules

- Bổ sung các runtime modules còn thiếu vào PyInstaller package.
- Cải thiện Windows CI validation cho package output.

## [0.1.10] — Duplicate index và cleanup quota

- Tối ưu duplicate index giữa các lần chạy.
- Bổ sung giới hạn cleanup và quản lý cache/output an toàn hơn.

## [0.1.9] — Adaptive extraction và queue telemetry

- Thêm adaptive extraction budget.
- Bổ sung telemetry vòng đời queue và tiến độ xử lý.

## [0.1.8] — Windows benchmark encoding

- Sửa vấn đề encoding console khi chạy benchmark trên Windows.

## [0.1.7] — Persistent queue và adaptive workers

- Thêm persistent queue SQLite.
- Bổ sung adaptive worker và benchmark RAM/tốc độ trên CI.
- Thêm checkpoint cấp frame/scene.

## [0.1.6] — Timeline, channels và rollback updater

- Thêm interactive timeline.
- Thêm stable/beta update channel.
- Bổ sung rollback updater và signing/release workflow.

## [0.1.5] — Retry/cancel test coverage

- Bổ sung automated tests cho retry queue và cancel processing.
- Cải thiện các trạng thái queue cơ bản.

## [0.1.4] — Update manifest validation

- Validate public update manifest trước khi hiển thị thông báo update.
- Kiểm tra checksum và cấu trúc metadata an toàn hơn.

## [0.1.3] — Startup update check

- Kiểm tra app update ngay khi khởi động thay vì chỉ dựa vào cache dài hạn.

## [0.1.2] — Persistent output folders

- Ghi nhớ thư mục lưu video và screenshot.
- Cải thiện update UX và config persistence.

## [0.1.1] — Release workflow fix

- Sửa checkout/release validation trong GitHub Actions.

## [0.1.0] — Public app updates

- Bật cơ chế public one-click app updates.

[Unreleased]: https://github.com/GiaHan1907/FrameForge/compare/v0.1.39...HEAD
[0.1.39]: https://github.com/GiaHan1907/FrameForge/releases/tag/v0.1.39
[0.1.38]: https://github.com/GiaHan1907/FrameForge/releases/tag/v0.1.38
[0.1.37]: https://github.com/GiaHan1907/FrameForge/releases/tag/v0.1.37
[0.1.36]: https://github.com/GiaHan1907/FrameForge/releases/tag/v0.1.36
[0.1.35]: https://github.com/GiaHan1907/FrameForge/releases/tag/v0.1.35
[0.1.34]: https://github.com/GiaHan1907/FrameForge/releases/tag/v0.1.34
[0.1.33]: https://github.com/GiaHan1907/FrameForge/releases/tag/v0.1.33
[0.1.32]: https://github.com/GiaHan1907/FrameForge/releases/tag/v0.1.32
[0.1.31]: https://github.com/GiaHan1907/FrameForge/releases/tag/v0.1.31
[0.1.30]: https://github.com/GiaHan1907/FrameForge/releases/tag/v0.1.30
