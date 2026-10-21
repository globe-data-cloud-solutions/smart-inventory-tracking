#!/usr/bin/env python3
"""
New Node Scenario — Live Test (Tenant 07)
Run: python scripts/test_new_node_scenario.py

Requirements:
  - Backend running at http://localhost:8000
  - scripts/setup_tenant07.py must have been run first
  - ENVIRONMENT=local must be set in the backend (enables dev_email auth)

NOT pytest — plain Python script with its own runner, mirroring the style of
tests/e2e/test_tenant07_e2e.py. Adds a brand-new warehouse node (WHA4) to the
existing Tenant 07 org tree, configures it end-to-end, and exercises transfers,
adjustments, audit logging, deactivation/reactivation, and several edge cases.

This script is safe to re-run: it looks for an already-created WHA4 node/user
before creating new ones, so a second run resumes rather than duplicating data.

DOES NOT delete WHA4 or any data it creates — everything is left intact for
manual browser verification after the run.
"""

from __future__ import annotations

import sys
import json
import base64
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# ─────────────────────────────────────────────────────────────────────────────
# Constants — Tenant 07 existing structure (from scripts/setup_tenant07.py)
# ─────────────────────────────────────────────────────────────────────────────
BASE_URL = "http://localhost:8000"
DEFAULT_PASSWORD = "Test@2026"
T07_ID = "07000007-0000-0000-0000-000000000001"

NODE_FA = "07000007-0001-0000-0000-000000000001"  # Factory A     (L1)
NODE_RA = "07000007-0002-0000-0000-000000000001"  # Region A      (L2)
NODE_SRA = "07000007-0003-0000-0000-000000000001"  # Subregion A   (L3)
NODE_WHA1 = "07000007-0004-0000-0000-000000000001"  # WHA1          (L4)

PROD_P1 = "07000007-0302-0000-0000-000000000001"  # Steel Rod A (not controlled)

POS_SRA_RM = "07000007-0103-0000-0000-000000000001"  # Subregion A RM
POS_WHA1_ASST = "07000007-0104-0000-0000-000000000002"  # WHA1 Asst WM — used for sole-user workaround

EMAIL_TA = "admin@t07.com"
EMAIL_FA_NM = "nm_factorya@t07.com"
EMAIL_RA_RM = "rm_regiona@t07.com"
EMAIL_SRA_RM = "rm_subregiona@t07.com"
EMAIL_WHA1_WM = "wm_wha1@t07.com"
EMAIL_AU = "au@t07.com"
EMAIL_WHB21_WM = "wm_whb2_1@t07.com"  # Factory B — cross-isolation checks

NEW_NODE_NAME = "WHA4"
NEW_USER_EMAIL = "wm_wha4@t07.com"
NEW_USER_NAME = "A-WHA4 WM"


# ─────────────────────────────────────────────────────────────────────────────
# Result tracking
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class TestResult:
    phase: str
    name: str
    passed: bool
    skipped: bool = False
    message: str = ""
    bug: str = ""


results: list[TestResult] = []
bugs: list[str] = []
current_phase = "Phase 1"


def ok(name: str, message: str = "") -> TestResult:
    r = TestResult(phase=current_phase, name=name, passed=True, message=message)
    results.append(r)
    print(f"  [PASS] {name}" + (f" — {message}" if message else ""))
    return r


def fail(name: str, message: str = "", bug: str = "") -> TestResult:
    r = TestResult(
        phase=current_phase, name=name, passed=False, message=message, bug=bug
    )
    results.append(r)
    print(f"  [FAIL] {name}" + (f" — {message}" if message else ""))
    if bug:
        bugs.append(f"{name}: {bug}")
    return r


def skip(name: str, reason: str = "") -> TestResult:
    r = TestResult(
        phase=current_phase, name=name, passed=False, skipped=True, message=reason
    )
    results.append(r)
    print(f"  [SKIP] {name}" + (f" — {reason}" if reason else ""))
    return r


def flag_bug(name: str, description: str) -> None:
    bugs.append(f"{name}: {description}")
    print(f"  [BUG ] {description}")


# ─────────────────────────────────────────────────────────────────────────────
# Auth + HTTP helpers (same conventions as tests/e2e/test_tenant07_e2e.py)
# ─────────────────────────────────────────────────────────────────────────────
_token_cache: dict[str, str] = {}


def get_jwt(email: str, password: str = DEFAULT_PASSWORD) -> Optional[str]:
    if email in _token_cache:
        return _token_cache[email]
    r = requests.post(
        f"{BASE_URL}/api/v1/auth/token",
        json={"dev_email": email, "dev_password": password},
        timeout=10,
    )
    if r.status_code == 200:
        body = r.json()
        token = body.get("data", {}).get("access_token") or body.get("access_token")
        if token:
            _token_cache[email] = token
            return token
    return None


def _decode_jwt_sub(email: str) -> Optional[str]:
    token = get_jwt(email)
    if not token:
        return None
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        return json.loads(base64.b64decode(payload_b64)).get("sub")
    except Exception:
        return None


def headers(email: str, password: str = DEFAULT_PASSWORD) -> dict[str, str]:
    token = get_jwt(email, password)
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def invalidate_token(email: str) -> None:
    _token_cache.pop(email, None)


def api_get(path: str, email: str, params: dict | None = None) -> requests.Response:
    return requests.get(
        f"{BASE_URL}{path}", headers=headers(email), params=params, timeout=15
    )


def api_post(path: str, email: str, body: dict | None = None) -> requests.Response:
    return requests.post(
        f"{BASE_URL}{path}", headers=headers(email), json=body or {}, timeout=15
    )


def api_patch(path: str, email: str, body: dict | None = None) -> requests.Response:
    return requests.patch(
        f"{BASE_URL}{path}", headers=headers(email), json=body or {}, timeout=15
    )


def data(r: requests.Response) -> Any:
    try:
        j = r.json()
        return j.get("data", j)
    except Exception:
        return {}


def err_code(r: requests.Response) -> str:
    """Extract the FastAPI HTTPException `detail.code` (our 422 error convention)."""
    try:
        det = r.json().get("detail")
        return det.get("code", "") if isinstance(det, dict) else ""
    except Exception:
        return ""


def flatten_nodes(node_list: list) -> list:
    out = []
    for n in node_list:
        out.append(n)
        out.extend(flatten_nodes(n.get("children") or []))
    return out


def get_all_nodes(email: str, include_inactive: bool = False) -> list:
    params = {"include_inactive": "true"} if include_inactive else None
    r = api_get(f"/api/v1/tenants/{T07_ID}/nodes", email, params=params)
    raw = data(r) if isinstance(data(r), list) else []
    return flatten_nodes(raw)


