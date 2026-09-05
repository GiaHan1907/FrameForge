# FrameForge — Release Notes

> Bản mới nhất: **v0.1.43**. Lịch sử đầy đủ từng bản: [CHANGELOG.md](CHANGELOG.md). Ghi chú riêng cho một số bản cũ: RELEASE_NOTES_v0.1.31.md, RELEASE_NOTES_v0.1.32.md, RELEASE_NOTES_v0.1.33.md, UPDATE_GUIDE_v0.1.31.md.

# FrameForge v0.1.43

## Lưu API key tìm ảnh mã hóa trên máy (Windows DPAPI) + quản lý & kiểm tra key

- Ô API key của Pexels / Pixabay / Unsplash giờ có checkbox **💾 Lưu key trên máy này**: key được mã hóa bằng Windows DPAPI qua `core/key_store.py`, lưu trong thư mục app của người dùng — không bao giờ lưu plaintext, không cần gõ lại key mỗi phiên.
- Thêm phần **API key tìm ảnh** trong tab Cài đặt & Lịch sử: liệt kê từng nguồn với trạng thái key đã lưu (chỉ hiện 4 ký tự cuối, che phần còn lại), ghi rõ khi biến môi trường `FRAMEFORGE_*` đang ghi đè key đã lưu, và nút **🗑 Xóa** theo 2 bước xác nhận (một cú click nhầm không thể mất key).
- Thêm nút **Kiểm tra key** cạnh checkbox lưu: gọi thử nguồn ảnh bằng key vừa nhập **trước khi lưu** — key hoạt động mới được lưu; key bị từ chối (401/403) báo lỗi rõ và không ghi vào máy.
- Sửa thông báo gây hiểu nhầm: khi nguồn cần key từ chối key (hết hạn / sai), app báo đúng "key bị từ chối — kiểm tra lại key" thay vì "không tìm thấy ảnh"; sau mỗi lượt tìm hiện dòng nhỏ cho biết key nào đã phục vụ (biến môi trường / đã lưu trên máy / nhập trong phiên) để phát hiện key cũ đang bị env var che.
- Quy tắc ưu tiên key (gõ tay > biến môi trường > key lưu) gom về một chỗ duy nhất `core/key_store.py::resolve_api_key` — engine và UI cùng đọc một nguồn quyết định nên không thể lệch nhau.
- Tổng suite: 386 tests OK, 16 skipped.

# FrameForge v0.1.42

## Sửa lỗi thiếu bs4 trên bản cài Windows (.exe)

- Ứng dụng bản đóng gói lỗi `ModuleNotFoundError: No module named 'bs4'` ngay khi khởi động: `core/google_images.py` được nhúng dạng source nên PyInstaller không tự phát hiện import `BeautifulSoup` bên trong file.
- Khai báo tường minh `hiddenimports += ["bs4", "soupsieve"]` trong cả 3 spec PyInstaller (minimal / onedir / full) - bản cài này bundle đầy đủ 2 thư viện.
- Phòng thủ thêm: import bs4 chuyển thành lazy, chỉ nạp trong hàm parse HTML duy nhất cần nó; nếu thiếu bs4, parser fallback trả về rỗng thay vì làm sập toàn app.
- Thêm 3 unit test: 3 spec đều phải chứa hiddenimports bs4/soupsieve (chống tái phạm) + parser xử lý đúng khi có và khi không có bs4 (mô phỏng qua sys.modules). Tổng suite 328 tests.

# FrameForge v0.1.41

## Tìm ảnh theo địa điểm: 6 nguồn, có license rõ ràng

- Mở rộng từ DuckDuckGo lên **6 nguồn ảnh** chọn trong dropdown **Nguồn ảnh**: DuckDuckGo (mặc định), **Wikimedia Commons (CC, no key)**, Openverse (CC), Pexels, Pixabay, Unsplash.
- **Wikimedia Commons không cần API key** và trả ảnh Creative Commons/phạm vi công cộng kèm **license + tác giả + kích thước + trang nguồn** - đã kiểm chứng end-to-end (tìm -> tải -> crop) từ IP người dùng thật.
- Nguồn cần key (Pexels/Pixabay/Unsplash) hiện ô **🔑 API key cho …** kèm link đăng ký ngay trong giao diện; key dán vào ô chỉ lưu trong phiên, hoặc đặt biến môi trường `FRAMEFORGE_PEXELS_API_KEY` / `FRAMEFORGE_PIXABAY_API_KEY` / `FRAMEFORGE_UNSPLASH_ACCESS_KEY` (Openverse: `FRAMEFORGE_OPENVERSE_TOKEN`) để dùng lâu dài.
- Dưới mỗi ảnh hiện dòng **license + tác giả** để biết quyền sử dụng trước khi tải.

