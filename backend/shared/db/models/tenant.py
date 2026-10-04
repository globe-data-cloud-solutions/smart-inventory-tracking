import uuid
from typing import Optional

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.db.models.base import Base, SoftDeleteMixin, TimestampMixin

OrgType    = Enum("PRODUCER", "RETAILER", "HYBRID", name="organisation_type", create_type=False)
LocaleEnum = Enum("en", "am", "or",               name="supported_locale",   create_type=False)
PlanTierEnum = Enum("STARTER", "GROWTH", "ENTERPRISE", name="plan_tier",     create_type=False)


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
    plan_tier: Mapped[str] = mapped_column(PlanTierEnum, nullable=False, server_default="ENTERPRISE")
    max_warehouses: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_users: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    approval_thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    default_locale: Mapped[str] = mapped_column(
        LocaleEnum, nullable=False, server_default="en"
    )
    onboarding_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    signup_source: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="SA"
    )

    children = relationship("Tenant", backref="parent", remote_side=[id])