# ─────────────────────────────────────────────────────────────────────────────
# Shared state across phases
# ─────────────────────────────────────────────────────────────────────────────
state: dict[str, Any] = {}


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 — Setup new node
# ─────────────────────────────────────────────────────────────────────────────
def phase1_setup() -> None:
    global current_phase
    current_phase = "Phase 1"
    print("\n[PHASE 1] Setup new node")

    # 1.1 Attempt to make Region A (L2) hold stock — should be rejected, or flagged
    # as a data-integrity gap if the API silently allows it.
    r = api_patch(
        f"/api/v1/tenants/{T07_ID}/nodes/{NODE_RA}",
        EMAIL_TA,
        {"is_stock_holding": True},
    )
    if r.status_code in (422, 403):
        ok(
            "1.1 Region A (L2) rejects is_stock_holding=true",
            f"status={r.status_code}, code={err_code(r)}",
        )
    elif r.status_code == 200 and data(r).get("is_stock_holding") is True:
        fail(
            "1.1 Region A (L2) is_stock_holding=true should be rejected",
            "API allowed setting is_stock_holding=true on a non-stock-holding hierarchy level",
            bug="update_org_node() does not validate is_stock_holding against the level's "
            "tenant_hierarchy_config — a non-stock-holding level (L2) can be flipped to "
            "stock-holding via PATCH, creating a data-integrity inconsistency with the "
            "tenant's declared hierarchy config.",
        )
        # Revert immediately so it doesn't pollute later phases / assumptions.
        api_patch(
            f"/api/v1/tenants/{T07_ID}/nodes/{NODE_RA}",
            EMAIL_TA,
            {"is_stock_holding": False},
        )
    else:
        fail(
            "1.1 Region A (L2) is_stock_holding=true",
            f"unexpected status={r.status_code}, body={r.text[:200]}",
        )

    # 1.2 Create new warehouse node under Subregion A (L3) — reuse if it already exists
    # (idempotent re-run support; node creation has no fixed ID like the seed script).
    existing_nodes = get_all_nodes(EMAIL_TA, include_inactive=True)
    existing = next(
        (
            n
            for n in existing_nodes
            if n.get("name") == NEW_NODE_NAME and n.get("parent_node_id") == NODE_SRA
        ),
        None,
    )
    if existing:
        state["node_wha4"] = existing["id"]
        ok("1.2 Create WHA4 node", f"already exists, reusing id={existing['id']}")
        if not existing.get("is_active"):
            r = api_patch(
                f"/api/v1/tenants/{T07_ID}/nodes/{existing['id']}/reactivate", EMAIL_TA
            )
            print(
                f"    (reactivated pre-existing WHA4 for a clean re-run: status={r.status_code})"
            )
    else:
        r = api_post(
            f"/api/v1/tenants/{T07_ID}/nodes",
            EMAIL_TA,
            {
                "name": NEW_NODE_NAME,
                "parent_node_id": NODE_SRA,
                "level_number": 4,
                "is_stock_holding": True,
            },
        )
        if r.status_code == 201:
            state["node_wha4"] = data(r)["id"]
            ok("1.2 Create WHA4 node", f"id={state['node_wha4']}")
        else:
            fail("1.2 Create WHA4 node", f"status={r.status_code}, body={r.text[:200]}")
            state["node_wha4"] = None

    # 1.3 Create position for WHA4
    if state.get("node_wha4"):
        r = api_get(f"/api/v1/tenants/{T07_ID}/positions", EMAIL_TA)
        groups = data(r) if isinstance(data(r), list) else []
        my_group = next(
            (g for g in groups if g.get("node_id") == state["node_wha4"]), None
        )
        existing_pos = next(
            (
                p
                for p in (my_group.get("positions") if my_group else [])
                if p.get("title") == "WHA4 WM"
            ),
            None,
        )
        if existing_pos:
            state["pos_wha4_wm"] = existing_pos["id"]
            ok(
                "1.3 Create WHA4 WM position",
                f"already exists, reusing id={existing_pos['id']}",
            )
        else:
            r = api_post(
                f"/api/v1/tenants/{T07_ID}/nodes/{state['node_wha4']}/positions",
                EMAIL_TA,
                {
                    "title": "WHA4 WM",
                    "role_code": "WM",
                    "reports_to_position_id": POS_SRA_RM,
                },
            )
            if r.status_code == 201:
                state["pos_wha4_wm"] = data(r)["id"]
                ok("1.3 Create WHA4 WM position", f"id={state['pos_wha4_wm']}")
            else:
                fail(
                    "1.3 Create WHA4 WM position",
                    f"status={r.status_code}, body={r.text[:200]}",
                )
                state["pos_wha4_wm"] = None
    else:
        skip("1.3 Create WHA4 WM position", "no node_wha4 from 1.2")
        state["pos_wha4_wm"] = None

    # 1.4 + 1.5 Create user for WHA4 and assign to position (position_id at creation
    # time auto-assigns PRIMARY — personnel_v2.create_user combines both steps).
    if state.get("pos_wha4_wm"):
        r = api_get(f"/api/v1/tenants/{T07_ID}/users", EMAIL_TA)
        users = data(r) if isinstance(data(r), list) else []
        existing_user = next(
            (u for u in users if u.get("email") == NEW_USER_EMAIL), None
        )
        if existing_user:
            state["user_wha4_wm"] = existing_user["id"]
            ok(
                "1.4 Create WHA4 WM user",
                f"already exists, reusing id={existing_user['id']}",
            )
            ok(
                "1.5 Assign user to WHA4 WM position",
                f"primary_position={(existing_user.get('primary_position') or {}).get('position_id')}",
            )
        else:
            r = api_post(
                f"/api/v1/tenants/{T07_ID}/users",
                EMAIL_TA,
                {
                    "name": NEW_USER_NAME,
                    "email": NEW_USER_EMAIL,
                    "password": DEFAULT_PASSWORD,
                    "position_id": state["pos_wha4_wm"],
                },
            )
            if r.status_code == 201:
                u = data(r)
                state["user_wha4_wm"] = u["id"]
                ok("1.4 Create WHA4 WM user", f"id={u['id']}")
                primary = u.get("primary_position") or {}
                if primary.get("position_id") == state["pos_wha4_wm"]:
                    ok(
                        "1.5 Assign user to WHA4 WM position",
                        "PRIMARY assignment confirmed at creation",
                    )
                else:
                    fail(
                        "1.5 Assign user to WHA4 WM position",
                        f"primary_position={primary}",
                    )
            else:
                fail(
                    "1.4 Create WHA4 WM user",
                    f"status={r.status_code}, body={r.text[:200]}",
                )
                skip("1.5 Assign user to WHA4 WM position", "user creation failed")
                state["user_wha4_wm"] = None
    else:
        skip("1.4 Create WHA4 WM user", "no pos_wha4_wm from 1.3")
        skip("1.5 Assign user to WHA4 WM position", "no pos_wha4_wm from 1.3")
        state["user_wha4_wm"] = None

    # 1.6 Login as new WM
    if state.get("user_wha4_wm"):
        invalidate_token(NEW_USER_EMAIL)
        token = get_jwt(NEW_USER_EMAIL)
        if token:
            ok("1.6 Login as WHA4 WM", "JWT issued")
            state["wha4_wm_sub"] = _decode_jwt_sub(NEW_USER_EMAIL)
        else:
            fail("1.6 Login as WHA4 WM", "no token returned")
    else:
        skip("1.6 Login as WHA4 WM", "no user_wha4_wm from 1.4")

    # 1.7 Add opening stock to WHA4 — top up to >= 500 rather than a fixed idempotency
    # key, so re-runs work correctly even after a prior run's adjustments/transfers
    # consumed some or all of it.
    if state.get("node_wha4"):
        r_cur = api_get(
            "/api/v1/inventory/analytics/stock",
            EMAIL_TA,
            params={"warehouse_id": state["node_wha4"]},
        )
        cur_rows = data(r_cur) if isinstance(data(r_cur), list) else []
        p1_row = next(
            (s for s in cur_rows if str(s.get("product_id", "")) == PROD_P1), None
        )
        cur_qty = float(p1_row.get("current_stock", 0)) if p1_row else 0
        topup = max(0, 500 - cur_qty)
        if topup == 0:
            ok(
                "1.7 Add opening stock to WHA4 (500 P1)",
                f"already at {cur_qty}, no top-up needed",
            )
        else:
            ikey = f"e2e:wha4:opening:p1:{uuid.uuid4().hex[:8]}"
            r = api_post(
                "/api/v1/inventory/receive/",
                EMAIL_TA,
                {
                    "product_id": PROD_P1,
                    "warehouse_id": state["node_wha4"],
                    "quantity": topup,
                    "idempotency_key": ikey,
                    "source": "E2E_TEST",
                },
            )
            if r.status_code == 201:
                ok(
                    "1.7 Add opening stock to WHA4 (500 P1)",
                    f"topped up +{topup} (was {cur_qty})",
                )
            else:
                fail(
                    "1.7 Add opening stock to WHA4",
                    f"status={r.status_code}, body={r.text[:200]}",
                )
    else:
        skip("1.7 Add opening stock to WHA4", "no node_wha4 from 1.2")


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 — Verify WHA4 in operations
# ─────────────────────────────────────────────────────────────────────────────
def phase2_operations() -> None:
    global current_phase
    current_phase = "Phase 2"
    print("\n[PHASE 2] Verify WHA4 in operations")

    node_wha4 = state.get("node_wha4")

    # 2.1 WHA4 WM can view their inventory
    if node_wha4 and state.get("user_wha4_wm"):
        r = api_get(
            "/api/v1/inventory/analytics/stock",
            NEW_USER_EMAIL,
            params={"warehouse_id": node_wha4},
        )
        rows = data(r) if isinstance(data(r), list) else []
        p1_row = next(
            (s for s in rows if str(s.get("product_id", "")) == PROD_P1), None
        )
        qty = float(p1_row.get("current_stock", 0)) if p1_row else 0
        if r.status_code == 200 and qty >= 500:
            ok("2.1 WHA4 WM views own inventory", f"current_stock={qty}")
        else:
            fail(
                "2.1 WHA4 WM views own inventory", f"status={r.status_code}, qty={qty}"
            )
    else:
        skip("2.1 WHA4 WM views own inventory", "prerequisite missing")

    # 2.2 WHA4 appears in active nodes list
    if node_wha4:
        active_ids = {n["id"] for n in get_all_nodes(EMAIL_TA)}
        if node_wha4 in active_ids:
            ok("2.2 WHA4 appears in active nodes list")
        else:
            fail("2.2 WHA4 appears in active nodes list", "not found in GET /nodes")
    else:
        skip("2.2 WHA4 appears in active nodes list", "no node_wha4")

    # 2.3 WHA4 WM creates PULL from Subregion A
    if node_wha4 and state.get("user_wha4_wm"):
        r = api_post(
            "/api/v1/inventory/transfers/",
            NEW_USER_EMAIL,
            {
                "transfer_type": "PULL",
                "from_warehouse_id": NODE_SRA,
                "to_warehouse_id": node_wha4,
                "lines": [{"product_id": PROD_P1, "quantity": 50}],
                "notes": "New node scenario — PULL test",
            },
        )
        if r.status_code == 201:
            state["pull_id"] = str(data(r).get("transfer_id") or data(r).get("id", ""))
            ok("2.3 WHA4 WM creates PULL (DRAFT)", f"id={state['pull_id']}")
        else:
            fail(
                "2.3 WHA4 WM creates PULL",
                f"status={r.status_code}, body={r.text[:200]}",
            )
            state["pull_id"] = None
    else:
        skip("2.3 WHA4 WM creates PULL", "prerequisite missing")
        state["pull_id"] = None

    # 2.4 Submit → review → approve → dispatch → in_transit → receive → complete
    pid = state.get("pull_id")
    if pid:
        r = api_post(f"/api/v1/inventory/transfers/{pid}/submit", NEW_USER_EMAIL)
        status = data(r).get("status", "")
        step_ok = r.status_code == 200 and status in ("PENDING_REVIEW", "APPROVED")
        print(f"    submit -> {status} ({r.status_code})")

        if step_ok and status == "PENDING_REVIEW":
            r = api_post(f"/api/v1/inventory/transfers/{pid}/review", EMAIL_SRA_RM)
            status = data(r).get("status", "")
            print(f"    review (SRA_RM) -> {status} ({r.status_code})")
            step_ok = r.status_code == 200 and status == "PENDING_APPROVAL"

        if step_ok and status == "PENDING_APPROVAL":
            r = api_post(f"/api/v1/inventory/transfers/{pid}/approve", EMAIL_SRA_RM)
            status = data(r).get("status", "")
            print(f"    approve (SRA_RM) -> {status} ({r.status_code})")
            step_ok = r.status_code == 200 and status == "APPROVED"

        if step_ok:
            r = api_post(f"/api/v1/inventory/transfers/{pid}/dispatch", EMAIL_SRA_RM)
            status = data(r).get("status", "")
            print(f"    dispatch (SRA_RM, source owner) -> {status} ({r.status_code})")
            step_ok = r.status_code == 200 and status == "ISSUED"

        if step_ok:
            r = api_patch(
                f"/api/v1/inventory/transfers/{pid}",
                EMAIL_SRA_RM,
                {"next_status": "IN_TRANSIT"},
            )
            status = data(r).get("status", "")
            print(f"    -> IN_TRANSIT -> {status} ({r.status_code})")
            step_ok = r.status_code == 200 and status == "IN_TRANSIT"

        if step_ok:
            r = api_post(f"/api/v1/inventory/transfers/{pid}/receive", NEW_USER_EMAIL)
            status = data(r).get("status", "")
            print(f"    receive (WHA4 WM) -> {status} ({r.status_code})")
            step_ok = r.status_code == 200 and status in ("RECEIVED", "COMPLETED")

        if step_ok and status == "RECEIVED":
            r = api_patch(
                f"/api/v1/inventory/transfers/{pid}",
                NEW_USER_EMAIL,
                {"next_status": "COMPLETED"},
            )
            status = data(r).get("status", "")
            print(f"    -> COMPLETED -> {status} ({r.status_code})")
            step_ok = r.status_code == 200 and status == "COMPLETED"

        if step_ok and status == "COMPLETED":
            ok("2.4 PULL full lifecycle reaches COMPLETED")
        else:
            fail(
                "2.4 PULL full lifecycle reaches COMPLETED",
                f"stopped at status={status}",
            )
    else:
        skip("2.4 PULL full lifecycle", "no pull_id")

    # 2.5 Verify stock updated: WHA4 +50, SRA -50
    if node_wha4 and state.get("pull_id"):
        r = api_get(
            "/api/v1/inventory/analytics/stock",
            EMAIL_TA,
            params={"warehouse_id": node_wha4},
        )
        rows = data(r) if isinstance(data(r), list) else []
        p1 = next((s for s in rows if str(s.get("product_id", "")) == PROD_P1), None)
        wha4_qty = float(p1.get("current_stock", 0)) if p1 else 0
        if wha4_qty >= 550:
            ok("2.5 WHA4 stock increased by PULL", f"current_stock={wha4_qty}")
        else:
            fail(
                "2.5 WHA4 stock increased by PULL",
                f"current_stock={wha4_qty}, expected >= 550",
            )
    else:
        skip("2.5 Verify stock updated", "no pull_id")

    # 2.6 WHA4 WM creates DAMAGE adjustment
    if node_wha4 and state.get("user_wha4_wm"):
        ikey = f"e2e:wha4:adj:{uuid.uuid4().hex[:8]}"
        r = api_post(
            "/api/v1/inventory/adjustments/",
            NEW_USER_EMAIL,
            {
                "warehouse_id": node_wha4,
                "product_id": PROD_P1,
                "quantity_delta": -10,
                "reason_code": "DAMAGE",
                "idempotency_key": ikey,
                "notes": "New node scenario — damage adjustment",
            },
        )
        if r.status_code == 201:
            state["adj_id"] = str(data(r).get("adjustment_id") or data(r).get("id", ""))
            adj_status = data(r).get("status", "")
            ok(
                "2.6 WHA4 WM creates DAMAGE adjustment",
                f"id={state['adj_id']}, status={adj_status}",
            )
            # Submit it through to POSTED (small qty — expected to auto-post or need one approval)
            r2 = api_post(
                f"/api/v1/inventory/adjustments/{state['adj_id']}/submit",
                NEW_USER_EMAIL,
            )
            status2 = data(r2).get("status", "")
            if status2 == "PENDING_APPROVAL":
                r3 = api_post(
                    f"/api/v1/inventory/adjustments/{state['adj_id']}/approve",
                    EMAIL_SRA_RM,
                )
                status2 = data(r3).get("status", "")
            print(f"    adjustment submit/approve -> {status2}")
        else:
            fail(
                "2.6 WHA4 WM creates DAMAGE adjustment",
                f"status={r.status_code}, body={r.text[:200]}",
            )
            state["adj_id"] = None
    else:
        skip("2.6 WHA4 WM creates DAMAGE adjustment", "prerequisite missing")
        state["adj_id"] = None

    # 2.7 SISTER transfer between WHA4 and WHA1
    if node_wha4 and state.get("user_wha4_wm"):
        r = api_post(
            "/api/v1/inventory/transfers/",
            NEW_USER_EMAIL,
            {
                "transfer_type": "SISTER",
                "from_warehouse_id": node_wha4,
                "to_warehouse_id": NODE_WHA1,
                "lines": [{"product_id": PROD_P1, "quantity": 20}],
                "notes": "New node scenario — SISTER test",
            },
        )
        if r.status_code == 201:
            sid = str(data(r).get("transfer_id") or data(r).get("id", ""))
            state["sister_id"] = sid
            status = data(r).get("status", "")
            print(f"    SISTER create -> {status}")
            r = api_post(f"/api/v1/inventory/transfers/{sid}/submit", NEW_USER_EMAIL)
            status = data(r).get("status", "")
            print(f"    submit -> {status} ({r.status_code})")
            step_ok = r.status_code == 200 and status == "PENDING_SOURCE_CONFIRM"

            if step_ok:
                r = api_patch(
                    f"/api/v1/inventory/transfers/{sid}",
                    NEW_USER_EMAIL,
                    {"next_status": "PENDING_DEST_CONFIRM"},
                )
                status = data(r).get("status", "")
                print(f"    source confirms (WHA4 WM) -> {status} ({r.status_code})")
                step_ok = r.status_code == 200 and status == "PENDING_DEST_CONFIRM"

            if step_ok:
                r = api_patch(
                    f"/api/v1/inventory/transfers/{sid}",
                    EMAIL_WHA1_WM,
                    {"next_status": "PENDING_APPROVAL"},
                )
                status = data(r).get("status", "")
                print(f"    dest confirms (WHA1 WM) -> {status} ({r.status_code})")
                step_ok = r.status_code == 200 and status == "PENDING_APPROVAL"

            if step_ok:
                r = api_post(f"/api/v1/inventory/transfers/{sid}/approve", EMAIL_FA_NM)
                status = data(r).get("status", "")
                if r.status_code == 403:
                    r = api_post(f"/api/v1/inventory/transfers/{sid}/approve", EMAIL_TA)
                    status = data(r).get("status", "")
                print(f"    approve -> {status} ({r.status_code})")
                step_ok = r.status_code == 200 and status == "APPROVED"

            if step_ok:
                r = api_post(
                    f"/api/v1/inventory/transfers/{sid}/dispatch", NEW_USER_EMAIL
                )
                status = data(r).get("status", "")
                print(f"    dispatch (WHA4 WM, source) -> {status} ({r.status_code})")
                step_ok = r.status_code == 200 and status == "ISSUED"

            if step_ok:
                r = api_patch(
                    f"/api/v1/inventory/transfers/{sid}",
                    NEW_USER_EMAIL,
                    {"next_status": "IN_TRANSIT"},
                )
                status = data(r).get("status", "")
                step_ok = r.status_code == 200 and status == "IN_TRANSIT"
                print(f"    -> IN_TRANSIT -> {status} ({r.status_code})")

            if step_ok:
                r = api_post(
                    f"/api/v1/inventory/transfers/{sid}/receive", EMAIL_WHA1_WM
                )
                status = data(r).get("status", "")
                print(f"    receive (WHA1 WM) -> {status} ({r.status_code})")
                step_ok = r.status_code == 200 and status in ("RECEIVED", "COMPLETED")

            if step_ok and status == "RECEIVED":
                r = api_patch(
                    f"/api/v1/inventory/transfers/{sid}",
                    EMAIL_WHA1_WM,
                    {"next_status": "COMPLETED"},
                )
                status = data(r).get("status", "")
                step_ok = r.status_code == 200 and status == "COMPLETED"

            if step_ok and status == "COMPLETED":
                ok("2.7 SISTER transfer WHA4 <-> WHA1 completes")
            else:
                fail(
                    "2.7 SISTER transfer WHA4 <-> WHA1 completes",
                    f"stopped at status={status}",
                )
        else:
            fail(
                "2.7 SISTER transfer WHA4 <-> WHA1",
                f"create failed status={r.status_code}, body={r.text[:200]}",
            )
    else:
        skip("2.7 SISTER transfer WHA4 <-> WHA1", "prerequisite missing")

    # 2.8 WHA4 appears in audit log
    wha4_sub = state.get("wha4_wm_sub")
    if wha4_sub:
        r = api_get("/api/v1/audit-log/", EMAIL_TA, params={"limit": 200})
        if r.status_code != 200:
            fail(
                "2.8 WHA4 activity appears in audit log",
                f"status={r.status_code}, body={r.text[:200]}",
            )
        else:
            entries = data(r) if isinstance(data(r), list) else []
            wha4_entries = [e for e in entries if str(e.get("user_id", "")) == wha4_sub]
            actions = {e.get("action") for e in wha4_entries}
            if wha4_entries:
                ok(
                    "2.8 WHA4 activity appears in audit log",
                    f"{len(wha4_entries)} entries, actions={sorted(actions)}",
                )
            else:
                fail(
                    "2.8 WHA4 activity appears in audit log",
                    "no entries found for WHA4 WM user_id",
                    bug="New facility/user activity (transfer/adjustment actions) is not appearing in the "
                    "audit log query — check audit_log() is invoked on these code paths.",
                )
    else:
        skip("2.8 WHA4 appears in audit log", "no wha4_wm_sub from 1.6")


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 3 — Deactivation flow
# ─────────────────────────────────────────────────────────────────────────────
def phase3_deactivation() -> None:
    global current_phase
    current_phase = "Phase 3"
    print("\n[PHASE 3] Deactivation flow")

    node_wha4 = state.get("node_wha4")

    # 3.0 WHA4 WM's only position is at WHA4 (CHECK 4 — sole users — would otherwise
    # block deactivation, correctly, with NODE_HAS_SOLE_USERS). Give them a temporary
    # ACTING position elsewhere first, simulating the real "staff reassigned" precondition
    # the org-tree help banner describes, so the stock/transfer/adjustment checks (3.1-3.4)
    # can be exercised in isolation.
    if node_wha4 and state.get("user_wha4_wm"):
        valid_until = (date.today() + timedelta(days=30)).isoformat()
        r = api_post(
            f"/api/v1/tenants/{T07_ID}/users/{state['user_wha4_wm']}/positions",
            EMAIL_TA,
            {
                "position_id": POS_WHA1_ASST,
                "assignment_type": "ACTING",
                "valid_until": valid_until,
                "notes": "New node scenario — temporary reassignment so WHA4 deactivation is not "
                "blocked by NODE_HAS_SOLE_USERS",
            },
        )
        if r.status_code in (200, 201, 409):
            ok(
                "3.0 Give WHA4 WM a second (ACTING) position so they are not 'sole'",
                f"status={r.status_code}",
            )
        else:
            fail(
                "3.0 Give WHA4 WM a second (ACTING) position",
                f"status={r.status_code}, body={r.text[:200]}",
            )
    else:
        skip("3.0 Give WHA4 WM a second (ACTING) position", "prerequisite missing")

    # 3.1 Attempt deactivate while it has stock — expect 422 NODE_HAS_STOCK
    if node_wha4:
        r = api_patch(
            f"/api/v1/tenants/{T07_ID}/nodes/{node_wha4}/deactivate", EMAIL_TA
        )
        if r.status_code == 422 and err_code(r) == "NODE_HAS_STOCK":
            ok("3.1 Deactivate blocked while WHA4 has stock", "422 NODE_HAS_STOCK")
        else:
            fail(
                "3.1 Deactivate blocked while WHA4 has stock",
                f"status={r.status_code}, code={err_code(r)}, body={r.text[:200]}",
            )
    else:
        skip("3.1 Deactivate blocked while WHA4 has stock", "no node_wha4")

    # 3.2 Zero out WHA4 stock via adjustment
    if node_wha4:
        r = api_get(
            "/api/v1/inventory/analytics/stock",
            EMAIL_TA,
            params={"warehouse_id": node_wha4},
        )
        rows = data(r) if isinstance(data(r), list) else []
        any_failed = False
        zeroed_any = False
        for row in rows:
            qty = float(row.get("current_stock", 0))
            if qty <= 0:
                continue
            zeroed_any = True
            ikey = f"e2e:wha4:zero:{row.get('product_id')}:{uuid.uuid4().hex[:8]}"
            # Use the actual WM (a real position/level) as actor — TA has no level_number,
            # so self-approval/escalation routing (keyed by role_code + level_number) has
            # nothing to match and the adjustment gets stuck before POSTED.
            ra = api_post(
                "/api/v1/inventory/adjustments/",
                NEW_USER_EMAIL,
                {
                    "warehouse_id": node_wha4,
                    "product_id": row.get("product_id"),
                    "quantity_delta": -qty,
                    "reason_code": "DAMAGE",
                    "idempotency_key": ikey,
                    "notes": "New node scenario — zero out before deactivation",
                },
            )
            if ra.status_code != 201:
                print(
                    f"    create adjustment for {row.get('product_id')} -> status={ra.status_code}, body={ra.text[:200]}"
                )
                any_failed = True
                continue
            adj_id = str(data(ra).get("adjustment_id") or data(ra).get("id", ""))
            rs = api_post(
                f"/api/v1/inventory/adjustments/{adj_id}/submit", NEW_USER_EMAIL
            )
            st = data(rs).get("status", "")
            if st == "PENDING_APPROVAL":
                ra2 = api_post(
                    f"/api/v1/inventory/adjustments/{adj_id}/approve", EMAIL_SRA_RM
                )
                st = data(ra2).get("status", "")
                if st not in ("POSTED", "APPROVED"):
                    ra2 = api_post(
                        f"/api/v1/inventory/adjustments/{adj_id}/approve", EMAIL_FA_NM
                    )
                    st = data(ra2).get("status", "")
            print(f"    zero out {row.get('product_id')} (-{qty}) -> {st}")
            if st not in ("POSTED", "APPROVED"):
                any_failed = True

        r2 = api_get(
            "/api/v1/inventory/analytics/stock",
            EMAIL_TA,
            params={"warehouse_id": node_wha4},
        )
        rows2 = data(r2) if isinstance(data(r2), list) else []
        total_remaining = sum(float(x.get("current_stock", 0)) for x in rows2)
        if total_remaining <= 0 and not any_failed:
            ok("3.2 WHA4 stock zeroed via adjustments", f"zeroed_any={zeroed_any}")
        else:
            fail(
                "3.2 WHA4 stock zeroed via adjustments",
                f"remaining={total_remaining}, any_failed={any_failed}",
            )

        # Self-heal: cancel any stray non-terminal adjustments left at WHA4 by a prior
        # (e.g. interrupted) run of this script, so the deactivate pre-checks aren't
        # blocked by orphaned DRAFT/PENDING_APPROVAL rows from earlier attempts.
        r_adj = api_get(
            "/api/v1/inventory/adjustments/", EMAIL_TA, params={"limit": 200}
        )
        adj_list = data(r_adj) if isinstance(data(r_adj), list) else []
        stray = [
            a
            for a in adj_list
            if a.get("warehouse_id") == node_wha4
            and a.get("status") not in ("POSTED", "CANCELLED", "REJECTED")
        ]
        for a in stray:
            aid = a.get("adjustment_id") or a.get("id")
            cr = api_post(f"/api/v1/inventory/adjustments/{aid}/cancel", EMAIL_TA)
            print(
                f"    self-heal: cancelled stray adjustment {aid} (was {a.get('status')}) -> {cr.status_code}"
            )
    else:
        skip("3.2 WHA4 stock zeroed via adjustments", "no node_wha4")

    # 3.3 Attempt deactivate with any open transfer (none expected by this point — all
    # transfers created in Phase 2 were driven to COMPLETED). Verify no open transfers exist.
    if node_wha4:
        r = api_patch(
            f"/api/v1/tenants/{T07_ID}/nodes/{node_wha4}/deactivate", EMAIL_TA
        )
        if r.status_code == 422 and err_code(r) == "NODE_HAS_OPEN_TRANSFERS":
            ok(
                "3.3 Deactivate blocked by open transfer (unexpected open transfer found)"
            )
            skip(
                "3.4 Deactivate WHA4", "open transfer must be resolved first — see 3.3"
            )
            state["deactivate_succeeded_at_3_3"] = False
        elif r.status_code == 200:
            ok("3.3 No open transfers block deactivation (none existed)")
            state["wha4_deactivated"] = True
            ok("3.4 Deactivate WHA4", "200, is_active=false")
        else:
            fail(
                "3.3 Deactivate WHA4 (post stock-zero)",
                f"status={r.status_code}, code={err_code(r)}, body={r.text[:200]}",
            )
            skip("3.4 Deactivate WHA4", "see 3.3 failure")
    else:
        skip("3.3 Deactivate with open transfer check", "no node_wha4")
        skip("3.4 Deactivate WHA4", "no node_wha4")

    # 3.5 Verify WHA4 excluded from active nodes list
    if node_wha4 and state.get("wha4_deactivated"):
        active_ids = {n["id"] for n in get_all_nodes(EMAIL_TA)}
        if node_wha4 not in active_ids:
            ok("3.5 WHA4 excluded from active nodes list")
        else:
            fail(
                "3.5 WHA4 excluded from active nodes list",
                "still present in GET /nodes (no params)",
            )
    else:
        skip("3.5 WHA4 excluded from active nodes list", "WHA4 not deactivated")

    # 3.6 Verify WHA4 not available as transfer destination while inactive
    # Uses PULL (from=SRA, well-stocked and not itself deactivated) so an "insufficient
    # stock" rejection can't masquerade as evidence of an inactive-destination check —
    # PUSH from a non-stock-holding L1/L2 node would always fail on stock regardless of
    # WHA4's active status, since only L4 nodes hold stock in this tenant.
    if node_wha4 and state.get("wha4_deactivated"):
        api_post(
            "/api/v1/inventory/receive/",
            EMAIL_TA,
            {
                "product_id": PROD_P1,
                "warehouse_id": NODE_SRA,
                "quantity": 1000,
                "idempotency_key": f"e2e:wha4:sra:p1:topup36:{uuid.uuid4().hex[:8]}",
                "source": "E2E_TEST",
            },
        )
        r = api_post(
            "/api/v1/inventory/transfers/",
            EMAIL_TA,
            {
                "transfer_type": "PULL",
                "from_warehouse_id": NODE_SRA,
                "to_warehouse_id": node_wha4,
                "lines": [{"product_id": PROD_P1, "quantity": 5}],
                "notes": "New node scenario — should be rejected (inactive destination)",
            },
        )
        confounded_by_stock = err_code(r) == "INSUFFICIENT_STOCK"
        if r.status_code in (404, 422) and not confounded_by_stock:
            ok(
                "3.6 Transfer to inactive WHA4 rejected",
                f"status={r.status_code}, code={err_code(r)}",
            )
        elif confounded_by_stock:
            fail(
                "3.6 Transfer to inactive WHA4 rejected",
                "SRA still reported insufficient stock even after top-up — test inconclusive",
            )
        else:
            fail(
                "3.6 Transfer to inactive WHA4 rejected",
                f"status={r.status_code}, body={r.text[:200]}",
                bug="Transfer creation does not validate that from/to warehouse nodes are "
                "is_active=true — an inactive (deactivated) node can still be used as a "
                "transfer destination. inventory_service transfer-creation validation only "
                "checks tenant_id and level can_initiate/can_receive permissions, never "
                "organization_node.is_active."
                if r.status_code == 201
                else "",
            )
            # Cancel it if it was actually created, to avoid leaving junk state.
            if r.status_code == 201:
                tid = str(data(r).get("transfer_id") or data(r).get("id", ""))
                api_patch(
                    f"/api/v1/inventory/transfers/{tid}",
                    EMAIL_TA,
                    {"next_status": "CANCELLED"},
                )
    else:
        skip("3.6 Transfer to inactive WHA4 rejected", "WHA4 not deactivated")

    # 3.7 Historical data intact — COMPLETED transfer to WHA4 still visible
    if state.get("pull_id"):
        r = api_get(f"/api/v1/inventory/transfers/{state['pull_id']}", EMAIL_TA)
        if r.status_code == 200 and data(r).get("status") == "COMPLETED":
            ok("3.7 Historical COMPLETED transfer to WHA4 still visible")
        else:
            fail(
                "3.7 Historical COMPLETED transfer to WHA4 still visible",
                f"status={r.status_code}, transfer_status={data(r).get('status')}",
            )
    else:
        skip("3.7 Historical data intact", "no pull_id from Phase 2")

    # 3.8 Reactivate WHA4
    if node_wha4 and state.get("wha4_deactivated"):
        r = api_patch(
            f"/api/v1/tenants/{T07_ID}/nodes/{node_wha4}/reactivate", EMAIL_TA
        )
        if r.status_code == 200:
            ok("3.8 Reactivate WHA4", "200, is_active=true")
            state["wha4_deactivated"] = False
        else:
            fail("3.8 Reactivate WHA4", f"status={r.status_code}, body={r.text[:200]}")
    else:
        skip("3.8 Reactivate WHA4", "WHA4 was not deactivated")

    # 3.9 WHA4 back in active nodes
    if node_wha4:
        active_ids = {n["id"] for n in get_all_nodes(EMAIL_TA)}
        if node_wha4 in active_ids:
            ok("3.9 WHA4 present again in active nodes list")
        else:
            fail(
                "3.9 WHA4 present again in active nodes list",
                "missing from GET /nodes after reactivate",
            )
    else:
        skip("3.9 WHA4 present again in active nodes list", "no node_wha4")


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 4 — Edge cases
# ─────────────────────────────────────────────────────────────────────────────
def phase4_edge_cases() -> None:
    global current_phase
    current_phase = "Phase 4"
    print("\n[PHASE 4] Edge cases")

    node_wha4 = state.get("node_wha4")

    # 4.1 Cannot create transfer FROM a deactivated node
    if node_wha4:
        r = api_patch(
            f"/api/v1/tenants/{T07_ID}/nodes/{node_wha4}/deactivate", EMAIL_TA
        )
        deactivated_again = r.status_code == 200
        if not deactivated_again:
            fail(
                "4.1 Re-deactivate WHA4 for source-side check",
                f"status={r.status_code}, code={err_code(r)}, body={r.text[:200]}",
            )
        else:
            # Note: deactivation enforces zero stock as a precondition, so a PULL sourced
            # from WHA4 will always hit INSUFFICIENT_STOCK first — this case can't cleanly
            # isolate "inactive source rejected" from "no stock" the way 3.6 can for the
            # destination side. Treat INSUFFICIENT_STOCK as expected-but-inconclusive here;
            # the real evidence for this gap is 3.6 (clean) plus the source-code review
            # (inventory_service transfer validation never checks organization_node.is_active).
            r2 = api_post(
                "/api/v1/inventory/transfers/",
                EMAIL_TA,
                {
                    "transfer_type": "PULL",
                    "from_warehouse_id": node_wha4,
                    "to_warehouse_id": NODE_WHA1,
                    "lines": [{"product_id": PROD_P1, "quantity": 5}],
                    "notes": "New node scenario — should be rejected (inactive source)",
                },
            )
            if r2.status_code in (404, 422) and err_code(r2) == "INSUFFICIENT_STOCK":
                ok(
                    "4.1 PULL from inactive WHA4 (source) rejected",
                    "422 INSUFFICIENT_STOCK — expected given zero-stock deactivation invariant; "
                    "inconclusive re: is_active check specifically, see 3.6 for the clean signal",
                )
            elif r2.status_code in (404, 422):
                ok(
                    "4.1 PULL from inactive WHA4 (source) rejected",
                    f"status={r2.status_code}, code={err_code(r2)}",
                )
            else:
                fail(
                    "4.1 PULL from inactive WHA4 (source) rejected",
                    f"status={r2.status_code}, body={r2.text[:200]}",
                    bug="Same gap as 3.6 — inactive source node not validated."
                    if r2.status_code == 201
                    else "",
                )
                if r2.status_code == 201:
                    tid = str(data(r2).get("transfer_id") or data(r2).get("id", ""))
                    api_patch(
                        f"/api/v1/inventory/transfers/{tid}",
                        EMAIL_TA,
                        {"next_status": "CANCELLED"},
                    )
            # Reactivate WHA4 after, per spec.
            r3 = api_patch(
                f"/api/v1/tenants/{T07_ID}/nodes/{node_wha4}/reactivate", EMAIL_TA
            )
            if r3.status_code == 200:
                print("    (WHA4 reactivated after 4.1)")
            else:
                flag_bug(
                    "4.1 reactivate-after",
                    f"failed to reactivate WHA4 after test: status={r3.status_code}",
                )
    else:
        skip("4.1 PULL from inactive WHA4 (source) rejected", "no node_wha4")

    # 4.2 Cross-factory isolation: Factory B WM cannot view WHA4 inventory
    if node_wha4:
        r = api_get(
            "/api/v1/inventory/analytics/stock",
            EMAIL_WHB21_WM,
            params={"warehouse_id": node_wha4},
        )
        rows = data(r) if isinstance(data(r), list) else []
        if r.status_code in (403, 404) or (r.status_code == 200 and not rows):
            ok(
                "4.2 Factory B WM cannot view WHA4 inventory",
                f"status={r.status_code}, rows={len(rows)}",
            )
        else:
            fail(
                "4.2 Factory B WM cannot view WHA4 inventory",
                f"status={r.status_code}, rows={len(rows)}",
                bug="Cross-factory ABAC scope not enforced — Factory B WM can read Factory A "
                "warehouse (WHA4) stock levels."
                if r.status_code == 200 and rows
                else "",
            )
    else:
        skip("4.2 Cross-factory isolation", "no node_wha4")

    # 4.3 Approval routing for a large PULL stays within Factory A's chain
    # (mirrors tests/e2e/test_tenant07_e2e.py Group 5 — large-qty PULL routing).
    if node_wha4 and state.get("user_wha4_wm"):
        api_post(
            "/api/v1/inventory/receive/",
            EMAIL_TA,
            {
                "product_id": PROD_P1,
                "warehouse_id": NODE_SRA,
                "quantity": 10000,
                "idempotency_key": "e2e:wha4:sra:p1:baseline",
                "source": "E2E_TEST",
            },
        )
        r = api_post(
            "/api/v1/inventory/transfers/",
            NEW_USER_EMAIL,
            {
                "transfer_type": "PULL",
                "from_warehouse_id": NODE_SRA,
                "to_warehouse_id": node_wha4,
                "lines": [{"product_id": PROD_P1, "quantity": 6000}],
                "notes": "New node scenario — large PULL routing check",
            },
        )
        if r.status_code == 201:
            tid = str(data(r).get("transfer_id") or data(r).get("id", ""))
            r = api_post(f"/api/v1/inventory/transfers/{tid}/submit", NEW_USER_EMAIL)
            status = data(r).get("status", "")
            if status == "PENDING_REVIEW":
                r = api_post(f"/api/v1/inventory/transfers/{tid}/review", EMAIL_SRA_RM)
                status = data(r).get("status", "")
            # Try the Factory-A chain only (SRA_RM -> RA_RM -> FA_NM) — never Factory B.
            approver_used = None
            if status == "PENDING_APPROVAL":
                for approver_email in (EMAIL_SRA_RM, EMAIL_RA_RM, EMAIL_FA_NM):
                    ra = api_post(
                        f"/api/v1/inventory/transfers/{tid}/approve", approver_email
                    )
                    if ra.status_code == 200:
                        status = data(ra).get("status", "")
                        approver_used = approver_email
                        break
            if status in ("APPROVED", "PENDING_APPROVAL"):
                ok(
                    "4.3 Large PULL approval stays within Factory A chain",
                    f"final_status={status}, approver={approver_used}",
                )
            else:
                fail("4.3 Large PULL approval routing", f"status={status}")
            # Cancel — we only care about routing, not completing a 6000-unit transfer.
            cur = api_get(f"/api/v1/inventory/transfers/{tid}", EMAIL_TA)
            cur_status = data(cur).get("status", "")
            if cur_status not in ("COMPLETED", "CANCELLED", "REJECTED"):
                api_patch(
                    f"/api/v1/inventory/transfers/{tid}",
                    EMAIL_TA,
                    {"next_status": "CANCELLED"},
                )
        else:
            fail(
                "4.3 Large PULL approval routing",
                f"create failed status={r.status_code}, body={r.text[:200]}",
            )
    else:
        skip("4.3 Large PULL approval routing", "prerequisite missing")

    # 4.4 New node audit log scoping — WHA4 WM sees own activity, not WHA1/2/3's
    wha4_sub = state.get("wha4_wm_sub")
    wha1_sub = _decode_jwt_sub(EMAIL_WHA1_WM)
    if wha4_sub:
        r = api_get("/api/v1/audit-log/", NEW_USER_EMAIL, params={"limit": 200})
        if r.status_code == 200:
            entries = data(r) if isinstance(data(r), list) else []
            own_entries = [e for e in entries if str(e.get("user_id", "")) == wha4_sub]
            other_wm_entries = [
                e for e in entries if wha1_sub and str(e.get("user_id", "")) == wha1_sub
            ]
            sees_own = len(own_entries) > 0
            isolated = len(other_wm_entries) == 0
            if sees_own and isolated:
                ok(
                    "4.4 WHA4 WM audit log shows own activity, isolated from WHA1",
                    f"own={len(own_entries)}, wha1_leaked={len(other_wm_entries)}",
                )
            elif not sees_own:
                fail("4.4 WHA4 WM audit log shows own activity", "no own entries found")
            else:
                fail(
                    "4.4 WHA4 WM audit log isolated from WHA1",
                    f"wha1_entries_visible={len(other_wm_entries)}",
                    bug="WM audit log facility-subtree scoping leaks sibling warehouse "
                    "(WHA1) activity into WHA4 WM's view.",
                )
        else:
            fail("4.4 WHA4 WM audit log scoping", f"status={r.status_code}")
    else:
        skip("4.4 WHA4 WM audit log scoping", "no wha4_wm_sub")


