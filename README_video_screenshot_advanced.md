# Video Screenshot Filter: CLI, Scene Detection và Web UI

Bộ công cụ gồm hai cách sử dụng: CLI nâng cao trong `video_screenshot_advanced.py` và giao diện Web Streamlit trong `streamlit_app.py`. Cả hai đều hỗ trợ lọc frame mờ và frame trùng trước khi lưu.

## Cài đặt

Cài [FFmpeg](https://ffmpeg.org/) và `ffprobe` trước. Trên Ubuntu hoặc Debian:

```bash
sudo apt update
sudo apt install ffmpeg
```

Cài các thư viện Python:

```bash
python3 -m pip install -r requirements_video_screenshot.txt
```

Nếu muốn dùng môi trường ảo:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements_video_screenshot.txt
```

## 1. Scene detection bằng CLI

Chế độ scene detection dùng bộ lọc scene của FFmpeg để tìm frame đầu tiên sau mỗi thay đổi cảnh. Frame đầu của vùng xử lý luôn được thêm vào, vì vậy cảnh đầu video không bị bỏ qua.

```bash
python3 video_screenshot_advanced.py video.mp4 \
  --scene-detection \
  --scene-threshold 0.30 \
  --min-scene-gap 0.5 \
  --output screenshots_by_scene
```

Xử lý nhiều video trong thư mục:

```bash
python3 video_screenshot_advanced.py ./videos \
  --recursive \
  --scene-detection \
  --scene-threshold 0.25 \
  --min-scene-gap 1.0 \
  --min-sharpness 100 \
  --duplicate-threshold 6 \
  --report screenshots_by_scene/report.json
```

Giới hạn scene detection vào một đoạn video:

```bash
python3 video_screenshot_advanced.py video.mp4 \
  --scene-detection --start 60 --end 600
```

### Điều chỉnh độ nhạy scene

`--scene-threshold` nhận giá trị từ `0` đến `1`. Giá trị thấp hơn nhạy hơn và có thể tạo nhiều mốc scene; giá trị cao hơn chỉ giữ những thay đổi rõ rệt. `--min-scene-gap` loại các mốc quá sát nhau.

| Tình huống | Thiết lập gợi ý |
|---|---|
| Video thông thường | `--scene-threshold 0.30 --min-scene-gap 0.5` |
| Muốn phát hiện cả thay đổi nhẹ | `--scene-threshold 0.15 --min-scene-gap 0.3` |
| Chỉ lấy các chuyển cảnh rõ | `--scene-threshold 0.45 --min-scene-gap 1.0` |
| Video có nhiều flash hoặc rung | Tăng threshold và tăng min gap. |

Scene detection chỉ chọn mốc thời gian; frame vẫn đi qua bộ lọc độ nét và trùng lặp sau đó.

## 2. Các chế độ CLI

Cắt theo khoảng thời gian cố định:

```bash
python3 video_screenshot_advanced.py video.mp4 --every 2
```

Cắt đúng số lượng frame:

```bash
python3 video_screenshot_advanced.py video.mp4 --count 50 --start 30 --end 600
```

Các bộ lọc:

```bash
python3 video_screenshot_advanced.py video.mp4 \
  --every 1 \
  --min-sharpness 100 \
  --duplicate-threshold 6 \
  --format jpg \
  --quality 95 \
  --width 1280
```

Đặt `--min-sharpness 0` để tắt lọc frame mờ. Đặt `--duplicate-threshold 0` để tắt lọc frame trùng. Báo cáo JSON với `--report` chứa số frame yêu cầu, số ảnh lưu, số frame bị loại vì mờ/trùng và số lỗi capture.

## 3. Chạy giao diện Web Streamlit

Khởi động ứng dụng:

```bash
streamlit run streamlit_app.py
```

Sau đó mở địa chỉ được Streamlit hiển thị, thường là `http://localhost:8501`.

Trong giao diện, người dùng có thể tải lên một hoặc nhiều video, chọn một trong ba chế độ **Tự động nhận diện phân cảnh**, **Mỗi N giây** hoặc **Đúng N frame**, rồi điều chỉnh ngưỡng scene, độ nét, dHash, định dạng và kích thước ảnh.

Sau khi nhấn **Bắt đầu xử lý**, ứng dụng hiển thị thống kê, xem trước tối đa 24 ảnh và cung cấp một file ZIP chứa toàn bộ screenshot cùng `report.json`.

## 4. Tham số chính

| Tham số | Mặc định | Mô tả |
|---|---:|---|
| `input` | bắt buộc | File video hoặc thư mục video. |
| `--scene-detection` | tắt | Chọn frame tại các thay đổi cảnh. Không dùng cùng `--every` hoặc `--count`. |
| `--scene-threshold` | `0.30` | Độ nhạy thay đổi cảnh, từ 0 đến 1. |
| `--min-scene-gap` | `0.5` | Khoảng cách tối thiểu giữa hai mốc scene, tính bằng giây. |
| `--every N` | `5` | Chọn một frame sau mỗi N giây. |
| `--count N` | không dùng | Chọn đúng N frame phân bố đều trong khoảng đã chọn. |
| `--start N` | `0` | Thời điểm bắt đầu, tính bằng giây. |
| `--end N` | cuối video | Thời điểm kết thúc, tính bằng giây. |
| `--min-sharpness N` | `100` | Ngưỡng độ nét Laplacian; giá trị thấp hơn bị loại. `0` để tắt. |
| `--duplicate-threshold N` | `6` | Khoảng cách dHash tối đa để xem là trùng. `0` để tắt. |
| `--format` | `jpg` | `jpg`, `png` hoặc `webp`. |
| `--quality` | `95` | Chất lượng JPG/WebP từ 1 đến 100. |
| `--width N` | giữ nguyên | Đổi chiều rộng ảnh và giữ tỷ lệ. |
| `--recursive` | tắt | Quét cả thư mục con. |
| `--overwrite` | tắt | Ghi đè ảnh đã tồn tại. |
| `--report FILE` | không ghi | Ghi thống kê dạng JSON. |

## 5. Gợi ý tinh chỉnh

Frame được lọc mờ bằng phương sai Laplacian và được lọc trùng bằng dHash 64-bit. Điểm độ nét phụ thuộc vào độ phân giải, độ nén và nội dung video, nên các giá trị mặc định là điểm bắt đầu chứ không phải ngưỡng tuyệt đối.

| Loại nội dung | Thiết lập gợi ý |
|---|---|
| Video nói chuyện, máy quay ổn định | `--min-sharpness 100 --duplicate-threshold 6` |
| Video hành động, lia máy nhanh | `--min-sharpness 40–80` |
| Slide hoặc cảnh tĩnh dài | `--duplicate-threshold 8–12` |
| Video độ phân giải thấp | `--min-sharpness 20–60` |
| Muốn giữ mọi frame | `--min-sharpness 0 --duplicate-threshold 0` |

## 6. File đầu ra

Tên ảnh có dạng:

```text
ten_video_00001_00-00-12.400.jpg
```

Khi xử lý một thư mục, mỗi video có thư mục riêng. Khi dùng `--recursive`, cấu trúc thư mục tương đối được giữ lại. Scene detection được ghi trong `report.json` với trường `selection_mode` có giá trị `scene_detection`.

## Tham khảo

1. [FFmpeg Documentation](https://ffmpeg.org/documentation.html)
2. [Streamlit Documentation](https://docs.streamlit.io/)
