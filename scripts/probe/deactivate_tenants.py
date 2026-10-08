"""deactivate_tenants.py — Deactivate probe/test tenants by slug via the SA API.

Soft-delete only, through the public API surface a human SA would use —
never direct SQL, never a hard delete (CLAUDE.md §8). Logs in as SA
(credentials from SA_EMAIL/SA_PASSWORD env vars, defaulting to the local-dev
SA account), resolves each slug to a tenant_id via GET /tenants/sa/registry,
then calls PATCH /tenants/{tenant_id}/deactivate. Idempotent: a tenant
already DEACTIVATED is reported as already-done, not an error.

Usage:
    python scripts/probe/deactivate_tenants.py zz-s7-e2e-1791456715982 zz-s7-e2e-1791456715997

Requires the api-gateway running (default http://localhost:8000 — override
with API_BASE).
"""
from __future__ import annotations

import os
import sys

import httpx

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
SA_EMAIL = os.environ.get("SA_EMAIL", "smartadmin@smart-inventory.com")
SA_PASSWORD = os.environ.get("SA_PASSWORD", "Admin@2026")


def main(slugs: list[str]) -> int:
    if not slugs:
        print("Usage: python scripts/probe/deactivate_tenants.py <slug> [<slug> ...]")
        return 1

    with httpx.Client(timeout=15.0) as client:
        token_resp = client.post(
            f"{API_BASE}/api/v1/auth/token",
            json={"email": SA_EMAIL, "password": SA_PASSWORD},
        )
        if token_resp.status_code != 200:
            print(f"SA login failed: {token_resp.status_code} {token_resp.text}")
            return 1
        access_token = token_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        registry_resp = client.get(f"{API_BASE}/api/v1/tenants/sa/registry", headers=headers)
        if registry_resp.status_code != 200:
            print(f"Registry fetch failed: {registry_resp.status_code} {registry_resp.text}")
            return 1
        tenants = registry_resp.json()["data"]
        by_slug = {t["slug"]: t["id"] for t in tenants}

        exit_code = 0
        for slug in slugs:
            tenant_id = by_slug.get(slug)
            if tenant_id is None:
                print(f"{slug}: NOT FOUND")
                exit_code = 1
                continue

            resp = client.patch(f"{API_BASE}/api/v1/tenants/{tenant_id}/deactivate", headers=headers)
            if resp.status_code == 200:
                print(f"{slug}: DEACTIVATED")
            elif resp.status_code == 422 and resp.json().get("detail", {}).get("code") == "ALREADY_DEACTIVATED":
                print(f"{slug}: already deactivated")
            else:
                print(f"{slug}: FAILED ({resp.status_code}) {resp.text}")
                exit_code = 1

        return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