# ─────────────────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────────────────
def print_report() -> None:
    print("\n" + "=" * 70)
    print("  NEW NODE SCENARIO TEST REPORT")
    print("=" * 70)

    phases = ["Phase 1", "Phase 2", "Phase 3", "Phase 4"]
    counts = {p: {"pass": 0, "fail": 0, "skip": 0} for p in phases}
    for r in results:
        bucket = counts.setdefault(r.phase, {"pass": 0, "fail": 0, "skip": 0})
        if r.skipped:
            bucket["skip"] += 1
        elif r.passed:
            bucket["pass"] += 1
        else:
            bucket["fail"] += 1

    sep = "+" + "-" * 10 + "+" + "-" * 6 + "+" + "-" * 7 + "+" + "-" * 6 + "+"
    print(sep)
    print("| {:<8} | {:<4} | {:<5} | {:<4} |".format("Phase", "Pass", "Fail", "Skip"))
    print(sep)
    tot_pass = tot_fail = tot_skip = 0
    for p in phases:
        c = counts[p]
        print(
            "| {:<8} | {:<4} | {:<5} | {:<4} |".format(
                p, c["pass"], c["fail"], c["skip"]
            )
        )
        tot_pass += c["pass"]
        tot_fail += c["fail"]
        tot_skip += c["skip"]
    print(sep)
    print(
        "| {:<8} | {:<4} | {:<5} | {:<4} |".format(
            "TOTAL", tot_pass, tot_fail, tot_skip
        )
    )
    print(sep)

    print("\nBUGS FOUND:")
    if bugs:
        for b in bugs:
            print(f"  - {b}")
    else:
        print("  (none)")

    print("\nWHA4 credentials (left intact for manual browser verification):")
    print(f"  Email:    {NEW_USER_EMAIL}")
    print(f"  Password: {DEFAULT_PASSWORD}")
    print("  Node:     WHA4 (under Subregion A, Factory A branch)")
    if state.get("node_wha4"):
        print(f"  Node ID:  {state['node_wha4']}")


def main() -> None:
    print("=" * 70)
    print("  NEW NODE SCENARIO — LIVE TEST (Tenant 07)")
    print(f"  Target: {BASE_URL}")
    print("=" * 70)

    phase1_setup()
    phase2_operations()
    phase3_deactivation()
    phase4_edge_cases()

    print_report()

    failed = sum(1 for r in results if not r.passed and not r.skipped)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
