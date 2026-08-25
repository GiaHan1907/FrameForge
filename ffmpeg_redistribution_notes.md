
## Bổ sung nguồn Windows

Trang releases của BtbN/FFmpeg-Builds hiện liệt kê các gói Windows x86_64 `lgpl` và `lgpl-shared`, cùng các gói `gpl`; package nên chọn một bản LGPL phù hợp nếu muốn hạn chế phạm vi giấy phép, sau khi kiểm tra cấu hình codec thực tế. Bản static chứa executable tự đủ hơn bản shared; bản shared có thêm DLL và cần xử lý dependency DLL khi chạy.

Nguồn xem xét: https://github.com/BtbN/FFmpeg-Builds/releases

Không nên tự động tải binary không ghim version vào build sản phẩm. Nên ghim release/tag, kiểm tra checksum, lưu source/configure/license tương ứng trong package và xác nhận điều kiện phân phối trước khi phát hành.
