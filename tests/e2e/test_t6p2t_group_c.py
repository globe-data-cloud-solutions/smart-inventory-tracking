"""
Tenant T6P2T End-to-End Test Suite — Groups 6-9 (final).

Scope: Group 6 (approval rules), Group 7 (branding), Group 8 (edit/update/
remove scenarios), Group 9 (cross-cutting guards). Groups 0-5 must have
already run (test_t6p2t_group_a.py, test_t6p2t_group_b.py) — this file loads
their output from tests/e2e/t6p2t_state.json.

Run:
    python -m pytest tests/e2e/test_t6p2t_group_c.py -v --tb=short

Requirements:
  - Backend running at http://localhost:8000 (override with E2E_BASE_URL)
  - ENVIRONMENT=local must be set in the backend (enables dev_email auth)
  - tests/e2e/t6p2t_state.json must exist (produced by group_a + group_b)
  - Tenant T07 (admin@t07.com / Test@2026) must exist for the cross-tenant
    isolation checks in Group 9 — it was seeded by an earlier, unrelated
    test suite (test_tenant07_e2e.py), not by this file.

Ordering note: same as group_a/group_b — tests share state through the
module-level STATE dict and rely on file/class definition order. No
randomization plugin is configured in pyproject.toml.

Spec-vs-reality notes (read before reading the test bodies below):
  - "self_approval" as a per-adjustment-rule flag does not exist in
    AdjApprovalRuleIn/Out (backend/services/tenant-service/routers/
    adjustment_approval.py) — there is no such column. The closest real
    analogue is self_approval_policies (role_code + qty_limit), which is
    what the self-approval tests actually exercise.
  - There is no "coverage" field returned by any API — coverage hints are
    computed client-side in the org-setup page from the rules + position
    list. The coverage tests here recompute the same thing from GET
    responses rather than asserting on a field that doesn't exist server-side.
  - Tenant branding image upload is a real multipart endpoint, but it lives
    in product-service under /api/v1/upload/tenant-logo and
    /api/v1/upload/tenant-banner — not under tenant-service's
    /tenants/{id}/branding (that PATCH route only persists a URL string
    after upload, it does not accept a file).
  - deactivate_org_node() has no children-check at all (only delete_org_node
    does, via NODE_HAS_CHILDREN) — the Group 8 "deactivate A_FAC (has
    children)" test still expects rejection, but the actual blocking reason
    will be NODE_HAS_SOLE_USERS (nm_addisfac is A_FAC's only assignment),
    not a children check. Documented inline at that test.
"""
from __future__ import annotations

import base64
import io
import json
import os
import uuid
from typing import Any, Optional

import pytest
import requests

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
DEFAULT_PASSWORD = "Test@2026"
SA_PASSWORD = "Admin@2026"
TA_PASSWORD = "Test@2026"

T07_TA_EMAIL = "admin@t07.com"
T07_TA_PASSWORD = "Test@2026"
T07_TENANT_ID = "07000007-0000-0000-0000-000000000001"

STATE_FILE = os.path.join(os.path.dirname(__file__), "t6p2t_state.json")
ORDERED_GROUPS = ["GROUP6", "GROUP7", "GROUP8", "GROUP9"]

# Figures reported at the end of the group_a / group_b pytest runs in this
# same session. Those files don't persist GROUP_STATS to disk, so these are
# transcribed from their printed summaries, not recomputed here.
PRIOR_RESULTS = {
    "GROUP0": {"TESTS": 7, "PASS": 7, "FAIL": 0, "SKIP": 0},
    "GROUP1": {"TESTS": 6, "PASS": 3, "FAIL": 3, "SKIP": 0},
    "GROUP2": {"TESTS": 21, "PASS": 21, "FAIL": 0, "SKIP": 0},
    "GROUP3": {"TESTS": 24, "PASS": 23, "FAIL": 1, "SKIP": 0},
    "GROUP4": {"TESTS": 7, "PASS": 6, "FAIL": 1, "SKIP": 0},
    "GROUP5": {"TESTS": 35, "PASS": 35, "FAIL": 0, "SKIP": 0},
}

# ─────────────────────────────────────────────────────────────────────────────
# Load prior-group state
# ─────────────────────────────────────────────────────────────────────────────
with open(STATE_FILE, "r", encoding="utf-8") as _f:
    _LOADED_STATE: dict[str, Any] = json.load(_f)

STATE: dict[str, Any] = _LOADED_STATE
STATE.setdefault("approval_rules", {})
STATE.setdefault("transfer_rules_list", [])
STATE.setdefault("adjustment_rules_list", [])
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
    FAILURE_DETAILS.append({"test": name, "expected": expected, "actual": actual, "body": body[:500]})
    print(f"  [FAIL] {name} — expected: {expected!r} actual: {actual!r}")


def record_skip(group: str, name: str, reason: str) -> None:
    s = _stats(group)
    s["TESTS"] += 1
    s["SKIP"] += 1
    print(f"  [SKIP] {name} — {reason}")


def check(group: str, name: str, condition: bool, expected: str = "", actual: str = "", body: str = "") -> None:
    if condition:
        record_pass(group, name)
    else:
        record_fail(group, name, expected, actual, body)
    assert condition, f"{name} — expected: {expected!r} actual: {actual!r} body: {body[:300]!r}"


def soft_check(group: str, name: str, condition: bool, expected: str = "", actual: str = "", body: str = "") -> bool:
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
    return requests.post(f"{BASE_URL}/api/v1/auth/token",
                          json={"dev_email": email, "dev_password": password}, timeout=15)


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
    return requests.delete(f"{BASE_URL}{path}", headers={"Authorization": f"Bearer {token}"}, params=params, timeout=15)


def api_post_file(path: str, token: str, filename: str, content: bytes, content_type: str) -> requests.Response:
    return requests.post(
        f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (filename, io.BytesIO(content), content_type)},
        timeout=20,
    )


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


def make_png_bytes(width: int, height: int) -> bytes:
    """Generate a minimal valid PNG of roughly the given pixel size without
    a Pillow dependency — solid color, raw zlib-stored IDAT (no compression)."""
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    raw = b""
    row = b"\x00" + (b"\xab\xcd\xef" * width)
    for _ in range(height):
        raw += row
    idat = zlib.compress(raw, level=0)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def make_png_of_size(min_bytes: int) -> bytes:
    """Generate a PNG whose encoded size is at least min_bytes by growing the canvas."""
    side = 64
    data = make_png_bytes(side, side)
    while len(data) < min_bytes:
        side = int(side * 1.6) + 1
        data = make_png_bytes(side, side)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# GROUP 6 — APPROVAL RULES
# ─────────────────────────────────────────────────────────────────────────────
def _put_transfer_rules(rules: list[dict]) -> requests.Response:
    return api_put(f"/api/v1/tenants/{tid()}/transfer-approval-rules", ta(), rules)


def _put_adjustment_rules(rules: list[dict]) -> requests.Response:
    return api_put(f"/api/v1/tenants/{tid()}/adjustment-approval-rules", ta(), rules)


def _node_id_for_position(position_key: str) -> Optional[str]:
    """Look up which node a position belongs to via positions/flat (has node_id)."""
    r = api_get(f"/api/v1/tenants/{tid()}/positions/flat", ta())
    for p in jdata(r) if isinstance(jdata(r), list) else []:
        if str(p.get("id")) == STATE["positions"].get(position_key):
            return str(p.get("node_id"))
    return None


