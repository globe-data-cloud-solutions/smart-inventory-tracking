"""token_revocation_probe.py — Live probe for JWT revocation-on-password-change
and revocation-on-tenant-deactivate, through the real gateway + services.

Flow:
  1. Sign up a probe tenant (public self sign-up).
  2. Log in as the TA -> token A. Confirm A works.
  3. Change the TA's own password via PATCH /auth/password/{sub} -> expect A
     is now revoked (401 TOKEN_REVOKED on the next call).
  4. Log in with the new password -> token B. Confirm B works.
  5. Deactivate the probe tenant via scripts/probe/deactivate_tenants.py (SA
     API path) -> expect B is now revoked.
  6. Print the Redis TTLs for both revoked_before keys.

Requires the api-gateway running (default http://localhost:8000 — override
with API_BASE) and REDIS_URL/redis-cli available for the TTL check in P6.

Usage:
    python scripts/probe/token_revocation_probe.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import httpx
from jose import jwt

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")


def _print_step(step: str, expected: str, resp: httpx.Response) -> None:
    body = resp.text[:120]
    print(f"{step} {expected} -> {resp.status_code} {body}")


def main() -> int:
    slug = f"zz-tv-{int(time.time())}"
    probe_password = "ProbePass@2026!"

    with httpx.Client(timeout=15.0) as client:
        signup_resp = client.post(
            f"{API_BASE}/api/v1/tenants/public/signup",
            json={
                "company_name": f"Token Revocation Probe {slug}",
                "slug": slug,
                "organisation_type": "RETAILER",
                "tier": "GROWTH",
                "billing_period": "MONTHLY",
                "admin_full_name": "Probe Admin",
                "admin_email": f"{slug}@probe.local",
                "admin_password": probe_password,
                "accept_terms": True,
                "terms_version": os.environ.get("TERMS_VERSION", "2026-10"),
            },
        )
        print(f"signup -> {signup_resp.status_code} {signup_resp.text[:200]}")
        if signup_resp.status_code not in (200, 201):
            print(f"Signup failed, aborting. slug={slug}")
            return 1
        admin_email = f"{slug}@probe.local"
        print(
            f"probe tenant slug={slug} admin_email={admin_email} password={probe_password}"
        )

        # P1
        login_a = client.post(
            f"{API_BASE}/api/v1/auth/token",
            json={"email": admin_email, "password": probe_password},
        )
        if login_a.status_code != 200:
            _print_step("P1", "200", login_a)
            return 1
        token_a = login_a.json()["access_token"]
        sub = jwt.get_unverified_claims(token_a)["sub"]
        tenant_id = jwt.get_unverified_claims(token_a)["tenant_id"]

        resp_a1 = client.get(
            f"{API_BASE}/api/v1/tenants/me/plan",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        _print_step("P1", "200", resp_a1)

        # P2
        new_password = "ProbePass2@2026!"
        resp_p2 = client.patch(
            f"{API_BASE}/api/v1/auth/password/{sub}",
            json={
                "user_id": sub,
                "current_password": probe_password,
                "new_password": new_password,
            },
            headers={"Authorization": f"Bearer {token_a}"},
        )
        _print_step("P2", "200", resp_p2)

        # P3
        resp_p3 = client.get(
            f"{API_BASE}/api/v1/tenants/me/plan",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        _print_step("P3", "401 TOKEN_REVOKED", resp_p3)

        # P4
        login_b = client.post(
            f"{API_BASE}/api/v1/auth/token",
            json={"email": admin_email, "password": new_password},
        )
        if login_b.status_code != 200:
            _print_step("P4", "200", login_b)
            return 1
        token_b = login_b.json()["access_token"]
        resp_b1 = client.get(
            f"{API_BASE}/api/v1/tenants/me/plan",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        _print_step("P4", "200", resp_b1)

        # P5
        deactivate_script = os.path.join(
            os.path.dirname(__file__), "deactivate_tenants.py"
        )
        proc = subprocess.run(
            [sys.executable, deactivate_script, slug],
            capture_output=True,
            text=True,
        )
        print(
            f"P5 deactivate_tenants.py -> {proc.returncode} {proc.stdout.strip()} {proc.stderr.strip()[:200]}"
        )

        resp_b2 = client.get(
            f"{API_BASE}/api/v1/tenants/me/plan",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        _print_step("P5", "401 TOKEN_REVOKED", resp_b2)

        # P6
        for key in (
            f"revoked_before:user:{sub.lower()}",
            f"revoked_before:tenant:{str(tenant_id).lower()}",
        ):
            ttl_proc = subprocess.run(
                ["redis-cli", "TTL", key], capture_output=True, text=True
            )
            print(
                f"P6 TTL {key} -> {ttl_proc.stdout.strip()} {ttl_proc.stderr.strip()[:200]}"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
