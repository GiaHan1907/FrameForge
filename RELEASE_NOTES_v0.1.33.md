# FrameForge v0.1.33

## Force-fill số lượng screenshot sau filter

FrameForge v0.1.33 giải quyết trường hợp người dùng yêu cầu một số lượng ảnh cụ thể nhưng toàn bộ frame bị loại bởi bộ lọc mờ, motion blur hoặc duplicate. Khi bật **Ép đủ số ảnh yêu cầu (fallback cuối)**, ứng dụng sẽ cố gắng tạo đúng target count thay vì kết thúc với 0 ảnh hoặc thiếu ảnh mà không có giải thích rõ ràng.

## Cách hoạt động

Vòng xử lý chính vẫn áp dụng đầy đủ các filter hiện có. Engine ưu tiên candidate đạt ngưỡng sharpness, motion blur và duplicate trước. Nếu sau vòng này số ảnh lưu được vẫn thấp hơn target, engine sắp xếp các candidate bị loại theo mức độ ưu tiên và dùng chúng ở vòng fallback cuối.

Fallback không tạo frame giả và không lặp lại việc decode không cần thiết. Nó chỉ dùng các candidate thực sự đã đọc được từ video. Nếu video không có đủ frame đọc được, hệ thống vẫn báo shortfall đúng thực tế.

Khi timestamp tạo ra tên file đã tồn tại, fallback tự thêm suffix dạng `_fallback_0001_1` để không ghi đè output cũ nếu người dùng chưa bật overwrite.

## Áp dụng cho các chế độ

Tùy chọn fallback áp dụng cho:

- `Đúng N frame`.
- `Mỗi N giây`.
- `Scene detection`.
- `Best frame per scene`.

Trong giao diện, tùy chọn được bật mặc định với nhãn **Ép đủ số ảnh yêu cầu (fallback cuối)**. CLI vẫn hỗ trợ:

```bash
python video_screenshot_advanced.py \
  --max-screenshots 10 \
  --target-count-after-filter
```

Nếu muốn giữ filter tuyệt đối và chấp nhận thiếu ảnh, tắt tùy chọn fallback trong giao diện hoặc không truyền `--target-count-after-filter` khi chạy CLI.

## Diagnostics và UI

Report JSON và manifest ghi nhận các trường mới:

| Trường | Ý nghĩa |
|---|---|
| `forced_fallback_saved` | Số ảnh được lưu bằng fallback |
| `forced_fallback_reasons` | Lý do candidate bị loại ở vòng chính |
| `force_fill_shortfall` | Số ảnh vẫn còn thiếu sau fallback |
| `shortfall_message` | Thông báo phân biệt đủ target, fallback hoặc không đủ candidate |

UI hiển thị rõ sự khác biệt giữa `Đạt mục tiêu sau filter` và `Đủ mục tiêu có fallback`. Người dùng vì vậy biết chính xác khi nào một phần ảnh có thể không đạt ngưỡng filter ban đầu.

## Tương thích và migration

Không có migration database bắt buộc. SQLite queue, manifest, checkpoint, output và config từ các phiên bản trước vẫn được giữ nguyên. Manifest mới chỉ bổ sung thông tin report; không thay đổi stable item ID hoặc semantics resume.

Trước khi nâng cấp, nên sao lưu thư mục output, SQLite queue và checkpoint. Khi resume job cũ, giữ nguyên source video, output directory và cấu hình để `run_signature` tiếp tục khớp.

## Chất lượng và giới hạn

Force-fill bảo đảm số lượng khi có đủ candidate thực tế, nhưng không bảo đảm mọi ảnh fallback đạt các ngưỡng filter ban đầu. Ảnh fallback có thể mờ hơn, gần trùng hơn hoặc thuộc candidate đã bị loại vì motion blur. Nếu chất lượng quan trọng hơn số lượng, nên tắt fallback hoặc giảm độ nghiêm của filter trước khi chạy.

Nếu video quá ngắn, bị lỗi đọc, có ít frame hợp lệ hoặc output bị giới hạn bởi quyền ghi/disk, hệ thống không thể tạo đủ target count. Trong trường hợp đó `force_fill_shortfall` và `shortfall` vẫn phản ánh số thiếu thực tế.

## Kiểm thử

Bổ sung regression test mô phỏng 10 candidate đều bị filter loại và xác nhận 10 ảnh fallback được tạo, `forced_fallback_saved=10` và `force_fill_shortfall=0`. Full regression suite đạt 68 tests, compile check và `git diff --check` đạt.

## Ghi chú phát hành

Bản Windows cần được build lại từ source v0.1.33 để nhận behavior force-fill. Bản installer cũ không tự có thay đổi engine chỉ vì file config được giữ lại.