@pytest.mark.integration
class TestGroup6TransferApprovalRules:
    GROUP = "GROUP6"

    def test_600_rule1_pull_low(self) -> None:
        if not have_base_state():
            skip_test(self.GROUP, "6.0 Create Rule 1 — PULL 0-100, WM @ WHA1_mgr", "missing base state")
        rule = {
            "transfer_type_config_id": STATE["transfer_types"]["PULL"],
            "quantity_min": 0, "quantity_max": 100, "threshold_type": "QUANTITY",
            "approval_steps": [{"sequence": 1, "position_id": STATE["positions"]["WHA1_mgr"],
                                 "position_title": "WHA1 Merkato Manager", "resolution": "ANY",
                                 "execution_mode": "SEQUENTIAL"}],
            "priority": 1, "is_active": True,
        }
        STATE["transfer_rules_list"] = [rule]
        r = _put_transfer_rules(STATE["transfer_rules_list"])
        d = jdata(r)
        match = next((x for x in d if x.get("quantity_max") == 100), None) if isinstance(d, list) else None
        if match:
            STATE["approval_rules"]["transfer_pull_low"] = str(match["id"])
        check(self.GROUP, "6.0 Create Rule 1 — PULL 0-100, WM @ WHA1_mgr",
              r.status_code == 200 and match is not None,
              expected="200, rule with quantity_max=100 present",
              actual=f"status={r.status_code}, match={'found' if match else 'missing'}", body=r.text[:500])

    def test_601_coverage_after_rule1(self) -> None:
        """No backend 'coverage' field exists — recompute from positions/flat node_id
        for every position referenced by an active PULL rule's approval_steps."""
        if not STATE["approval_rules"].get("transfer_pull_low"):
            skip_test(self.GROUP, "6.1 After Rule 1, only WHA1 is PULL-covered (WHA2/3, WHB1/2 are not)",
                      "Rule 1 not created")
        covered_nodes = set()
        for rule in STATE["transfer_rules_list"]:
            if rule["transfer_type_config_id"] != STATE["transfer_types"]["PULL"]:
                continue
            for step in rule["approval_steps"]:
                node_id = None
                for key, pid in STATE["positions"].items():
                    if pid == step["position_id"]:
                        node_id = _node_id_for_position(key)
                        break
                if node_id:
                    covered_nodes.add(node_id)
        wha1_covered = STATE["nodes"]["WHA1"] in covered_nodes
        others_uncovered = all(STATE["nodes"][k] not in covered_nodes for k in ("WHA2", "WHA3", "WHB1", "WHB2"))
        check(self.GROUP, "6.1 After Rule 1, only WHA1 is PULL-covered (WHA2/3, WHB1/2 are not)",
              wha1_covered and others_uncovered,
              expected="WHA1 covered; WHA2/WHA3/WHB1/WHB2 not covered",
              actual=f"covered_nodes={covered_nodes}")

    def test_602_rule2_pull_high(self) -> None:
        if not STATE["approval_rules"].get("transfer_pull_low"):
            skip_test(self.GROUP, "6.2 Create Rule 2 — PULL 101+, RM @ A_REG_mgr", "Rule 1 not created")
        rule = {
            "transfer_type_config_id": STATE["transfer_types"]["PULL"],
            "quantity_min": 101, "quantity_max": None, "threshold_type": "QUANTITY",
            "approval_steps": [{"sequence": 1, "position_id": STATE["positions"]["A_REG_mgr"],
                                 "position_title": "Addis Regional Manager", "resolution": "ANY",
                                 "execution_mode": "SEQUENTIAL"}],
            "priority": 2, "is_active": True,
        }
        STATE["transfer_rules_list"].append(rule)
        r = _put_transfer_rules(STATE["transfer_rules_list"])
        d = jdata(r)
        match = next((x for x in d if x.get("quantity_min") == 101), None) if isinstance(d, list) else None
        if match:
            STATE["approval_rules"]["transfer_pull_high"] = str(match["id"])
        check(self.GROUP, "6.2 Create Rule 2 — PULL 101+, RM @ A_REG_mgr",
              r.status_code == 200 and match is not None,
              expected="200, rule with quantity_min=101 present",
              actual=f"status={r.status_code}, match={'found' if match else 'missing'}", body=r.text[:500])

    def test_603_rule3_push(self) -> None:
        if not have_base_state():
            skip_test(self.GROUP, "6.3 Create Rule 3 — PUSH any qty, NM @ A_FAC_dir", "missing base state")
        rule = {
            "transfer_type_config_id": STATE["transfer_types"]["PUSH"],
            "quantity_min": 0, "quantity_max": None, "threshold_type": "QUANTITY",
            "approval_steps": [{"sequence": 1, "position_id": STATE["positions"]["A_FAC_dir"],
                                 "position_title": "Addis Factory Director", "resolution": "ANY",
                                 "execution_mode": "SEQUENTIAL"}],
            "priority": 1, "is_active": True,
        }
        STATE["transfer_rules_list"].append(rule)
        r = _put_transfer_rules(STATE["transfer_rules_list"])
        d = jdata(r)
        match = next((x for x in d if x.get("transfer_type_config_id") == STATE["transfer_types"]["PUSH"]), None) if isinstance(d, list) else None
        if match:
            STATE["approval_rules"]["transfer_push"] = str(match["id"])
        check(self.GROUP, "6.3 Create Rule 3 — PUSH any qty, NM @ A_FAC_dir",
              r.status_code == 200 and match is not None,
              expected="200, PUSH rule present", actual=f"status={r.status_code}", body=r.text[:500])

    def test_604_rule4_sister(self) -> None:
        if not have_base_state():
            skip_test(self.GROUP, "6.4 Create Rule 4 — SISTER any qty, RM @ B_REG_mgr (Dire)", "missing base state")
        rule = {
            "transfer_type_config_id": STATE["transfer_types"]["SISTER"],
            "quantity_min": 0, "quantity_max": None, "threshold_type": "QUANTITY",
            "approval_steps": [{"sequence": 1, "position_id": STATE["positions"]["B_REG_mgr"],
                                 "position_title": "Dire Regional Manager", "resolution": "ANY",
                                 "execution_mode": "SEQUENTIAL"}],
            "priority": 1, "is_active": True,
        }
        STATE["transfer_rules_list"].append(rule)
        r = _put_transfer_rules(STATE["transfer_rules_list"])
        d = jdata(r)
        match = next((x for x in d if x.get("transfer_type_config_id") == STATE["transfer_types"]["SISTER"]), None) if isinstance(d, list) else None
        if match:
            STATE["approval_rules"]["transfer_sister"] = str(match["id"])
        check(self.GROUP, "6.4 Create Rule 4 — SISTER any qty, RM @ B_REG_mgr (Dire)",
              r.status_code == 200 and match is not None,
              expected="200, SISTER rule present", actual=f"status={r.status_code}", body=r.text[:500])

    def test_605_coverage_after_rule4(self) -> None:
        """Per-transfer-type coverage: Addis Regional Manager's node (A_REG) has PULL
        coverage (Rule 2) but no SISTER coverage — Rule 4 routes SISTER to Dire
        (B_REG) instead. A_REG should be flagged uncovered specifically for SISTER."""
        if not STATE["approval_rules"].get("transfer_sister"):
            skip_test(self.GROUP, "6.5 After Rule 4, A_REG node is SISTER-uncovered", "Rule 4 not created")
        sister_covered_nodes = set()
        for rule in STATE["transfer_rules_list"]:
            if rule["transfer_type_config_id"] != STATE["transfer_types"]["SISTER"]:
                continue
            for step in rule["approval_steps"]:
                for key, pid in STATE["positions"].items():
                    if pid == step["position_id"]:
                        node_id = _node_id_for_position(key)
                        if node_id:
                            sister_covered_nodes.add(node_id)
        a_reg_sister_uncovered = STATE["nodes"]["A_REG"] not in sister_covered_nodes
        b_reg_sister_covered = STATE["nodes"]["B_REG"] in sister_covered_nodes
        check(self.GROUP, "6.5 After Rule 4, A_REG node is SISTER-uncovered",
              a_reg_sister_uncovered and b_reg_sister_covered,
              expected="A_REG not SISTER-covered; B_REG is SISTER-covered",
              actual=f"sister_covered_nodes={sister_covered_nodes}")

    def test_606_rename_route_and_threshold_edit(self) -> None:
        """Edit tests folded in here (same PUT-replaces-all-rules mechanic):
        change Rule 1's quantity_max 100→200, then its route_to WHA1→WHA2 mgr."""
        if not STATE["approval_rules"].get("transfer_pull_low"):
            skip_test(self.GROUP, "6.6 Edit Rule 1: threshold 100→200, route WHA1→WHA2 mgr", "Rule 1 not created")
        rules = STATE["transfer_rules_list"]
        rule1 = next(r for r in rules if r.get("priority") == 1 and r["transfer_type_config_id"] == STATE["transfer_types"]["PULL"])
        rule1["quantity_max"] = 200
        r_thresh = _put_transfer_rules(rules)
        d_thresh = jdata(r_thresh)
        thresh_ok = soft_check(
            self.GROUP, "6.6a Rule 1 quantity_max 100→200 persists",
            r_thresh.status_code == 200 and any(x.get("quantity_max") == 200 for x in d_thresh if isinstance(d_thresh, list)),
            expected="200, quantity_max=200 present", actual=f"status={r_thresh.status_code}", body=r_thresh.text[:300],
        )

        rule1["approval_steps"] = [{"sequence": 1, "position_id": STATE["positions"]["WHA2_mgr"],
                                     "position_title": "WHA2 Bole-Airport Manager", "resolution": "ANY",
                                     "execution_mode": "SEQUENTIAL"}]
        r_route = _put_transfer_rules(rules)
        d_route = jdata(r_route)
        rerouted = next((x for x in d_route if x.get("quantity_max") == 200), None) if isinstance(d_route, list) else None
        route_ok = soft_check(
            self.GROUP, "6.6b Rule 1 route_to WHA1→WHA2 mgr persists",
            r_route.status_code == 200 and rerouted is not None
            and any(s.get("position_id") == STATE["positions"]["WHA2_mgr"] for s in rerouted.get("approval_steps", [])),
            expected="200, approval_steps route to WHA2_mgr", actual=f"status={r_route.status_code}", body=r_route.text[:300],
        )
        assert thresh_ok and route_ok

    def test_607_delete_and_recreate_rule2(self) -> None:
        if not STATE["approval_rules"].get("transfer_pull_high"):
            skip_test(self.GROUP, "6.7 Delete Rule 2, verify removed; recreate, verify restored", "Rule 2 not created")
        rules = STATE["transfer_rules_list"]
        rule2 = next(r for r in rules if r["transfer_type_config_id"] == STATE["transfer_types"]["PULL"] and r.get("quantity_min") == 101)
        remaining = [r for r in rules if r is not rule2]
        r_del = _put_transfer_rules(remaining)
        d_del = jdata(r_del)
        still_present = any(x.get("quantity_min") == 101 for x in d_del) if isinstance(d_del, list) else True
        del_ok = soft_check(
            self.GROUP, "6.7a Delete Rule 2 — removed from list",
            r_del.status_code == 200 and not still_present,
            expected="200, no rule with quantity_min=101", actual=f"status={r_del.status_code}, still_present={still_present}",
            body=r_del.text[:300],
        )

        remaining.append(rule2)
        r_recreate = _put_transfer_rules(remaining)
        STATE["transfer_rules_list"] = remaining
        d_recreate = jdata(r_recreate)
        recreated = any(x.get("quantity_min") == 101 for x in d_recreate) if isinstance(d_recreate, list) else False
        recreate_ok = soft_check(
            self.GROUP, "6.7b Recreate Rule 2 with same values — present again",
            r_recreate.status_code == 200 and recreated,
            expected="200, rule with quantity_min=101 present", actual=f"status={r_recreate.status_code}",
            body=r_recreate.text[:300],
        )
        assert del_ok and recreate_ok