## Crop ảnh đúng tỷ lệ ngay khi tải

- Dropdown **Tỷ lệ crop khi tải**: `Giữ nguyên`, `Vuông 1:1`, `4:5 (Portrait)`, `3:2`, `16:9 (Landscape)`, `9:16 (Story/Reels)` - mỗi ảnh tải về được center-crop đúng tỷ lệ bằng Pillow trước khi lưu (không cần OpenCV).
- Khi tải từ nguồn có license/tác giả, app ghi kèm file **`sources.tsv`** trong thư mục lưu (file · license · tác giả · trang nguồn · URL gốc) để ghi credit hợp pháp.

## Tải ảnh ổn định hơn

- `download_image` giờ **retry có backoff** với HTTP 429 / 5xx / lỗi mạng (2 lần retry, chờ 2s -> 5s, tôn trọng header Retry-After) - Wikimedia/Openverse hay bị rate-limit thoáng qua sẽ không còn mất ảnh.

## Chất lượng

- Thêm 31 unit test mock HTTP cho backend mới (parse Wikimedia/Openverse/Pexels/Pixabay/Unsplash, thiếu key trả về rỗng, routing dispatcher, crop box math, sources.tsv, retry backoff) - tổng suite 325 tests.
- Đồng bộ `HUONG_DAN_SU_DUNG.md` + `README.md` cho 6 nguồn/cách nhập API key/crop ratio; registry CANONICAL_LABELS mở rộng lên 34 nhãn để CI chặn docs lỗi thời.

# FrameForge v0.1.40

## Luồng làm việc gọn hơn: tải video trước, cấu hình vào tab chính

- Đảo thứ tự tab: **`⬇️ Tải video công khai`** giờ đứng **trước** `⚙️ Xử lý video` — dán URL xong là thấy tab Xử lý ngay kế bên.
- Wizard 4 bước chuyển từ sidebar vào **tab Xử lý video**: cấu hình nằm ngay trong 4 expander thu gọn theo từng bước (Nguồn video / Cách chọn frame / Chất lượng & tốc độ / Đầu ra); bước đang chọn trên radio wizard tự mở sẵn.
- **Sidebar chỉ còn**: thương hiệu + nút **🔍 Tìm ảnh theo địa điểm**. Toàn bộ widget keys giữ nguyên nên preset và cấu hình đã lưu không bị reset.

## Sửa tính năng Tìm ảnh theo địa điểm

- Google Images chặn scraper không-JS (trả trang “enable JavaScript” → 0 kết quả): chuyển engine mặc định sang **DuckDuckGo Images** (không cần API key, không cần JS); parser Google cũ giữ làm fallback.
- Sửa lỗi `thumbnail_url` không tồn tại khi hiển thị lưới kết quả (dùng `thumbnail` đúng field).
- UI inline nâng cấp: ô địa điểm + slider số ảnh + lưới 3 cột + ô **📁 Thư mục lưu ảnh** + nút **📥 Tải tất cả** (batch) và **Tải #N** từng ảnh.

## Dọn mã & chất lượng

- Xóa `ui/image_search.py` (page standalone cũ gọi `st.set_page_config`, không còn dùng) — gỡ khỏi spec đóng gói onedir để tránh nhầm lẫn.
- Thêm 15 unit test mock HTTP cho `_ddg_search_images` / `search_google_images`: chặn tái phạm lỗi “0 kết quả” (trang chặn thiếu token vqd, network error, JSON hỏng → trả `[]`; fallback đúng thứ tự DDG → Google cũ).


# FrameForge v0.1.39

## Giao diện rút gọn — giảm cuộn tối đa

