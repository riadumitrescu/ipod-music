from zipstream import ZipStream
from pathlib import Path


def create_zip_stream(session_dir: Path, filenames: dict[str, str]):
    """Generator yielding zip chunks for streaming response.

    filenames: {video_id: "Clean Title.mp4"} mapping
    """
    zs = ZipStream(sized=True)

    for video_id, clean_name in filenames.items():
        # Find the file (could be .mp4, .webm, etc.)
        for f in session_dir.iterdir():
            if f.stem == video_id and f.is_file():
                zs.add_path(f, arcname=clean_name)
                break

    yield from zs
