import asyncio
import json
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from models import PlaylistInfo, PlaylistRequest, VideoInfo
from services.cleanup import cleanup_loop
from services.downloader import download_video
from services.zipper import create_zip_stream
from services.extractor import extract_playlist_info

DOWNLOADS_DIR = Path("downloads")

# In-memory session store: session_id -> {videos, dir, downloaded, title}
sessions: dict[str, dict] = {}
# Progress queues for SSE: session_id -> asyncio.Queue
progress_queues: dict[str, asyncio.Queue] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    task = asyncio.create_task(cleanup_loop())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.post("/api/extract")
async def extract_playlist(req: PlaylistRequest):
    """Extract playlist metadata from a YouTube URL."""
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    try:
        info = await asyncio.to_thread(extract_playlist_info, url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    session_id = str(uuid.uuid4())
    session_dir = DOWNLOADS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    videos = []
    for entry in info["entries"]:
        vid = VideoInfo(
            video_id=entry.get("id", ""),
            title=entry.get("title", "Unknown"),
            thumbnail=entry.get("thumbnail")
            or (entry.get("thumbnails") or [{}])[-1].get("url"),
            duration=entry.get("duration"),
            duration_str=_format_duration(entry.get("duration")),
            uploader=entry.get("uploader"),
            url=f"https://www.youtube.com/watch?v={entry.get('id', '')}",
        )
        videos.append(vid)

    sessions[session_id] = {
        "videos": {v.video_id: v for v in videos},
        "dir": session_dir,
        "downloaded": {},  # video_id -> filename on disk
        "title": info["title"],
    }

    return PlaylistInfo(
        playlist_id=info["playlist_id"],
        title=info["title"],
        video_count=len(videos),
        videos=videos,
        session_id=session_id,
    )


@app.get("/api/download/{session_id}")
async def download_and_stream_progress(
    session_id: str, video_ids: str, fmt: str = "mp3", request: Request = None
):
    """SSE endpoint that starts downloads and streams progress events.

    video_ids: comma-separated list of video IDs, or "all".
    fmt: "mp3" for audio-only, "mp4" for video.
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    audio_only = fmt == "mp3"
    session = sessions[session_id]
    session["format"] = fmt
    ids = (
        list(session["videos"].keys())
        if video_ids == "all"
        else video_ids.split(",")
    )

    queue: asyncio.Queue = asyncio.Queue()
    progress_queues[session_id] = queue
    loop = asyncio.get_event_loop()
    semaphore = asyncio.Semaphore(3)

    async def download_one(vid_id: str):
        async with semaphore:
            video = session["videos"].get(vid_id)
            if not video:
                await queue.put(
                    {
                        "event_type": "error",
                        "video_id": vid_id,
                        "message": "Video not found in session",
                    }
                )
                return

            await queue.put(
                {
                    "event_type": "downloading",
                    "video_id": vid_id,
                    "title": video.title,
                }
            )

            def sync_progress_callback(data):
                loop.call_soon_threadsafe(queue.put_nowait, data)

            try:
                await asyncio.to_thread(
                    download_video,
                    video.url,
                    vid_id,
                    session["dir"],
                    sync_progress_callback,
                    audio_only,
                )
                # Find the downloaded file
                for f in session["dir"].iterdir():
                    if f.stem == vid_id and f.is_file():
                        session["downloaded"][vid_id] = f.name
                        break
                await queue.put(
                    {
                        "event_type": "complete",
                        "video_id": vid_id,
                        "title": video.title,
                    }
                )
            except Exception as e:
                err_msg = str(e)
                # Clean up yt-dlp verbose error messages
                if "ERROR:" in err_msg:
                    err_msg = err_msg.split("ERROR:")[-1].strip()
                if len(err_msg) > 200:
                    err_msg = err_msg[:200]
                await queue.put(
                    {
                        "event_type": "error",
                        "video_id": vid_id,
                        "title": video.title,
                        "message": err_msg or "Download failed",
                    }
                )

    async def run_downloads():
        tasks = [download_one(vid_id) for vid_id in ids]
        await asyncio.gather(*tasks)
        await queue.put({"event_type": "all_complete"})

    asyncio.create_task(run_downloads())

    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("event_type") == "all_complete":
                    break
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/file/{session_id}/{video_id}")
async def get_file(session_id: str, video_id: str):
    """Download a single completed video file."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = sessions[session_id]
    filename = session["downloaded"].get(video_id)
    if not filename:
        raise HTTPException(status_code=404, detail="File not downloaded yet")

    filepath = session["dir"] / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    title = session["videos"][video_id].title
    safe_title = _safe_filename(title)
    ext = filepath.suffix
    media_type = "audio/mpeg" if ext == ".mp3" else "video/mp4"
    return FileResponse(
        filepath,
        filename=f"{safe_title}{ext}",
        media_type=media_type,
    )


@app.get("/api/zip/{session_id}")
async def get_zip(session_id: str):
    """Stream all downloaded videos as a ZIP file."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = sessions[session_id]
    if not session["downloaded"]:
        raise HTTPException(status_code=400, detail="No files downloaded yet")

    filenames = {}
    for vid_id, disk_name in session["downloaded"].items():
        title = session["videos"][vid_id].title
        safe_title = _safe_filename(title)
        ext = Path(disk_name).suffix
        filenames[vid_id] = f"{safe_title}{ext}"

    playlist_title = _safe_filename(session.get("title", "playlist"))

    return StreamingResponse(
        create_zip_stream(session["dir"], filenames),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{playlist_title}.zip"'
        },
    )


@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str):
    """Clean up a session's downloaded files."""
    if session_id in sessions:
        shutil.rmtree(sessions[session_id]["dir"], ignore_errors=True)
        del sessions[session_id]
    progress_queues.pop(session_id, None)
    return {"status": "cleaned"}


def _format_duration(seconds):
    if not seconds:
        return None
    s = int(seconds)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _safe_filename(title: str) -> str:
    return "".join(c for c in title if c.isalnum() or c in " -_().").strip()[:200]
