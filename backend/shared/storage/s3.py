import asyncio
import os
import uuid
from pathlib import Path

from .base import StorageService

_BASE_URL = "/static/uploads"
_KEY_PREFIX = "uploads/"


def _s3_client():
    import boto3

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    endpoint_url = os.environ.get("STORAGE_S3_ENDPOINT_URL") or None
    return boto3.client("s3", region_name=region, endpoint_url=endpoint_url)


class S3StorageService(StorageService):
    """Saves files to S3 under uploads/{folder}/.

    Served via product-service's GET /static/uploads/{path:path} route (main.py),
    which proxies storage.get() — same public URL format as LocalStorageService so
    callers never change.
    """

    def __init__(self) -> None:
        self._bucket = os.environ.get("STORAGE_S3_BUCKET")

    async def save(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        folder: str,
    ) -> str:
        safe_name = f"{uuid.uuid4().hex}_{Path(filename).name}"
        key = f"{_KEY_PREFIX}{folder}/{safe_name}"

        def _put() -> None:
            _s3_client().put_object(
                Bucket=self._bucket,
                Key=key,
                Body=file_bytes,
                ContentType=content_type,
            )

        await asyncio.to_thread(_put)

        return f"{_BASE_URL}/{folder}/{safe_name}"

    async def delete(self, url: str) -> None:
        if not url.startswith(_BASE_URL + "/"):
            return
        rel = url[len(_BASE_URL) + 1:]
        key = f"{_KEY_PREFIX}{rel}"

        def _delete() -> None:
            _s3_client().delete_object(Bucket=self._bucket, Key=key)

        await asyncio.to_thread(_delete)

    async def get(self, rel_path: str) -> tuple[bytes, str] | None:
        key = f"{_KEY_PREFIX}{rel_path}"

        def _get() -> tuple[bytes, str] | None:
            from botocore.exceptions import ClientError

            try:
                obj = _s3_client().get_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                    return None
                raise
            return obj["Body"].read(), obj.get("ContentType", "application/octet-stream")

        return await asyncio.to_thread(_get)
