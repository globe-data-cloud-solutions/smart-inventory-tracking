"""
Tenant T6P2T End-to-End Test Suite — Groups 0-2 ONLY.

Scope: Group 0 (tenant + TA creation), Group 1 (org hierarchy levels),
Group 2 (org tree — 13 nodes). Groups 3-9 are out of scope for this file.

Run:
    python -m pytest tests/e2e/test_t6p2t_group_a.py -v --tb=short

Requirements:
  - Backend running at http://localhost:8000 (override with E2E_BASE_URL)
  - ENVIRONMENT=local must be set in the backend (enables dev_email auth)
  - SA account smartadmin@smart-inventory.com / Test@2026 must exist

Ordering note: tests within this module share state (tenant_id, tokens, node
ids) through the module-level STATE dict and rely on running in file/class
definition order. pyproject.toml's [tool.pytest.ini_options] does not enable
any randomization plugin, so default pytest collection order (top-to-bottom)
is preserved. Each test still uses skip_test() to degrade gracefully if an
earlier prerequisite failed, instead of crashing.
"""
from __future__ import annotations

import base64
import json
import os
import uuid
from typing import Any, Optional

import pytest
import requests

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
DEFAULT_PASSWORD = "Test@2026"

SA_EMAIL = "smartadmin@smart-inventory.com"
# NOTE: the SA account's password in this dev environment is "Admin@2026", not the
# "Test@2026" tenant-user default — confirmed against scripts/seed_demo_data.py and
# every scripts/int_test_*.py helper, all of which use Admin@2026 for this account.
SA_PASSWORD = "Admin@2026"

TENANT_NAME = "Tenant_6_P2T"
TENANT_SLUG = "tenant-6-p2t"

TA_EMAIL = "admin@t6p2t.com"
TA_NAME = "T6P2T Admin"

STATE_FILE = os.path.join(os.path.dirname(__file__), "t6p2t_state.json")

ORDERED_GROUPS = ["GROUP0", "GROUP1", "GROUP2"]

# ─────────────────────────────────────────────────────────────────────────────
# Shared state + result tracking
# ─────────────────────────────────────────────────────────────────────────────
STATE: dict[str, Any] = {"nodes": {}, "level_ids": {}}
GROUP_STATS: dict[str, dict[str, int]] = {}
FAILURE_DETAILS: list[dict[str, str]] = []


def _stats(group: str) -> dict[str, int]:
    return GROUP_STATS.setdefault(group, {"TESTS": 0, "PASS": 0, "FAIL": 0, "SKIP": 0})


def record_pass(group: str, name: str) -> None:
    s = _stats(group)
    s["TESTS"] += 1
    s["PASS"] += 1
    print(f"  [PASS] {name}")


def record_fail(group: str, name: str, expected: str, actual: str, body: str = "") -> None:
    s = _stats(group)
    s["TESTS"] += 1
    s["FAIL"] += 1
    FAILURE_DETAILS.append(
        {"test": name, "expected": expected, "actual": actual, "body": body[:500]}
    )
    print(f"  [FAIL] {name} — expected: {expected!r} actual: {actual!r}")


def record_skip(group: str, name: str, reason: str) -> None:
    s = _stats(group)
    s["TESTS"] += 1
    s["SKIP"] += 1
    print(f"  [SKIP] {name} — {reason}")


def check(
    group: str,
    name: str,
    condition: bool,
    expected: str = "",
    actual: str = "",
    body: str = "",
) -> None:
    if condition:
        record_pass(group, name)
    else:
        record_fail(group, name, expected, actual, body)
    assert condition, f"{name} — expected: {expected!r} actual: {actual!r} body: {body[:300]!r}"


def skip_test(group: str, name: str, reason: str) -> None:
    record_skip(group, name, reason)
    pytest.skip(reason)


# ─────────────────────────────────────────────────────────────────────────────
# HTTP helpers
# ─────────────────────────────────────────────────────────────────────────────
def login(email: str, password: str = DEFAULT_PASSWORD) -> requests.Response:
    return requests.post(
        f"{BASE_URL}/api/v1/auth/token",
        json={"dev_email": email, "dev_password": password},
        timeout=15,
    )


def decode_jwt(token: str) -> dict:
    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    return json.loads(base64.b64decode(payload_b64))