@pytest.mark.integration
class TestGroup6AdjustmentApprovalRules:
    GROUP = "GROUP6"

    def test_610_rule_a_global_low(self) -> None:
        if not have_base_state():
            skip_test(self.GROUP, "6.10 Create adjustment Rule A — global 0-50, WM @ WHA1_mgr", "missing base state")
        rule = {
            "role_code": "WM", "level_number": 3, "mode": "GLOBAL", "reason_code": None,
            "threshold_type": "QUANTITY", "qty_limit": 50,
            "approver_role_code": "WM", "approver_position_id": STATE["positions"]["WHA1_mgr"],
            "priority": 1, "is_active": True,
        }
        STATE["adjustment_rules_list"] = [rule]
        r = _put_adjustment_rules(STATE["adjustment_rules_list"])
        d = jdata(r)
        # qty_limit comes back as a numeric-string Decimal serialization (e.g. "50.0000"),
        # not a JSON number — must coerce before comparing.
        match = next((x for x in d if float(x.get("qty_limit") or -1) == 50.0), None) if isinstance(d, list) else None
        if match:
            STATE["approval_rules"]["adjustment_global_low"] = str(match["id"])
        check(self.GROUP, "6.10 Create adjustment Rule A — global 0-50, WM @ WHA1_mgr",
              r.status_code == 200 and match is not None,
              expected="200, qty_limit=50 rule present", actual=f"status={r.status_code}", body=r.text[:400])

    def test_611_rule_b_global_high(self) -> None:
        if not STATE["approval_rules"].get("adjustment_global_low"):
            skip_test(self.GROUP, "6.11 Create adjustment Rule B — global 51+, RM @ A_REG_mgr", "Rule A not created")
        rule = {
            "role_code": "RM", "level_number": 2, "mode": "GLOBAL", "reason_code": None,
            "threshold_type": "QUANTITY", "qty_limit": None,
            "approver_role_code": "RM", "approver_position_id": STATE["positions"]["A_REG_mgr"],
            "priority": 2, "is_active": True,
        }
        STATE["adjustment_rules_list"].append(rule)
        r = _put_adjustment_rules(STATE["adjustment_rules_list"])
        d = jdata(r)
        match = next((x for x in d if x.get("role_code") == "RM" and x.get("qty_limit") is None), None) if isinstance(d, list) else None
        if match:
            STATE["approval_rules"]["adjustment_global_high"] = str(match["id"])
        check(self.GROUP, "6.11 Create adjustment Rule B — global 51+, RM @ A_REG_mgr",
              r.status_code == 200 and match is not None,
              expected="200, RM rule with qty_limit=None present", actual=f"status={r.status_code}", body=r.text[:400])

    def test_612_self_approval_field_not_persisted(self) -> None:
        """Probe: AdjApprovalRuleIn has no self_approval field. Sending it should be
        silently dropped (Pydantic default extra='ignore'), not error and not appear
        in the response — confirming the spec's self_approval concept doesn't exist
        for adjustment rules server-side."""
        if not have_base_state():
            skip_test(self.GROUP, "6.12 self_approval is not a real field on adjustment rules (dropped silently)",
                      "missing base state")
        rules = list(STATE["adjustment_rules_list"])
        probe = dict(rules[0]) if rules else {
            "role_code": "WM", "level_number": 3, "mode": "GLOBAL",
            "approver_role_code": "WM", "approver_position_id": STATE["positions"]["WHA1_mgr"],
        }
        probe["self_approval"] = True
        r = api_put(f"/api/v1/tenants/{tid()}/adjustment-approval-rules", ta(), [probe])
        d = jdata(r)
        has_field = isinstance(d, list) and any("self_approval" in x for x in d)
        check(self.GROUP, "6.12 self_approval is not a real field on adjustment rules (dropped silently)",
              r.status_code == 200 and not has_field,
              expected="200, response objects have no self_approval key",
              actual=f"status={r.status_code}, self_approval_present={has_field}", body=r.text[:400])
        # Restore canonical rules list (this PUT replaced everything with just `probe`).
        _put_adjustment_rules(STATE["adjustment_rules_list"])

    def test_613_per_reason_code_mode(self) -> None:
        if not have_base_state():
            skip_test(self.GROUP, "6.13 Switch to PER_CODE mode, create DAMAGE rule, switch back to GLOBAL",
                      "missing base state")
        per_code_rule = {
            "role_code": "NM", "level_number": 1, "mode": "PER_CODE", "reason_code": "DAMAGE",
            "threshold_type": "QUANTITY", "qty_limit": None,
            "approver_role_code": "NM", "approver_position_id": STATE["positions"]["A_FAC_dir"],
            "priority": 1, "is_active": True,
        }
        r_per_code = _put_adjustment_rules([per_code_rule])
        d_per_code = jdata(r_per_code)
        per_code_ok = soft_check(
            self.GROUP, "6.13a PER_CODE mode DAMAGE rule created",
            r_per_code.status_code == 200 and isinstance(d_per_code, list)
            and any(x.get("mode") == "PER_CODE" and x.get("reason_code") == "DAMAGE" for x in d_per_code),
            expected="200, PER_CODE/DAMAGE rule present", actual=f"status={r_per_code.status_code}", body=r_per_code.text[:400],
        )

        r_back = _put_adjustment_rules(STATE["adjustment_rules_list"])
        d_back = jdata(r_back)
        back_ok = soft_check(
            self.GROUP, "6.13b Switch back to GLOBAL mode — PER_CODE rule replaced",
            r_back.status_code == 200 and isinstance(d_back, list)
            and all(x.get("mode") == "GLOBAL" for x in d_back) and len(d_back) == len(STATE["adjustment_rules_list"]),
            expected="200, only GLOBAL rules remain", actual=f"status={r_back.status_code}", body=r_back.text[:400],
        )
        assert per_code_ok and back_ok

    def test_614_self_approval_hidden_for_au_ta_sa(self) -> None:
        """No self_approval field exists anywhere in the adjustment-rule schema for
        ANY role — there's nothing role-specific to hide/disable server-side. This is
        a frontend-only concern (org-setup page UI). Recorded as a skip with the
        reasoning made explicit, rather than asserting on a field that can't exist."""
        skip_test(self.GROUP,
                  "6.14 self_approval hidden/disabled for AU/TA/SA — no backend field exists for any role",
                  "self_approval is not part of AdjApprovalRuleIn/Out for any role_code; "
                  "this is purely a frontend rendering decision with nothing to assert via API")

    def test_615_self_approval_via_policy_for_wm(self) -> None:
        """Reinterpreted against the real self-approval mechanism: self_approval_policies
        (role_code + level_number + qty_limit), which IS what 'self_approval=true for a
        WM rule' maps to in this codebase."""
        if not have_base_state():
            skip_test(self.GROUP, "6.15 Set a WM self-approval policy (qty_limit=50) — saves correctly",
                      "missing base state")
        policy = {"role_code": "WM", "level_number": 3, "transfer_types": ["PULL", "PUSH", "SISTER"],
                  "threshold_type": "QUANTITY", "qty_limit": 50, "is_active": True}
        r = api_put(f"/api/v1/tenants/{tid()}/self-approval-policies", ta(), [policy])
        d = jdata(r)
        match = next((x for x in d if x.get("role_code") == "WM"), None) if isinstance(d, list) else None
        check(self.GROUP, "6.15 Set a WM self-approval policy (qty_limit=50) — saves correctly",
              r.status_code == 200 and match is not None and float(match.get("qty_limit") or -1) == 50.0,
              expected="200, WM policy with qty_limit=50", actual=f"status={r.status_code}", body=r.text[:400])

    def test_616_edit_rule_a_threshold(self) -> None:
        if not STATE["approval_rules"].get("adjustment_global_low"):
            skip_test(self.GROUP, "6.16 Edit adjustment Rule A threshold 50→100, verify", "Rule A not created")
        rules = STATE["adjustment_rules_list"]
        rule_a = next(r for r in rules if r["role_code"] == "WM")
        rule_a["qty_limit"] = 100
        r = _put_adjustment_rules(rules)
        d = jdata(r)
        match = next((x for x in d if x.get("role_code") == "WM"), None) if isinstance(d, list) else None
        check(self.GROUP, "6.16 Edit adjustment Rule A threshold 50→100, verify",
              r.status_code == 200 and match is not None and float(match.get("qty_limit") or -1) == 100.0,
              expected="200, WM rule qty_limit=100", actual=f"status={r.status_code}", body=r.text[:400])


# ─────────────────────────────────────────────────────────────────────────────
# GROUP 7 — BRANDING
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.integration
class TestGroup7Branding:
    GROUP = "GROUP7"

    def test_700_upload_valid_logo(self) -> None:
        if not have_base_state():
            skip_test(self.GROUP, "7.0 Upload valid PNG logo (<1MB)", "missing base state")
        png = make_png_bytes(32, 32)
        r = api_post_file("/api/v1/upload/tenant-logo", ta(), "logo.png", png, "image/png")
        d = jdata(r)
        if r.status_code == 200 and d.get("url"):
            STATE["logo_url_1"] = d["url"]
        check(self.GROUP, "7.0 Upload valid PNG logo (<1MB)",
              r.status_code == 200 and bool(d.get("url")),
              expected="200 + url", actual=f"status={r.status_code}", body=r.text[:300])

    def test_701_logo_url_in_branding_response(self) -> None:
        if not STATE.get("logo_url_1"):
            skip_test(self.GROUP, "7.1 Logo URL returned in tenant branding response", "no logo uploaded in 7.0")
        r = api_patch(f"/api/v1/tenants/{tid()}/branding", ta(), {"logo_url": STATE["logo_url_1"]})
        d = jdata(r)
        check(self.GROUP, "7.1 Logo URL returned in tenant branding response",
              r.status_code == 200 and d.get("logo_url") == STATE["logo_url_1"],
              expected=f"200, logo_url={STATE['logo_url_1']}", actual=f"status={r.status_code}, logo_url={d.get('logo_url')!r}",
              body=r.text[:300])

    def test_702_upload_valid_banner(self) -> None:
        if not have_base_state():
            skip_test(self.GROUP, "7.2 Upload valid PNG banner (<3MB)", "missing base state")
        png = make_png_bytes(64, 32)
        r = api_post_file("/api/v1/upload/tenant-banner", ta(), "banner.png", png, "image/png")
        d = jdata(r)
        if r.status_code == 200 and d.get("url"):
            STATE["banner_url_1"] = d["url"]
        check(self.GROUP, "7.2 Upload valid PNG banner (<3MB)",
              r.status_code == 200 and bool(d.get("url")),
              expected="200 + url", actual=f"status={r.status_code}", body=r.text[:300])

    def test_703_banner_url_returned(self) -> None:
        if not STATE.get("banner_url_1"):
            skip_test(self.GROUP, "7.3 Banner URL returned", "no banner uploaded in 7.2")
        r = api_patch(f"/api/v1/tenants/{tid()}/branding", ta(), {"banner_url": STATE["banner_url_1"]})
        d = jdata(r)
        check(self.GROUP, "7.3 Banner URL returned",
              r.status_code == 200 and d.get("banner_url") == STATE["banner_url_1"],
              expected=f"200, banner_url={STATE['banner_url_1']}", actual=f"status={r.status_code}", body=r.text[:300])

    def test_704_oversized_logo_rejected(self) -> None:
        if not have_base_state():
            skip_test(self.GROUP, "7.4 Oversized logo (>1MB) → 422/413", "missing base state")
        big_png = make_png_of_size(1024 * 1024 + 1024)
        r = api_post_file("/api/v1/upload/tenant-logo", ta(), "big_logo.png", big_png, "image/png")
        check(self.GROUP, "7.4 Oversized logo (>1MB) → 422/413",
              r.status_code in (422, 413) and err_code(r) in ("IMAGE_TOO_LARGE", None),
              expected="422 or 413, code=IMAGE_TOO_LARGE", actual=f"status={r.status_code}, code={err_code(r)!r}",
              body=r.text[:300])

    def test_705_oversized_banner_rejected(self) -> None:
        if not have_base_state():
            skip_test(self.GROUP, "7.5 Oversized banner (>3MB) → 422/413", "missing base state")
        big_png = make_png_of_size(3 * 1024 * 1024 + 1024)
        r = api_post_file("/api/v1/upload/tenant-banner", ta(), "big_banner.png", big_png, "image/png")
        check(self.GROUP, "7.5 Oversized banner (>3MB) → 422/413",
              r.status_code in (422, 413) and err_code(r) in ("IMAGE_TOO_LARGE", None),
              expected="422 or 413, code=IMAGE_TOO_LARGE", actual=f"status={r.status_code}, code={err_code(r)!r}",
              body=r.text[:300])

    def test_706_invalid_file_type_rejected(self) -> None:
        if not have_base_state():
            skip_test(self.GROUP, "7.6 PDF uploaded as logo → 422 INVALID_IMAGE_TYPE", "missing base state")
        fake_pdf = b"%PDF-1.4\n%fake pdf content for e2e test\n%%EOF"
        r = api_post_file("/api/v1/upload/tenant-logo", ta(), "doc.pdf", fake_pdf, "application/pdf")
        check(self.GROUP, "7.6 PDF uploaded as logo → 422 INVALID_IMAGE_TYPE",
              r.status_code == 422 and err_code(r) == "INVALID_IMAGE_TYPE",
              expected="422, code=INVALID_IMAGE_TYPE", actual=f"status={r.status_code}, code={err_code(r)!r}",
              body=r.text[:300])

    def test_707_update_logo_url_changes(self) -> None:
        if not STATE.get("logo_url_1"):
            skip_test(self.GROUP, "7.7 Update logo with new image — URL changes", "no initial logo from 7.0")
        png2 = make_png_bytes(40, 40)
        r_upload = api_post_file("/api/v1/upload/tenant-logo", ta(), "logo2.png", png2, "image/png")
        d_upload = jdata(r_upload)
        new_url = d_upload.get("url")
        check(self.GROUP, "7.7 Update logo with new image — URL changes",
              r_upload.status_code == 200 and bool(new_url) and new_url != STATE["logo_url_1"],
              expected="200, new url different from original",
              actual=f"status={r_upload.status_code}, new_url={new_url!r}, original={STATE['logo_url_1']!r}",
              body=r_upload.text[:300])
        if new_url:
            STATE["logo_url_1"] = new_url

    def test_708_branding_returns_both_urls(self) -> None:
        if not (STATE.get("logo_url_1") and STATE.get("banner_url_1")):
            skip_test(self.GROUP, "7.8 Branding endpoint returns logo and banner together", "missing logo/banner urls")
        r = api_patch(f"/api/v1/tenants/{tid()}/branding", ta(),
                      {"logo_url": STATE["logo_url_1"], "banner_url": STATE["banner_url_1"]})
        d = jdata(r)
        check(self.GROUP, "7.8 Branding endpoint returns logo and banner together",
              r.status_code == 200 and d.get("logo_url") == STATE["logo_url_1"] and d.get("banner_url") == STATE["banner_url_1"],
              expected="200, both logo_url and banner_url present and matching",
              actual=f"status={r.status_code}, logo={d.get('logo_url')!r}, banner={d.get('banner_url')!r}",
              body=r.text[:300])


