#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Pipeline tối ưu dùng OpenCV đọc video một lần; FFmpeg/ffprobe là tùy chọn.
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Lưu ý: không tìm thấy FFmpeg; ứng dụng vẫn chạy bằng OpenCV nếu codec được hỗ trợ."
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
exec streamlit run streamlit_app.py
