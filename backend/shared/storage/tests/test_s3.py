"""Unit tests for shared.storage — S3StorageService, LocalStorageService.get(),
and get_storage() backend selection. No network; the boto3 client is replaced
via the module-level factory function."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from shared.storage import LocalStorageService, S3StorageService, get_storage


def test_get_storage_defaults_to_local(monkeypatch) -> None:
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    assert isinstance(get_storage(), LocalStorageService)


def test_get_storage_picks_s3(monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    assert isinstance(get_storage(), S3StorageService)


@pytest.mark.asyncio
async def test_s3_save_calls_put_object_with_expected_args(monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_S3_BUCKET", "smart-dev-attachments")
    fake_client = MagicMock()

    with patch("shared.storage.s3._s3_client", return_value=fake_client):
        service = S3StorageService()
        url = await service.save(
            file_bytes=b"hello",
            filename="photo.jpg",
            content_type="image/jpeg",
            folder="products",
        )

    fake_client.put_object.assert_called_once()
    _, kwargs = fake_client.put_object.call_args
    assert kwargs["Bucket"] == "smart-dev-attachments"
    assert kwargs["Key"].startswith("uploads/products/")
    assert kwargs["Key"].endswith("_photo.jpg")
    assert kwargs["Body"] == b"hello"
    assert kwargs["ContentType"] == "image/jpeg"
    assert url.startswith("/static/uploads/products/")
    assert url.endswith("_photo.jpg")


@pytest.mark.asyncio
async def test_s3_delete_strips_base_url_prefix(monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_S3_BUCKET", "smart-dev-attachments")
    fake_client = MagicMock()

    with patch("shared.storage.s3._s3_client", return_value=fake_client):
        service = S3StorageService()
        await service.delete("/static/uploads/products/abc123_photo.jpg")

    fake_client.delete_object.assert_called_once_with(
        Bucket="smart-dev-attachments", Key="uploads/products/abc123_photo.jpg"
    )


@pytest.mark.asyncio
async def test_s3_get_returns_none_on_missing_key(monkeypatch) -> None:
    from botocore.exceptions import ClientError

    monkeypatch.setenv("STORAGE_S3_BUCKET", "smart-dev-attachments")
    fake_client = MagicMock()
    fake_client.get_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject"
    )

    with patch("shared.storage.s3._s3_client", return_value=fake_client):
        service = S3StorageService()
        result = await service.get("products/missing.jpg")

    assert result is None


@pytest.mark.asyncio
async def test_s3_get_returns_bytes_and_content_type(monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_S3_BUCKET", "smart-dev-attachments")
    fake_body = MagicMock()
    fake_body.read.return_value = b"image-bytes"
    fake_client = MagicMock()
    fake_client.get_object.return_value = {"Body": fake_body, "ContentType": "image/png"}

    with patch("shared.storage.s3._s3_client", return_value=fake_client):
        service = S3StorageService()
        result = await service.get("products/photo.png")

    assert result == (b"image-bytes", "image/png")


@pytest.mark.asyncio
async def test_local_get_returns_none_when_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    service = LocalStorageService()
    assert await service.get("products/does-not-exist.jpg") is None


@pytest.mark.asyncio
async def test_local_save_then_get_round_trips(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    service = LocalStorageService()
    url = await service.save(
        file_bytes=b"hello",
        filename="photo.jpg",
        content_type="image/jpeg",
        folder="products",
    )
    rel_path = url[len("/static/uploads/"):]
    result = await service.get(rel_path)
    assert result is not None
    content, content_type = result
    assert content == b"hello"
    assert content_type == "image/jpeg"