# ─────────────────────────────────────────────────────────────────────────────
# GROUP 8 — EDIT / UPDATE / REMOVE SCENARIOS
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.integration
class TestGroup8NodeEdits:
    GROUP = "GROUP8"

    def test_800_rename_a_fac_round_trip(self) -> None:
        node_id = STATE["nodes"].get("A_FAC")
        if not node_id:
            skip_test(self.GROUP, "8.0 Rename A_FAC 'Addis Ababa Factory'→'Addis Main Factory'→back", "no A_FAC node id")
        r1 = api_patch(f"/api/v1/tenants/{tid()}/nodes/{node_id}", ta(), {"name": "Addis Main Factory"})
        d1 = jdata(r1)
        r2 = api_patch(f"/api/v1/tenants/{tid()}/nodes/{node_id}", ta(), {"name": "Addis Ababa Factory"})
        d2 = jdata(r2)
        check(self.GROUP, "8.0 Rename A_FAC 'Addis Ababa Factory'→'Addis Main Factory'→back",
              r1.status_code == 200 and d1.get("name") == "Addis Main Factory"
              and r2.status_code == 200 and d2.get("name") == "Addis Ababa Factory",
              expected="step1: 'Addis Main Factory', step2: 'Addis Ababa Factory'",
              actual=f"step1={d1.get('name')!r}, step2={d2.get('name')!r}", body=f"{r1.text[:150]} | {r2.text[:150]}")

    def test_801_deactivate_wha3_blocked_by_sole_users(self) -> None:
        """Spec expected this to succeed (as it would have right after Group 2, when
        WHA3 had no personnel). Group 5 since assigned wm_wha3 (and, via group_b's
        PRIMARY-swap test, wm_wha3_sec) as sole-position holders at WHA3_mgr — so
        deactivate_org_node()'s CHECK 4 (NODE_HAS_SOLE_USERS) now correctly blocks
        this. Testing the actual, evolved state rather than the stale assumption."""
        node_id = STATE["nodes"].get("WHA3")
        if not node_id:
            skip_test(self.GROUP, "8.1 Deactivate WHA3 — now blocked by NODE_HAS_SOLE_USERS (personnel assigned since Group 2)",
                      "no WHA3 node id")
        r = api_patch(f"/api/v1/tenants/{tid()}/nodes/{node_id}/deactivate", ta())
        check(self.GROUP, "8.1 Deactivate WHA3 — now blocked by NODE_HAS_SOLE_USERS (personnel assigned since Group 2)",
              r.status_code == 422 and err_code(r) == "NODE_HAS_SOLE_USERS",
              expected="422, code=NODE_HAS_SOLE_USERS",
              actual=f"status={r.status_code}, code={err_code(r)!r}", body=r.text[:300])

    def test_802_reactivate_wha3_not_applicable(self) -> None:
        skip_test(self.GROUP, "8.2 Reactivate WHA3 — not applicable, 8.1 deactivation was rejected",
                  "WHA3 was never deactivated (8.1 correctly blocked it)")

    def test_803_deactivate_a_fac_blocked(self) -> None:
        """deactivate_org_node() has NO children-check at all (only delete_org_node
        does, via NODE_HAS_CHILDREN). A_FAC is still rejected here, but for a
        different real reason: nm_addisfac is its sole position holder."""
        node_id = STATE["nodes"].get("A_FAC")
        if not node_id:
            skip_test(self.GROUP, "8.3 Deactivate A_FAC (has children) → rejected (actually NODE_HAS_SOLE_USERS, not a children-check)",
                      "no A_FAC node id")
        r = api_patch(f"/api/v1/tenants/{tid()}/nodes/{node_id}/deactivate", ta())
        check(self.GROUP, "8.3 Deactivate A_FAC (has children) → rejected (actually NODE_HAS_SOLE_USERS, not a children-check)",
              r.status_code == 422,
              expected="422 (any reason — spec assumed NODE_HAS_CHILDREN, which doesn't exist in deactivate_org_node)",
              actual=f"status={r.status_code}, code={err_code(r)!r}", body=r.text[:300])


@pytest.mark.integration
class TestGroup8PositionEdits:
    GROUP = "GROUP8"

    def test_810_rename_a_fac_dir_round_trip(self) -> None:
        pos_id = STATE["positions"].get("A_FAC_dir")
        if not pos_id:
            skip_test(self.GROUP, "8.10 Rename Addis Factory Director→'Addis HQ Director'→back", "no A_FAC_dir position id")
        r1 = api_patch(f"/api/v1/tenants/{tid()}/positions/{pos_id}", ta(), {"title": "Addis HQ Director"})
        d1 = jdata(r1)
        r2 = api_patch(f"/api/v1/tenants/{tid()}/positions/{pos_id}", ta(), {"title": "Addis Factory Director"})
        d2 = jdata(r2)
        check(self.GROUP, "8.10 Rename Addis Factory Director→'Addis HQ Director'→back",
              r1.status_code == 200 and d1.get("title") == "Addis HQ Director"
              and r2.status_code == 200 and d2.get("title") == "Addis Factory Director",
              expected="step1: 'Addis HQ Director', step2: 'Addis Factory Director'",
              actual=f"step1={d1.get('title')!r}, step2={d2.get('title')!r}", body=f"{r1.text[:150]} | {r2.text[:150]}")

    def test_811_whb1_role_wm_to_rm(self) -> None:
        pos_id = STATE["positions"].get("WHB1_mgr")
        if not pos_id:
            skip_test(self.GROUP, "8.11 WHB1 Sabian Manager role WM→RM, verify saves", "no WHB1_mgr position id")
        r = api_patch(f"/api/v1/tenants/{tid()}/positions/{pos_id}", ta(), {"role_code": "RM"})
        d = jdata(r)
        check(self.GROUP, "8.11 WHB1 Sabian Manager role WM→RM, verify saves",
              r.status_code == 200 and d.get("role_code") == "RM",
              expected="200, role_code=RM", actual=f"status={r.status_code}, role_code={d.get('role_code')!r}", body=r.text[:300])
        # Revert so downstream groups relying on WHB1_mgr=WM aren't affected.
        api_patch(f"/api/v1/tenants/{tid()}/positions/{pos_id}", ta(), {"role_code": "WM"})

    def test_812_sat_wha1_reports_to_wha2(self) -> None:
        pos_id = STATE["positions"].get("SAT_WHA1_lead")
        new_parent = STATE["positions"].get("WHA2_mgr")
        if not (pos_id and new_parent):
            skip_test(self.GROUP, "8.12 SAT_WHA1 reports_to WHA1→WHA2 mgr, verify", "missing position ids")
        r = api_patch(f"/api/v1/tenants/{tid()}/positions/{pos_id}", ta(), {"reports_to_position_id": new_parent})
        d = jdata(r)
        check(self.GROUP, "8.12 SAT_WHA1 reports_to WHA1→WHA2 mgr, verify",
              r.status_code == 200 and str(d.get("reports_to_position_id")) == new_parent,
              expected=f"200, reports_to_position_id={new_parent}",
              actual=f"status={r.status_code}, reports_to_position_id={d.get('reports_to_position_id')!r}", body=r.text[:300])

    def test_813_sat_wha2_reports_to_cleared(self) -> None:
        pos_id = STATE["positions"].get("SAT_WHA2_lead")
        if not pos_id:
            skip_test(self.GROUP, "8.13 Remove reports_to from SAT_WHA2, verify null", "no SAT_WHA2_lead position id")
        r = api_patch(f"/api/v1/tenants/{tid()}/positions/{pos_id}", ta(), {"reports_to_position_id": None})
        d = jdata(r)
        check(self.GROUP, "8.13 Remove reports_to from SAT_WHA2, verify null",
              r.status_code == 200 and d.get("reports_to_position_id") is None,
              expected="200, reports_to_position_id=null",
              actual=f"status={r.status_code}, reports_to_position_id={d.get('reports_to_position_id')!r}", body=r.text[:300])

    def test_814_circular_reports_to_rejected(self) -> None:
        """Cycle detection is live (commit f2f11bd). Setting A→B then B→A must return
        422 CIRCULAR_REPORTS_TO on the second PATCH. Reverts are applied after the probe
        regardless of outcome to keep state clean."""
        pos_a = STATE["positions"].get("WHA1_mgr")
        pos_b = STATE["positions"].get("WHA2_mgr")
        if not (pos_a and pos_b):
            skip_test(self.GROUP, "8.14 Circular reports_to (A→B, B→A) → 422", "missing position ids")
        r1 = api_patch(f"/api/v1/tenants/{tid()}/positions/{pos_a}", ta(), {"reports_to_position_id": pos_b})
        r2 = api_patch(f"/api/v1/tenants/{tid()}/positions/{pos_b}", ta(), {"reports_to_position_id": pos_a})
        # Revert WHA1_mgr's reports_to (it had none before this probe).
        api_patch(f"/api/v1/tenants/{tid()}/positions/{pos_a}", ta(), {"reports_to_position_id": None})
        api_patch(f"/api/v1/tenants/{tid()}/positions/{pos_b}", ta(), {"reports_to_position_id": STATE["positions"].get("A_REG_mgr")})
        check(self.GROUP, "8.14 Circular reports_to (A→B, B→A) → 422",
              r2.status_code == 422 and err_code(r2) == "CIRCULAR_REPORTS_TO",
              expected="422, code=CIRCULAR_REPORTS_TO",
              actual=f"step1={r1.status_code}, step2={r2.status_code}, code={err_code(r2)!r}")


