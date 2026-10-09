import os

from .local import LocalStorageService
from .s3 import S3StorageService

__all__ = ["LocalStorageService", "S3StorageService", "get_storage"]


def get_storage() -> LocalStorageService | S3StorageService:
    backend = os.environ.get("STORAGE_BACKEND", "local")
    if backend == "s3":
        return S3StorageService()
    return LocalStorageService()