Toàn bộ giao diện được thu gọn để mở app là làm được việc ngay, hầu như không phải cuộn:

- Trang chính chia thành **3 tab**: `⚙️ Xử lý video`, `⬇️ Tải video công khai`, `📁 Cài đặt & Lịch sử`. Tab Xử lý chỉ còn: wizard 4 bước (1 dòng) + 4 card tóm tắt + nút **Bắt đầu xử lý**.
- **Sidebar ngắn lại ~một nửa**: các tùy chọn nâng cao (scene detection, hiệu năng, lọc mờ/trùng, retry/cache) gói trong 4 expander thu gọn; vẫn giữ nguyên mọi giá trị và preset đã lưu.
- **Preview workspace** (video player + crop overlay + timeline + frame gallery) gói trong 1 expander thu gọn, chỉ còn 1 dòng chọn video khi chưa cần xem.
- **Form tải video** (URL, chất lượng, giới hạn playlist, retry) gói trong 1 expander thu gọn; label tự báo số URL đã dán. Kết quả tải vẫn hiện phía dưới khi đang chạy.
- **Panel Cập nhật & kênh** gói trong expander thu gọn; khi có bản mới label tự đổi thành `🔔 Có bản FrameForge X`. Preset cá nhân và lịch sử job cũng là expander thu gọn riêng.
- Các widget keys không đổi, nên preset, autosave và mọi cấu hình đã lưu từ bản cũ vẫn giữ nguyên.

## Sửa lỗi ổn định trên bản cài Windows (.exe)

- **Hết lỗi `ModuleNotFoundError: No module named 'pyarrow'`**: bảng Lịch sử job chuyển sang HTML/CSS thuần (thay `st.dataframe`), profile minimal không còn cần Pandas/PyArrow.
- Sửa các spec PyInstaller: thiếu trailing comma (lỗi `'tuple' object is not callable`), thiếu `core/google_images.py`, `core/pipeline.py` trong datas; bổ sung `requests` + `beautifulsoup4` vào requirements.
- Sửa hàng loạt lỗi chạy bản cài: thiếu `import streamlit as st` trong `ui/sidebar.py`, `Expander` thiếu field `entries`, biến `count`/`downloaded_paths` chưa gán, đường dẫn tải về giờ xử lý đúng khi là chuỗi.
- **Tìm ảnh theo địa điểm** giờ chạy ngay trong app (trước đây dùng `st.page_link` bị lỗi trên bản đóng gói).
- Release tự **publish** khi push tag (không còn release draft); `latest.json` kèm metadata rollback tới bản stable trước đó.

# FrameForge v0.1.38

## Giao diện rút gọn — 3 tab, ít cuộn

- Trang chính thành **3 tab**: `⚙️ Xử lý video`, `⬇️ Tải video công khai`, `📁 Cài đặt & Lịch sử`; bỏ hero, card tổng quan và step cards.
- Sidebar, preview workspace, form tải video và panel Cập nhật gói vào các expander thu gọn.
- Widget keys giữ nguyên nên preset/autosave không đổi.

# FrameForge v0.1.37

## Sửa ổn định bản cài Windows (.exe)

- Bảng lịch sử job chuyển sang HTML/CSS thuần, hết lỗi thiếu pyarrow trên profile minimal.
- Sửa spec PyInstaller và requirements (`requests`, `beautifulsoup4`); fix thiếu `import streamlit`/`Expander`, biến `count`/`downloaded_paths`.
- Tìm ảnh theo địa điểm chạy inline trong app; CI tự publish release khi push tag.

# FrameForge v0.1.36

## Tách module phân tích và tăng tốc các lần chạy lặp lại

- Tách `core/analysis.py` (11 hàm phân tích cv2); thêm TTL cache cho RAM/RSS và memoize processing signature.
- Cải thiện accessibility/mobile theo Web Interface Guidelines.

# FrameForge v0.1.35

## Tách module lớn và CLI headless

- Chia `core/pipeline.py` và `streamlit_app.py` thành các module `core/*`, `ui/*`; dataclass `FrameForgeConfig`; widget globals chuyển sang `st.session_state`.
- CLI headless mới: `python -m core.cli` — xử lý video không cần Streamlit.