def hdrs(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def api_get(path: str, token: str, params: Optional[dict] = None) -> requests.Response:
    return requests.get(f"{BASE_URL}{path}", headers=hdrs(token), params=params, timeout=15)


def api_post(path: str, token: str, body: Optional[dict] = None) -> requests.Response:
    return requests.post(f"{BASE_URL}{path}", headers=hdrs(token), json=body or {}, timeout=15)


def api_put(path: str, token: str, body: Any = None) -> requests.Response:
    return requests.put(f"{BASE_URL}{path}", headers=hdrs(token), json=body, timeout=15)


def api_patch(path: str, token: str, body: Optional[dict] = None) -> requests.Response:
    return requests.patch(f"{BASE_URL}{path}", headers=hdrs(token), json=body or {}, timeout=15)


def jdata(r: requests.Response) -> Any:
    try:
        j = r.json()
        return j.get("data", j)
    except Exception:
        return {}


def err_code(r: requests.Response) -> Optional[str]:
    """Extract the `code` field from a FastAPI HTTPException({"code":..., "message":...}) body."""
    try:
        detail = r.json().get("detail")
        return detail.get("code") if isinstance(detail, dict) else None
    except Exception:
        return None


def uniq(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


# ─────────────────────────────────────────────────────────────────────────────
# GROUP 0 — Tenant + TA creation (via SA)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.integration
class TestGroup0TenantAndTA:
    GROUP = "GROUP0"

    def test_00_sa_login(self) -> None:
        r = login(SA_EMAIL, SA_PASSWORD)
        token = r.json().get("access_token") if r.status_code == 200 else None
        if token:
            STATE["sa_token"] = token
            STATE["sa_user_id"] = decode_jwt(token).get("sub")
        check(
            self.GROUP,
            "0.0 SA login (smartadmin@smart-inventory.com) succeeds, JWT returned",
            r.status_code == 200 and bool(token),
            expected="200 + access_token",
            actual=f"status={r.status_code}",
            body=r.text,
        )

    def test_01_create_tenant(self) -> None:
        if not STATE.get("sa_token"):
            skip_test(self.GROUP, "0.1 SA creates tenant Tenant_6_P2T", "no sa_token from 0.0")
        r = api_post(
            "/api/v1/tenants/",
            STATE["sa_token"],
            # organisation_type is Optional[str] in TenantCreateRequest but NOT NULL at
            # the DB level (tenants.organisation_type) — omitting it 500s with
            # NotNullViolationError. Supplying PRODUCER here is a workaround for that
            # schema/DB mismatch, not a requirement from the test spec.
            {"name": TENANT_NAME, "slug": TENANT_SLUG, "organisation_type": "PRODUCER"},
        )
        d = jdata(r)
        if r.status_code == 201:
            STATE["tenant_id"] = str(d.get("id"))
            STATE["tenant_slug"] = d.get("slug")
        check(
            self.GROUP,
            "0.1 SA creates tenant Tenant_6_P2T (slug=tenant-6-p2t)",
            r.status_code == 201 and d.get("slug") == TENANT_SLUG and d.get("id"),
            expected="201, slug='tenant-6-p2t', id present",
            actual=f"status={r.status_code}, slug={d.get('slug')!r}, id={d.get('id')!r}",
            body=r.text,
        )

    def test_02_verify_tenant_created(self) -> None:
        if not (STATE.get("tenant_id") and STATE.get("sa_token")):
            skip_test(self.GROUP, "0.2 Verify tenant created (id + slug correct)", "no tenant_id/sa_token")
        r = api_get(f"/api/v1/tenants/{STATE['tenant_id']}", STATE["sa_token"])
        d = jdata(r)
        check(
            self.GROUP,
            "0.2 Verify tenant created (id + slug correct)",
            r.status_code == 200
            and str(d.get("id")) == STATE["tenant_id"]
            and d.get("slug") == TENANT_SLUG,
            expected=f"200, id={STATE.get('tenant_id')}, slug='{TENANT_SLUG}'",
            actual=f"status={r.status_code}, id={d.get('id')!r}, slug={d.get('slug')!r}",
            body=r.text,
        )

    def test_03_create_ta_account(self) -> None:
        if not (STATE.get("tenant_id") and STATE.get("sa_token")):
            skip_test(self.GROUP, "0.3 SA creates TA account admin@t6p2t.com", "no tenant_id/sa_token")
        r = api_post(
            f"/api/v1/tenants/{STATE['tenant_id']}/users",
            STATE["sa_token"],
            {
                "name": TA_NAME,
                "email": TA_EMAIL,
                "password": DEFAULT_PASSWORD,
                "system_role": "TA",
            },
        )
        d = jdata(r)
        if r.status_code == 201:
            STATE["ta_user_id"] = str(d.get("id"))
        check(
            self.GROUP,
            "0.3 SA creates TA account admin@t6p2t.com",
            r.status_code == 201 and d.get("role") == "TA",
            expected="201, role='TA'",
            actual=f"status={r.status_code}, role={d.get('role')!r}",
            body=r.text,
        )

    def test_04_ta_login_and_verify_role(self) -> None:
        r = login(TA_EMAIL, DEFAULT_PASSWORD)
        token = r.json().get("access_token") if r.status_code == 200 else None
        claims = decode_jwt(token) if token else {}
        if token:
            STATE["ta_token"] = token
        check(
            self.GROUP,
            "0.4 TA login succeeds, JWT returned, role=TA confirmed",
            r.status_code == 200 and bool(token) and claims.get("role") == "TA",
            expected="200, access_token present, role='TA'",
            actual=f"status={r.status_code}, token_present={bool(token)}, role={claims.get('role')!r}",
            body=r.text,
        )

    def test_05_sa_cannot_be_displaced_by_ta(self) -> None:
        """TA must not be able to view or act on the SA account. The SA user row has
        tenant_id=NULL; get_db_session_for_tenant binds every non-SA caller to exactly
        their own tenant_id (TENANT_ACCESS_DENIED otherwise), and a tenant-scoped lookup
        for the SA's user id inside this tenant simply finds no matching row → 404."""
        if not (STATE.get("ta_token") and STATE.get("sa_user_id") and STATE.get("tenant_id")):
            skip_test(
                self.GROUP,
                "0.5 TA cannot view/manage SA account (tenant isolation)",
                "missing ta_token/sa_user_id/tenant_id",
            )
        r = api_get(
            f"/api/v1/tenants/{STATE['tenant_id']}/users/{STATE['sa_user_id']}",
            STATE["ta_token"],
        )
        check(
            self.GROUP,
            "0.5 TA cannot view/manage SA account (tenant isolation) → 404",
            r.status_code == 404,
            expected="404 (SA account not visible inside tenant scope)",
            actual=f"status={r.status_code}",
            body=r.text,
        )

    def test_06_ta_cannot_create_another_ta(self) -> None:
        if not (STATE.get("ta_token") and STATE.get("tenant_id")):
            skip_test(self.GROUP, "0.6 TA cannot create TA → 403 ROLE_CEILING_EXCEEDED", "missing ta_token/tenant_id")
        r = api_post(
            f"/api/v1/tenants/{STATE['tenant_id']}/users",
            STATE["ta_token"],
            {
                "name": "Rogue TA Attempt",
                "email": f"rogue-ta-{uniq()}@t6p2t.com",
                "password": DEFAULT_PASSWORD,
                "system_role": "TA",
            },
        )
        code = err_code(r)
        check(
            self.GROUP,
            "0.6 TA POST /users system_role=TA → 403 ROLE_CEILING_EXCEEDED",
            r.status_code == 403 and code == "ROLE_CEILING_EXCEEDED",
            expected="403, code=ROLE_CEILING_EXCEEDED",
            actual=f"status={r.status_code}, code={code!r}",
            body=r.text,
        )


# ─────────────────────────────────────────────────────────────────────────────
# GROUP 1 — Org levels (4 levels, all stock-holding)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.integration
class TestGroup1OrgLevels:
    GROUP = "GROUP1"

    LEVELS = [
        {"level_number": 1, "level_name": "Factory", "is_stock_holding": True},
        {"level_number": 2, "level_name": "Region", "is_stock_holding": True},
        {"level_number": 3, "level_name": "Warehouse", "is_stock_holding": True},
        {"level_number": 4, "level_name": "Satellite", "is_stock_holding": True},
    ]

    def test_10_create_4_levels(self) -> None:
        if not (STATE.get("ta_token") and STATE.get("tenant_id")):
            skip_test(self.GROUP, "1.0 TA creates 4 org levels", "missing ta_token/tenant_id")
        r = api_put(
            f"/api/v1/tenants/{STATE['tenant_id']}/hierarchy/config",
            STATE["ta_token"],
            self.LEVELS,
        )
        d = jdata(r)
        check(
            self.GROUP,
            "1.0 TA creates 4 org levels (Factory/Region/Warehouse/Satellite, all stock-holding)",
            r.status_code == 200 and isinstance(d, list) and len(d) == 4,
            expected="200, 4 levels created",
            actual=f"status={r.status_code}, count={len(d) if isinstance(d, list) else 'n/a'}",
            body=r.text,
        )

    def test_11_verify_levels(self) -> None:
        if not (STATE.get("tenant_id") and STATE.get("ta_token")):
            skip_test(self.GROUP, "1.1 Verify all 4 levels created and returned correctly", "missing tenant_id/ta_token")
        r = api_get(f"/api/v1/tenants/{STATE['tenant_id']}/hierarchy/config", STATE["ta_token"])
        d = jdata(r)
        names: dict[int, str] = {}
        if isinstance(d, list):
            for lv in d:
                names[lv["level_number"]] = lv["level_name"]
                STATE["level_ids"][lv["level_number"]] = str(lv["id"])
        expected_names = {1: "Factory", 2: "Region", 3: "Warehouse", 4: "Satellite"}
        check(
            self.GROUP,
            "1.1 Verify all 4 levels created and returned correctly",
            r.status_code == 200 and names == expected_names,
            expected=f"{expected_names}",
            actual=f"status={r.status_code}, names={names}",
            body=r.text,
        )

    def test_12_rename_l2_round_trip(self) -> None:
        level_id = STATE["level_ids"].get(2)
        if not level_id:
            skip_test(self.GROUP, "1.2 Rename L2 'Region'→'Regional Hub'→'Region' persists", "no level_id for L2 from 1.1")
        r1 = api_patch(
            f"/api/v1/tenants/{STATE['tenant_id']}/hierarchy/config/{level_id}",
            STATE["ta_token"],
            {"level_name": "Regional Hub"},
        )
        d1 = jdata(r1)
        r2 = api_patch(
            f"/api/v1/tenants/{STATE['tenant_id']}/hierarchy/config/{level_id}",
            STATE["ta_token"],
            {"level_name": "Region"},
        )
        d2 = jdata(r2)
        check(
            self.GROUP,
            "1.2 Rename L2 'Region'→'Regional Hub'→'Region' persists",
            r1.status_code == 200
            and d1.get("level_name") == "Regional Hub"
            and r2.status_code == 200
            and d2.get("level_name") == "Region",
            expected="step1: 200/'Regional Hub', step2: 200/'Region'",
            actual=f"step1={r1.status_code}/{d1.get('level_name')!r}, step2={r2.status_code}/{d2.get('level_name')!r}",
            body=f"{r1.text[:200]} | {r2.text[:200]}",
        )

    def test_13_duplicate_level_name_rejected(self) -> None:
        """Probe for level_name uniqueness validation. The router (HierarchyLevelRename)
        and the tenant_hierarchy_config schema (uq_tenant_level on tenant_id+level_number
        only) show no name-uniqueness constraint, so this is expected to surface a gap
        rather than a tooling mistake. The level is reverted immediately either way."""
        level_id = STATE["level_ids"].get(1)
        if not level_id:
            skip_test(self.GROUP, "1.3 Duplicate level_name → 409/422", "no level_id for L1 from 1.1")
        r = api_patch(
            f"/api/v1/tenants/{STATE['tenant_id']}/hierarchy/config/{level_id}",
            STATE["ta_token"],
            {"level_name": "Region"},  # collides with L2's name
        )
        # Revert regardless of outcome so later tests aren't affected by a corrupted name.
        api_patch(
            f"/api/v1/tenants/{STATE['tenant_id']}/hierarchy/config/{level_id}",
            STATE["ta_token"],
            {"level_name": "Factory"},
        )
        check(
            self.GROUP,
            "1.3 Duplicate level_name → 409/422",
            r.status_code in (409, 422),
            expected="409 or 422",
            actual=f"status={r.status_code}",
            body=r.text,
        )

    def test_14_duplicate_level_number_rejected(self) -> None:
        """Probe for level_number duplicate rejection within a single PUT payload.
        upsert_hierarchy_config() uses ON CONFLICT (tenant_id, level_number) DO UPDATE
        and loops sequentially, so two entries sharing a level_number in one call simply
        upsert twice (last write wins) rather than raising — expected to surface a gap."""
        if not (STATE.get("tenant_id") and STATE.get("ta_token")):
            skip_test(self.GROUP, "1.4 Duplicate level_number → 409/422", "missing tenant_id/ta_token")
        bad_body = self.LEVELS + [
            {"level_number": 1, "level_name": "Factory Duplicate", "is_stock_holding": True}
        ]
        r = api_put(
            f"/api/v1/tenants/{STATE['tenant_id']}/hierarchy/config",
            STATE["ta_token"],
            bad_body,
        )
        # Restore the canonical 4-level config regardless of outcome.
        api_put(
            f"/api/v1/tenants/{STATE['tenant_id']}/hierarchy/config",
            STATE["ta_token"],
            self.LEVELS,
        )
        check(
            self.GROUP,
            "1.4 Duplicate level_number → 409/422",
            r.status_code in (409, 422),
            expected="409 or 422",
            actual=f"status={r.status_code}",
            body=r.text,
        )

    def test_15_level_count_lock(self) -> None:
        """Probe for a level-count lock after the initial 4 levels are saved. The route
        only enforces 1<=level_number<=5 per item; there is no per-tenant lock once a
        config exists, so a 5th level is expected to be accepted rather than rejected —
        a discovered gap, not a tooling mistake. NOTE: there is no DELETE endpoint for
        hierarchy levels, so if this succeeds the L5 row cannot be cleaned up afterward;
        it does not affect Group 2, which only uses levels 1-4."""
        if not (STATE.get("tenant_id") and STATE.get("ta_token")):
            skip_test(self.GROUP, "1.5 Adding L5 after 4 levels saved is rejected/locked", "missing tenant_id/ta_token")
        body_with_l5 = self.LEVELS + [
            {"level_number": 5, "level_name": "Outpost", "is_stock_holding": True}
        ]
        r = api_put(
            f"/api/v1/tenants/{STATE['tenant_id']}/hierarchy/config",
            STATE["ta_token"],
            body_with_l5,
        )
        check(
            self.GROUP,
            "1.5 Adding L5 after 4 levels saved is rejected/locked",
            r.status_code in (409, 422),
            expected="409 or 422 (locked)",
            actual=f"status={r.status_code}",
            body=r.text,
        )


# ─────────────────────────────────────────────────────────────────────────────
# GROUP 2 — Org tree (13 nodes: 2 roots + 1 mid-test addition WHA3)
# ─────────────────────────────────────────────────────────────────────────────
def _create_node(group: str, key: str, label: str, level: int, parent_key: Optional[str], test_name: str) -> None:
    if not (STATE.get("ta_token") and STATE.get("tenant_id")):
        skip_test(group, test_name, "missing ta_token/tenant_id")
    parent_id = STATE["nodes"].get(parent_key) if parent_key else None
    if parent_key and not parent_id:
        skip_test(group, test_name, f"parent node {parent_key} not created")
    body: dict[str, Any] = {"name": label, "level_number": level, "is_stock_holding": True}
    if parent_id:
        body["parent_node_id"] = parent_id
    r = api_post(f"/api/v1/tenants/{STATE['tenant_id']}/nodes", STATE["ta_token"], body)
    d = jdata(r)
    if r.status_code == 201 and d.get("id"):
        STATE["nodes"][key] = str(d.get("id"))
    check(
        group,
        test_name,
        r.status_code == 201 and bool(d.get("id")),
        expected="201 + node id",
        actual=f"status={r.status_code}",
        body=r.text,
    )


def _flatten(nodes: list[dict]) -> list[dict]:
    out: list[dict] = []
    for n in nodes:
        out.append(n)
        out.extend(_flatten(n.get("children") or []))
    return out


@pytest.mark.integration
class TestGroup2OrgTree:
    GROUP = "GROUP2"

    # ── L1 roots ──────────────────────────────────────────────────────────────
    def test_20_create_a_fac(self) -> None:
        _create_node(self.GROUP, "A_FAC", "Addis Ababa Factory", 1, None, "2.0 Create A_FAC (Addis Ababa Factory, L1, root)")

    def test_21_create_b_fac(self) -> None:
        _create_node(self.GROUP, "B_FAC", "Dire Dawa Factory", 1, None, "2.1 Create B_FAC (Dire Dawa Factory, L1, root)")

    # ── L2 regions ────────────────────────────────────────────────────────────
    def test_22_create_a_reg(self) -> None:
        _create_node(self.GROUP, "A_REG", "Addis Region", 2, "A_FAC", "2.2 Create A_REG (Addis Region, L2, parent=A_FAC)")

    def test_23_create_b_reg(self) -> None:
        _create_node(self.GROUP, "B_REG", "Dire Region", 2, "B_FAC", "2.3 Create B_REG (Dire Region, L2, parent=B_FAC)")

    # ── L3 warehouses ─────────────────────────────────────────────────────────
    def test_24_create_wha1(self) -> None:
        _create_node(self.GROUP, "WHA1", "WHA1 Merkato", 3, "A_REG", "2.4 Create WHA1 (WHA1 Merkato, L3, parent=A_REG)")

    def test_25_create_wha2(self) -> None:
        _create_node(self.GROUP, "WHA2", "WHA2 Bole", 3, "A_REG", "2.5 Create WHA2 (WHA2 Bole, L3, parent=A_REG)")

    def test_26_create_whb1(self) -> None:
        _create_node(self.GROUP, "WHB1", "WHB1 Sabian", 3, "B_REG", "2.6 Create WHB1 (WHB1 Sabian, L3, parent=B_REG)")

    def test_27_create_whb2(self) -> None:
        _create_node(self.GROUP, "WHB2", "WHB2 Kezira", 3, "B_REG", "2.7 Create WHB2 (WHB2 Kezira, L3, parent=B_REG)")

    # ── L4 satellites ─────────────────────────────────────────────────────────
    def test_28_create_sat_wha1(self) -> None:
        _create_node(self.GROUP, "SAT_WHA1", "Satellite Merkato", 4, "WHA1", "2.8 Create SAT_WHA1 (Satellite Merkato, L4, parent=WHA1)")

    def test_29_create_sat_wha2(self) -> None:
        _create_node(self.GROUP, "SAT_WHA2", "Satellite Bole", 4, "WHA2", "2.9 Create SAT_WHA2 (Satellite Bole, L4, parent=WHA2)")

    def test_30_create_sat_whb1(self) -> None:
        _create_node(self.GROUP, "SAT_WHB1", "Satellite Sabian", 4, "WHB1", "2.10 Create SAT_WHB1 (Satellite Sabian, L4, parent=WHB1)")

    def test_31_create_sat_whb2(self) -> None:
        _create_node(self.GROUP, "SAT_WHB2", "Satellite Kezira", 4, "WHB2", "2.11 Create SAT_WHB2 (Satellite Kezira, L4, parent=WHB2)")

    # ── Mid-test org growth ──────────────────────────────────────────────────
    def test_32_create_wha3(self) -> None:
        _create_node(self.GROUP, "WHA3", "WHA3 Lideta", 3, "A_REG", "2.12 Create WHA3 (WHA3 Lideta, L3, parent=A_REG — added mid-test)")

    # ── Tree verification ────────────────────────────────────────────────────
    def test_33_total_node_count_and_roots(self) -> None:
        if not (STATE.get("ta_token") and STATE.get("tenant_id")):
            skip_test(self.GROUP, "2.13 Total node count = 13, exactly 2 roots", "missing ta_token/tenant_id")
        r = api_get(f"/api/v1/tenants/{STATE['tenant_id']}/nodes", STATE["ta_token"])
        roots = jdata(r) if isinstance(jdata(r), list) else []
        flat = _flatten(roots)
        check(
            self.GROUP,
            "2.13 Total node count = 13, exactly 2 roots",
            r.status_code == 200 and len(flat) == 13 and len(roots) == 2,
            expected="200, 13 total nodes, 2 roots",
            actual=f"status={r.status_code}, total={len(flat)}, roots={len(roots)}",
            body=r.text[:500],
        )

    def test_34_parent_node_id_matches(self) -> None:
        if not (STATE.get("ta_token") and STATE.get("tenant_id")):
            skip_test(self.GROUP, "2.14 Each node's parent_node_id matches expected", "missing ta_token/tenant_id")
        r = api_get(f"/api/v1/tenants/{STATE['tenant_id']}/nodes", STATE["ta_token"])
        roots = jdata(r) if isinstance(jdata(r), list) else []
        flat = {str(n["id"]): n for n in _flatten(roots)}

        expected_parent = {
            "A_FAC": None, "B_FAC": None,
            "A_REG": "A_FAC", "B_REG": "B_FAC",
            "WHA1": "A_REG", "WHA2": "A_REG", "WHA3": "A_REG",
            "WHB1": "B_REG", "WHB2": "B_REG",
            "SAT_WHA1": "WHA1", "SAT_WHA2": "WHA2",
            "SAT_WHB1": "WHB1", "SAT_WHB2": "WHB2",
        }
        mismatches = []
        for key, parent_key in expected_parent.items():
            node_id = STATE["nodes"].get(key)
            if not node_id or node_id not in flat:
                mismatches.append(f"{key}: not found in tree")
                continue
            actual_parent = flat[node_id].get("parent_node_id")
            expected_parent_id = STATE["nodes"].get(parent_key) if parent_key else None
            if (str(actual_parent) if actual_parent else None) != expected_parent_id:
                mismatches.append(f"{key}: expected parent={expected_parent_id}, got {actual_parent}")
        check(
            self.GROUP,
            "2.14 Each node's parent_node_id matches expected",
            r.status_code == 200 and not mismatches,
            expected="all 13 nodes' parent_node_id correct",
            actual=f"status={r.status_code}, mismatches={mismatches}",
            body=r.text[:500],
        )

    def test_35_tree_depth_via_ancestry(self) -> None:
        if not (STATE.get("ta_token") and STATE.get("tenant_id")):
            skip_test(self.GROUP, "2.15 Tree depth L1→L2→L3→L4 verified via ancestry", "missing ta_token/tenant_id")
        r = api_get(f"/api/v1/tenants/{STATE['tenant_id']}/nodes", STATE["ta_token"])
        roots = jdata(r) if isinstance(jdata(r), list) else []
        flat = {str(n["id"]): n for n in _flatten(roots)}

        sat_wha1_id = STATE["nodes"].get("SAT_WHA1")
        chain_ok = False
        chain_desc = ""
        if sat_wha1_id and sat_wha1_id in flat:
            sat = flat[sat_wha1_id]
            wha1_id = str(sat.get("parent_node_id") or "")
            wha1 = flat.get(wha1_id, {})
            a_reg_id = str(wha1.get("parent_node_id") or "")
            a_reg = flat.get(a_reg_id, {})
            a_fac_id = str(a_reg.get("parent_node_id") or "")
            a_fac = flat.get(a_fac_id, {})
            chain_desc = (
                f"SAT_WHA1(L{sat.get('hierarchy_level')})->WHA1(L{wha1.get('hierarchy_level')})"
                f"->A_REG(L{a_reg.get('hierarchy_level')})->A_FAC(L{a_fac.get('hierarchy_level')}, parent={a_fac.get('parent_node_id')})"
            )
            chain_ok = (
                wha1_id == STATE["nodes"].get("WHA1")
                and a_reg_id == STATE["nodes"].get("A_REG")
                and a_fac_id == STATE["nodes"].get("A_FAC")
                and sat.get("hierarchy_level") == 4
                and wha1.get("hierarchy_level") == 3
                and a_reg.get("hierarchy_level") == 2
                and a_fac.get("hierarchy_level") == 1
                and a_fac.get("parent_node_id") is None
            )
        check(
            self.GROUP,
            "2.15 Tree depth L1→L2→L3→L4 verified via ancestry (SAT_WHA1 chain)",
            r.status_code == 200 and chain_ok,
            expected="SAT_WHA1(L4)->WHA1(L3)->A_REG(L2)->A_FAC(L1, root)",
            actual=f"status={r.status_code}, chain={chain_desc or 'incomplete'}",
            body=r.text[:500],
        )

    # ── Edit tests ────────────────────────────────────────────────────────────
    def test_36_rename_wha2_round_trip(self) -> None:
        node_id = STATE["nodes"].get("WHA2")
        if not node_id:
            skip_test(self.GROUP, "2.16 Rename WHA2 'WHA2 Bole'→'WHA2 Bole-Airport'→back persists", "no node id for WHA2")
        r1 = api_patch(
            f"/api/v1/tenants/{STATE['tenant_id']}/nodes/{node_id}",
            STATE["ta_token"],
            {"name": "WHA2 Bole-Airport"},
        )
        d1 = jdata(r1)
        r2 = api_patch(
            f"/api/v1/tenants/{STATE['tenant_id']}/nodes/{node_id}",
            STATE["ta_token"],
            {"name": "WHA2 Bole"},
        )
        d2 = jdata(r2)
        check(
            self.GROUP,
            "2.16 Rename WHA2 'WHA2 Bole'→'WHA2 Bole-Airport'→back persists",
            r1.status_code == 200
            and d1.get("name") == "WHA2 Bole-Airport"
            and r2.status_code == 200
            and d2.get("name") == "WHA2 Bole",
            expected="step1: 200/'WHA2 Bole-Airport', step2: 200/'WHA2 Bole'",
            actual=f"step1={r1.status_code}/{d1.get('name')!r}, step2={r2.status_code}/{d2.get('name')!r}",
            body=f"{r1.text[:200]} | {r2.text[:200]}",
        )

    # ── Deactivation pre-check tests (leaf node, no stock/transfers/adjustments) ──
    def test_37_deactivate_sat_wha2(self) -> None:
        node_id = STATE["nodes"].get("SAT_WHA2")
        if not node_id:
            skip_test(self.GROUP, "2.17 Deactivate SAT_WHA2 (leaf, no stock/transfers) succeeds", "no node id for SAT_WHA2")
        r = api_patch(f"/api/v1/tenants/{STATE['tenant_id']}/nodes/{node_id}/deactivate", STATE["ta_token"])
        check(
            self.GROUP,
            "2.17 Deactivate SAT_WHA2 (leaf, no stock/transfers) succeeds",
            r.status_code == 200,
            expected="200",
            actual=f"status={r.status_code}",
            body=r.text,
        )

    def test_38_sat_wha2_inactive_in_tree(self) -> None:
        node_id = STATE["nodes"].get("SAT_WHA2")
        if not node_id:
            skip_test(self.GROUP, "2.18 SAT_WHA2 absent from default tree, inactive with include_inactive=true", "no node id for SAT_WHA2")
        r_default = api_get(f"/api/v1/tenants/{STATE['tenant_id']}/nodes", STATE["ta_token"])
        flat_default = {str(n["id"]): n for n in _flatten(jdata(r_default) if isinstance(jdata(r_default), list) else [])}
        r_all = api_get(
            f"/api/v1/tenants/{STATE['tenant_id']}/nodes", STATE["ta_token"], params={"include_inactive": "true"}
        )
        flat_all = {str(n["id"]): n for n in _flatten(jdata(r_all) if isinstance(jdata(r_all), list) else [])}
        absent_by_default = node_id not in flat_default
        inactive_when_included = node_id in flat_all and flat_all[node_id].get("is_active") is False
        check(
            self.GROUP,
            "2.18 SAT_WHA2 absent from default tree, inactive with include_inactive=true",
            absent_by_default and inactive_when_included,
            expected="absent by default; is_active=false with include_inactive=true",
            actual=f"absent_by_default={absent_by_default}, inactive_when_included={inactive_when_included}",
            body=f"default={r_default.status_code}, all={r_all.status_code}",
        )

    def test_39_reactivate_sat_wha2(self) -> None:
        node_id = STATE["nodes"].get("SAT_WHA2")
        if not node_id:
            skip_test(self.GROUP, "2.19 Reactivate SAT_WHA2 succeeds", "no node id for SAT_WHA2")
        r = api_patch(f"/api/v1/tenants/{STATE['tenant_id']}/nodes/{node_id}/reactivate", STATE["ta_token"])
        check(
            self.GROUP,
            "2.19 Reactivate SAT_WHA2 succeeds",
            r.status_code == 200,
            expected="200",
            actual=f"status={r.status_code}",
            body=r.text,
        )

    def test_40_sat_wha2_active_again(self) -> None:
        node_id = STATE["nodes"].get("SAT_WHA2")
        if not node_id:
            skip_test(self.GROUP, "2.20 SAT_WHA2 reappears active in default tree (status toggled both ways)", "no node id for SAT_WHA2")
        r = api_get(f"/api/v1/tenants/{STATE['tenant_id']}/nodes", STATE["ta_token"])
        flat = {str(n["id"]): n for n in _flatten(jdata(r) if isinstance(jdata(r), list) else [])}
        present_and_active = node_id in flat and flat[node_id].get("is_active") is True
        check(
            self.GROUP,
            "2.20 SAT_WHA2 reappears active in default tree (status toggled both ways)",
            r.status_code == 200 and present_and_active,
            expected="present in default tree, is_active=true",
            actual=f"status={r.status_code}, present_and_active={present_and_active}",
            body=r.text[:500],
        )


# ─────────────────────────────────────────────────────────────────────────────
# STATE FILE + REPORTING (always runs last — file/class definition order)
# ─────────────────────────────────────────────────────────────────────────────
class TestZZStateFileAndSummary:
    def test_91_write_state_file(self) -> None:
        out = {
            "tenant_id": STATE.get("tenant_id"),
            "tenant_slug": STATE.get("tenant_slug"),
            "ta_token": STATE.get("ta_token"),
            "sa_token": STATE.get("sa_token"),
            "nodes": STATE.get("nodes", {}),
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        print(f"\nState file written to {STATE_FILE}")
        assert True

    def test_92_print_summary(self) -> None:
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"{'GROUP':<10} {'TESTS':>6} {'PASS':>6} {'FAIL':>6} {'SKIP':>6}")
        totals = {"TESTS": 0, "PASS": 0, "FAIL": 0, "SKIP": 0}
        for group in ORDERED_GROUPS:
            s = GROUP_STATS.get(group, {"TESTS": 0, "PASS": 0, "FAIL": 0, "SKIP": 0})
            print(f"{group:<10} {s['TESTS']:>6} {s['PASS']:>6} {s['FAIL']:>6} {s['SKIP']:>6}")
            for k in totals:
                totals[k] += s[k]
        print("-" * 70)
        print(f"{'TOTAL':<10} {totals['TESTS']:>6} {totals['PASS']:>6} {totals['FAIL']:>6} {totals['SKIP']:>6}")
        print("=" * 70)

        if FAILURE_DETAILS:
            print("\nFAILURE DETAILS")
            print("-" * 70)
            for f in FAILURE_DETAILS:
                print(f"test:     {f['test']}")
                print(f"expected: {f['expected']}")
                print(f"actual:   {f['actual']}")
                if f["body"]:
                    print(f"body:     {f['body']}")
                print("-" * 70)
        assert True
