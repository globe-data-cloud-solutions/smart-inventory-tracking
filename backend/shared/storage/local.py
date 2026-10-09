import mimetypes
import uuid
from pathlib import Path

from .base import StorageService

# Root of the uploads directory relative to the project root.
# In ECS this is replaced by S3StorageService — same interface.
_BASE_PATH = Path("uploads")
_BASE_URL = "/static/uploads"


class LocalStorageService(StorageService):
    """Saves files to local disk under uploads/{folder}/.

    Served via the /static/uploads StaticFiles mount.
    Swap to S3StorageService for production without changing callers.
    """

    async def save(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        folder: str,
    ) -> str:
        dest_dir = _BASE_PATH / folder
        dest_dir.mkdir(parents=True, exist_ok=True)

        safe_name = f"{uuid.uuid4().hex}_{Path(filename).name}"
        dest_file = dest_dir / safe_name
        dest_file.write_bytes(file_bytes)

        return f"{_BASE_URL}/{folder}/{safe_name}"

    async def delete(self, url: str) -> None:
        # Strip base URL prefix to get relative path
        if url.startswith(_BASE_URL + "/"):
            rel = url[len(_BASE_URL) + 1:]
            path = _BASE_PATH / rel
            if path.exists():
                path.unlink()

    async def get(self, rel_path: str) -> tuple[bytes, str] | None:
        path = _BASE_PATH / rel_path
        if not path.exists():
            return None
        content_type, _ = mimetypes.guess_type(path.name)
        return path.read_bytes(), content_type or "application/octet-stream"