# FrameForge v0.1.34

## Security hardening và dọn code

- Chặn path traversal khi đọc `pending.json` của app update; dọn dead code trong `PersistentQueueStore`; đồng bộ version spec/installer.

# FrameForge v0.1.33

## Ép đủ số screenshot sau filter

- Tùy chọn **Ép đủ số ảnh yêu cầu (fallback cuối)**: khi frame bị loại nhiều vì mờ/motion blur/duplicate, engine dùng lại candidate bị loại theo mức ưu tiên để đạt đủ target; không tạo frame giả. Report ghi `forced_fallback_saved`/`force_fill_shortfall`.
- Xem chi tiết: [RELEASE_NOTES_v0.1.33.md](RELEASE_NOTES_v0.1.33.md).

# FrameForge v0.1.32

## Desktop auto-shutdown khi đóng web

- Watchdog tự dừng `VideoScreenshotFilter.exe` khi browser session cuối cùng đóng, cancel job an toàn, có PID guard.
- Xem chi tiết: [RELEASE_NOTES_v0.1.32.md](RELEASE_NOTES_v0.1.32.md).

# FrameForge v0.1.31

## Silent Windows runtime

- Bỏ cửa sổ terminal chớp khi kiểm tra update/FFmpeg; shortcut trỏ thẳng tới EXE windowed.
- Xem chi tiết: [RELEASE_NOTES_v0.1.31.md](RELEASE_NOTES_v0.1.31.md) và [UPDATE_GUIDE_v0.1.31.md](UPDATE_GUIDE_v0.1.31.md).

# FrameForge v0.1.30

## Accessibility, keyboard navigation và responsive polish

Bổ sung focus ring rõ ràng cho keyboard navigation, touch target tối thiểu 40px và vùng trạng thái `aria-live` để các thay đổi quan trọng dễ nhận biết hơn. Giao diện hiển thị hướng dẫn dùng phím Tab, Enter và Space cho các control chính.

Responsive layout được tinh chỉnh cho màn hình dưới 900px và 640px: sticky summary chuyển về flow tĩnh để không che nội dung, timeline legend tự xuống dòng, khoảng cách cột được thu gọn và card vẫn giữ chiều cao tối thiểu dễ thao tác. `prefers-reduced-motion` được hỗ trợ để giảm animation với người dùng đã bật tùy chọn hệ thống.

Thêm visual regression contract tests nhằm bảo vệ các selector CSS, breakpoint, trạng thái accessibility và đảm bảo các tính năng preview workspace, job history, config export và queue dashboard không bị mất trong các lần chỉnh UI tiếp theo.

# FrameForge v0.1.29

## Preset cá nhân, job history và cấu hình portable

Bổ sung khu vực **Preset cá nhân và cấu hình** cho phép lưu nhiều preset theo tên riêng, áp dụng lại ở các lần chạy sau và ghi dữ liệu vào thư mục UI per-user. Preset cá nhân chỉ lưu các tham số xử lý cần thiết, không lưu video nguồn, cookie, thông tin đăng nhập hoặc dữ liệu nhạy cảm.

Người dùng có thể xuất cấu hình hiện tại thành `frameforge-config.json` để sao lưu hoặc chuyển sang máy khác, và nhập lại file JSON qua giao diện. File import được kiểm tra schema/object trước khi áp dụng; các giá trị hợp lệ được nạp vào session state rồi giao diện rerun để tránh trạng thái widget cũ.

FrameForge bắt đầu lưu **job history** tối đa 50 job gần nhất, gồm thời gian hoàn tất, trạng thái, thư mục output, số video, số ảnh đã lưu, shortfall và lỗi tổng quát. Lịch sử hiển thị trong expander gọn, không làm che khuất workflow xử lý chính.

Diagnostic action được chuẩn hóa thành payload JSON có version và lỗi rút gọn, hỗ trợ tải xuống khi queue thất bại. Payload không bao gồm cookie hoặc thông tin đăng nhập.

Regression assertions bao phủ các helper lưu preset, import/export, job history và UI panel mới.

# FrameForge v0.1.28

## Preview workspace: scene markers, frame gallery và crop tương tác

