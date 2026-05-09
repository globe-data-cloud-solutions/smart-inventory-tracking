import uuid
from typing import Optional

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.db.models.base import Base, SoftDeleteMixin, TimestampMixin

OrgType = Enum("PRODUCER", "RETAILER", "HYBRID", name="organisation_type")
LocaleEnum = Enum("en", "am", "or", name="supported_locale")


class Tenant(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    organisation_type: Mapped[str] = mapped_column(OrgType, nullable=False)
    parent_tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    feature_flags: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    sku_cap: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    approval_thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    default_locale: Mapped[str] = mapped_column(
        LocaleEnum, nullable=False, server_default="en"
    )
    onboarding_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    children = relationship("Tenant", backref="parent", remote_side=[id])
