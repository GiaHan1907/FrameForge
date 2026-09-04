#!/usr/bin/env python3
"""Nhe: quet cac file .md "live" tim tu khoa UI/version loi thoi.

Chan cac mo ta giao dien cu (truoc v0.1.38/v0.1.39: 3 tab, sidebar 4 nhom,
expander thu gon) quay lai trong cac tai lieu mo ta trang thai hien tai:
README.md, HUONG_DAN_SU_DUNG.md, README_video_screenshot_advanced.md.

Cac file ghi chu theo ban cu (RELEASE_NOTES_v0.1.x.md, UPDATE_GUIDE_*,
ROADMAP_*) va vung lich su trong RELEASE_NOTES.md khong nam trong danh sach
quet mac dinh vi chung la tai lieu luu tru co banner rieng.

Cach dung:
    python check_docs_stale.py                  # quet danh sach live mac dinh
    python check_docs_stale.py --files a.md b.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_FILES = [
    "README.md",
    "HUONG_DAN_SU_DUNG.md",
    "README_video_screenshot_advanced.md",
]

# (tu khoa loi thoi, goi y noi dung thay the / cach sua)
STALE_WORDINGS: list[tuple[str, str]] = [
    ("Xem trước video", "khu vực preview cũ - dùng dropdown 'Chọn video để xem preview' + expander 'Xem video · crop · timeline'"),
    ("Tự động nhận diện phân cảnh", "tên chế độ cũ - hiện là 'Scene detection'"),
    ("bộ lọc scene của FFmpeg để tìm", "sai kỹ thuật: scene do engine OpenCV (core/analysis.py) phát hiện, không dùng FFmpeg filter"),
    ("ten_video_00001", "mẫu tên file cũ - tên ảnh hiện dạng HH-MM-SS.mmm.ext"),
    ("FrameForge-Setup-1.0.0.exe", "tên Setup cứng cũ - dùng FRAMEFORGE_VERSION hoặc MyAppVersion trong FrameForge.iss"),
    ("FrameForge-Setup-0.1.34", "version mặc định cũ của FrameForge.iss (hiện 0.1.39)"),
    ("Chọn thư mục video", "nút cũ - hiện là ô 'Thư mục lưu video' + nút 'Chọn…'"),
    ("Chọn thư mục screenshot", "nút cũ - hiện là ô 'Thư mục gốc lưu screenshot' + nút 'Chọn…'"),
    ("Nơi lưu file", "tên cũ - hiện là expander '📁 Thư mục lưu file'"),
    ("Xem trước tối đa 24 ảnh", "số ảnh xem trước cũ - nội dung ZIP đầy đủ ở nút tải trong kết quả job"),
    ("compare/v0.1.34", "link compare cũ trong CHANGELOG - dùng v0.1.39...HEAD"),
    ("0.1.35 được ghi", "mục Unreleased cũ của CHANGELOG"),
    ("giao diện hiển thị một nút", "mô tả update cũ - nút nằm trong tab 'Cài đặt & Lịch sử'"),
]


def scan_text(text: str, path: str) -> list[str]:
    findings: list[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for stale, hint in STALE_WORDINGS:
            if stale in line:
                findings.append(f"{path}:{line_no}: từ khoá lỗi thời '{stale}' - {hint}")
    return findings


def scan_files(files: list[str], root: Path = ROOT) -> list[str]:
    findings: list[str] = []
    for name in files:
        path = root / name
        if not path.exists():
            findings.append(f"{name}: FILE NOT FOUND")
            continue
        findings.extend(scan_text(path.read_text(encoding="utf-8"), name))
    return findings


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Quét docs .md live tìm từ khoá UI/version lỗi thời")
    parser.add_argument("--files", nargs="*", default=DEFAULT_FILES,
                        help="Danh sách file .md cần quét (mặc định: docs live)")
    args = parser.parse_args(argv)

    findings = scan_files(args.files)
    for finding in findings:
        print(f"  {finding}")
    if findings:
        print(f"FAILED: {len(findings)} từ khoá lỗi thời trong docs live - cập nhật lại mô tả cho khớp UI hiện tại.")
        return 1
    print(f"OK: {len(args.files)} docs live không chứa từ khoá UI/version lỗi thời.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