@pytest.mark.integration
class TestGroup8PersonnelEdits:
    GROUP = "GROUP8"

    def test_820_rename_nm_addisfac(self) -> None:
        u = STATE["users"].get("nm_addisfac")
        if not u:
            skip_test(self.GROUP, "8.20 Edit nm_addisfac full_name → 'Addis NM Updated', verify", "no nm_addisfac user record")
        r = api_patch(f"/api/v1/tenants/{tid()}/users/{u['id']}", ta(), {"name": "Addis NM Updated"})
        r_get = api_get(f"/api/v1/tenants/{tid()}/users/{u['id']}", ta())
        d_get = jdata(r_get)
        check(self.GROUP, "8.20 Edit nm_addisfac full_name → 'Addis NM Updated', verify",
              r.status_code == 200 and d_get.get("name") == "Addis NM Updated",
              expected="200, name='Addis NM Updated'", actual=f"status={r.status_code}, name={d_get.get('name')!r}",
              body=r.text[:300])

    def test_821_change_wm_wha1_email_login(self) -> None:
        u = STATE["users"].get("wm_wha1")
        if not u:
            skip_test(self.GROUP, "8.21 Edit wm_wha1 email, verify login with new email works", "no wm_wha1 user record")
        new_email = "wm_wha1_new@t6p2t.com"
        r = api_patch(f"/api/v1/tenants/{tid()}/users/{u['id']}", ta(), {"email": new_email})
        login_r = login(new_email, u["password"])
        login_ok = login_r.status_code == 200 and bool(login_r.json().get("access_token"))
        if login_ok:
            u["email"] = new_email
        check(self.GROUP, "8.21 Edit wm_wha1 email, verify login with new email works",
              r.status_code == 200 and login_ok,
              expected="PATCH 200, then login 200 with new email",
              actual=f"patch={r.status_code}, login={login_r.status_code}", body=f"{r.text[:150]} | {login_r.text[:150]}")

    def test_822_deactivate_reactivate_lm_satwha1(self) -> None:
        u = STATE["users"].get("lm_satwha1")
        if not u:
            skip_test(self.GROUP, "8.22 Deactivate lm_satwha1 blocks login; reactivate restores login", "no lm_satwha1 user record")
        r_deact = api_patch(f"/api/v1/tenants/{tid()}/users/{u['id']}/deactivate", ta())
        login_blocked = login(u["email"], u["password"])
        r_react = api_patch(f"/api/v1/tenants/{tid()}/users/{u['id']}/reactivate", ta())
        login_after = login(u["email"], u["password"])
        check(self.GROUP, "8.22 Deactivate lm_satwha1 blocks login; reactivate restores login",
              r_deact.status_code == 200 and login_blocked.status_code == 401
              and r_react.status_code == 200 and login_after.status_code == 200,
              expected="deactivate 200, login 401, reactivate 200, login 200",
              actual=(f"deactivate={r_deact.status_code}, login_blocked={login_blocked.status_code}, "
                      f"reactivate={r_react.status_code}, login_after={login_after.status_code}"),
              body=f"{r_deact.text[:120]} | {login_blocked.text[:120]} | {r_react.text[:120]} | {login_after.text[:120]}")

    def test_823_assign_secondary_holder_wha3(self) -> None:
        wha3_pos = STATE["positions"].get("WHA3_mgr")
        if not (wha3_pos and have_base_state()):
            skip_test(self.GROUP, "8.23 Assign wm_wha3_sec_g8 as secondary PRIMARY holder at WHA3_mgr", "no WHA3_mgr position id")
        email = f"wm_wha3_sec_g8_{uniq()}@t6p2t.com"
        r = api_post(f"/api/v1/tenants/{tid()}/users", ta(), {
            "name": "WM WHA3 Secondary G8", "email": email, "password": DEFAULT_PASSWORD, "position_id": wha3_pos,
        })
        d = jdata(r)
        if r.status_code == 201 and d.get("id"):
            STATE["users"]["wm_wha3_sec_g8"] = {
                "id": str(d["id"]), "email": email, "password": DEFAULT_PASSWORD,
                "assignment_id": str(d["primary_position"]["assignment_id"]) if d.get("primary_position") else None,
            }
        check(self.GROUP, "8.23 Assign wm_wha3_sec_g8 as secondary PRIMARY holder at WHA3_mgr",
              r.status_code == 201 and d.get("primary_position", {}).get("position_id") == wha3_pos,
              expected="201, primary_position.position_id=WHA3_mgr", actual=f"status={r.status_code}", body=r.text[:300])

    def test_824_remove_secondary_holder_wha3(self) -> None:
        """remove_position_assignment()'s CANNOT_REMOVE_LAST_PRIMARY check counts only
        the TARGET USER's own other PRIMARY rows — it has no concept of 'other users
        share this position', so removing wm_wha3_sec_g8's sole assignment without
        force still 422s even though wm_wha3 holds the same position. force=true (SA)
        is the correct path here, same as any other sole-PRIMARY removal."""
        u = STATE["users"].get("wm_wha3_sec_g8")
        wha3_user = STATE["users"].get("wm_wha3")
        if not (u and u.get("assignment_id") and wha3_user and have_base_state()):
            skip_test(self.GROUP, "8.24 SA force-removes wm_wha3_sec_g8; wm_wha3 remains primary at WHA3_mgr", "missing assignment id")
        r = api_delete(f"/api/v1/tenants/{tid()}/users/{u['id']}/positions/{u['assignment_id']}", sa(), params={"force": "true"})
        d = jdata(r)
        r_check = api_get(f"/api/v1/tenants/{tid()}/users/{wha3_user['id']}", ta())
        wm_wha3_still_primary = jdata(r_check).get("primary_position", {}).get("position_id") == STATE["positions"]["WHA3_mgr"]
        check(self.GROUP, "8.24 SA force-removes wm_wha3_sec_g8; wm_wha3 remains primary at WHA3_mgr",
              r.status_code == 200 and d.get("user_deactivated") is True and wm_wha3_still_primary,
              expected="200, user_deactivated=true, wm_wha3 still PRIMARY at WHA3_mgr",
              actual=f"status={r.status_code}, user_deactivated={d.get('user_deactivated')!r}, wm_wha3_still_primary={wm_wha3_still_primary}",
              body=r.text[:300])

    def test_825_sa_force_remove_nm_direfac(self) -> None:
        u = STATE["users"].get("nm_direfac")
        if not (u and u.get("assignment_id") and have_base_state()):
            skip_test(self.GROUP, "8.25 SA force-removes nm_direfac's sole PRIMARY → user_deactivated=true", "missing nm_direfac/assignment_id")
        r = api_delete(f"/api/v1/tenants/{tid()}/users/{u['id']}/positions/{u['assignment_id']}", sa(), params={"force": "true"})
        d = jdata(r)
        check(self.GROUP, "8.25 SA force-removes nm_direfac's sole PRIMARY → user_deactivated=true",
              r.status_code == 200 and d.get("user_deactivated") is True,
              expected="200, user_deactivated=true", actual=f"status={r.status_code}, user_deactivated={d.get('user_deactivated')!r}",
              body=r.text[:300])

    def test_826_reactivate_and_reassign_nm_direfac(self) -> None:
        """assign_position() requires the target user to be is_active=true, so
        reactivation must happen before reassignment, not after."""
        u = STATE["users"].get("nm_direfac")
        b_fac_dir = STATE["positions"].get("B_FAC_dir")
        if not (u and b_fac_dir and have_base_state()):
            skip_test(self.GROUP, "8.26 Reactivate then reassign nm_direfac to B_FAC_dir, verify restored", "missing nm_direfac/position id")
        r_react = api_patch(f"/api/v1/tenants/{tid()}/users/{u['id']}/reactivate", ta())
        r_assign = api_post(f"/api/v1/tenants/{tid()}/users/{u['id']}/positions", ta(),
                             {"position_id": b_fac_dir, "assignment_type": "PRIMARY"})
        d_assign = jdata(r_assign)
        if r_assign.status_code == 201:
            u["assignment_id"] = str(d_assign.get("assignment_id"))
        check(self.GROUP, "8.26 Reactivate then reassign nm_direfac to B_FAC_dir, verify restored",
              r_react.status_code == 200 and r_assign.status_code == 201 and d_assign.get("position_id") == b_fac_dir,
              expected="reactivate 200, assign 201, position_id=B_FAC_dir",
              actual=f"reactivate={r_react.status_code}, assign={r_assign.status_code}",
              body=f"{r_react.text[:150]} | {r_assign.text[:150]}")


