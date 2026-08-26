from __future__ import annotations

from pathlib import Path
from typing import Iterable


def build_timeline_entries(reports: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    """Chuẩn hóa scene markers và frame đại diện thành dữ liệu timeline."""
    entries: list[dict[str, object]] = []
    for report in reports:
        video_name = Path(str(report.get("video", "video"))).name
        raw_selected = report.get("selected_times", [])
        selected_times = [float(item) for item in raw_selected] if isinstance(raw_selected, list) else []
        raw_scene = report.get("scene_times", [])
        scene_times = [float(item) for item in raw_scene] if isinstance(raw_scene, list) and raw_scene else selected_times
        for scene_number, timestamp in enumerate(scene_times, start=1):
            representative = min(selected_times, key=lambda value: abs(value - timestamp)) if selected_times else timestamp
            entries.append(
                {
                    "video": video_name,
                    "scene": scene_number,
                    "time_seconds": round(timestamp, 3),
                    "representative_seconds": round(representative, 3),
                    "cache_hit": bool(report.get("cache_hit", False)),
                }
            )
    return entries


def filter_timeline_entries(
    entries: Iterable[dict[str, object]],
    video_name: str = "Tất cả",
    query: str = "",
    min_seconds: float = 0.0,
    max_seconds: float | None = None,
) -> list[dict[str, object]]:
    """Lọc marker theo video, từ khóa và khoảng timestamp."""
    normalized_query = query.strip().casefold()
    low = max(0.0, float(min_seconds))
    high = float(max_seconds) if max_seconds is not None else float("inf")
    filtered: list[dict[str, object]] = []
    for entry in entries:
        entry_video = str(entry.get("video", ""))
        timestamp = float(entry.get("time_seconds", 0.0))
        haystack = f"{entry_video} scene {entry.get('scene', '')}".casefold()
        if video_name != "Tất cả" and entry_video != video_name:
            continue
        if normalized_query and normalized_query not in haystack:
            continue
        if timestamp < low or timestamp > high:
            continue
        filtered.append(entry)
    return filtered
