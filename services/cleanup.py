import asyncio
import shutil
from pathlib import Path
from datetime import datetime, timedelta

DOWNLOADS_DIR = Path("downloads")
MAX_AGE = timedelta(hours=1)


async def cleanup_loop():
    """Background task that cleans old download sessions every 30 minutes."""
    while True:
        await asyncio.sleep(1800)
        if DOWNLOADS_DIR.exists():
            now = datetime.now()
            for session_dir in DOWNLOADS_DIR.iterdir():
                if session_dir.is_dir():
                    try:
                        mtime = datetime.fromtimestamp(session_dir.stat().st_mtime)
                        if now - mtime > MAX_AGE:
                            shutil.rmtree(session_dir, ignore_errors=True)
                    except OSError:
                        pass
