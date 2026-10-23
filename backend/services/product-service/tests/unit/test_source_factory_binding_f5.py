"""E2E finding F5: a product can be bound to a home factory.

Before this change POST /products silently dropped source_factory_id, so the
factory-scoped pull rule (CLAUDE.md §6) could not be set up through the API.
The field is now accepted on create and PATCH, and must name an active node
of the same tenant.

Router and schema imports happen inside each test, as in the other product-service
unit tests, so a full-suite run does not pick up another service's `routers` package.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

TENANT = str(uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001"))
FACTORY = uuid.UUID("01b676f4-575e-4673-bb2a-c3c58c98f40d")


def _db(found: bool) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.fetchone.return_value = (1,) if found else None
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.unit
class TestSourceFactorySchema:
    def test_create_accepts_a_factory_id(self) -> None:
        from schemas.product import ProductCreateRequest

        body = ProductCreateRequest(name="Flour", type_code="FLR", source_factory_id=FACTORY)
        assert body.source_factory_id == FACTORY

    def test_create_defaults_to_no_factory(self) -> None:
        from schemas.product import ProductCreateRequest

        assert ProductCreateRequest(name="Flour", type_code="FLR").source_factory_id is None

    def test_update_accepts_a_factory_id(self) -> None:
        from schemas.product import ProductUpdateRequest

        assert ProductUpdateRequest(source_factory_id=FACTORY).source_factory_id == FACTORY

    def test_non_uuid_factory_is_rejected(self) -> None:
        from schemas.product import ProductCreateRequest

        with pytest.raises(ValidationError):
            ProductCreateRequest(name="Flour", type_code="FLR", source_factory_id="not-a-uuid")


@pytest.mark.unit
class TestValidateSourceFactory:
    async def test_no_factory_skips_the_lookup(self) -> None:
        from routers.products import _validate_source_factory

        db = _db(found=False)
        await _validate_source_factory(db, TENANT, None)
        db.execute.assert_not_awaited()

    async def test_active_factory_in_the_tenant_passes(self) -> None:
        from routers.products import _validate_source_factory

        db = _db(found=True)
        await _validate_source_factory(db, TENANT, FACTORY)
        params = db.execute.call_args.args[1]
        assert params == {"nid": str(FACTORY), "tid": TENANT}

    async def test_factory_not_in_the_tenant_is_rejected(self) -> None:
        from routers.products import _validate_source_factory

        db = _db(found=False)
        with pytest.raises(HTTPException) as exc:
            await _validate_source_factory(db, TENANT, FACTORY)
        assert exc.value.status_code == 422
        assert exc.value.detail == {
            "code": "SOURCE_FACTORY_NOT_FOUND",
            "source_factory_id": str(FACTORY),
        }
