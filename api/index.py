import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

# Add project root to Python path for services imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.extractor import extract_playlist_info
from services.downloader import download_video

app = FastAPI()


# --- Models ---

class ExtractRequest(BaseModel):
    url: str


class VideoItem(BaseModel):
    video_id: str
    title: str
    thumbnail: Optional[str] = None
    duration: Optional[int] = None
    duration_str: Optional[str] = None
    uploader: Optional[str] = None
    url: str


class DownloadRequest(BaseModel):
    url: str
    fmt: str = "mp3"
    title: str = "video"
    save_dir: Optional[str] = None


# --- Helpers ---

def _format_duration(seconds):
    if not seconds:
        return None
    s = int(seconds)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _safe_filename(title: str) -> str:
    return "".join(c for c in title if c.isalnum() or c in " -_().").strip()[:200]


# --- Endpoints ---

@app.post("/api/extract")
async def extract(req: ExtractRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    try:
        info = await asyncio.to_thread(extract_playlist_info, url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    videos = []
    for entry in info["entries"]:
        videos.append(VideoItem(
            video_id=entry.get("id", ""),
            title=entry.get("title", "Unknown"),
            thumbnail=entry.get("thumbnail")
            or (entry.get("thumbnails") or [{}])[-1].get("url"),
            duration=entry.get("duration"),
            duration_str=_format_duration(entry.get("duration")),
            uploader=entry.get("uploader"),
            url=f"https://www.youtube.com/watch?v={entry.get('id', '')}",
        ))

    return {
        "playlist_id": info["playlist_id"],
        "title": info["title"],
        "video_count": len(videos),
        "videos": [v.model_dump() for v in videos],
    }


@app.post("/api/download")
async def download(req: DownloadRequest):
    audio_only = req.fmt == "mp3"
    tmp_dir = Path(tempfile.mkdtemp(prefix="ytdl_"))

    try:
        filepath = await asyncio.to_thread(
            download_video, req.url, tmp_dir, audio_only
        )

        safe_title = _safe_filename(req.title)
        ext = filepath.suffix

        # Save directly to chosen folder if provided
        if req.save_dir:
            dest_dir = Path(req.save_dir).expanduser()
            if not dest_dir.is_dir():
                raise ValueError(f"Folder not found: {dest_dir}")
            dest_path = dest_dir / f"{safe_title}{ext}"
            shutil.copy2(filepath, dest_path)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return {"saved": str(dest_path)}

        media_type = "audio/mpeg" if ext == ".mp3" else "video/mp4"

        content = filepath.read_bytes()
        shutil.rmtree(tmp_dir, ignore_errors=True)

        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{safe_title}{ext}"'
            },
        )
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        error_msg = str(e)
        if len(error_msg) > 200:
            error_msg = error_msg[:200]
        raise HTTPException(status_code=500, detail=error_msg)


# Local development: serve static files from public/
if os.environ.get("VERCEL") is None:
    from fastapi.staticfiles import StaticFiles

    _public_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public"
    )
    if os.path.isdir(_public_dir):
        app.mount("/", StaticFiles(directory=_public_dir, html=True), name="public")
