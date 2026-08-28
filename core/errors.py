"""Unified error classification for FrameForge.

Consolidates ErrorInfo (queue_per_video.py) and DownloadErrorInfo
(video_downloader.py) with merged _ERROR_RULES so every error category
is defined in one place.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorInfo:
    """Phân loại lỗi thành mã ổn định cho UI."""

    code: str
    label: str
    retryable: bool
    suggestion: str


# Superset of tokens from both queue_per_video and video_downloader.
# Ordered by specificity — first match wins.
_ERROR_RULES: tuple[tuple[str, tuple[str, ...], str, bool, str], ...] = (
    (
        "access_denied",
        (
            "login required", "login", "sign in", "private",
            "not available in your country", "forbidden",
            "http error 401", "http error 403",
            "403",
        ),
        "URL yêu cầu đăng nhập hoặc không truy cập được",
        False,
        "Kiểm tra URL còn công khai và bạn có quyền sử dụng nội dung; FrameForge không hỗ trợ cookie hoặc bypass đăng nhập.",
    ),
    (
        "rate_limited",
        (
            "too many requests", "rate limit",
            "http error 429", "temporarily blocked", "captcha",
            "429",
        ),
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
        (
            "requested format is not available", "requested format",
            "format is not available", "format not available",
            "no video formats found", "no video formats",
            "no formats", "no suitable format",
            "unable to extract",
        ),
        "Không tìm thấy format video phù hợp",
        False,
        "Thử chất lượng thấp hơn hoặc kiểm tra video còn công khai; một số nội dung không cung cấp format cho yt-dlp.",
    ),
    (
        "output_error",
        (
            "permission denied", "access is denied",
            "no space left", "disk full",
            "cannot create", "cannot write", "could not write",
            "không tạo được file video",
            "no space", "output",
        ),
        "Không ghi được file đầu ra",
        False,
        "Kiểm tra thư mục lưu, quyền ghi và dung lượng ổ đĩa.",
    ),
    (
        "network_error",
        (
            "timed out", "timeout", "connection reset", "connection refused",
            "temporary failure", "unable to download",
            "http error 5", "network",
            "503", "502",
        ),
        "Lỗi mạng hoặc nguồn tạm thời không phản hồi",
        True,
        "Kiểm tra kết nối mạng; FrameForge sẽ tự retry với thời gian chờ tăng dần.",
    ),
)


def classify_error(
    exc: BaseException,
    *,
    ffmpeg_available: bool = True,
) -> ErrorInfo:
    """Phân loại lỗi yt-dlp/FFmpeg thành mã ổn định cho UI.

    Parameters
    ----------
    exc:
        Lỗi cần phân loại.
    ffmpeg_available:
        Nếu ``True``, bỏ qua rule ``ffmpeg_missing`` (giả định FFmpeg đã có).
    """
    message = str(exc or "").lower()
    if not ffmpeg_available and any(
        token in message for token in ("ffmpeg", "ffprobe", "merging", "postprocess")
    ):
        return ErrorInfo(
            "ffmpeg_missing",
            "Thiếu FFmpeg để ghép video/audio",
            False,
            "Cài bản FrameForge có FFmpeg nhúng hoặc thêm ffmpeg.exe vào PATH.",
        )
    for code, tokens, label, retryable, suggestion in _ERROR_RULES:
        if code == "ffmpeg_missing" and ffmpeg_available:
            continue
        if any(token in message for token in tokens):
            return ErrorInfo(code, label, retryable, suggestion)
    return ErrorInfo(
        "unknown",
        "Lỗi không xác định",
        True,
        "Kiểm tra URL và kết nối mạng; xem chi tiết lỗi rồi thử lại nếu lỗi có tính tạm thời.",
    )
