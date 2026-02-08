from pydantic import BaseModel
from typing import Optional


class PlaylistRequest(BaseModel):
    url: str


class VideoInfo(BaseModel):
    video_id: str
    title: str
    thumbnail: Optional[str] = None
    duration: Optional[int] = None
    duration_str: Optional[str] = None
    uploader: Optional[str] = None
    url: str


class PlaylistInfo(BaseModel):
    playlist_id: str
    title: str
    video_count: int
    videos: list[VideoInfo]
    session_id: str


class DownloadRequest(BaseModel):
    session_id: str
    video_ids: list[str]