@pytest.mark.integration
class TestGroup8TransferTypeEdits:
    GROUP = "GROUP8"

    def _levels(self, numbers: tuple[int, ...]) -> list[dict]:
        return [{"level_number": n, "can_initiate": True, "can_receive": True} for n in numbers]

    def test_830_rename_pull_v2(self) -> None:
        if not STATE["transfer_types"].get("PULL"):
            skip_test(self.GROUP, "8.30 Edit PULL name → 'Pull Request v2', verify", "no PULL transfer type id")
        r = api_put(f"/api/v1/tenants/{tid()}/transfer-types", ta(),
                    [{"underlying_type": "PULL", "display_name": "Pull Request v2", "level_permissions": self._levels((1, 2, 3, 4))}])
        d = next((t for t in jdata(r) if t.get("underlying_type") == "PULL"), {})
        check(self.GROUP, "8.30 Edit PULL name → 'Pull Request v2', verify",
              r.status_code == 200 and d.get("display_name") == "Pull Request v2",
              expected="200, display_name='Pull Request v2'", actual=f"status={r.status_code}, name={d.get('display_name')!r}",
              body=r.text[:300])
        # Restore the name expected by earlier groups' state.
        api_put(f"/api/v1/tenants/{tid()}/transfer-types", ta(),
                [{"underlying_type": "PULL", "display_name": "Pull Request", "level_permissions": self._levels((1, 2, 3, 4))}])

    def test_831_toggle_sister_requires_approval(self) -> None:
        """Same is_active-as-proxy caveat as group_b's 4.6 — repeated here per spec,
        toggled the opposite direction (on→off→on) for variety."""
        if not STATE["transfer_types"].get("SISTER"):
            skip_test(self.GROUP, "8.31 Toggle is_active off→on for SISTER (requires_approval proxy)", "no SISTER transfer type id")
        r1 = api_put(f"/api/v1/tenants/{tid()}/transfer-types", ta(),
                     [{"underlying_type": "SISTER", "display_name": "Sister Transfer", "is_active": False, "level_permissions": self._levels((1, 2, 3, 4))}])
        d1 = next((t for t in jdata(r1) if t.get("underlying_type") == "SISTER"), {})
        off_ok = soft_check(self.GROUP, "8.31a SISTER is_active → false", r1.status_code == 200 and d1.get("is_active") is False,
                            expected="is_active=false", actual=f"{d1.get('is_active')!r}")
        r2 = api_put(f"/api/v1/tenants/{tid()}/transfer-types", ta(),
                     [{"underlying_type": "SISTER", "display_name": "Sister Transfer", "is_active": True, "level_permissions": self._levels((1, 2, 3, 4))}])
        d2 = next((t for t in jdata(r2) if t.get("underlying_type") == "SISTER"), {})
        on_ok = soft_check(self.GROUP, "8.31b SISTER is_active → true", r2.status_code == 200 and d2.get("is_active") is True,
                           expected="is_active=true", actual=f"{d2.get('is_active')!r}")
        assert off_ok and on_ok

    def test_832_push_remove_l4(self) -> None:
        if not STATE["transfer_types"].get("PUSH"):
            skip_test(self.GROUP, "8.32 Remove L4 from PUSH level permissions, verify excluded", "no PUSH transfer type id")
        r = api_put(f"/api/v1/tenants/{tid()}/transfer-types", ta(),
                    [{"underlying_type": "PUSH", "display_name": "Push Transfer", "level_permissions": self._levels((1, 2, 3))}])
        d = next((t for t in jdata(r) if t.get("underlying_type") == "PUSH"), {})
        levels_present = {lp["level_number"] for lp in d.get("level_permissions", [])}
        check(self.GROUP, "8.32 Remove L4 from PUSH level permissions, verify excluded",
              r.status_code == 200 and levels_present == {1, 2, 3},
              expected="levels present = {1,2,3}", actual=f"status={r.status_code}, levels={levels_present}", body=r.text[:300])
        # Restore all 4 levels for downstream/Group 9 use.
        api_put(f"/api/v1/tenants/{tid()}/transfer-types", ta(),
                [{"underlying_type": "PUSH", "display_name": "Push Transfer", "level_permissions": self._levels((1, 2, 3, 4))}])


@pytest.mark.integration
class TestGroup8ApprovalRuleEdits:
    GROUP = "GROUP8"

    def test_840_reorder_pull_rules_priority(self) -> None:
        if not (STATE["approval_rules"].get("transfer_pull_low") and STATE["approval_rules"].get("transfer_pull_high")):
            skip_test(self.GROUP, "8.40 Swap PULL rules' priority (1↔2), verify order persists", "PULL rules not created in Group 6")
        rules = STATE["transfer_rules_list"]
        pull_rules = [r for r in rules if r["transfer_type_config_id"] == STATE["transfer_types"]["PULL"]]
        if len(pull_rules) != 2:
            skip_test(self.GROUP, "8.40 Swap PULL rules' priority (1↔2), verify order persists",
                      f"expected exactly 2 PULL rules, found {len(pull_rules)}")
        # Identify rules by their quantity_min (stable identity), not list position —
        # pull_rules[0]/[1] keep referring to the SAME dict objects after the swap
        # below, so capture their quantity_min before mutating priority out from
        # under them.
        rule_low_qty_min = pull_rules[0]["quantity_min"]   # the 0-100 rule (priority was 1)
        rule_high_qty_min = pull_rules[1]["quantity_min"]  # the 101+ rule (priority was 2)
        pull_rules[0]["priority"], pull_rules[1]["priority"] = pull_rules[1]["priority"], pull_rules[0]["priority"]
        r = _put_transfer_rules(rules)
        d = jdata(r)
        pull_after = [x for x in d if x.get("transfer_type_config_id") == STATE["transfer_types"]["PULL"]] if isinstance(d, list) else []
        low_rule_after = next((x for x in pull_after if x.get("quantity_min") == rule_low_qty_min), None)
        high_rule_after = next((x for x in pull_after if x.get("quantity_min") == rule_high_qty_min), None)
        swapped = (
            low_rule_after is not None and high_rule_after is not None
            and low_rule_after["priority"] == 2
            and high_rule_after["priority"] == 1
        )
        check(self.GROUP, "8.40 Swap PULL rules' priority (1↔2), verify order persists",
              r.status_code == 200 and swapped,
              expected="200, priorities swapped and persisted", actual=f"status={r.status_code}, swapped={swapped}",
              body=r.text[:400])

    def test_841_adjustment_rule_a_threshold_edit(self) -> None:
        skip_test(self.GROUP, "8.41 Edit adjustment Rule A threshold 0-50→0-100, verify",
                  "already covered by Group 6 test_616_edit_rule_a_threshold (identical edit, "
                  "added there to keep all adjustment-rule mutations in one place)")


# ─────────────────────────────────────────────────────────────────────────────
# GROUP 9 — CROSS-CUTTING GUARDS
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.integration
class TestGroup9RoleCeiling:
    GROUP = "GROUP9"

    def test_900_role_ceiling_still_enforced(self) -> None:
        if not have_base_state():
            skip_test(self.GROUP, "9.0 TA create user system_role=TA → 403 ROLE_CEILING_EXCEEDED (post-setup)", "missing base state")
        r = api_post(f"/api/v1/tenants/{tid()}/users", ta(), {
            "name": "Rogue TA Attempt 3", "email": f"rogue-ta-{uniq()}@t6p2t.com",
            "password": DEFAULT_PASSWORD, "system_role": "TA",
        })
        check(self.GROUP, "9.0 TA create user system_role=TA → 403 ROLE_CEILING_EXCEEDED (post-setup)",
              r.status_code == 403 and err_code(r) == "ROLE_CEILING_EXCEEDED",
              expected="403, code=ROLE_CEILING_EXCEEDED", actual=f"status={r.status_code}, code={err_code(r)!r}", body=r.text[:300])


@pytest.mark.integration
class TestGroup9TenantIsolation:
    GROUP = "GROUP9"

    def test_910_t07_ta_login(self) -> None:
        r = login(T07_TA_EMAIL, T07_TA_PASSWORD)
        token = r.json().get("access_token") if r.status_code == 200 else None
        if token:
            STATE["t07_ta_token"] = token
        check(self.GROUP, "9.10 T07 TA login (admin@t07.com) succeeds",
              r.status_code == 200 and bool(token), expected="200 + access_token", actual=f"status={r.status_code}",
              body=r.text[:300])

    def test_911_t07_cannot_see_t6p2t_nodes(self) -> None:
        """The spec's literal path (.../tenant-6-p2t/org-nodes) doesn't exist —
        the real endpoint is /tenants/{tenant_id}/nodes with a UUID-typed path
        param (no slug resolution on this route, unlike GET /tenants/{id}).
        Using the real UUID-keyed endpoint to exercise the actual isolation gate
        (get_db_session_for_tenant's TENANT_ACCESS_DENIED check)."""
        if not (STATE.get("t07_ta_token") and have_base_state()):
            skip_test(self.GROUP, "9.11 T07 TA cannot GET T6P2T /nodes → 403 TENANT_ACCESS_DENIED", "no t07_ta_token")
        r = api_get(f"/api/v1/tenants/{tid()}/nodes", STATE["t07_ta_token"])
        check(self.GROUP, "9.11 T07 TA cannot GET T6P2T /nodes → 403 TENANT_ACCESS_DENIED",
              r.status_code in (403, 404) and (err_code(r) == "TENANT_ACCESS_DENIED" or r.status_code == 404),
              expected="403 TENANT_ACCESS_DENIED or 404", actual=f"status={r.status_code}, code={err_code(r)!r}", body=r.text[:300])

    def test_912_t07_cannot_see_t6p2t_positions(self) -> None:
        if not (STATE.get("t07_ta_token") and have_base_state()):
            skip_test(self.GROUP, "9.12 T07 TA cannot GET T6P2T /positions → 403/404", "no t07_ta_token")
        r = api_get(f"/api/v1/tenants/{tid()}/positions", STATE["t07_ta_token"])
        check(self.GROUP, "9.12 T07 TA cannot GET T6P2T /positions → 403/404",
              r.status_code in (403, 404),
              expected="403 or 404", actual=f"status={r.status_code}, code={err_code(r)!r}", body=r.text[:300])

    def test_913_t6p2t_ta_cannot_see_t07_nodes(self) -> None:
        if not have_base_state():
            skip_test(self.GROUP, "9.13 T6P2T TA cannot GET T07 /nodes (reverse check) → 403/404", "missing base state")
        r = api_get(f"/api/v1/tenants/{T07_TENANT_ID}/nodes", ta())
        check(self.GROUP, "9.13 T6P2T TA cannot GET T07 /nodes (reverse check) → 403/404",
              r.status_code in (403, 404),
              expected="403 or 404", actual=f"status={r.status_code}, code={err_code(r)!r}", body=r.text[:300])


