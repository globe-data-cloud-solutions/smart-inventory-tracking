import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, Enum, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.models.base import Base, TimestampMixin

TxTypeEnum = Enum(
    "RECEIVE",
    "TRANSFER_OUT",
    "TRANSFER_IN",
    "ISSUE",
    "ADJUSTMENT",
    "RESERVE",
    "RELEASE",
    "RETURN",
    "COUNT_VARIANCE",
    "LOT_OPENING",
    name="transaction_type",
    create_type=False,
)
TransferStatusEnum = Enum(
    "DRAFT",
    "SUBMITTED",
    "APPROVED",
    "IN_TRANSIT",
    "RECEIVED",
    "CLOSED",
    "REJECTED",
    "CANCELLED",
    name="transfer_status",
    create_type=False,
)
DispatchEnum = Enum("FEFO", "FIFO", "LIFO", name="dispatch_strategy", create_type=False)


class InventoryTransaction(Base):
    """Immutable ledger — INSERT only, no UPDATE or DELETE."""

    __tablename__ = "inventory_transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_date: Mapped[date] = mapped_column(Date, primary_key=True, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    type: Mapped[str] = mapped_column(TxTypeEnum, nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    unit_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 4), nullable=True)
    lot_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    reference_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, server_default="WEB")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class InventoryBalance(Base, TimestampMixin):
    __tablename__ = "inventory_balances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False, default=0)
    lot_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)


class InventoryTransactionKey(Base):
    __tablename__ = "inventory_transaction_keys"

    idempotency_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    transaction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DispatchStrategyConfig(Base, TimestampMixin):
    __tablename__ = "dispatch_strategy_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    strategy: Mapped[str] = mapped_column(DispatchEnum, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    configured_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
