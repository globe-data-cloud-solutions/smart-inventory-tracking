import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, Enum, ForeignKey, Numeric, Text
from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.models.base import Base

TransferRequestStatusEnum = Enum(
    "PENDING",
    "APPROVED",
    "REJECTED",
    "FULFILLED",
    "CANCELLED",
    name="transfer_request_status",
    create_type=False,
)


class TransferRequest(Base):
    """A warehouse requests stock to be sent from another warehouse or factory.
    Notification of the source warehouse is written to the outbox in the same
    transaction — not via a post-commit event dispatcher.
    """

    __tablename__ = "transfer_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    requesting_warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    required_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        TransferRequestStatusEnum, nullable=False, server_default="PENDING"
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