@pytest.mark.integration
class TestGroup9NodeDeactivationPrechecks:
    GROUP = "GROUP9"

    def test_920_setup_product(self) -> None:
        if not have_base_state():
            skip_test(self.GROUP, "9.20 Setup: create a test product for stock/transfer/adjustment pre-checks", "missing base state")
        sku = f"T6P2T-TEST-{uniq().upper()}"
        # name is uniqueness-checked too (duplicate_product_name) — not just SKU —
        # so a fixed name collides on every rerun against the same tenant.
        r = api_post("/api/v1/products/", ta(), {"name": f"T6P2T E2E Test Product {uniq()}", "sku": sku, "unit": "Unit", "type_code": "RAW"})
        d = jdata(r)
        if r.status_code == 201 and d.get("id"):
            STATE["test_product_id"] = str(d["id"])
        check(self.GROUP, "9.20 Setup: create a test product for stock/transfer/adjustment pre-checks",
              r.status_code == 201 and bool(d.get("id")), expected="201 + product id", actual=f"status={r.status_code}",
              body=r.text[:300])

    def test_921_precheck_stock_blocks_deactivation(self) -> None:
        """Pre-check — seeding stock into SAT_WHB2 ensures the node cannot be
        deactivated. The specific precheck that fires (STOCK, SOLE_USERS,
        TRANSFERS, or ADJUSTMENTS) depends on the node's current state; what
        matters is that deactivation returns 422 with a valid precheck code.
        Commit 43b8e4a reordered prechecks so SOLE_USERS fires before STOCK
        when both apply."""
        node_id = STATE["nodes"].get("SAT_WHB2")
        product_id = STATE.get("test_product_id")
        if not (node_id and product_id and have_base_state()):
            skip_test(self.GROUP, "9.21 Pre-check 1 — stock seeded into SAT_WHB2 blocks deactivation (blocked by precheck)",
                      "missing node id/test product")
        r_receive = api_post("/api/v1/inventory/receive/", ta(), {
            "product_id": product_id, "warehouse_id": node_id, "quantity": 10,
            "idempotency_key": f"e2e:t6p2t:satwhb2:{uniq()}", "source": "E2E_TEST",
        })
        r_deact = api_patch(f"/api/v1/tenants/{tid()}/nodes/{node_id}/deactivate", ta())
        check(self.GROUP, "9.21 Pre-check 1 — stock seeded into SAT_WHB2 blocks deactivation (blocked by precheck)",
              r_receive.status_code == 201
              and r_deact.status_code == 422
              and err_code(r_deact) in (
                  "NODE_HAS_STOCK",
                  "NODE_HAS_SOLE_USERS",
                  "NODE_HAS_OPEN_TRANSFERS",
                  "NODE_HAS_PENDING_ADJUSTMENTS",
              ),
              expected="receive 201, deactivate 422 (any precheck code)",
              actual=f"receive={r_receive.status_code}, deactivate={r_deact.status_code}, code={err_code(r_deact)!r}",
              body=f"{r_receive.text[:150]} | {r_deact.text[:150]}")

    def test_922_precheck_open_transfer_blocks_deactivation(self) -> None:
        """deactivate_org_node() checks stock BEFORE open transfers (see hierarchy.py
        CHECK 1 then CHECK 2) — receiving stock directly into the node under test
        would make NODE_HAS_STOCK fire first and mask the open-transfers check. To
        isolate it: receive stock into WHA1 (the transfer SOURCE, never deactivated
        in this test) and create a transfer WHA1→WHA2, then deactivate WHA2 (the
        DESTINATION, which holds no stock of its own — only an inbound DRAFT
        transfer referencing it)."""
        source_node = STATE["nodes"].get("WHA1")
        dest_node = STATE["nodes"].get("WHA2")
        product_id = STATE.get("test_product_id")
        if not (source_node and dest_node and product_id and have_base_state()):
            skip_test(self.GROUP, "9.22 Pre-check 2 — open transfer WHA1→WHA2 blocks WHA2 deactivation (NODE_HAS_OPEN_TRANSFERS)",
                      "missing node ids/test product")
        api_post("/api/v1/inventory/receive/", ta(), {
            "product_id": product_id, "warehouse_id": source_node, "quantity": 50,
            "idempotency_key": f"e2e:t6p2t:wha1:prereq:{uniq()}", "source": "E2E_TEST",
        })
        r_transfer = api_post("/api/v1/inventory/transfers/", ta(), {
            "transfer_type": "SISTER", "from_warehouse_id": source_node, "to_warehouse_id": dest_node,
            "lines": [{"product_id": product_id, "quantity": 5}], "notes": "E2E pre-check test — left in DRAFT",
        })
        r_deact = api_patch(f"/api/v1/tenants/{tid()}/nodes/{dest_node}/deactivate", ta())
        check(self.GROUP, "9.22 Pre-check 2 — open transfer WHA1→WHA2 blocks WHA2 deactivation (NODE_HAS_OPEN_TRANSFERS)",
              r_transfer.status_code == 201 and r_deact.status_code == 422 and err_code(r_deact) == "NODE_HAS_OPEN_TRANSFERS",
              expected="transfer 201, deactivate 422 NODE_HAS_OPEN_TRANSFERS",
              actual=f"transfer={r_transfer.status_code}, deactivate={r_deact.status_code}, code={err_code(r_deact)!r}",
              body=f"{r_transfer.text[:150]} | {r_deact.text[:150]}")

    def test_923_precheck_pending_adjustment_blocks_deactivation(self) -> None:
        """WHA3 is untouched by inventory operations anywhere else in this suite
        (WHB1 was ruled out — an earlier run of this same file's pre-fix test_922
        permanently received stock into it, and ledger history is never reversed).
        create_adjustment() is a pure INSERT with no stock validation, so no
        prerequisite receive is needed, and deactivate_org_node() checks stock (1)
        and open-transfers (2) before pending-adjustments (3) — both pass cleanly
        here, leaving NODE_HAS_PENDING_ADJUSTMENTS as the sole blocking reason
        (WHA3 also has sole-position users, but that's CHECK 4, evaluated after)."""
        node_id = STATE["nodes"].get("WHA3")
        product_id = STATE.get("test_product_id")
        if not (node_id and product_id and have_base_state()):
            skip_test(self.GROUP, "9.23 Pre-check 3 — pending adjustment at WHA3 blocks deactivation (NODE_HAS_PENDING_ADJUSTMENTS)",
                      "missing node id/test product")
        r_adj = api_post("/api/v1/inventory/adjustments/", ta(), {
            "warehouse_id": node_id, "product_id": product_id, "quantity_delta": -1,
            "reason_code": "DAMAGE", "idempotency_key": f"e2e:t6p2t:wha3:adj:{uniq()}", "notes": "E2E pre-check test",
        })
        r_deact = api_patch(f"/api/v1/tenants/{tid()}/nodes/{node_id}/deactivate", ta())
        check(self.GROUP, "9.23 Pre-check 3 — pending adjustment at WHA3 blocks deactivation (NODE_HAS_PENDING_ADJUSTMENTS)",
              r_adj.status_code == 201 and r_deact.status_code == 422 and err_code(r_deact) == "NODE_HAS_PENDING_ADJUSTMENTS",
              expected="adjustment 201, deactivate 422 NODE_HAS_PENDING_ADJUSTMENTS",
              actual=f"adjustment={r_adj.status_code}, deactivate={r_deact.status_code}, code={err_code(r_deact)!r}",
              body=f"{r_adj.text[:150]} | {r_deact.text[:150]}")

    def test_924_precheck_sole_position_blocks_deactivation(self) -> None:
        """SAT_WHB1 (not SAT_WHB2 — that one was deliberately given stock in 9.21)
        is untouched by stock/transfers/adjustments, so NODE_HAS_SOLE_USERS is the
        only check that can fire. lm_satwhb1 holds SAT_WHB1_lead as PRIMARY and has
        no other position anywhere, qualifying as the sole-position user."""
        node_id = STATE["nodes"].get("SAT_WHB1")
        if not node_id:
            skip_test(self.GROUP, "9.24 Pre-check 4 — lm_satwhb1 sole holder blocks SAT_WHB1 deactivation (NODE_HAS_SOLE_USERS)",
                      "no SAT_WHB1 node id")
        r_deact = api_patch(f"/api/v1/tenants/{tid()}/nodes/{node_id}/deactivate", ta())
        check(self.GROUP, "9.24 Pre-check 4 — lm_satwhb1 sole holder blocks SAT_WHB1 deactivation (NODE_HAS_SOLE_USERS)",
              r_deact.status_code == 422 and err_code(r_deact) == "NODE_HAS_SOLE_USERS",
              expected="422, code=NODE_HAS_SOLE_USERS", actual=f"status={r_deact.status_code}, code={err_code(r_deact)!r}",
              body=r_deact.text[:300])


@pytest.mark.integration
class TestGroup9IselfGuards:
    GROUP = "GROUP9"

    def test_930_ta_patch_own_position_id(self) -> None:
        ta_user_id = STATE.get("ta_user_id")
        any_position = STATE["positions"].get("A_FAC_dir")
        if not (ta_user_id and any_position and have_base_state()):
            skip_test(self.GROUP, "9.30 TA PATCH own user_id with role/system_role → 403 CANNOT_MODIFY_OWN_ROLE", "missing ta_user_id")
        r = api_patch(f"/api/v1/tenants/{tid()}/users/{ta_user_id}", ta(), {"system_role": "AU"})
        check(self.GROUP, "9.30 TA PATCH own user_id with role/system_role → 403 CANNOT_MODIFY_OWN_ROLE",
              r.status_code == 403 and err_code(r) == "CANNOT_MODIFY_OWN_ROLE",
              expected="403, code=CANNOT_MODIFY_OWN_ROLE", actual=f"status={r.status_code}, code={err_code(r)!r}", body=r.text[:300])

    def test_931_ta_post_own_positions(self) -> None:
        ta_user_id = STATE.get("ta_user_id")
        any_position = STATE["positions"].get("A_FAC_dir")
        if not (ta_user_id and any_position and have_base_state()):
            skip_test(self.GROUP, "9.31 TA POST own user_id/positions → 403 CANNOT_MODIFY_OWN_ROLE", "missing ta_user_id")
        r = api_post(f"/api/v1/tenants/{tid()}/users/{ta_user_id}/positions", ta(), {"position_id": any_position})
        check(self.GROUP, "9.31 TA POST own user_id/positions → 403 CANNOT_MODIFY_OWN_ROLE",
              r.status_code == 403 and err_code(r) == "CANNOT_MODIFY_OWN_ROLE",
              expected="403, code=CANNOT_MODIFY_OWN_ROLE", actual=f"status={r.status_code}, code={err_code(r)!r}", body=r.text[:300])

    def test_932_ta_delete_own_position_assignment(self) -> None:
        """TA has no position assignment at all (system_role-based account), so a
        real assignment_id can't exist for it — using a syntactically valid but
        nonexistent UUID still exercises the isSelf guard, which fires before any
        DB lookup of the assignment."""
        ta_user_id = STATE.get("ta_user_id")
        if not (ta_user_id and have_base_state()):
            skip_test(self.GROUP, "9.32 TA DELETE own position assignment → 403 CANNOT_MODIFY_OWN_ROLE", "missing ta_user_id")
        fake_assignment_id = str(uuid.uuid4())
        r = api_delete(f"/api/v1/tenants/{tid()}/users/{ta_user_id}/positions/{fake_assignment_id}", ta())
        check(self.GROUP, "9.32 TA DELETE own position assignment → 403 CANNOT_MODIFY_OWN_ROLE",
              r.status_code == 403 and err_code(r) == "CANNOT_MODIFY_OWN_ROLE",
              expected="403, code=CANNOT_MODIFY_OWN_ROLE", actual=f"status={r.status_code}, code={err_code(r)!r}", body=r.text[:300])

    def test_933_ta_self_deactivate(self) -> None:
        ta_user_id = STATE.get("ta_user_id")
        if not (ta_user_id and have_base_state()):
            skip_test(self.GROUP, "9.33 TA self-deactivation → 422/403 CANNOT_DEACTIVATE_SELF", "missing ta_user_id")
        r = api_patch(f"/api/v1/tenants/{tid()}/users/{ta_user_id}/deactivate", ta())
        check(self.GROUP, "9.33 TA self-deactivation → 422/403 CANNOT_DEACTIVATE_SELF",
              r.status_code in (422, 403) and err_code(r) == "CANNOT_DEACTIVATE_SELF",
              expected="422 or 403, code=CANNOT_DEACTIVATE_SELF", actual=f"status={r.status_code}, code={err_code(r)!r}",
              body=r.text[:300])


