"""
File Downloader — Async download with progress tracking.
"""
import os
import logging
import asyncio
import time
import re
import httpx

logger = logging.getLogger("downloader.file_downloader")

DOWNLOAD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}

# Global task store for progress
download_tasks = {}


def sanitize_filename(name: str, max_len: int = 80) -> str:
    """Remove invalid characters from filename."""
    name = re.sub(r'[\\/:*?"<>|\n\r\t]', '', name)
    name = name.strip('. ')
    return name[:max_len] if name else "video"


class DownloadTask:
    def __init__(self, task_id: str, url: str, save_path: str, filename: str):
        self.task_id = task_id
        self.url = url
        self.save_path = save_path
        self.filename = filename
        self.status = "pending"  # pending, downloading, done, error
        self.progress = 0
        self.total_size = 0
        self.downloaded = 0
        self.error = ""
        self.start_time = 0
        self.end_time = 0

    def to_dict(self):
        elapsed = (self.end_time or time.time()) - self.start_time if self.start_time else 0
        speed = self.downloaded / elapsed if elapsed > 0 else 0
        return {
            "task_id": self.task_id,
            "filename": self.filename,
            "status": self.status,
            "progress": self.progress,
            "total_size": self.total_size,
            "downloaded": self.downloaded,
            "speed": int(speed),
            "error": self.error,
        }


class FileDownloader:
    """Async file downloader with progress tracking."""

    def __init__(self, download_dir: str, chunk_size: int = 1048576):
        self.download_dir = download_dir
        self.chunk_size = chunk_size
        os.makedirs(download_dir, exist_ok=True)

    async def download(
        self,
        url: str,
        filename: str,
        task_id: str,
        proxy: str = None,
        headers: dict = None,
    ) -> DownloadTask:
        safe_name = sanitize_filename(filename)
        save_path = os.path.join(self.download_dir, safe_name)

        task = DownloadTask(task_id, url, save_path, safe_name)
        download_tasks[task_id] = task

        # Start download in background
        asyncio.create_task(self._do_download(task, proxy, headers))
        return task

    async def _do_download(
        self,
        task: DownloadTask,
        proxy: str = None,
        extra_headers: dict = None,
    ):
        task.status = "downloading"
        task.start_time = time.time()
        headers = {**DOWNLOAD_HEADERS}
        if extra_headers:
            headers.update(extra_headers)

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(60, connect=15),
                follow_redirects=True,
                proxy=proxy,
                headers=headers,
            ) as client:
                async with client.stream("GET", task.url) as resp:
                    resp.raise_for_status()
                    total = int(resp.headers.get("content-length", 0))
                    task.total_size = total

                    # Detect extension from content-type if needed
                    ct = resp.headers.get("content-type", "")
                    if not os.path.splitext(task.save_path)[1]:
                        ext = ".mp4"
                        if "jpeg" in ct or "jpg" in ct:
                            ext = ".jpg"
                        elif "png" in ct:
                            ext = ".png"
                        elif "webp" in ct:
                            ext = ".webp"
                        task.save_path += ext
                        task.filename += ext

                    with open(task.save_path, "wb") as f:
                        async for chunk in resp.aiter_bytes(self.chunk_size):
                            f.write(chunk)
                            task.downloaded += len(chunk)
                            if total > 0:
                                task.progress = int(task.downloaded / total * 100)

            task.status = "done"
            task.progress = 100
            task.end_time = time.time()
            logger.info(f"Download complete: {task.filename}")

        except Exception as e:
            task.status = "error"
            task.error = str(e)
            task.end_time = time.time()
            logger.error(f"Download failed: {e}")

    def get_task(self, task_id: str) -> DownloadTask:
        return download_tasks.get(task_id)

    def get_history(self) -> list:
        """List all downloaded files."""
        files = []
        if not os.path.exists(self.download_dir):
            return files
        for f in os.listdir(self.download_dir):
            path = os.path.join(self.download_dir, f)
            if os.path.isfile(path):
                stat = os.stat(path)
                files.append({
                    "filename": f,
                    "size": stat.st_size,
                    "modified": int(stat.st_mtime),
                })
        files.sort(key=lambda x: x["modified"], reverse=True)
        return files

    def delete_file(self, filename: str) -> bool:
        path = os.path.join(self.download_dir, filename)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False
