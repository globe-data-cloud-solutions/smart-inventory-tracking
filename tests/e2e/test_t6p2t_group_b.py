"""
Tenant T6P2T End-to-End Test Suite — Groups 3-5.

Scope: Group 3 (positions), Group 4 (transfer types), Group 5 (personnel).
Groups 0-2 must have already run (test_t6p2t_group_a.py) — this file loads
their output from tests/e2e/t6p2t_state.json. Groups 6-9 are out of scope here.

Run:
    python -m pytest tests/e2e/test_t6p2t_group_b.py -v --tb=short

Requirements:
  - Backend running at http://localhost:8000 (override with E2E_BASE_URL)
  - ENVIRONMENT=local must be set in the backend (enables dev_email auth)
  - tests/e2e/t6p2t_state.json must exist (produced by test_t6p2t_group_a.py)

Ordering note: tests within this module share state through the module-level
STATE dict and rely on running in file/class definition order. pyproject.toml's
[tool.pytest.ini_options] does not enable any randomization plugin, so default
pytest collection order (top-to-bottom) is preserved. Each test still uses
skip_test() to degrade gracefully if an earlier prerequisite failed.
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
DEFAULT_PASSWORD = "Test@2026"   # password for every tenant user created in this file

SA_PASSWORD = "Admin@2026"       # SA's dev-env password (NOT Test@2026 — see group_a notes)
TA_PASSWORD = "Test@2026"

STATE_FILE = os.path.join(os.path.dirname(__file__), "t6p2t_state.json")

ORDERED_GROUPS = ["GROUP3", "GROUP4", "GROUP5"]

# ─────────────────────────────────────────────────────────────────────────────
# Load prior-group state
# ─────────────────────────────────────────────────────────────────────────────
with open(STATE_FILE, "r", encoding="utf-8") as _f:
    _LOADED_STATE: dict[str, Any] = json.load(_f)

STATE: dict[str, Any] = _LOADED_STATE
STATE.setdefault("positions", {})
STATE.setdefault("users", {})
STATE.setdefault("transfer_types", {})
TA_EMAIL = "admin@t6p2t.com"
SA_EMAIL = "smartadmin@smart-inventory.com"


def _decode_jwt_sub(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        return json.loads(base64.b64decode(payload_b64)).get("sub")
    except Exception:
        return None


# group_a's state file dump did not persist ta_user_id/sa_user_id — they're
# recoverable from the `sub` claim already embedded in the saved tokens.
STATE.setdefault("ta_user_id", _decode_jwt_sub(STATE.get("ta_token")))
STATE.setdefault("sa_user_id", _decode_jwt_sub(STATE.get("sa_token")))

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


def check(group: str, name: str, condition: bool, expected: str = "", actual: str = "", body: str = "") -> None:
    """Hard check — raises AssertionError (and so fails the pytest test) on failure."""
    if condition:
        record_pass(group, name)
    else:
        record_fail(group, name, expected, actual, body)
    assert condition, f"{name} — expected: {expected!r} actual: {actual!r} body: {body[:300]!r}"


def soft_check(group: str, name: str, condition: bool, expected: str = "", actual: str = "", body: str = "") -> bool:
    """Non-raising check for use inside a loop within a single test — lets every
    sub-case in the loop run and be recorded, instead of aborting at the first
    failure. The caller asserts the aggregate result once the loop completes."""
    if condition:
        record_pass(group, name)
    else:
        record_fail(group, name, expected, actual, body)
    return condition


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


def api_post(path: str, token: str, body: Any = None) -> requests.Response:
    return requests.post(f"{BASE_URL}{path}", headers=hdrs(token), json=body if body is not None else {}, timeout=15)


def api_put(path: str, token: str, body: Any = None) -> requests.Response:
    return requests.put(f"{BASE_URL}{path}", headers=hdrs(token), json=body, timeout=15)


def api_patch(path: str, token: str, body: Optional[dict] = None) -> requests.Response:
    return requests.patch(f"{BASE_URL}{path}", headers=hdrs(token), json=body or {}, timeout=15)


def api_delete(path: str, token: str, params: Optional[dict] = None) -> requests.Response:
    return requests.delete(f"{BASE_URL}{path}", headers=hdrs(token), params=params, timeout=15)


def jdata(r: requests.Response) -> Any:
    try:
        j = r.json()
        return j.get("data", j)
    except Exception:
        return {}


def err_code(r: requests.Response) -> Optional[str]:
    try:
        detail = r.json().get("detail")
        return detail.get("code") if isinstance(detail, dict) else None
    except Exception:
        return None


def uniq(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def tid() -> str:
    return STATE["tenant_id"]


def ta() -> str:
    return STATE["ta_token"]


def sa() -> str:
    return STATE["sa_token"]


def have_base_state() -> bool:
    return bool(STATE.get("tenant_id") and STATE.get("ta_token") and STATE.get("sa_token"))


def _refresh_tokens() -> None:
    """Re-login at import time so tokens are always fresh regardless of
    when t6p2t_state.json was last written. JWTs expire after 60 min;
    this ensures the module-level STATE dict always holds a live token
    before any test class is collected."""
    ta_email = "admin@t6p2t.com"
    ta_password = "Test@2026"
    sa_email = "smartadmin@smart-inventory.com"
    sa_password = "Admin@2026"

    try:
        ta_resp = login(ta_email, ta_password)
        if ta_resp.status_code == 200:
            token = ta_resp.json().get("access_token")
            if token:
                STATE["ta_token"] = token
    except Exception:
        pass  # leave stale token in place — individual tests will surface the 401

    try:
        sa_resp = login(sa_email, sa_password)
        if sa_resp.status_code == 200:
            token = sa_resp.json().get("access_token")
            if token:
                STATE["sa_token"] = token
    except Exception:
        pass


_refresh_tokens()


# ─────────────────────────────────────────────────────────────────────────────
# GROUP 3 — POSITIONS
# ─────────────────────────────────────────────────────────────────────────────
def _create_position(group: str, key: str, node_key: str, title: str, role: str, test_name: str) -> None:
    if not have_base_state():
        skip_test(group, test_name, "missing tenant_id/ta_token/sa_token")
    node_id = STATE["nodes"].get(node_key)
    if not node_id:
        skip_test(group, test_name, f"node {node_key} not found in state")
    r = api_post(f"/api/v1/tenants/{tid()}/nodes/{node_id}/positions", ta(), {"title": title, "role_code": role})
    d = jdata(r)
    if r.status_code == 201 and d.get("id"):
        STATE["positions"][key] = str(d["id"])
    check(
        group, test_name,
        r.status_code == 201 and bool(d.get("id")) and d.get("role_code") == role,
        expected=f"201, role_code={role}",
        actual=f"status={r.status_code}, role_code={d.get('role_code')!r}",
        body=r.text,
    )


@pytest.mark.integration
class TestGroup3Positions:
    GROUP = "GROUP3"

    # ── Side A (1 position per node) ─────────────────────────────────────────
    def test_300_a_fac_dir(self): _create_position(self.GROUP, "A_FAC_dir", "A_FAC", "Addis Factory Director", "NM", "3.0 Create position A_FAC_dir (Addis Factory Director, NM)")
    def test_301_a_reg_mgr(self): _create_position(self.GROUP, "A_REG_mgr", "A_REG", "Addis Regional Manager", "RM", "3.1 Create position A_REG_mgr (Addis Regional Manager, RM)")
    def test_302_wha1_mgr(self): _create_position(self.GROUP, "WHA1_mgr", "WHA1", "WHA1 Merkato Manager", "WM", "3.2 Create position WHA1_mgr (WHA1 Merkato Manager, WM)")
    def test_303_wha2_mgr(self): _create_position(self.GROUP, "WHA2_mgr", "WHA2", "WHA2 Bole Manager", "WM", "3.3 Create position WHA2_mgr (WHA2 Bole Manager, WM)")
    def test_304_wha3_mgr(self): _create_position(self.GROUP, "WHA3_mgr", "WHA3", "WHA3 Lideta Manager", "WM", "3.4 Create position WHA3_mgr (WHA3 Lideta Manager, WM)")
    def test_305_sat_wha1_lead(self): _create_position(self.GROUP, "SAT_WHA1_lead", "SAT_WHA1", "Satellite Merkato Lead", "LM", "3.5 Create position SAT_WHA1_lead (Satellite Merkato Lead, LM)")
    def test_306_sat_wha2_lead(self): _create_position(self.GROUP, "SAT_WHA2_lead", "SAT_WHA2", "Satellite Bole Lead", "LM", "3.6 Create position SAT_WHA2_lead (Satellite Bole Lead, LM)")

    # ── Side B (2 positions per node — main + assistant) ─────────────────────
    def test_307_b_fac_dir(self): _create_position(self.GROUP, "B_FAC_dir", "B_FAC", "Dire Factory Director", "NM", "3.7 Create position B_FAC_dir (Dire Factory Director, NM)")
    def test_308_b_fac_dir_asst(self): _create_position(self.GROUP, "B_FAC_dir_asst", "B_FAC", "Asst_Dire Factory Director", "NM", "3.8 Create position B_FAC_dir_asst (Asst_Dire Factory Director, NM)")
    def test_309_b_reg_mgr(self): _create_position(self.GROUP, "B_REG_mgr", "B_REG", "Dire Regional Manager", "RM", "3.9 Create position B_REG_mgr (Dire Regional Manager, RM)")
    def test_310_b_reg_mgr_asst(self): _create_position(self.GROUP, "B_REG_mgr_asst", "B_REG", "Asst_Dire Regional Manager", "RM", "3.10 Create position B_REG_mgr_asst (Asst_Dire Regional Manager, RM)")
    def test_311_whb1_mgr(self): _create_position(self.GROUP, "WHB1_mgr", "WHB1", "WHB1 Sabian Manager", "WM", "3.11 Create position WHB1_mgr (WHB1 Sabian Manager, WM)")
    def test_312_whb1_mgr_asst(self): _create_position(self.GROUP, "WHB1_mgr_asst", "WHB1", "Asst_WHB1 Sabian Manager", "WM", "3.12 Create position WHB1_mgr_asst (Asst_WHB1 Sabian Manager, WM)")
    def test_313_whb2_mgr(self): _create_position(self.GROUP, "WHB2_mgr", "WHB2", "WHB2 Kezira Manager", "WM", "3.13 Create position WHB2_mgr (WHB2 Kezira Manager, WM)")
    def test_314_whb2_mgr_asst(self): _create_position(self.GROUP, "WHB2_mgr_asst", "WHB2", "Asst_WHB2 Kezira Manager", "WM", "3.14 Create position WHB2_mgr_asst (Asst_WHB2 Kezira Manager, WM)")
    def test_315_sat_whb1_lead(self): _create_position(self.GROUP, "SAT_WHB1_lead", "SAT_WHB1", "Satellite Sabian Lead", "LM", "3.15 Create position SAT_WHB1_lead (Satellite Sabian Lead, LM)")
    def test_316_sat_whb1_lead_asst(self): _create_position(self.GROUP, "SAT_WHB1_lead_asst", "SAT_WHB1", "Asst_Satellite Sabian Lead", "LM", "3.16 Create position SAT_WHB1_lead_asst (Asst_Satellite Sabian Lead, LM)")
    def test_317_sat_whb2_lead(self): _create_position(self.GROUP, "SAT_WHB2_lead", "SAT_WHB2", "Satellite Kezira Lead", "LM", "3.17 Create position SAT_WHB2_lead (Satellite Kezira Lead, LM)")
    def test_318_sat_whb2_lead_asst(self): _create_position(self.GROUP, "SAT_WHB2_lead_asst", "SAT_WHB2", "Asst_Satellite Kezira Lead", "LM", "3.18 Create position SAT_WHB2_lead_asst (Asst_Satellite Kezira Lead, LM)")

    # ── Reports-to chain ──────────────────────────────────────────────────────
    def test_319_reports_to_chain(self) -> None:
        if not have_base_state():
            skip_test(self.GROUP, "3.19 Reports-to chain set for all 17 links", "missing base state")
        chain = [
            ("A_REG_mgr", "A_FAC_dir"), ("WHA1_mgr", "A_REG_mgr"), ("WHA2_mgr", "A_REG_mgr"),
            ("WHA3_mgr", "A_REG_mgr"), ("SAT_WHA1_lead", "WHA1_mgr"), ("SAT_WHA2_lead", "WHA2_mgr"),
            ("B_REG_mgr", "B_FAC_dir"), ("WHB1_mgr", "B_REG_mgr"), ("WHB2_mgr", "B_REG_mgr"),
            ("SAT_WHB1_lead", "WHB1_mgr"), ("SAT_WHB2_lead", "WHB2_mgr"),
            ("B_FAC_dir_asst", "B_FAC_dir"), ("B_REG_mgr_asst", "B_REG_mgr"),
            ("WHB1_mgr_asst", "WHB1_mgr"), ("WHB2_mgr_asst", "WHB2_mgr"),
            ("SAT_WHB1_lead_asst", "SAT_WHB1_lead"), ("SAT_WHB2_lead_asst", "SAT_WHB2_lead"),
        ]
        all_ok = True
        for child_key, parent_key in chain:
            child_id = STATE["positions"].get(child_key)
            parent_id = STATE["positions"].get(parent_key)
            name = f"3.19.{child_key} reports_to {parent_key}"
            if not (child_id and parent_id):
                soft_check(self.GROUP, name, False, expected="both position ids present",
                           actual=f"child={child_id}, parent={parent_id}")
                all_ok = False
                continue
            r = api_patch(f"/api/v1/tenants/{tid()}/positions/{child_id}", ta(),
                          {"reports_to_position_id": parent_id})
            d = jdata(r)
            ok = r.status_code == 200 and str(d.get("reports_to_position_id")) == parent_id
            if not soft_check(self.GROUP, name, ok,
                               expected=f"200, reports_to_position_id={parent_id}",
                               actual=f"status={r.status_code}, reports_to_position_id={d.get('reports_to_position_id')!r}",
                               body=r.text):
                all_ok = False
        assert all_ok, "one or more reports-to links failed — see FAILURE_DETAILS in summary"

    # ── Position edit tests ───────────────────────────────────────────────────
    def test_320_rename_wha2_position(self) -> None:
        pos_id = STATE["positions"].get("WHA2_mgr")
        if not pos_id:
            skip_test(self.GROUP, "3.20 Rename WHA2 position title, verify", "no position id for WHA2_mgr")
        r = api_patch(f"/api/v1/tenants/{tid()}/positions/{pos_id}", ta(), {"title": "WHA2 Bole-Airport Manager"})
        d = jdata(r)
        check(
            self.GROUP, "3.20 Rename WHA2 position title, verify",
            r.status_code == 200 and d.get("title") == "WHA2 Bole-Airport Manager",
            expected="200, title='WHA2 Bole-Airport Manager'",
            actual=f"status={r.status_code}, title={d.get('title')!r}", body=r.text,
        )

    def test_321_wha3_role_code_round_trip(self) -> None:
        pos_id = STATE["positions"].get("WHA3_mgr")
        if not pos_id:
            skip_test(self.GROUP, "3.21 WHA3 role_code WM→LM→WM round trip persists", "no position id for WHA3_mgr")
        r1 = api_patch(f"/api/v1/tenants/{tid()}/positions/{pos_id}", ta(), {"role_code": "LM"})
        d1 = jdata(r1)
        r2 = api_patch(f"/api/v1/tenants/{tid()}/positions/{pos_id}", ta(), {"role_code": "WM"})
        d2 = jdata(r2)
        check(
            self.GROUP, "3.21 WHA3 role_code WM→LM→WM round trip persists",
            r1.status_code == 200 and d1.get("role_code") == "LM"
            and r2.status_code == 200 and d2.get("role_code") == "WM",
            expected="step1: 200/LM, step2: 200/WM",
            actual=f"step1={r1.status_code}/{d1.get('role_code')!r}, step2={r2.status_code}/{d2.get('role_code')!r}",
            body=f"{r1.text[:200]} | {r2.text[:200]}",
        )

    def test_322_duplicate_position_title_rejected(self) -> None:
        """Probe for title-uniqueness validation at a node. create_position() in
        positions.py performs no such check, so a 201 here is an expected gap."""
        node_id = STATE["nodes"].get("A_FAC")
        if not node_id:
            skip_test(self.GROUP, "3.22 Duplicate position title at same node → 409/422", "no node id for A_FAC")
        r = api_post(f"/api/v1/tenants/{tid()}/nodes/{node_id}/positions", ta(),
                     {"title": "Addis Factory Director", "role_code": "NM"})
        check(
            self.GROUP, "3.22 Duplicate position title at same node → 409/422",
            r.status_code in (409, 422),
            expected="409 or 422", actual=f"status={r.status_code}", body=r.text,
        )

    def test_323_invalid_role_code_rejected(self) -> None:
        node_id = STATE["nodes"].get("A_FAC")
        if not node_id:
            skip_test(self.GROUP, "3.23 Invalid role_code → 422", "no node id for A_FAC")
        r = api_post(f"/api/v1/tenants/{tid()}/nodes/{node_id}/positions", ta(),
                     {"title": "Bogus Position", "role_code": "ZZ"})
        check(
            self.GROUP, "3.23 Invalid role_code → 422",
            r.status_code == 422 and err_code(r) == "INVALID_ROLE_CODE",
            expected="422, code=INVALID_ROLE_CODE", actual=f"status={r.status_code}, code={err_code(r)!r}",
            body=r.text,
        )

    def test_324_isself_guard_ta_cannot_assign_own_position(self) -> None:
        """positions.py has no notion of 'TA's own position' since TA has none — the
        actual isSelf guard lives in personnel_v2.assign_position()/update_user(),
        triggered by comparing the caller's user id to the target user id. Probing it
        here via POST /users/{ta_user_id}/positions with the TA acting on itself."""
        ta_user_id = STATE.get("ta_user_id")
        any_position_id = STATE["positions"].get("A_FAC_dir")
        if not (ta_user_id and any_position_id):
            skip_test(self.GROUP, "3.24 TA cannot assign own position → 403 CANNOT_MODIFY_OWN_ROLE",
                      "missing ta_user_id or position id")
        r = api_post(f"/api/v1/tenants/{tid()}/users/{ta_user_id}/positions", ta(),
                     {"position_id": any_position_id, "assignment_type": "PRIMARY"})
        check(
            self.GROUP, "3.24 TA cannot assign own position → 403 CANNOT_MODIFY_OWN_ROLE",
            r.status_code == 403 and err_code(r) == "CANNOT_MODIFY_OWN_ROLE",
            expected="403, code=CANNOT_MODIFY_OWN_ROLE",
            actual=f"status={r.status_code}, code={err_code(r)!r}", body=r.text,
        )


# ─────────────────────────────────────────────────────────────────────────────
# GROUP 4 — TRANSFER TYPES
# ─────────────────────────────────────────────────────────────────────────────
def _all_level_permissions() -> list[dict]:
    return [{"level_number": n, "can_initiate": True, "can_receive": True} for n in (1, 2, 3, 4)]


def _create_transfer_type(group: str, underlying_type: str, display_name: str, test_name: str) -> None:
    if not have_base_state():
        skip_test(group, test_name, "missing base state")
    body = [{
        "underlying_type": underlying_type,
        "display_name": display_name,
        "is_active": True,
        "sort_order": 0,
        "level_permissions": _all_level_permissions(),
    }]
    r = api_put(f"/api/v1/tenants/{tid()}/transfer-types", ta(), body)
    d = jdata(r)
    match = next((t for t in d if isinstance(d, list) and t.get("underlying_type") == underlying_type), None)
    if match and match.get("id"):
        STATE["transfer_types"][underlying_type] = str(match["id"])
    check(
        group, test_name,
        r.status_code == 200 and match is not None and len(match.get("level_permissions", [])) == 4,
        expected="200, underlying_type present with 4 level_permissions",
        actual=f"status={r.status_code}, match={'found' if match else 'missing'}",
        body=r.text[:500],
    )


@pytest.mark.integration
class TestGroup4TransferTypes:
    GROUP = "GROUP4"

    def test_40_create_pull(self):
        _create_transfer_type(self.GROUP, "PULL", "Pull Request", "4.0 Create transfer type PULL (Pull Request, all 4 levels)")

    def test_41_create_push(self):
        _create_transfer_type(self.GROUP, "PUSH", "Push Transfer", "4.1 Create transfer type PUSH (Push Transfer, all 4 levels)")

    def test_42_create_sister(self):
        _create_transfer_type(self.GROUP, "SISTER", "Sister Transfer", "4.2 Create transfer type SISTER (Sister Transfer, all 4 levels)")

    def test_43_default_thresholds(self) -> None:
        """Default thresholds (quantity: min=0, no upper bound) live on
        transfer_approval_rules, not transfer_type_config — set via the approval
        rules endpoint, one rule per type, with no source/destination level
        restriction (applies tenant-wide)."""
        if not have_base_state():
            skip_test(self.GROUP, "4.3 Set default thresholds (qty min=0, no max) per type", "missing base state")
        rules = [
            {"transfer_type_config_id": ctid, "quantity_min": 0, "threshold_type": "QUANTITY",
             "approval_steps": [], "priority": 0, "is_active": True}
            for ctid in STATE["transfer_types"].values()
        ]
        r = api_put(f"/api/v1/tenants/{tid()}/transfer-approval-rules", ta(), rules)
        d = jdata(r)
        check(
            self.GROUP, "4.3 Set default thresholds (qty min=0, no max) per type",
            r.status_code == 200 and isinstance(d, list) and len(d) == len(rules),
            expected=f"200, {len(rules)} rules", actual=f"status={r.status_code}, count={len(d) if isinstance(d, list) else 'n/a'}",
            body=r.text[:500],
        )

    def test_44_rename_pull_round_trip(self) -> None:
        if not STATE["transfer_types"].get("PULL"):
            skip_test(self.GROUP, "4.4 Rename 'Pull Request'→'Pull Order'→back, verify", "no PULL transfer type id")
        body1 = [{"underlying_type": "PULL", "display_name": "Pull Order", "level_permissions": _all_level_permissions()}]
        r1 = api_put(f"/api/v1/tenants/{tid()}/transfer-types", ta(), body1)
        d1 = next((t for t in jdata(r1) if t.get("underlying_type") == "PULL"), {})
        body2 = [{"underlying_type": "PULL", "display_name": "Pull Request", "level_permissions": _all_level_permissions()}]
        r2 = api_put(f"/api/v1/tenants/{tid()}/transfer-types", ta(), body2)
        d2 = next((t for t in jdata(r2) if t.get("underlying_type") == "PULL"), {})
        check(
            self.GROUP, "4.4 Rename 'Pull Request'→'Pull Order'→back, verify",
            d1.get("display_name") == "Pull Order" and d2.get("display_name") == "Pull Request",
            expected="step1: 'Pull Order', step2: 'Pull Request'",
            actual=f"step1={d1.get('display_name')!r}, step2={d2.get('display_name')!r}",
            body=f"{r1.text[:200]} | {r2.text[:200]}",
        )

    def test_45_duplicate_type_code_rejected(self) -> None:
        """Probe for duplicate-code rejection. upsert_transfer_types() is keyed by
        underlying_type and upserts unconditionally — submitting PULL twice in one
        PUT just upserts twice (last write wins), so a 200 here is an expected gap,
        not a tooling mistake."""
        if not have_base_state():
            skip_test(self.GROUP, "4.5 Duplicate transfer type code in one PUT → 409/422", "missing base state")
        body = [
            {"underlying_type": "PULL", "display_name": "Pull Request A", "level_permissions": []},
            {"underlying_type": "PULL", "display_name": "Pull Request B", "level_permissions": []},
        ]
        r = api_put(f"/api/v1/tenants/{tid()}/transfer-types", ta(), body)
        # Restore canonical PULL config regardless of outcome.
        api_put(f"/api/v1/tenants/{tid()}/transfer-types", ta(),
                [{"underlying_type": "PULL", "display_name": "Pull Request", "level_permissions": _all_level_permissions()}])
        check(
            self.GROUP, "4.5 Duplicate transfer type code in one PUT → 409/422",
            r.status_code in (409, 422),
            expected="409 or 422", actual=f"status={r.status_code}", body=r.text,
        )

    def test_46_toggle_requires_approval(self) -> None:
        """'requires_approval' as a standalone flag does not exist on
        TransferTypeConfigIn/Out — the schema only has is_active, sort_order, and
        level_permissions. The closest analogue is is_active (a type can be turned
        off entirely). Toggling is_active off then on and verifying persistence."""
        if not STATE["transfer_types"].get("SISTER"):
            skip_test(self.GROUP, "4.6 Toggle is_active off→on for SISTER, verify persists", "no SISTER transfer type id")
        off_body = [{"underlying_type": "SISTER", "display_name": "Sister Transfer", "is_active": False, "level_permissions": _all_level_permissions()}]
        r1 = api_put(f"/api/v1/tenants/{tid()}/transfer-types", ta(), off_body)
        d1 = next((t for t in jdata(r1) if t.get("underlying_type") == "SISTER"), {})
        on_body = [{"underlying_type": "SISTER", "display_name": "Sister Transfer", "is_active": True, "level_permissions": _all_level_permissions()}]
        r2 = api_put(f"/api/v1/tenants/{tid()}/transfer-types", ta(), on_body)
        d2 = next((t for t in jdata(r2) if t.get("underlying_type") == "SISTER"), {})
        check(
            self.GROUP, "4.6 Toggle is_active off→on for SISTER, verify persists",
            d1.get("is_active") is False and d2.get("is_active") is True,
            expected="step1: is_active=false, step2: is_active=true",
            actual=f"step1={d1.get('is_active')!r}, step2={d2.get('is_active')!r}",
            body=f"{r1.text[:200]} | {r2.text[:200]}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# GROUP 5 — PERSONNEL
# ─────────────────────────────────────────────────────────────────────────────
def _create_user(
    group: str, key: str, email: str, name: str, test_name: str,
    position_id: Optional[str] = None, system_role: Optional[str] = None,
) -> None:
    if not have_base_state():
        skip_test(group, test_name, "missing base state")
    body: dict[str, Any] = {"name": name, "email": email, "password": DEFAULT_PASSWORD}
    if position_id:
        body["position_id"] = position_id
    if system_role:
        body["system_role"] = system_role
    r = api_post(f"/api/v1/tenants/{tid()}/users", ta(), body)
    d = jdata(r)
    if r.status_code == 201 and d.get("id"):
        STATE["users"][key] = {
            "id": str(d["id"]), "email": email, "password": DEFAULT_PASSWORD,
            "assignment_id": str(d["primary_position"]["assignment_id"]) if d.get("primary_position") else None,
        }
    check(
        group, test_name,
        r.status_code == 201 and bool(d.get("id")),
        expected="201 + user id", actual=f"status={r.status_code}", body=r.text,
    )


@pytest.mark.integration
class TestGroup5PersonnelSideA:
    GROUP = "GROUP5"

    def test_500_nm_addisfac(self):
        _create_user(self.GROUP, "nm_addisfac", "nm_addisfac@t6p2t.com", "NM Addis Fac",
                      "5.0 Create user nm_addisfac@t6p2t.com (Addis Factory Director)",
                      position_id=STATE["positions"].get("A_FAC_dir"))

    def test_501_rm_addisreg(self):
        _create_user(self.GROUP, "rm_addisreg", "rm_addisreg@t6p2t.com", "RM Addis Reg",
                      "5.1 Create user rm_addisreg@t6p2t.com (Addis Regional Manager)",
                      position_id=STATE["positions"].get("A_REG_mgr"))

    def test_502_wm_wha1(self):
        _create_user(self.GROUP, "wm_wha1", "wm_wha1@t6p2t.com", "WM WHA1",
                      "5.2 Create user wm_wha1@t6p2t.com (WHA1 Merkato Manager)",
                      position_id=STATE["positions"].get("WHA1_mgr"))

    def test_503_wm_wha2(self):
        _create_user(self.GROUP, "wm_wha2", "wm_wha2@t6p2t.com", "WM WHA2",
                      "5.3 Create user wm_wha2@t6p2t.com (WHA2 Bole-Airport Manager)",
                      position_id=STATE["positions"].get("WHA2_mgr"))

    def test_504_wm_wha3(self):
        _create_user(self.GROUP, "wm_wha3", "wm_wha3@t6p2t.com", "WM WHA3",
                      "5.4 Create user wm_wha3@t6p2t.com (WHA3 Lideta Manager)",
                      position_id=STATE["positions"].get("WHA3_mgr"))

    def test_505_lm_satwha1(self):
        _create_user(self.GROUP, "lm_satwha1", "lm_satwha1@t6p2t.com", "LM Sat WHA1",
                      "5.5 Create user lm_satwha1@t6p2t.com (Satellite Merkato Lead)",
                      position_id=STATE["positions"].get("SAT_WHA1_lead"))

    def test_506_lm_satwha2(self):
        _create_user(self.GROUP, "lm_satwha2", "lm_satwha2@t6p2t.com", "LM Sat WHA2",
                      "5.6 Create user lm_satwha2@t6p2t.com (Satellite Bole Lead)",
                      position_id=STATE["positions"].get("SAT_WHA2_lead"))


@pytest.mark.integration
class TestGroup5PersonnelSideB:
    GROUP = "GROUP5"

    def test_510_nm_direfac(self):
        _create_user(self.GROUP, "nm_direfac", "nm_direfac@t6p2t.com", "NM Dire Fac",
                      "5.10 Create user nm_direfac@t6p2t.com (Dire Factory Director)",
                      position_id=STATE["positions"].get("B_FAC_dir"))

    def test_511_nm_direfac_asst(self):
        _create_user(self.GROUP, "nm_direfac_asst", "nm_direfac_asst@t6p2t.com", "Asst NM Dire Fac",
                      "5.11 Create user nm_direfac_asst@t6p2t.com (Asst_Dire Factory Director)",
                      position_id=STATE["positions"].get("B_FAC_dir_asst"))

    def test_512_rm_direreg(self):
        _create_user(self.GROUP, "rm_direreg", "rm_direreg@t6p2t.com", "RM Dire Reg",
                      "5.12 Create user rm_direreg@t6p2t.com (Dire Regional Manager)",
                      position_id=STATE["positions"].get("B_REG_mgr"))

    def test_513_rm_direreg_asst(self):
        _create_user(self.GROUP, "rm_direreg_asst", "rm_direreg_asst@t6p2t.com", "Asst RM Dire Reg",
                      "5.13 Create user rm_direreg_asst@t6p2t.com (Asst_Dire Regional Manager)",
                      position_id=STATE["positions"].get("B_REG_mgr_asst"))

    def test_514_wm_whb1(self):
        _create_user(self.GROUP, "wm_whb1", "wm_whb1@t6p2t.com", "WM WHB1",
                      "5.14 Create user wm_whb1@t6p2t.com (WHB1 Sabian Manager)",
                      position_id=STATE["positions"].get("WHB1_mgr"))

    def test_515_wm_whb1_asst(self):
        _create_user(self.GROUP, "wm_whb1_asst", "wm_whb1_asst@t6p2t.com", "Asst WM WHB1",
                      "5.15 Create user wm_whb1_asst@t6p2t.com (Asst_WHB1 Sabian Manager)",
                      position_id=STATE["positions"].get("WHB1_mgr_asst"))

    def test_516_wm_whb2(self):
        _create_user(self.GROUP, "wm_whb2", "wm_whb2@t6p2t.com", "WM WHB2",
                      "5.16 Create user wm_whb2@t6p2t.com (WHB2 Kezira Manager)",
                      position_id=STATE["positions"].get("WHB2_mgr"))

    def test_517_wm_whb2_asst(self):
        _create_user(self.GROUP, "wm_whb2_asst", "wm_whb2_asst@t6p2t.com", "Asst WM WHB2",
                      "5.17 Create user wm_whb2_asst@t6p2t.com (Asst_WHB2 Kezira Manager)",
                      position_id=STATE["positions"].get("WHB2_mgr_asst"))

    def test_518_lm_satwhb1(self):
        _create_user(self.GROUP, "lm_satwhb1", "lm_satwhb1@t6p2t.com", "LM Sat WHB1",
                      "5.18 Create user lm_satwhb1@t6p2t.com (Satellite Sabian Lead)",
                      position_id=STATE["positions"].get("SAT_WHB1_lead"))

    def test_519_lm_satwhb1_asst(self):
        _create_user(self.GROUP, "lm_satwhb1_asst", "lm_satwhb1_asst@t6p2t.com", "Asst LM Sat WHB1",
                      "5.19 Create user lm_satwhb1_asst@t6p2t.com (Asst_Satellite Sabian Lead)",
                      position_id=STATE["positions"].get("SAT_WHB1_lead_asst"))

    def test_520_lm_satwhb2(self):
        _create_user(self.GROUP, "lm_satwhb2", "lm_satwhb2@t6p2t.com", "LM Sat WHB2",
                      "5.20 Create user lm_satwhb2@t6p2t.com (Satellite Kezira Lead)",
                      position_id=STATE["positions"].get("SAT_WHB2_lead"))

    def test_521_lm_satwhb2_asst(self):
        _create_user(self.GROUP, "lm_satwhb2_asst", "lm_satwhb2_asst@t6p2t.com", "Asst LM Sat WHB2",
                      "5.21 Create user lm_satwhb2_asst@t6p2t.com (Asst_Satellite Kezira Lead)",
                      position_id=STATE["positions"].get("SAT_WHB2_lead_asst"))


@pytest.mark.integration
class TestGroup5PersonnelTenantWideAndSecondary:
    GROUP = "GROUP5"

    def test_530_au_tenant_wide(self):
        _create_user(self.GROUP, "au_t6p2t", "au_t6p2t@t6p2t.com", "Tenant Auditor",
                      "5.30 Create user au_t6p2t@t6p2t.com (tenant-wide AU)", system_role="AU")

    def test_531_lm_tenant_wide(self):
        _create_user(self.GROUP, "lm_tenant", "lm_tenant@t6p2t.com", "Tenant LM",
                      "5.31 Create user lm_tenant@t6p2t.com (tenant-wide LM, no node)", system_role="LM")

    def test_532_wm_wha1_sec(self):
        _create_user(self.GROUP, "wm_wha1_sec", "wm_wha1_sec@t6p2t.com", "WM WHA1 Secondary",
                      "5.32 Create user wm_wha1_sec@t6p2t.com (2nd holder, WHA1 Merkato Manager)",
                      position_id=STATE["positions"].get("WHA1_mgr"))

    def test_533_rm_addisreg_sec(self):
        _create_user(self.GROUP, "rm_addisreg_sec", "rm_addisreg_sec@t6p2t.com", "RM Addis Reg Secondary",
                      "5.33 Create user rm_addisreg_sec@t6p2t.com (2nd holder, Addis Regional Manager)",
                      position_id=STATE["positions"].get("A_REG_mgr"))

    def test_534_lm_satwha1_sec(self):
        _create_user(self.GROUP, "lm_satwha1_sec", "lm_satwha1_sec@t6p2t.com", "LM Sat WHA1 Secondary",
                      "5.34 Create user lm_satwha1_sec@t6p2t.com (2nd holder, Satellite Merkato Lead)",
                      position_id=STATE["positions"].get("SAT_WHA1_lead"))


@pytest.mark.integration
class TestGroup5PersonnelGuardsAndFlows:
    GROUP = "GROUP5"

    def test_540_ta_cannot_create_another_ta(self) -> None:
        if not have_base_state():
            skip_test(self.GROUP, "5.40 TA cannot create another TA → 403 ROLE_CEILING_EXCEEDED", "missing base state")
        r = api_post(f"/api/v1/tenants/{tid()}/users", ta(), {
            "name": "Rogue TA Attempt 2",
            "email": f"rogue-ta-{uniq()}@t6p2t.com",
            "password": DEFAULT_PASSWORD,
            "system_role": "TA",
        })
        check(
            self.GROUP, "5.40 TA cannot create another TA → 403 ROLE_CEILING_EXCEEDED",
            r.status_code == 403 and err_code(r) == "ROLE_CEILING_EXCEEDED",
            expected="403, code=ROLE_CEILING_EXCEEDED", actual=f"status={r.status_code}, code={err_code(r)!r}", body=r.text,
        )

    def test_541_ta_cannot_edit_own_position(self) -> None:
        ta_user_id = STATE.get("ta_user_id")
        any_position_id = STATE["positions"].get("A_FAC_dir")
        if not (ta_user_id and any_position_id):
            skip_test(self.GROUP, "5.41 TA cannot edit own position → 403 CANNOT_MODIFY_OWN_ROLE", "missing ta_user_id/position id")
        r = api_post(f"/api/v1/tenants/{tid()}/users/{ta_user_id}/positions", ta(),
                     {"position_id": any_position_id, "assignment_type": "ACTING"})
        check(
            self.GROUP, "5.41 TA cannot edit own position → 403 CANNOT_MODIFY_OWN_ROLE",
            r.status_code == 403 and err_code(r) == "CANNOT_MODIFY_OWN_ROLE",
            expected="403, code=CANNOT_MODIFY_OWN_ROLE", actual=f"status={r.status_code}, code={err_code(r)!r}", body=r.text,
        )

    def test_542_no_self_deactivation(self) -> None:
        ta_user_id = STATE.get("ta_user_id")
        if not ta_user_id:
            skip_test(self.GROUP, "5.42 TA cannot deactivate own account → 422/403", "missing ta_user_id")
        r = api_patch(f"/api/v1/tenants/{tid()}/users/{ta_user_id}/deactivate", ta())
        check(
            self.GROUP, "5.42 TA cannot deactivate own account → 422/403",
            r.status_code in (422, 403) and err_code(r) == "CANNOT_DEACTIVATE_SELF",
            expected="422 or 403, code=CANNOT_DEACTIVATE_SELF",
            actual=f"status={r.status_code}, code={err_code(r)!r}", body=r.text,
        )

    def test_543_last_ta_deactivation_guard(self) -> None:
        """Distinguishes CANNOT_DEACTIVATE_LAST_TA from CANNOT_DEACTIVATE_SELF by having
        SA (a different caller) attempt to deactivate the tenant's only TA."""
        ta_user_id = STATE.get("ta_user_id")
        if not (ta_user_id and have_base_state()):
            skip_test(self.GROUP, "5.43 SA cannot deactivate the tenant's last TA → 422 CANNOT_DEACTIVATE_LAST_TA",
                      "missing ta_user_id/base state")
        r = api_patch(f"/api/v1/tenants/{tid()}/users/{ta_user_id}/deactivate", sa())
        check(
            self.GROUP, "5.43 SA cannot deactivate the tenant's last TA → 422 CANNOT_DEACTIVATE_LAST_TA",
            r.status_code == 422 and err_code(r) == "CANNOT_DEACTIVATE_LAST_TA",
            expected="422, code=CANNOT_DEACTIVATE_LAST_TA",
            actual=f"status={r.status_code}, code={err_code(r)!r}", body=r.text,
        )

    def test_544_password_reset_wm_wha1(self) -> None:
        u = STATE["users"].get("wm_wha1")
        if not u:
            skip_test(self.GROUP, "5.44 TA resets wm_wha1 password, new password logs in", "no wm_wha1 user record")
        new_password = "NewPass@2026"
        r = api_patch(f"/api/v1/tenants/{tid()}/users/{u['id']}", ta(), {"password": new_password})
        reset_ok = r.status_code == 200
        login_r = login(u["email"], new_password)
        login_ok = login_r.status_code == 200 and bool(login_r.json().get("access_token"))
        if login_ok:
            u["password"] = new_password
        check(
            self.GROUP, "5.44 TA resets wm_wha1 password, new password logs in",
            reset_ok and login_ok,
            expected="PATCH 200, then login 200 with new password",
            actual=f"reset_status={r.status_code}, login_status={login_r.status_code}, token_present={bool(login_r.json().get('access_token')) if login_r.status_code == 200 else False}",
            body=f"{r.text[:200]} | {login_r.text[:200]}",
        )

    def test_545_deactivate_reactivate_wm_wha2(self) -> None:
        u = STATE["users"].get("wm_wha2")
        if not u:
            skip_test(self.GROUP, "5.45 Deactivate wm_wha2 blocks login; reactivate restores login", "no wm_wha2 user record")
        r_deact = api_patch(f"/api/v1/tenants/{tid()}/users/{u['id']}/deactivate", ta())
        login_blocked = login(u["email"], u["password"])
        r_react = api_patch(f"/api/v1/tenants/{tid()}/users/{u['id']}/reactivate", ta())
        login_after = login(u["email"], u["password"])
        check(
            self.GROUP, "5.45 Deactivate wm_wha2 blocks login; reactivate restores login",
            r_deact.status_code == 200
            and login_blocked.status_code == 401
            and r_react.status_code == 200
            and login_after.status_code == 200,
            expected="deactivate 200, login 401, reactivate 200, login 200",
            actual=(
                f"deactivate={r_deact.status_code}, login_blocked={login_blocked.status_code}, "
                f"reactivate={r_react.status_code}, login_after={login_after.status_code}"
            ),
            body=f"{r_deact.text[:150]} | {login_blocked.text[:150]} | {r_react.text[:150]} | {login_after.text[:150]}",
        )

    def test_546_primary_swap_wha3(self) -> None:
        """assign_position()'s PRIMARY swap is per-USER, not per-POSITION: assigning
        a user a new PRIMARY deactivates *that same user's* existing PRIMARY
        elsewhere, but does not touch any other user's PRIMARY at the position
        being assigned to (multiple simultaneous PRIMARY holders at one position
        are explicitly supported — see the Group 5 SECONDARY users). So the real
        swap to exercise here is one user moving between two positions: create
        wm_wha3_sec at WHA3_mgr, swap them to SAT_WHA1_lead (WHA3_mgr should
        auto-deactivate), then swap back to WHA3_mgr (SAT_WHA1_lead should
        auto-deactivate) — verifying the confirmation-free atomic swap both ways."""
        wha3_pos = STATE["positions"].get("WHA3_mgr")
        other_pos = STATE["positions"].get("SAT_WHA1_lead")
        if not (wha3_pos and other_pos and have_base_state()):
            skip_test(self.GROUP, "5.46 PRIMARY swap: wm_wha3_sec WHA3_mgr→SAT_WHA1_lead→back, verify final state",
                      "missing WHA3_mgr/SAT_WHA1_lead position ids")

        sec_email = f"wm_wha3_sec_{uniq()}@t6p2t.com"
        r_create = api_post(f"/api/v1/tenants/{tid()}/users", ta(), {
            "name": "WM WHA3 Secondary", "email": sec_email, "password": DEFAULT_PASSWORD,
            "position_id": wha3_pos,
        })
        sec_user_id = jdata(r_create).get("id")
        if not sec_user_id:
            check(self.GROUP, "5.46 PRIMARY swap: wm_wha3_sec WHA3_mgr→SAT_WHA1_lead→back, verify final state",
                  False, expected="201 + user id", actual=f"status={r_create.status_code}", body=r_create.text)
            return

        r_swap_out = api_post(f"/api/v1/tenants/{tid()}/users/{sec_user_id}/positions", ta(), {
            "position_id": other_pos, "assignment_type": "PRIMARY",
        })
        primary_after_swap_out = jdata(r_swap_out).get("position_id")

        r_swap_back = api_post(f"/api/v1/tenants/{tid()}/users/{sec_user_id}/positions", ta(), {
            "position_id": wha3_pos, "assignment_type": "PRIMARY",
        })
        primary_after_swap_back = jdata(r_swap_back).get("position_id")

        r_final = api_get(f"/api/v1/tenants/{tid()}/users/{sec_user_id}", ta())
        final_primary = jdata(r_final).get("primary_position") or {}

        check(
            self.GROUP, "5.46 PRIMARY swap: wm_wha3_sec WHA3_mgr→SAT_WHA1_lead→back, verify final state",
            r_create.status_code == 201
            and r_swap_out.status_code == 201 and primary_after_swap_out == other_pos
            and r_swap_back.status_code == 201 and primary_after_swap_back == wha3_pos
            and final_primary.get("position_id") == wha3_pos,
            expected="swap-out PRIMARY=SAT_WHA1_lead, swap-back PRIMARY=WHA3_mgr, final state=WHA3_mgr",
            actual=(
                f"create={r_create.status_code}, swap_out={r_swap_out.status_code}/{primary_after_swap_out}, "
                f"swap_back={r_swap_back.status_code}/{primary_after_swap_back}, "
                f"final={final_primary.get('position_id')}"
            ),
            body=f"{r_swap_out.text[:200]} | {r_swap_back.text[:200]}",
        )

    def test_547_sa_force_remove_sole_primary(self) -> None:
        u = STATE["users"].get("lm_satwha2")
        if not (u and u.get("assignment_id") and have_base_state()):
            skip_test(self.GROUP, "5.47 SA force-removes lm_satwha2's sole PRIMARY → user_deactivated=true",
                      "missing lm_satwha2 user/assignment_id")
        r = api_delete(
            f"/api/v1/tenants/{tid()}/users/{u['id']}/positions/{u['assignment_id']}",
            sa(), params={"force": "true"},
        )
        d = jdata(r)
        check(
            self.GROUP, "5.47 SA force-removes lm_satwha2's sole PRIMARY → user_deactivated=true",
            r.status_code == 200 and d.get("user_deactivated") is True,
            expected="200, user_deactivated=true",
            actual=f"status={r.status_code}, user_deactivated={d.get('user_deactivated')!r}", body=r.text,
        )

    def test_548_au_login_read_only(self) -> None:
        u = STATE["users"].get("au_t6p2t")
        if not u:
            skip_test(self.GROUP, "5.48 AU can read tenant data but cannot create/manage", "no au_t6p2t user record")
        login_r = login(u["email"], u["password"])
        token = login_r.json().get("access_token") if login_r.status_code == 200 else None
        if not token:
            check(self.GROUP, "5.48 AU can read tenant data but cannot create/manage", False,
                  expected="200 + access_token", actual=f"status={login_r.status_code}", body=login_r.text)
            return
        r_read = api_get(f"/api/v1/tenants/{tid()}", token)
        r_create_position = api_post(
            f"/api/v1/tenants/{tid()}/nodes/{STATE['nodes']['A_FAC']}/positions", token,
            {"title": "AU Attempt", "role_code": "NM"},
        )
        r_manage_approval = api_put(f"/api/v1/tenants/{tid()}/transfer-approval-rules", token, [])
        check(
            self.GROUP, "5.48 AU can read tenant data but cannot create/manage",
            r_read.status_code == 200 and r_create_position.status_code == 403 and r_manage_approval.status_code == 403,
            expected="read=200, create_position=403, manage_approval=403",
            actual=f"read={r_read.status_code}, create_position={r_create_position.status_code}, manage_approval={r_manage_approval.status_code}",
            body=f"{r_read.text[:150]} | {r_create_position.text[:150]} | {r_manage_approval.text[:150]}",
        )

    def test_549_lm_login_node_scoped(self) -> None:
        """Probes whether LM's tenant-wide read access (position:view, tenant:view)
        is restricted to its own node. middleware.py's FACILITY_SCOPED_ROLES set is
        {WM, SA_GT, RT} — LM is deliberately excluded ('management roles operate
        across warehouses within their authority'), so LM is expected to see the
        FULL tenant-wide position list, not a node-scoped subset. A full list here
        disproves 'node-scoped access only' — an expected gap relative to the spec,
        not a tooling mistake."""
        u = STATE["users"].get("lm_satwhb1")
        if not u:
            skip_test(self.GROUP, "5.49 LM sees only its own node's positions (node-scoped)", "no lm_satwhb1 user record")
        login_r = login(u["email"], u["password"])
        token = login_r.json().get("access_token") if login_r.status_code == 200 else None
        if not token:
            check(self.GROUP, "5.49 LM sees only its own node's positions (node-scoped)", False,
                  expected="200 + access_token", actual=f"status={login_r.status_code}", body=login_r.text)
            return
        r_positions = api_get(f"/api/v1/tenants/{tid()}/positions/flat", token)
        positions = jdata(r_positions) if isinstance(jdata(r_positions), list) else []
        own_node_id = str(STATE["nodes"]["SAT_WHB1"])
        only_own_node = all(str(p.get("node_id")) == own_node_id for p in positions) if positions else False
        check(
            self.GROUP, "5.49 LM sees only its own node's positions (node-scoped)",
            r_positions.status_code == 200 and only_own_node,
            expected="200, every returned position scoped to LM's own node",
            actual=f"status={r_positions.status_code}, total_positions={len(positions)}, only_own_node={only_own_node}",
            body=r_positions.text[:500],
        )


# ─────────────────────────────────────────────────────────────────────────────
# STATE FILE + REPORTING (always runs last — file/class definition order)
# ─────────────────────────────────────────────────────────────────────────────
class TestZZStateFileAndSummary:
    def test_91_write_state_file(self) -> None:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(STATE, f, indent=2)
        print(f"\nState file updated at {STATE_FILE}")
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
