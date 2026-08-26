from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

try:
    import yt_dlp
except ImportError as exc:  # pragma: no cover - friendly runtime message
    yt_dlp = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


SUPPORTED_HOSTS = {
    "facebook.com",
    "fb.watch",
    "tiktok.com",
    "pinterest.com",
    "pin.it",
}

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".ts"}

QUALITY_FORMATS = {
    "Tốt nhất": "bv*+ba/b",
    "1080p hoặc thấp hơn": "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b",
    "720p hoặc thấp hơn": "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b",
    "480p hoặc thấp hơn": "bv*[height<=480]+ba/b[height<=480]/bv*+ba/b",
}


@dataclass
class DownloadResult:
    path: Path
    title: str
    webpage_url: str
    extractor: str
    height: int | None
    duration: float | None
    filesize: int | None
    playlist_index: int | None = None


@dataclass(frozen=True)
class DownloadErrorInfo:
    code: str
    label: str
    retryable: bool
    suggestion: str


@dataclass
class DownloadFailure(RuntimeError):
    url: str
    code: str
    label: str
    retryable: bool
    attempts: int
    message: str
    suggestion: str

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.__str__())

    def __str__(self) -> str:
        detail = self.message.strip() or "Không có thông tin chi tiết từ yt-dlp."
        return (
            f"[{self.code}] {self.label}: {self.url}\\n"
            f"Đã thử {self.attempts} lần. {detail}\\n"
            f"Gợi ý: {self.suggestion}"
        )


_ERROR_RULES: tuple[tuple[str, tuple[str, ...], str, bool, str], ...] = (
    (
        "access_denied",
        ("login required", "sign in", "private", "not available in your country", "http error 401", "http error 403", "forbidden"),
        "URL yêu cầu đăng nhập hoặc không truy cập được",
        False,
        "Kiểm tra URL còn công khai và bạn có quyền sử dụng nội dung; FrameForge không hỗ trợ cookie hoặc bypass đăng nhập.",
    ),
    (
        "rate_limited",
        ("too many requests", "rate limit", "http error 429", "temporarily blocked", "captcha"),
        "Nguồn đang giới hạn tần suất truy cập",
        True,
        "Chờ một lúc rồi thử lại với số URL nhỏ hơn; không tăng retry quá cao.",
    ),
    (
        "ffmpeg_missing",
        ("ffmpeg", "ffprobe", "merging", "postprocess"),
        "Thiếu FFmpeg để ghép video/audio",
        False,
        "Cài bản FrameForge có FFmpeg nhúng hoặc thêm ffmpeg.exe vào PATH.",
    ),
    (
        "format_unavailable",
        ("requested format is not available", "no video formats found", "format not available", "unable to extract", "no suitable format"),
        "Không tìm thấy format video phù hợp",
        False,
        "Thử chất lượng thấp hơn hoặc kiểm tra Reel còn công khai; một số nội dung không cung cấp format cho yt-dlp.",
    ),
    (
        "output_error",
        ("permission denied", "access is denied", "no space left", "disk full", "cannot create", "could not write", "không tạo được file video"),
        "Không ghi được file đầu ra",
        False,
        "Kiểm tra thư mục lưu, quyền ghi và dung lượng ổ đĩa.",
    ),
    (
        "network_error",
        ("timed out", "timeout", "connection reset", "connection refused", "temporary failure", "unable to download", "http error 5", "network"),
        "Lỗi mạng hoặc nguồn tạm thời không phản hồi",
        True,
        "Kiểm tra kết nối mạng; FrameForge sẽ tự retry với thời gian chờ tăng dần.",
    ),
)


def classify_download_error(exc: BaseException, ffmpeg_available: bool = True) -> DownloadErrorInfo:
    """Phân loại lỗi yt-dlp thành nhóm có thể retry hoặc cần người dùng xử lý."""
    message = str(exc or "").lower()
    if not ffmpeg_available and any(token in message for token in ("ffmpeg", "ffprobe", "merging", "postprocess")):
        return DownloadErrorInfo(
            "ffmpeg_missing",
            "Thiếu FFmpeg để ghép video/audio",
            False,
            "Cài bản FrameForge có FFmpeg nhúng hoặc thêm ffmpeg.exe vào PATH.",
        )
    for code, tokens, label, retryable, suggestion in _ERROR_RULES:
        if code == "ffmpeg_missing" and ffmpeg_available:
            continue
        if any(token in message for token in tokens):
            return DownloadErrorInfo(code, label, retryable, suggestion)
    return DownloadErrorInfo(
        "unknown",
        "Lỗi downloader chưa xác định",
        True,
        "Kiểm tra URL và kết nối mạng; xem chi tiết lỗi rồi thử lại nếu lỗi có tính tạm thời.",
    )


