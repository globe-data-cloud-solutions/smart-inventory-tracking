"""terms_reaccept_probe.py — Live proof of the account-owner terms
re-acceptance gate (feature (b)), exercised through the api-gateway.

Uses tenant A's owner account (created by public_signup.py against the
DEFAULT terms version, while auth/tenant are running with a TERMS_VERSION
override): logs in, expects terms_acceptance_required=true, accepts via
POST /tenants/me/terms-acceptance, repeats the POST (expects no duplicate
row), then logs in again expecting the flag is now false.

Usage:
    python scripts/probe/terms_reaccept_probe.py <owner_email> <owner_password>

Requires the api-gateway running (default http://localhost:8000 — override
with API_BASE).
"""

from __future__ import annotations

import os
import sys

import httpx

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")


def main(email: str, password: str) -> int:
    exit_code = 0
    with httpx.Client(timeout=15.0) as client:
        # T1 — login, expect terms_acceptance_required=true
        r1 = client.post(
            f"{API_BASE}/api/v1/auth/token", json={"email": email, "password": password}
        )
        body1 = r1.json()
        required1 = body1.get("terms_acceptance_required")
        ok1 = r1.status_code == 200 and required1 is True
        print(
            f"T1 200+required=true -> {r1.status_code} terms_acceptance_required={required1} {'OK' if ok1 else 'FAIL'}"
        )
        exit_code |= 0 if ok1 else 1
        token = body1.get("access_token", "")
        headers = {"Authorization": f"Bearer {token}"}

        # T2 — accept current terms
        r2 = client.post(
            f"{API_BASE}/api/v1/tenants/me/terms-acceptance", headers=headers, json={}
        )
        body2 = r2.json().get("data", {})
        ok2 = r2.status_code in (200, 201) and body2.get(
            "accepted_version"
        ) == body2.get("current_version")
        print(
            f"T2 200/201 accepted_version==current_version -> {r2.status_code} "
            f"accepted_version={body2.get('accepted_version')} current_version={body2.get('current_version')} "
            f"accepted_at={body2.get('accepted_at')} {'OK' if ok2 else 'FAIL'}"
        )
        exit_code |= 0 if ok2 else 1

        # T3 — repeat, expect same row (no duplicate)
        r3 = client.post(
            f"{API_BASE}/api/v1/tenants/me/terms-acceptance", headers=headers, json={}
        )
        body3 = r3.json().get("data", {})
        ok3 = r3.status_code in (200, 201) and body3.get("accepted_at") == body2.get(
            "accepted_at"
        )
        print(
            f"T3 same accepted_at as T2 -> {r3.status_code} accepted_at={body3.get('accepted_at')} "
            f"(T2 was {body2.get('accepted_at')}) {'OK' if ok3 else 'FAIL'}"
        )
        exit_code |= 0 if ok3 else 1

        # T4 — login again, expect terms_acceptance_required=false
        r4 = client.post(
            f"{API_BASE}/api/v1/auth/token", json={"email": email, "password": password}
        )
        body4 = r4.json()
        required4 = body4.get("terms_acceptance_required")
        ok4 = r4.status_code == 200 and required4 is False
        print(
            f"T4 200+required=false -> {r4.status_code} terms_acceptance_required={required4} {'OK' if ok4 else 'FAIL'}"
        )
        exit_code |= 0 if ok4 else 1

    return exit_code


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(
            "Usage: python scripts/probe/terms_reaccept_probe.py <owner_email> <owner_password>"
        )
        sys.exit(1)
    sys.exit(main(sys.argv[1], sys.argv[2]))
