"""Conftest for tenant-service unit tests.

Problem
───────
The full backend suite runs in one process with rootdir=smart-platform/.
inventory-service/tests/ has no __init__.py so pytest adds inventory-service/
to sys.path.  tenant-service/tests/ has __init__.py so pytest does NOT add
tenant-service/ automatically.

After inventory-service tests run, these bare-name packages are cached in
sys.modules pointing to inventory-service's files:
  routers, routers.*, dependencies, services, services.*, main

When tenant-service test methods do `from routers.positions import ...` they
find the stale inventory-service versions (which have none of those submodules).

Fix
───
Before each test:
  1. Pin tenant-service root to sys.path[0].
  2. Flush all bare-name service-local packages from sys.modules.
     After the flush, fresh imports resolve via sys.path[0] = tenant-service.
After each test flush again so later services are unaffected.
"""
from __future__ import annotations

import os
import sys
import pytest

_TENANT_SVC_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

# Bare-name packages that every service defines — the ones that collide when
# multiple services' tests run in the same process.
_SERVICE_PACKAGES = ("routers", "dependencies", "services", "main")


def _flush_service_modules() -> None:
    """Remove all per-service bare-name modules from sys.modules."""
    stale = [
        k for k in list(sys.modules)
        if any(k == p or k.startswith(p + ".") for p in _SERVICE_PACKAGES)
    ]
    for k in stale:
        sys.modules.pop(k, None)


def _pin_tenant_root() -> None:
    """Move tenant-service root to sys.path[0]."""
    try:
        sys.path.remove(_TENANT_SVC_ROOT)
    except ValueError:
        pass
    sys.path.insert(0, _TENANT_SVC_ROOT)


@pytest.fixture(autouse=True)
def _flush_stale_service_modules():
    """Pin tenant root and flush stale service modules before every test."""
    _pin_tenant_root()
    _flush_service_modules()
    yield
    _flush_service_modules()
