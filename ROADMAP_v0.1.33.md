# FrameForge v0.1.33 — Roadmap đề xuất

## Định hướng

v0.1.33 nên ưu tiên **kiểm soát chất lượng đầu ra và khả năng giải thích kết quả**. Sau khi v0.1.32 hoàn thiện auto-shutdown desktop, giá trị lớn nhất tiếp theo là giúp người dùng xem, lọc và xác nhận frame trước khi export mà không phải chạy lại toàn bộ video nhiều lần.

## Phạm vi ưu tiên

| Ưu tiên | Tính năng | Mục tiêu |
|---|---|---|
| P0 | Frame review/contact sheet | Xem và bỏ chọn frame trước khi export |
| P0 | Scene rejection inspector | Biết chính xác vì sao từng candidate bị loại |
| P0 | Output naming template | Tên file nhất quán, an toàn Windows và tránh collision |
| P0 | Queue observability | Theo dõi retry, resource wait, throughput và thời gian từng phase |
| P1 | Preview LRU cache | Kéo timeline/crop mượt hơn với giới hạn RAM |
| P1 | Startup readiness card | Kiểm tra FFmpeg, disk, quyền ghi và dependency trước khi chạy |
| P1 | Failure simulation | Kiểm thử permission, disk full, path change, crash và two-instance queue |
| P2 | Accessibility audit sâu | NVDA/Narrator, zoom 200%, contrast và target 44px |

## Chi tiết tính năng

### Frame review/contact sheet

Sau khi engine chọn frame, UI hiển thị contact sheet có thumbnail, timestamp, scene index, sharpness, crop ratio và trạng thái. Người dùng có thể bỏ chọn hoặc đánh dấu frame yêu thích trước khi export. Review là tùy chọn để không làm thay đổi workflow batch hiện tại.

Manifest và report phải ghi nhận số frame bị bỏ trong review, số frame giữ lại và shortfall sau review. Không lưu pixel đầy đủ của mọi frame vào SQLite; chỉ dùng thumbnail giới hạn kích thước và metadata nhẹ.

### Scene rejection inspector

Chuẩn hóa reason code gồm `blur`, `motion_blur`, `duplicate`, `flash`, `outside_range`, `not_best_in_scene`, `target_reached`, `encode_error` và `unknown`. UI cho phép lọc theo reason và scene, đồng thời hiển thị số lượng từng nhóm để người dùng điều chỉnh threshold có cơ sở.

### Output naming template

Hỗ trợ các biến `{video}`, `{scene}`, `{index}`, `{timestamp}` và `{date}`. Tên file phải được sanitize cho Windows, giới hạn độ dài, không tạo thư mục ngoài output directory và xử lý collision deterministic bằng suffix. Preview tên file chỉ là mô phỏng, không ghi file thật.

### Queue observability

Queue dashboard hiển thị riêng thời gian `queued`, `running`, `resource_wait`, `retrying` và `completed`. Mỗi item có candidate count, saved count, retry count, throughput và nút mở diagnostics. `resource_wait` và `retrying` không được hiển thị như lỗi thất bại.

## Acceptance criteria

| ID | Tiêu chí nghiệm thu |
|---|---|
| V33-AC01 | Contact sheet hiển thị đúng frame, timestamp, scene và crop ratio |
| V33-AC02 | Bỏ chọn frame cập nhật manifest/report nhưng không phá resume |
| V33-AC03 | Mọi candidate bị loại có reason code hợp lệ |
| V33-AC04 | Có thể lọc rejection theo reason và scene |
| V33-AC05 | Template tên file không tạo path traversal hoặc tên không hợp lệ trên Windows |
| V33-AC06 | Collision naming deterministic và được preview trước khi chạy |
| V33-AC07 | Queue phân biệt rõ thời gian chờ resource, retry và running |
| V33-AC08 | LRU cache có giới hạn entry/bytes và reset khi đổi video |
| V33-AC09 | Startup readiness phát hiện thiếu FFmpeg, output không ghi được hoặc disk thấp |
| V33-AC10 | DB/config/manifest v0.1.22–v0.1.32 mở được không mất dữ liệu |
| V33-AC11 | Clean install, upgrade install, silent console và auto-shutdown smoke đạt |
| V33-AC12 | Installer, latest.json và SHA256SUMS khớp sau release |

## Thứ tự triển khai

Giai đoạn đầu chuẩn hóa data contract cho reason code, review selection và filename template. Tiếp theo xây contact sheet phân trang/lazy-load để tránh tăng RAM, sau đó nối rejection inspector vào report và queue dashboard. LRU cache và startup readiness triển khai sau khi data contract ổn định. Cuối cùng chạy test freeze, Windows packaged smoke, Process Monitor và staged release.

## Rủi ro

Contact sheet có thể làm tăng RAM nếu tải quá nhiều thumbnail; cần pagination và giới hạn kích thước. Review có thể làm thay đổi số output sau khi job đã hoàn tất; phải chạy manifest verify/repair và cập nhật shortfall. Template tên file phải chỉ tạo basename sau sanitize. Cache phải giới hạn cả số lượng entry và dung lượng byte.

## Không thuộc v0.1.33

Cloud sync, collaboration, tài khoản người dùng, GPU pipeline, plugin marketplace và xử lý realtime chưa nên đưa vào bản này vì làm tăng đáng kể độ phức tạp packaging, bảo mật và migration.
