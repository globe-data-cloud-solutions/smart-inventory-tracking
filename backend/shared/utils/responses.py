from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str
    message: str


class SuccessResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorDetail
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