def _download_failure(
    url: str,
    exc: BaseException,
    attempts: int,
    ffmpeg_available: bool,
) -> DownloadFailure:
    info = classify_download_error(exc, ffmpeg_available=ffmpeg_available)
    return DownloadFailure(
        url=url,
        code=info.code,
        label=info.label,
        retryable=info.retryable,
        attempts=max(1, int(attempts)),
        message=str(exc),
        suggestion=info.suggestion,
    )


def _normalized_host(url: str) -> str:
    parsed = urlparse(url.strip())
    return (parsed.hostname or "").lower().removeprefix("www.")


def is_supported_public_url(url: str) -> bool:
    """Chỉ kiểm tra host/scheme; quyền truy cập và quyền sử dụng thuộc về người dùng."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = _normalized_host(url)
    return any(host == domain or host.endswith("." + domain) for domain in SUPPORTED_HOSTS)


def validate_public_url(url: str) -> None:
    if not is_supported_public_url(url):
        raise ValueError(
            "Chỉ hỗ trợ URL http(s) công khai từ Facebook, TikTok hoặc Pinterest. "
            "Không hỗ trợ URL riêng tư, URL yêu cầu đăng nhập hoặc URL vượt cơ chế bảo vệ."
        )


def _candidate_ffmpeg_dirs() -> list[Path]:
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(str(meipass)))
    roots.append(Path(__file__).resolve().parent)
    roots.append(Path.cwd())
    candidates: list[Path] = []
    for root in roots:
        candidates.extend(
            [
                root / "vendor" / "ffmpeg",
                root / "ffmpeg",
                root,
            ]
        )
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def embedded_ffmpeg_paths() -> tuple[str | None, str | None]:
    """Tìm binary nhúng trước, sau đó caller mới fallback về PATH."""
    suffix = ".exe" if sys.platform == "win32" else ""
    for directory in _candidate_ffmpeg_dirs():
        ffmpeg_path = directory / f"ffmpeg{suffix}"
        ffprobe_path = directory / f"ffprobe{suffix}"
        if ffmpeg_path.exists():
            return str(ffmpeg_path), str(ffprobe_path) if ffprobe_path.exists() else None
    return None, None


def ffmpeg_health() -> dict[str, object]:
    """Trả về trạng thái FFmpeg/ffprobe nhúng hoặc cài trong PATH."""
    embedded_ffmpeg, embedded_ffprobe = embedded_ffmpeg_paths()
    ffmpeg_path = embedded_ffmpeg or shutil.which("ffmpeg")
    ffprobe_path = embedded_ffprobe or shutil.which("ffprobe")
    result: dict[str, object] = {
        "ffmpeg_installed": bool(ffmpeg_path),
        "ffprobe_installed": bool(ffprobe_path),
        "ffmpeg_path": ffmpeg_path,
        "ffprobe_path": ffprobe_path,
        "version": None,
        "ready_for_merge": bool(ffmpeg_path),
        "source": "embedded" if embedded_ffmpeg else ("PATH" if ffmpeg_path else None),
        "message": "FFmpeg nhúng đã sẵn sàng để ghép video/audio." if embedded_ffmpeg else ("FFmpeg trong PATH đã sẵn sàng để ghép video/audio." if ffmpeg_path else "Chưa tìm thấy FFmpeg nhúng hoặc trong PATH."),
    }
    if ffmpeg_path:
        try:
            completed = subprocess.run(
                [ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            first_line = (completed.stdout or completed.stderr).splitlines()
            result["version"] = first_line[0] if first_line else None
        except (OSError, subprocess.SubprocessError) as exc:
            result["message"] = f"Tìm thấy FFmpeg nhưng không chạy được: {exc}"
            result["ready_for_merge"] = False
    return result


def _file_snapshot(output_dir: Path) -> dict[Path, int]:
    return {
        path: path.stat().st_mtime_ns
        for path in output_dir.iterdir()
        if path.is_file()
    }


def _new_video_files(output_dir: Path, before: dict[Path, int]) -> list[Path]:
    candidates = []
    for path in output_dir.iterdir():
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        if path not in before or path.stat().st_mtime_ns != before[path]:
            candidates.append(path)
    # Nếu FFmpeg để lại nhiều biến thể cùng stem, ưu tiên file MP4 đã ghép.
    grouped: dict[str, list[Path]] = {}
    for path in candidates:
        grouped.setdefault(path.stem, []).append(path)
    selected = []
    for paths in grouped.values():
        selected.append(
            next((item for item in paths if item.suffix.lower() == ".mp4"), max(paths, key=lambda item: item.stat().st_mtime_ns))
        )
    return sorted(selected, key=lambda item: item.stat().st_mtime_ns)


def _entry_for_path(path: Path, entries: list[dict[str, object]]) -> dict[str, object]:
    for entry in entries:
        entry_id = str(entry.get("id") or "")
        if entry_id and entry_id in path.name:
            return entry
    return entries[0] if entries else {}


def _timestamped_video_path(output_dir: Path, stamp: str, sequence: int, suffix: str) -> Path:
    """Create a compact timestamp filename without overwriting another download."""
    normalized_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    stem = f"video_{stamp}" if sequence == 1 else f"video_{stamp}_{sequence:02d}"
    candidate = output_dir / f"{stem}{normalized_suffix}"
    collision = 1
    while candidate.exists():
        candidate = output_dir / f"{stem}_{collision:02d}{normalized_suffix}"
        collision += 1
    return candidate


def _rename_downloaded_files(
    paths: list[Path], output_dir: Path, downloaded_at: str
) -> list[Path]:
    renamed: list[Path] = []
    for sequence, path in enumerate(paths, start=1):
        target = _timestamped_video_path(output_dir, downloaded_at, sequence, path.suffix.lower())
        if path.resolve() != target.resolve():
            path.replace(target)
        renamed.append(target)
    return renamed


def _download_batch(
    urls: list[str],
    output_dir: Path,
    quality: str,
    max_items: int | None = None,
    progress_hook=None,
    max_retries: int = 2,
    retry_delay_seconds: float = 1.0,
    error_hook=None,
) -> list[DownloadResult]:
    if yt_dlp is None:
        raise RuntimeError("Chưa cài yt-dlp. Hãy chạy: python -m pip install yt-dlp") from _IMPORT_ERROR
    if quality not in QUALITY_FORMATS:
        raise ValueError(f"Chất lượng không hợp lệ: {quality}")
    if not urls:
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    health = ffmpeg_health()
    base_template = "%(extractor)s_%(id)s_%(title).120s.%(ext)s"
    options: dict[str, object] = {
        "format": QUALITY_FORMATS[quality],
        "outtmpl": str(output_dir / base_template),
        "noplaylist": False,
        "restrictfilenames": True,
        "quiet": True,
        "no_warnings": True,
        "nopart": True,
        "merge_output_format": "mp4",
        "progress_hooks": [progress_hook or (lambda _data: None)],
    }
    if max_items and max_items > 0:
        options["playlistend"] = int(max_items)
    if health["ffmpeg_path"]:
        options["ffmpeg_location"] = str(Path(str(health["ffmpeg_path"])).parent)

    all_results: list[DownloadResult] = []
    retry_limit = max(0, int(max_retries))
    base_retry_delay = max(0.0, float(retry_delay_seconds))
    max_retry_delay = 60.0
    for url in urls:
        validate_public_url(url)
        last_error: DownloadFailure | None = None
        for attempt in range(retry_limit + 1):
            # Dùng staging riêng cho từng URL/lần thử. Nếu file cùng ID đã tồn tại ở
            # output_dir, yt-dlp có thể coi đó là download hoàn tất và không tạo file
            # mới; khi đó cách snapshot cũ dễ báo lỗi giả "không tạo được output".
            staging_dir = Path(tempfile.mkdtemp(prefix=".frameforge_download_", dir=str(output_dir)))
            attempt_options = dict(options)
            attempt_options["outtmpl"] = str(staging_dir / base_template)
            try:
                with yt_dlp.YoutubeDL(attempt_options) as downloader:
                    info = downloader.extract_info(url, download=True)
                    raw_entries = info.get("entries") if isinstance(info, dict) else None
                    entries = [item for item in (raw_entries or []) if isinstance(item, dict)] if raw_entries else [info]
                    new_files = _new_video_files(staging_dir, {})
                    if not new_files:
                        raise FileNotFoundError("yt-dlp không tạo được file video đầu ra trong staging.")
                    matched_entries = [_entry_for_path(path, entries) for path in new_files]
                    downloaded_at = datetime.now().strftime("%Y%m%d_%H%M%S")
                    new_files = _rename_downloaded_files(new_files, output_dir, downloaded_at)
                    for path, entry in zip(new_files, matched_entries):
                        all_results.append(
                            DownloadResult(
                                path=path,
                                title=str(entry.get("title") or path.stem),
                                webpage_url=str(entry.get("webpage_url") or url),
                                extractor=str(entry.get("extractor_key") or entry.get("extractor") or "unknown"),
                                height=int(entry["height"]) if entry.get("height") else None,
                                duration=float(entry["duration"]) if entry.get("duration") else None,
                                filesize=path.stat().st_size if path.exists() else None,
                                playlist_index=int(entry["playlist_index"]) if entry.get("playlist_index") else None,
                            )
                        )
                last_error = None
                break
            except Exception as exc:
                last_error = _download_failure(
                    url,
                    exc,
                    attempts=attempt + 1,
                    ffmpeg_available=bool(health["ffmpeg_path"]),
                )
                if attempt >= retry_limit or not last_error.retryable:
                    break
                delay = min(max_retry_delay, base_retry_delay * (2**attempt))
                if progress_hook is not None:
                    progress_hook(
                        {
                            "status": "retrying",
                            "url": url,
                            "attempt": attempt + 1,
                            "next_attempt": attempt + 2,
                            "total_attempts": retry_limit + 1,
                            "retry_delay": delay,
                            "error_code": last_error.code,
                            "error": str(last_error),
                        }
                    )
                if delay > 0:
                    time.sleep(delay)
            finally:
                shutil.rmtree(staging_dir, ignore_errors=True)
        if last_error is not None:
            if error_hook is not None:
                error_hook(last_error)
                continue
            raise last_error
    return all_results


def download_public_video(
    url: str,
    output_dir: Path,
    quality: str = "Tốt nhất",
    progress_hook=None,
) -> DownloadResult:
    """Tải một video công khai, không mở playlist ngoài ý muốn."""
    results = _download_batch([url], output_dir, quality, max_items=1, progress_hook=progress_hook)
    if not results:
        raise FileNotFoundError("Không có video nào được tải.")
    return results[0]


def download_public_videos(
    urls: list[str],
    output_dir: Path,
    quality: str = "Tốt nhất",
    max_playlist_items: int | None = 50,
    max_queue_items: int = 100,
    progress_hook=None,
    max_retries: int = 2,
    retry_delay_seconds: float = 1.0,
    error_hook=None,
) -> list[DownloadResult]:
    """Tải tuần tự queue URL; mỗi playlist bị giới hạn max_playlist_items mục."""
    clean_urls = [url.strip() for url in urls if url and url.strip()]
    clean_urls = clean_urls[:max(1, int(max_queue_items))]
    return _download_batch(
        clean_urls,
        output_dir,
        quality,
        max_items=max_playlist_items,
        progress_hook=progress_hook,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay_seconds,
        error_hook=error_hook,
    )


def result_summary(result: DownloadResult) -> str:
    height = f"{result.height}p" if result.height else "độ phân giải không rõ"
    duration = f"{result.duration:.1f}s" if result.duration else "thời lượng không rõ"
    size = "không rõ"
    if result.filesize:
        value = float(result.filesize)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                size = f"{value:.1f} {unit}"
                break
            value /= 1024
    return f"{result.title} · {height} · {duration} · {size}"