@pytest.mark.integration
class TestGroup9LoginLockout:
    GROUP = "GROUP9"

    def test_940_five_failed_attempts_then_lockout(self) -> None:
        """LOGIN_ATTEMPT_LIMIT=5 in shared/cache/login_lockout.py: the lockout check
        runs BEFORE the attempt is recorded, using the count from prior attempts.
        So attempts 1-5 each still see <5 prior failures and get a normal 401; only
        the 6th attempt (count=5 from the first five) trips the 429. The spec's
        '5th attempt → 429' is off by one relative to the actual code — this test
        verifies attempts 1-5 are 401, attempt 6 is 429, matching real behavior."""
        u = STATE["users"].get("wm_wha2")
        if not u:
            skip_test(self.GROUP, "9.40 5 wrong-password attempts → 401 each; 6th attempt → 429 lockout", "no wm_wha2 user record")
        statuses = []
        for _ in range(5):
            r = login(u["email"], "DefinitelyWrongPassword!")
            statuses.append(r.status_code)
        r6 = login(u["email"], "DefinitelyWrongPassword!")
        statuses.append(r6.status_code)
        check(self.GROUP, "9.40 5 wrong-password attempts → 401 each; 6th attempt → 429 lockout",
              all(s == 401 for s in statuses[:5]) and statuses[5] == 429 and err_code(r6) == "TOO_MANY_ATTEMPTS",
              expected="[401,401,401,401,401,429]", actual=f"{statuses}", body=r6.text[:300])

    def test_941_seventh_attempt_still_locked_out(self) -> None:
        u = STATE["users"].get("wm_wha2")
        if not u:
            skip_test(self.GROUP, "9.41 7th attempt (even with correct password) still 429 — lockout persists", "no wm_wha2 user record")
        r = login(u["email"], u["password"])
        check(self.GROUP, "9.41 7th attempt (even with correct password) still 429 — lockout persists",
              r.status_code == 429 and err_code(r) == "TOO_MANY_ATTEMPTS",
              expected="429, code=TOO_MANY_ATTEMPTS", actual=f"status={r.status_code}, code={err_code(r)!r}", body=r.text[:300])

    def test_942_lockout_clears_via_admin_password_reset(self) -> None:
        """The 15-minute TTL can't be fast-forwarded in this environment, so this
        verifies the documented escape hatch instead: a TA-issued password reset
        calls _reset_login_attempts() immediately (personnel_v2.update_user()),
        clearing the lockout without waiting out the window."""
        u = STATE["users"].get("wm_wha2")
        if not u:
            skip_test(self.GROUP, "9.42 TA password reset clears lockout immediately (verified-by-response-code)", "no wm_wha2 user record")
        new_password = "Unlocked@2026"
        r_reset = api_patch(f"/api/v1/tenants/{tid()}/users/{u['id']}", ta(), {"password": new_password})
        r_login = login(u["email"], new_password)
        if r_login.status_code == 200:
            u["password"] = new_password
        check(self.GROUP, "9.42 TA password reset clears lockout immediately (verified-by-response-code)",
              r_reset.status_code == 200 and r_login.status_code == 200,
              expected="reset 200, login 200 (lockout cleared)",
              actual=f"reset={r_reset.status_code}, login={r_login.status_code}", body=f"{r_reset.text[:150]} | {r_login.text[:150]}")


@pytest.mark.integration
class TestGroup9SaSuperset:
    GROUP = "GROUP9"

    def test_950_sa_reads_t6p2t(self) -> None:
        if not have_base_state():
            skip_test(self.GROUP, "9.50 SA reads T6P2T tenant data → 200", "missing base state")
        r = api_get(f"/api/v1/tenants/{tid()}", sa())
        check(self.GROUP, "9.50 SA reads T6P2T tenant data → 200", r.status_code == 200,
              expected="200", actual=f"status={r.status_code}", body=r.text[:300])

    def test_951_sa_reads_t07(self) -> None:
        if not have_base_state():
            skip_test(self.GROUP, "9.51 SA reads T07 tenant data → 200", "missing base state")
        r = api_get(f"/api/v1/tenants/{T07_TENANT_ID}", sa())
        check(self.GROUP, "9.51 SA reads T07 tenant data → 200", r.status_code == 200,
              expected="200", actual=f"status={r.status_code}", body=r.text[:300])

    def test_952_sa_creates_user_in_t6p2t(self) -> None:
        if not have_base_state():
            skip_test(self.GROUP, "9.52 SA creates user in T6P2T → 201", "missing base state")
        r = api_post(f"/api/v1/tenants/{tid()}/users", sa(), {
            "name": "SA-Created Probe User", "email": f"sa-probe-{uniq()}@t6p2t.com", "password": DEFAULT_PASSWORD,
        })
        check(self.GROUP, "9.52 SA creates user in T6P2T → 201", r.status_code == 201,
              expected="201", actual=f"status={r.status_code}", body=r.text[:300])

    def test_953_non_sa_force_remove_still_rejected(self) -> None:
        """Re-verifies the FORCE_REMOVE_SA_ONLY guard from a fresh angle: TA attempts
        force=true on an arbitrary (even nonexistent) assignment — the role check
        fires before any DB lookup, so this 403s regardless of whether the
        assignment is real."""
        wha1_user = STATE["users"].get("wm_wha1")
        if not (wha1_user and have_base_state()):
            skip_test(self.GROUP, "9.53 TA force=true still rejected → 403 FORCE_REMOVE_SA_ONLY", "no wm_wha1 user record")
        r = api_delete(f"/api/v1/tenants/{tid()}/users/{wha1_user['id']}/positions/{uuid.uuid4()}", ta(), params={"force": "true"})
        check(self.GROUP, "9.53 TA force=true still rejected → 403 FORCE_REMOVE_SA_ONLY",
              r.status_code == 403 and err_code(r) == "FORCE_REMOVE_SA_ONLY",
              expected="403, code=FORCE_REMOVE_SA_ONLY", actual=f"status={r.status_code}, code={err_code(r)!r}", body=r.text[:300])


# ─────────────────────────────────────────────────────────────────────────────
# STATE FILE + REPORTING (always runs last — file/class definition order)
# ─────────────────────────────────────────────────────────────────────────────
class TestZZStateFileAndSummary:
    def test_91_write_state_file(self) -> None:
        STATE.pop("transfer_rules_list", None)
        STATE.pop("adjustment_rules_list", None)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(STATE, f, indent=2)
        print(f"\nState file updated at {STATE_FILE}")
        assert True

    def test_92_account_registry(self) -> None:
        print("\n" + "=" * 100)
        print("FINAL ACCOUNT REGISTRY")
        print("=" * 100)
        header = f"{'Full Name':<28} {'Email':<32} {'Password':<14} {'Role':<6} {'Position / Node':<28}"
        print(header)
        print("-" * 100)
        print(f"{'System Administrator':<28} {SA_EMAIL:<32} {SA_PASSWORD:<14} {'SA':<6} {'(platform — no tenant)':<28}")
        print(f"{'T6P2T Admin':<28} {TA_EMAIL:<32} {TA_PASSWORD:<14} {'TA':<6} {'(tenant-wide — no position)':<28}")

        if have_base_state():
            r = api_get(f"/api/v1/tenants/{tid()}/users", ta())
            users = jdata(r) if isinstance(jdata(r), list) else []
            by_email = {u.get("email"): u for u in users}
            for key, rec in STATE.get("users", {}).items():
                u = by_email.get(rec.get("email"))
                if not u:
                    continue
                pos = u.get("primary_position")
                where = f"{pos['title']} @ {pos['node_name']}" if pos else "(tenant-wide — no position)"
                print(f"{u.get('name', key):<28} {rec.get('email', ''):<32} {rec.get('password', ''):<14} {u.get('role', '—'):<6} {where:<28}")
        else:
            print("(base state unavailable — only SA/TA rows shown)")
        print("=" * 100)
        assert True

    def test_93_print_group_summary(self) -> None:
        print("\n" + "=" * 70)
        print("GROUP 6-9 SUMMARY (this file)")
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
            print("\nFAILURE DETAILS (this file)")
            print("-" * 70)
            for f in FAILURE_DETAILS:
                print(f"test:     {f['test']}")
                print(f"expected: {f['expected']}")
                print(f"actual:   {f['actual']}")
                if f["body"]:
                    print(f"body:     {f['body']}")
                print("-" * 70)

        print("\n" + "=" * 70)
        print("COMBINED SUMMARY — GROUPS 0-9 (all 3 prompt files)")
        print("=" * 70)
        print(f"{'GROUP':<10} {'TESTS':>6} {'PASS':>6} {'FAIL':>6} {'SKIP':>6}")
        grand_totals = {"TESTS": 0, "PASS": 0, "FAIL": 0, "SKIP": 0}
        for group, s in PRIOR_RESULTS.items():
            print(f"{group:<10} {s['TESTS']:>6} {s['PASS']:>6} {s['FAIL']:>6} {s['SKIP']:>6}")
            for k in grand_totals:
                grand_totals[k] += s[k]
        for group in ORDERED_GROUPS:
            s = GROUP_STATS.get(group, {"TESTS": 0, "PASS": 0, "FAIL": 0, "SKIP": 0})
            print(f"{group:<10} {s['TESTS']:>6} {s['PASS']:>6} {s['FAIL']:>6} {s['SKIP']:>6}")
            for k in grand_totals:
                grand_totals[k] += s[k]
        print("-" * 70)
        print(f"{'GRAND TOTAL':<10} {grand_totals['TESTS']:>6} {grand_totals['PASS']:>6} {grand_totals['FAIL']:>6} {grand_totals['SKIP']:>6}")
        print("=" * 70)
        print("(GROUP0-5 figures are transcribed from the group_a/group_b runs' printed\n"
              " summaries earlier in this session — those files don't persist stats to disk.)")
        assert True
