import os
import shutil
from pathlib import Path

import yt_dlp

# Try to make ffmpeg available via imageio-ffmpeg (for Vercel)
try:
    import imageio_ffmpeg

    _ffmpeg_dir = str(Path(imageio_ffmpeg.get_ffmpeg_exe()).parent)
    if _ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _ffmpeg_dir + ":" + os.environ.get("PATH", "")
except ImportError:
    pass


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def download_video(
    video_url: str,
    output_dir: Path,
    audio_only: bool = False,
) -> Path:
    """Download a single video/audio to output_dir. Returns path to the file."""

    ydl_opts = {
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        "retries": 3,
        "fragment_retries": 3,
        "quiet": True,
        "no_warnings": True,
    }

    if audio_only:
        ydl_opts["format"] = "bestaudio/best"
        if _has_ffmpeg():
            ydl_opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]
    else:
        # Video mode — let yt-dlp pick the best format
        if _has_ffmpeg():
            ydl_opts["merge_output_format"] = "mp4"

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

    # Find the output file (skip .part files)
    files = [
        f
        for f in output_dir.iterdir()
        if f.is_file() and not f.name.endswith(".part")
    ]
    if not files:
        raise RuntimeError("Download produced no output file")

    # Prefer the expected extension
    expected_ext = ".mp3" if (audio_only and _has_ffmpeg()) else ".mp4"
    for f in files:
        if f.suffix == expected_ext:
            return f
    return files[0]
