from __future__ import annotations

import argparse
import json
from pathlib import Path


def size_bytes(path: Path) -> int:
    if path.is_symlink():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    if path.is_dir():
        total = 0
        for item in path.rglob("*"):
            if item.is_file() and not item.is_symlink():
                try:
                    total += item.stat().st_size
                except OSError:
                    pass
        return total
    return 0


def human(value: int) -> str:
    number = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if number < 1024 or unit == "GiB":
            return f"{number:.2f} {unit}"
        number /= 1024
    return f"{value} B"


def largest_entries(root: Path, limit: int) -> list[dict[str, object]]:
    if not root.exists():
        return []
    entries = []
    for child in root.iterdir():
        value = size_bytes(child)
        if value:
            entries.append({"path": str(child), "bytes": value, "human": human(value)})
    return sorted(entries, key=lambda item: int(item["bytes"]), reverse=True)[:limit]


def largest_files(root: Path, limit: int) -> list[dict[str, object]]:
    if not root.exists():
        return []
    entries = []
    for item in root.rglob("*"):
        if item.is_file() and not item.is_symlink():
            try:
                value = item.stat().st_size
            except OSError:
                continue
            entries.append({"path": str(item), "bytes": value, "human": human(value)})
    return sorted(entries, key=lambda item: int(item["bytes"]), reverse=True)[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description="Đo dung lượng package và PyInstaller artifact.")
    parser.add_argument("root", nargs="?", default=".", help="Thư mục package.")
    parser.add_argument("--dist-path", help="Đường dẫn dist cụ thể cần đo; mặc định là root/dist.")
    parser.add_argument("--top", type=int, default=20, help="Số mục lớn nhất in trong báo cáo chi tiết.")
    parser.add_argument("--json", dest="json_path", help="Ghi kết quả ra JSON.")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    dist_path = Path(args.dist_path).resolve() if args.dist_path else root / "dist"
    paths = {
        "vendor_ffmpeg": root / "vendor" / "ffmpeg",
        "python_sources": root,
        "pyinstaller_dist": dist_path,
        "pyinstaller_build": root / "build",
        "release_zip": root.with_suffix(".zip"),
    }
    records = []
    for name, path in paths.items():
        value = size_bytes(path)
        records.append({"name": name, "path": str(path), "bytes": value, "human": human(value), "exists": path.exists()})
    for item in sorted(records, key=lambda record: int(record["bytes"]), reverse=True):
        print(f"{item['name']:22} {item['human']:>12}  {item['path']}")

    runtime_total = size_bytes(dist_path)
    print(f"{'runtime_dist_total':22} {human(runtime_total):>12}  {dist_path}")
    print("\nLargest direct entries in runtime dist:")
    for item in largest_entries(dist_path, max(0, args.top)):
        print(f"  {item['human']:>12}  {item['path']}")
    print("\nLargest files in runtime dist:")
    for item in largest_files(dist_path, max(0, args.top)):
        print(f"  {item['human']:>12}  {item['path']}")

    symlink_count = sum(1 for item in dist_path.rglob("*") if item.is_symlink()) if dist_path.exists() else 0
    payload = {
        "root": str(root),
        "symlink_count_in_runtime_dist": symlink_count,
        "records": records,
        "runtime_dist_total_bytes": runtime_total,
        "runtime_dist_total_human": human(runtime_total),
        "largest_direct_entries": largest_entries(dist_path, max(0, args.top)),
        "largest_files": largest_files(dist_path, max(0, args.top)),
    }
    if args.json_path:
        json_path = Path(args.json_path)
        if not json_path.is_absolute():
            json_path = root / json_path
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