Khu vực xem trước được nâng cấp thành **Preview workspace** với video gốc và crop preview đặt cạnh nhau trong một container thống nhất. Người dùng có thể chọn timestamp bằng thanh trượt để xem frame thực tế tại bất kỳ mốc nào trong video; frame preview áp dụng trực tiếp crop ratio hiện tại mà không thay đổi file nguồn.

Timeline preview mới phân biệt timestamp ước tính bằng marker xanh và scene marker thật bằng marker xanh lá sau khi chạy **Phân tích nhanh scene thật**. Workspace hiển thị số marker, thời lượng video và số mốc dự kiến, giúp người dùng kiểm tra mật độ scene trước khi chạy pipeline đầy đủ.

Frame gallery cho phép xem nhanh frame tại mốc đang chọn, kèm timestamp và crop ratio. Cơ chế đọc frame dùng độ phân giải preview giới hạn để giữ giao diện phản hồi nhanh và tự dọn file tạm đối với video upload.

Regression tests tiếp tục bảo vệ crop overlay, scene preview, layout hai panel và các helper preview cũ.

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

---

> ⚠️ **Tài liệu gốc thời v0.1.9 trở về trước** — giữ lại để tham khảo lịch sử. Quy trình build/release, cấu trúc module và số đo kích thước hiện tại đã thay đổi; thông tin hiện hành xem [README.md](README.md) và [AUTO_UPDATE_AND_SIZE_GUIDE.md](AUTO_UPDATE_AND_SIZE_GUIDE.md).

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

> ⚠️ Ghi chú lịch sử (thời v0.1.9). Từ v0.1.31 trở đi bản Windows được build và kiểm thử trực tiếp trên GitHub Actions runner windows-2022; installer `.exe` được sinh ra tự động mỗi lần push tag `vX.Y.Z`.

## Phân phối FFmpeg

Giữ lại các file license, readme và `BUILD_METADATA.txt` do `prepare_ffmpeg_windows.ps1` tạo. Trước khi phát hành cần đối chiếu SHA-256, nguồn binary, configure flags và phạm vi license/codec của build FFmpeg đã chọn. Không dùng GPL/nonfree build chỉ vì mục tiêu giảm kích thước khi chưa rà soát nghĩa vụ phân phối.


## GitHub Actions

Workflow mới tại `.github/workflows/windows-release.yml` chạy trên `windows-2022`, chọn profile minimal/full, gọi `build_windows.bat`, smoke-test endpoint HTTP 200 của executable đã đóng gói, cài Inno Setup bằng Chocolatey, tạo Setup, sinh checksum và upload artifact. Push tag dạng `v1.2.3` sẽ tự tạo và **publish** GitHub Release (từ v0.1.37 không còn ở trạng thái draft); chạy thủ công cho phép chọn profile.

Workflow dùng `GITHUB_TOKEN` với `contents: write`. Repository phải cho phép Actions tạo Release. Không commit Personal Access Token hoặc secret nhạy cảm vào YAML. Trước phát hành chính thức nên thay URL FFmpeg alias `latest` bằng asset/version được ghim hoặc truyền qua Repository Variable/Secret.

Kênh `stable` tạo `latest.json` và GitHub Release thông thường. Kênh `beta` tạo prerelease và asset `latest-beta.json`; người dùng chọn kênh trong UI hoặc đặt `FRAMEFORGE_UPDATE_CHANNEL=beta`. Updater chỉ chấp nhận manifest đúng channel, HTTPS và SHA-256 hợp lệ. Stable release mới sẽ ghi metadata rollback tới stable release trước đó nếu asset `latest.json` cũ còn truy cập được.

Để ký installer bằng Authenticode, tạo hai Actions secrets: `WINDOWS_CERTIFICATE_BASE64` chứa file PFX đã mã hóa Base64 và `WINDOWS_CERTIFICATE_PASSWORD` chứa mật khẩu PFX. Workflow sẽ dùng `signtool.exe`, timestamp SHA-256 và kiểm tra `Get-AuthenticodeSignature`. Nếu secrets chưa được cấu hình, build vẫn phát hành nhưng manifest ghi rõ `signature_status=unsigned`; không nên coi bản unsigned là bản phân phối production cuối cùng.


