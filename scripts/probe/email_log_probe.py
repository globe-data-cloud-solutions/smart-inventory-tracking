"""email_log_probe.py — Live proof of the pluggable email sender running in
"log" mode (ENVIRONMENT=local), through the real gateway + auth/tenant
services.

Flow:
  E1 sign up a probe tenant -> 201.
  E2 forgot-password for the probe owner -> 202 (expect a [DEV EMAIL] line).
  E3 forgot-password for a nonexistent address -> 202 (no [DEV EMAIL] line —
     account existence is never revealed).
  E4 reset-password with the token from E2's link, then log in with the new
     password -> 200.

Requires the api-gateway running (default http://localhost:8000 — override
with API_BASE). The [DEV EMAIL] lines are printed from this probe's own
knowledge of the request only to the extent the caller tails the auth/
tenant service logs separately — this script does not read log files itself.

Usage:
    python scripts/probe/email_log_probe.py
"""

from __future__ import annotations

import os
import sys
import time

import httpx

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")


def _print_step(step: str, expected: str, resp: httpx.Response) -> None:
    body = resp.text[:200]
    print(f"{step} {expected} -> {resp.status_code} {body}")


def main() -> int:
    slug = f"zz-mail-{int(time.time())}"
    probe_password = "ProbePass@2026!"
    admin_email = f"{slug}@probe.local"
    nobody_email = f"nobody-{int(time.time())}@probe.local"

    with httpx.Client(timeout=15.0) as client:
        # E1
        signup_resp = client.post(
            f"{API_BASE}/api/v1/tenants/public/signup",
            json={
                "company_name": f"Email Log Probe {slug}",
                "slug": slug,
                "organisation_type": "RETAILER",
                "tier": "GROWTH",
                "billing_period": "MONTHLY",
                "admin_full_name": "Probe Admin",
                "admin_email": admin_email,
                "admin_password": probe_password,
                "accept_terms": True,
                "terms_version": os.environ.get("TERMS_VERSION", "2026-10"),
            },
        )
        _print_step("E1", "201", signup_resp)
        if signup_resp.status_code not in (200, 201):
            print(f"Signup failed, aborting. slug={slug}")
            return 1
        print(
            f"probe tenant slug={slug} admin_email={admin_email} password={probe_password}"
        )

        # E2
        resp_e2 = client.post(
            f"{API_BASE}/api/v1/auth/forgot-password",
            json={"email": admin_email},
        )
        _print_step("E2", "202", resp_e2)

        # E3
        resp_e3 = client.post(
            f"{API_BASE}/api/v1/auth/forgot-password",
            json={"email": nobody_email},
        )
        _print_step("E3", "202 (no email line expected)", resp_e3)

        print(
            f"\nNow tail the auth/tenant service logs for '[DEV EMAIL] reset {admin_email}:' "
            f"to retrieve the reset token, then re-run with it for E4."
        )

        reset_token = os.environ.get("RESET_TOKEN")
        if not reset_token:
            print(
                "RESET_TOKEN not set — skipping E4. Set RESET_TOKEN=<token> and re-run to "
                "complete the reset + login check."
            )
            return 0

        # E4
        new_password = "ProbePass2@2026!"
        resp_e4a = client.post(
            f"{API_BASE}/api/v1/auth/reset-password",
            json={"token": reset_token, "new_password": new_password},
        )
        _print_step("E4a reset", "200", resp_e4a)

        resp_e4b = client.post(
            f"{API_BASE}/api/v1/auth/token",
            json={"email": admin_email, "password": new_password},
        )
        _print_step("E4b login", "200", resp_e4b)

        print(
            f"\ndeactivate when done: python scripts/probe/deactivate_tenants.py {slug}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
