import yt_dlp
from pathlib import Path


def download_video(
    video_url: str,
    video_id: str,
    output_dir: Path,
    progress_callback,
    audio_only: bool = False,
):
    """Download a single video (or extract audio) with progress reporting.

    If audio_only=True, extracts audio and converts to MP3.
    Called via asyncio.to_thread().
    """

    def progress_hook(d):
        if d["status"] == "downloading":
            progress_callback(
                {
                    "event_type": "progress",
                    "video_id": video_id,
                    "percent": _parse_percent(d.get("_percent_str", "0%")),
                    "speed": d.get("_speed_str", ""),
                    "eta": d.get("_eta_str", ""),
                }
            )
        elif d["status"] == "finished":
            progress_callback(
                {
                    "event_type": "merging",
                    "video_id": video_id,
                    "message": "Converting..." if audio_only else "Processing...",
                }
            )

    if audio_only:
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
            "progress_hooks": [progress_hook],
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "retries": 3,
            "fragment_retries": 3,
            "noprogress": False,
            "quiet": True,
            "no_warnings": True,
        }
    else:
        ydl_opts = {
            # Let yt-dlp use its default format selection
            "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
            "progress_hooks": [progress_hook],
            "merge_output_format": "mp4",
            "retries": 3,
            "fragment_retries": 3,
            "noprogress": False,
            "quiet": True,
            "no_warnings": True,
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        if "Sign in" in error_msg or "age" in error_msg.lower():
            raise RuntimeError("Age-restricted or sign-in required")
        if "Private" in error_msg or "private" in error_msg:
            raise RuntimeError("Video is private")
        if "unavailable" in error_msg.lower():
            raise RuntimeError("Video is unavailable")
        if "copyright" in error_msg.lower():
            raise RuntimeError("Blocked by copyright")
        raise RuntimeError(f"Download failed: {error_msg[:150]}")


def _parse_percent(percent_str: str) -> float:
    try:
        return float(percent_str.strip().replace("%", ""))
    except (ValueError, AttributeError):
        return 0.0
