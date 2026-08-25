from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def human(value: int) -> str:
    number = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if number < 1024 or unit == "GiB":
            return f"{number:.2f} {unit}"
        number /= 1024
    return f"{value} B"


def category(path: Path, root: Path) -> str:
    rel = path.relative_to(root).as_posix()
    name = path.name.lower()
    suffix = path.suffix.lower()
    if rel == "VideoScreenshotFilter" or path.name == "VideoScreenshotFilter":
        return "pyinstaller_bootloader_executable"
    if suffix in {".so", ".dll", ".dylib", ".pyd"}:
        return "native_binary_or_shared_library"
    if suffix in {".js", ".map", ".css", ".html", ".svg", ".woff", ".woff2", ".ttf"} or "/static/" in f"/{rel.lower()}":
        return "frontend_static_asset"
    if suffix in {".py", ".pyc", ".pyo", ".zip"} or "/python" in f"/{rel.lower()}":
        return "python_bytecode_or_archive"
    if suffix in {".json", ".txt", ".md", ".toml", ".yaml", ".yml", ".ini", ".pem", ".crt"}:
        return "metadata_or_text"
    if suffix in {".a", ".lib", ".dat", ".bin"}:
        return "data_or_archive"
    if name.endswith(".exe"):
        return "native_executable"
    return "other"


def analyze(root: Path, limit: int) -> dict[str, object]:
    totals: dict[str, int] = defaultdict(int)
    files: list[tuple[int, Path, str]] = []
    for item in root.rglob("*"):
        if not item.is_file() or item.is_symlink():
            continue
        value = item.stat().st_size
        kind = category(item, root)
        totals[kind] += value
        files.append((value, item, kind))
    files.sort(reverse=True, key=lambda row: row[0])
    print(f"root={root}")
    print(f"total={human(sum(totals.values()))}")
    print("categories:")
    for kind, value in sorted(totals.items(), key=lambda row: row[1], reverse=True):
        print(f"  {kind:36} {human(value):>12} {value}")
    print("largest_files:")
    for value, path, kind in files[:limit]:
        print(f"  {human(value):>12} {kind:36} {path.relative_to(root)}")
    return {
        "root": str(root),
        "total_bytes": sum(totals.values()),
        "categories": {key: value for key, value in totals.items()},
        "largest_files": [
            {"path": str(path.relative_to(root)), "bytes": value, "category": kind}
            for value, path, kind in files[:limit]
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    payload = {str(root): analyze(root.resolve(), args.top) for root in args.roots}
    if args.json:
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
