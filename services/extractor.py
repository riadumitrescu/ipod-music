import yt_dlp


def extract_playlist_info(url: str) -> dict:
    """Extract playlist/channel metadata without downloading videos.

    Uses extract_flat for fast metadata retrieval (1-3s vs 30-60s).
    Runs in thread executor via asyncio.to_thread().
    """
    ydl_opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if info is None:
        raise ValueError("Could not extract info from URL. Check that the URL is valid.")

    # Handle single video (not a playlist)
    if info.get("_type") != "playlist":
        return {
            "playlist_id": info.get("id", "single"),
            "title": info.get("title", "Single Video"),
            "entries": [info],
        }

    entries = []
    for entry in info.get("entries") or []:
        if entry is None:
            continue  # skip unavailable/private videos
        entries.append(entry)

    return {
        "playlist_id": info.get("id", ""),
        "title": info.get("title", "Playlist"),
        "entries": entries,
    }
