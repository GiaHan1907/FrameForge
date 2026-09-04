#!/usr/bin/env python3
"""Nhe: quet cac file .md "live" tim tu khoa UI/version loi thoi.

Hai lop kiem tra, deu chi ap dung cho cac tai lieu mo ta trang thai hien tai
(README.md, HUONG_DAN_SU_DUNG.md, README_video_screenshot_advanced.md):

1. STALE_WORDINGS (blacklist) - cum tu sai/khong chuan da bi loai bo khoi UI
   (ten khu vuc cu, ten tab viet tat, ten nut cu...). Xuat hien lai la loi.
2. CANONICAL_LABELS (registry) - nhan UI dang dung (tab, nhom sidebar,
   expander, nut, che do). Moi nhan phai xuat hien >= 1 lan trong tong cac
   docs live; neu redesign doi ten, docs va registry phai doi cung luc.

Cac file ghi chu theo ban cu (RELEASE_NOTES_v0.1.x.md, UPDATE_GUIDE_*,
ROADMAP_*) va vung lich su trong RELEASE_NOTES.md khong nam trong danh sach
quet mac dinh vi chung la tai lieu luu tru co banner rieng.

== Cach them / doi pattern khi doi ten mot yeu to UI ==

1. Sua ten yeu to trong code (streamlit_app.py, ui/sidebar.py, ui/*.py).
2. Cap nhat CANONICAL_LABELS: dua nhan MOI vao, doi comment ghi vi tri code.
3. Them cum tu CU vao STALE_WORDINGS kem goi y nhan moi, de moi docs viet
   theo ten cu deu bi bat.
4. Quet toan repo tim ten cu con sot:  grep -rn "<ten cu>" *.md
   va cap nhat tung cho trong docs live.
5. Chay:  python check_docs_stale.py && python -m unittest tests.test_docs_stale

Nguyen tac tranh false positive: chi them pattern khi no co 0 lan xuat hien
trong docs live hien tai (hoac ban da sua het). Nhan canonical phai la chuoi
con khop chinh xac voi van ban docs, ke ca emoji va so thu tu nhom.

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
    # ── Tên tab ──────────────────────────────────────────────────────
    ("tab Xử lý video", "thiếu emoji - dùng '⚙️ Xử lý video'"),
    ("tab Tải video", "nhãn tab viết tắt - dùng '⬇️ Tải video công khai'"),
    ("tab Cài đặt", "nhãn tab viết tắt - dùng '📁 Cài đặt & Lịch sử'"),
    ("Trang tải video", "tên trang cũ - dùng tab '⬇️ Tải video công khai'"),
    ("Trang cài đặt", "tên trang cũ - dùng tab '📁 Cài đặt & Lịch sử'"),
    # ── Nhóm sidebar ─────────────────────────────────────────────────
    ("nhóm Nguồn video", "thiếu số thứ tự - dùng '01 · Nguồn video'"),
    ("nhóm Chọn frame", "thiếu số thứ tự - dùng '02 · Cách chọn frame'"),
    ("nhóm Chất lượng", "thiếu số thứ tự - dùng '03 · Chất lượng & tốc độ'"),
    ("nhóm Đầu ra", "thiếu số thứ tự - dùng '04 · Đầu ra'"),
    # ── Khu vực cũ ───────────────────────────────────────────────────
    ("khu vực Xem trước", "tên vùng cũ - preview nằm trong expander 'Xem video · crop · timeline'"),
    ("dùng layout hai tầng", "mô tả khu vực tải video cũ - tải video nằm trong tab '⬇️ Tải video công khai'"),
]


def scan_text(text: str, path: str) -> list[str]:
    findings: list[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for stale, hint in STALE_WORDINGS:
            if stale in line:
                findings.append(f"{path}:{line_no}: từ khoá lỗi thời '{stale}' - {hint}")
    return findings


# Nhan UI hien tai phai xuat hien >= 1 lan trong tong cac docs live.
# Khi doi ten trong code, cap nhat ca list nay lan docs (xem docstring).
CANONICAL_LABELS: list[tuple[str, str]] = [
    # Tabs - streamlit_app.py (st.tabs)
    ("⚙️ Xử lý video", "streamlit_app.py: st.tabs"),
    ("⬇️ Tải video công khai", "streamlit_app.py: st.tabs"),
    ("📁 Cài đặt & Lịch sử", "streamlit_app.py: st.tabs"),
    # Nhom sidebar - ui/sidebar.py (SectionHeading)
    ("01 · Nguồn video", "ui/sidebar.py"),
    ("02 · Cách chọn frame", "ui/sidebar.py"),
    ("03 · Chất lượng & tốc độ", "ui/sidebar.py"),
    ("04 · Đầu ra", "ui/sidebar.py"),
    # Expanders sidebar - ui/sidebar.py (Expander)
    ("Scene detection nâng cao", "ui/sidebar.py"),
    ("Hiệu năng phân tích", "ui/sidebar.py"),
    ("Lọc mờ · trùng lặp", "ui/sidebar.py"),
    ("Retry · cache · nâng cao", "ui/sidebar.py"),
    # Expanders khu vuc chinh
    ("📁 Thư mục lưu file", "streamlit_app.py: st.expander"),
    ("Xem video · crop · timeline", "ui/preview_section.py"),
    ("Preset cá nhân và cấu hình", "ui/timeline.py"),
    ("Lịch sử job", "ui/timeline.py"),
    # Nut chinh
    ("▶ Bắt đầu xử lý", "streamlit_app.py"),
    ("Tải queue", "ui/download_section.py"),
    ("Cập nhật ngay", "streamlit_app.py"),
    ("Phân tích nhanh scene thật", "ui/preview_section.py"),
    ("🔍 Tìm ảnh theo địa điểm", "streamlit_app.py: sidebar button"),
    ("Tìm kiếm", "ui/image_search_inline.py"),
    # Che do chon frame - ui/sidebar.py (Radio)
    ("Best frame per scene", "ui/sidebar.py"),
    ("Scene detection", "ui/sidebar.py"),
    ("Mỗi N giây", "ui/sidebar.py"),
    ("Đúng N frame", "ui/sidebar.py"),
    ("Chế độ xử lý", "ui/sidebar.py"),
    ("Queue có thể khôi phục", "streamlit_app.py"),
    ("Tiếp tục queue đã gián đoạn", "streamlit_app.py"),
    ("Áp dụng preset cá nhân", "ui/timeline.py"),
    ("Lưu preset hiện tại", "ui/timeline.py"),
    ("Cập nhật & kênh", "streamlit_app.py"),
]


def check_canonical(files: list[str], root: Path = ROOT) -> list[str]:
    """Moi nhan canonical phai xuat hien >= 1 lan trong tong cac file."""
    combined = []
    for name in files:
        path = root / name
        if path.exists():
            combined.append(path.read_text(encoding="utf-8"))
    blob = chr(10).join(combined)
    findings: list[str] = []
    for label, source in CANONICAL_LABELS:
        if label not in blob:
            findings.append(
                f"CANONICAL: nhãn UI '{label}' ({source}) không xuất hiện trong docs live "
                "- nếu vừa đổi tên UI, cập nhật CANONICAL_LABELS và docs."
            )
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

    stale = scan_files(args.files)
    canonical = check_canonical(args.files)
    for finding in stale + canonical:
        print(f"  {finding}")
    if stale or canonical:
        print(f"FAILED: {len(stale)} từ khoá lỗi thời, {len(canonical)} nhãn canonical thiếu - "
              "cập nhật docs và/hoặc CANONICAL_LABELS cho khớp UI hiện tại.")
        return 1
    print(f"OK: {len(args.files)} docs live sạch từ khoá lỗi thời, "
          f"{len(CANONICAL_LABELS)} nhãn canonical đều xuất hiện.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
