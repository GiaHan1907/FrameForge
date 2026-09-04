# Video Screenshot Filter: CLI, Scene Detection và Web UI

Bộ công cụ gồm hai cách sử dụng: CLI nâng cao và giao diện Web Streamlit trong `streamlit_app.py`. Cả hai đều hỗ trợ lọc frame mờ và frame trùng trước khi lưu.

### Cấu trúc code hiện tại (từ v0.1.35)

`video_screenshot_advanced.py` vẫn là entry engine đầy đủ (queue, checkpoint, report, worker), nhưng phần lớn logic thuần đã được tách sang `core/` để kiểm thử độc lập:

- `core/cli.py` — `parse_args()`/`build_config()` và entry headless mới `python -m core.cli <video> ...` (cùng tập flag ở dưới, không cần Streamlit).
- `core/analysis.py` — phân tích frame/scene bằng cv2: `normalized_difference`, `histogram_difference`, `smart_scene_difference`, `better_frame`, `crop_to_aspect_ratio`, `FrameCandidate`, `probe_video`.
- `core/cv2_helpers.py` — `laplacian_variance`, `motion_blur_score`, `dhash`, `hamming_distance`.
- `core/pipeline.py` + `checkpoint.py`, `workers.py`, `cleanup.py`, `targets.py` — cache scene, checkpoint/resume, adaptive workers, dọn dẹp và sinh candidate/target.
- `core/config.py` (dataclass `FrameForgeConfig`), `core/utils.py`, `core/errors.py`, `core/manifest.py`, `core/resources.py`.

Chạy CLI theo cách cũ `python video_screenshot_advanced.py ...` vẫn hoạt động như trước.

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

Chế độ scene detection **không dùng bộ lọc scene của FFmpeg**: engine tự phân tích frame bằng OpenCV (trong `core/analysis.py`), kết hợp sai khác pixel trung bình (`normalized_difference`) với sai khác histogram màu (`histogram_difference`) qua `smart_scene_difference`. Một mốc chỉ được ghi nhận khi frame đủ sắc nét, đạt `--min-scene-gap` và được xác nhận bởi `--scene-confirmations` frame liên tiếp (chống flash/nhiễu). Frame đầu của vùng xử lý luôn được thêm vào, vì vậy cảnh đầu video không bị bỏ qua.

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

Trong giao diện (bố cục v0.1.39), toàn bộ cấu hình nằm ở **sidebar** chia 4 nhóm khớp wizard: `01 · Nguồn video` (upload nhiều video mp4/mov/mkv/avi/webm/m4v/ts/mts), `02 · Cách chọn frame`, `03 · Chất lượng & tốc độ`, `04 · Đầu ra`. Nội dung chính gồm 3 tab: **⚙️ Xử lý video** (wizard 4 bước + 4 card tóm tắt + nút **Bắt đầu xử lý** + preview workspace), **⬇️ Tải video công khai** (yt-dlp) và **📁 Cài đặt & Lịch sử** (cập nhật, preset cá nhân, lịch sử job). Có bốn chế độ chọn frame: **Best frame per scene**, **Scene detection**, **Mỗi N giây** và **Đúng N frame**; ngưỡng scene, độ nét, dHash, motion blur, định dạng và kích thước ảnh đều chỉnh được trong sidebar (một số trường nâng cao nằm trong các expander thu gọn).

Sau khi bấm **Bắt đầu xử lý**, tab ⚙️ Xử lý video hiển thị progress theo từng video (FPS/ETA/RAM, tạm dừng/tiếp tục/hủy/retry); khi hoàn tất có nút tải file ZIP chứa toàn bộ screenshot cùng `report.json` (giao diện chỉ xem trước một phần ảnh). Hướng dẫn từng màn hình chi tiết tại [HUONG_DAN_SU_DUNG.md](HUONG_DAN_SU_DUNG.md).

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

Tên ảnh được đặt theo thời điểm frame, dạng `HH-MM-SS.mmm.jpg` (hoặc `.png`/`.webp` theo `--format`), ví dụ:

```text
00-00-12.400.jpg
```

Khi bật ép đủ số ảnh sau filter (`--target-count-after-filter`) mà timestamp đã có file trong thư mục output và chưa bật `--overwrite`, ảnh fallback được thêm hậu tố dạng `_fallback_0001_1` để không ghi đè output cũ. Các video được xử lý độc lập và tổng hợp trong `report.json`; trường `selection_mode` cho biết chế độ đã dùng (`scene_detection`, `best_frame_per_scene`, `fixed_interval` hoặc `count`).

## Tham khảo

1. [FFmpeg Documentation](https://ffmpeg.org/documentation.html)
2. [Streamlit Documentation](https://docs.streamlit.io/)
