from abc import ABC, abstractmethod


class StorageService(ABC):
    @abstractmethod
    async def save(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        folder: str,
    ) -> str:
        """Save file and return its public URL."""

    @abstractmethod
    async def delete(self, url: str) -> None:
        """Delete file by its public URL."""

    @abstractmethod
    async def get(self, rel_path: str) -> tuple[bytes, str] | None:
        """Return (bytes, content_type) for a path relative to the uploads root,
        or None if it does not exist."""
