"""
Group E (Groups 21-22) — Plan tier management + org level lock coverage tests.

Group 21: PATCH /plan endpoint + SA bypass verification.
Group 22: Hierarchy level lock (G3a) + approval-coverage endpoint + clone-level-permissions.
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

STATE_FILE = os.path.join(os.path.dirname(__file__), "t6p2t_state.json")
ORDERED_GROUPS = ["GROUP21", "GROUP22"]

# ─────────────────────────────────────────────────────────────────────────────
# Load prior-group state
# ─────────────────────────────────────────────────────────────────────────────
with open(STATE_FILE, "r", encoding="utf-8") as _f:
    _LOADED_STATE: dict[str, Any] = json.load(_f)

STATE: dict[str, Any] = _LOADED_STATE
STATE.setdefault("g21", {})
STATE.setdefault("g22", {})

TA_EMAIL = "admin@t6p2t.com"
SA_EMAIL = "smartadmin@smart-inventory.com"

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
    return requests.post(f"{BASE_URL}{path}", headers=hdrs(token),
                          json=body if body is not None else {}, timeout=15)


def api_put(path: str, token: str, body: Any = None) -> requests.Response:
    return requests.put(f"{BASE_URL}{path}", headers=hdrs(token), json=body, timeout=15)


def api_patch(path: str, token: str, body: Optional[dict] = None) -> requests.Response:
    return requests.patch(f"{BASE_URL}{path}", headers=hdrs(token), json=body or {}, timeout=15)


def api_delete(path: str, token: str, params: Optional[dict] = None) -> requests.Response:
    return requests.delete(f"{BASE_URL}{path}",
                            headers={"Authorization": f"Bearer {token}"},
                            params=params, timeout=15)


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


def _creds_for_email(email: str) -> str:
    for rec in STATE.get("users", {}).values():
        if rec.get("email") == email:
            return str(rec.get("password", DEFAULT_PASSWORD))
    return DEFAULT_PASSWORD


def _refresh_tokens() -> None:
    """Re-login at import time so tokens are always fresh regardless of when
    t6p2t_state.json was last written. JWTs expire after 60 min."""
    sa_password = "Admin@2026"
    for email in (TA_EMAIL, SA_EMAIL):
        password = sa_password if email == SA_EMAIL else _creds_for_email(email)
        try:
            r = login(email, password)
            if r.status_code == 200:
                token = r.json().get("access_token")
                if token:
                    if email == TA_EMAIL:
                        STATE["ta_token"] = token
                    elif email == SA_EMAIL:
                        STATE["sa_token"] = token
        except Exception:
            pass  # leave stale token — individual tests will surface the 401


_refresh_tokens()


_TOKEN_CACHE: dict[str, str] = {}


def tok(email: str) -> Optional[str]:
    if email in _TOKEN_CACHE:
        return _TOKEN_CACHE[email]
    r = login(email, _creds_for_email(email))
    if r.status_code == 200:
        token = r.json().get("access_token")
        if token:
            _TOKEN_CACHE[email] = token
            return token
    return None


def fresh_tok(email: str, password: str = DEFAULT_PASSWORD) -> Optional[str]:
    """Always performs a fresh login — use in long-running chains where cached token may expire."""
    r = login(email, password)
    if r.status_code == 200:
        return r.json().get("access_token")
    return None


# ── Node constants ────────────────────────────────────────────────────────────
NODE_A_FAC    = STATE["nodes"]["A_FAC"]
NODE_B_FAC    = STATE["nodes"]["B_FAC"]
NODE_A_REG    = STATE["nodes"]["A_REG"]
NODE_B_REG    = STATE["nodes"]["B_REG"]
NODE_WHA1     = STATE["nodes"]["WHA1"]
NODE_WHA2     = STATE["nodes"]["WHA2"]
NODE_WHA3     = STATE["nodes"]["WHA3"]
NODE_WHB1     = STATE["nodes"]["WHB1"]
NODE_WHB2     = STATE["nodes"]["WHB2"]
NODE_SAT_WHA1 = STATE["nodes"]["SAT_WHA1"]
NODE_SAT_WHA2 = STATE["nodes"]["SAT_WHA2"]
NODE_SAT_WHB1 = STATE["nodes"]["SAT_WHB1"]
NODE_SAT_WHB2 = STATE["nodes"]["SAT_WHB2"]
NODE_SAT_WHA3 = STATE["nodes"]["SAT_WHA3"]

# ── Emails ────────────────────────────────────────────────────────────────────
EMAIL_TA  = "admin@t6p2t.com"
EMAIL_SA  = "smartadmin@smart-inventory.com"
EMAIL_NM_A = "nm_addisfac@t6p2t.com"
EMAIL_WM_WHA1 = STATE["users"].get("wm_wha1", {}).get("email", "wm_wha1_new@t6p2t.com")

# ── URL constants ─────────────────────────────────────────────────────────────
_T = STATE["tenant_id"]
PLAN_URL    = f"/api/v1/tenants/{_T}/plan"
HIER_URL    = f"/api/v1/tenants/{_T}/hierarchy/config"
NODES_URL   = f"/api/v1/tenants/{_T}/nodes"
COV_URL     = f"/api/v1/tenants/{_T}/approval-coverage"
MY_PLAN_URL = "/api/v1/tenants/me/plan"


# ─────────────────────────────────────────────────────────────────────────────
# GROUP 21 — Plan Tier Management & SA Enforcement
# Tests: PATCH /plan endpoint, SA-only gate, TA bypass, invalid tier rejection.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.integration
class TestGroup21PlanTier:
    GROUP = "GROUP21"

    def test_2101_ta_reads_my_plan(self) -> None:
        """TA reads /me/plan — baseline: endpoint reachable, plan_tier present."""
        if not have_base_state():
            skip_test(self.GROUP, "21.01 TA reads /me/plan", "missing base state")
        r = api_get(MY_PLAN_URL, ta())
        data = jdata(r)
        check(self.GROUP, "21.01 TA reads /me/plan",
              r.status_code == 200 and isinstance(data, dict) and "plan_tier" in data,
              expected="200, plan_tier present",
              actual=f"status={r.status_code} keys={list(data.keys()) if isinstance(data, dict) else data}",
              body=r.text[:300])

    def test_2102_sa_patch_invalid_tier(self) -> None:
        """SA PATCH /plan with unrecognised tier → 422 INVALID_TIER."""
        r = api_patch(PLAN_URL, sa(), {"plan_tier": "FREEMIUM"})
        check(self.GROUP, "21.02 SA PATCH invalid tier → 422 INVALID_TIER",
              r.status_code == 422 and err_code(r) == "INVALID_TIER",
              expected="422, INVALID_TIER",
              actual=f"status={r.status_code} code={err_code(r)}",
              body=r.text[:300])

    def test_2103_non_sa_cannot_patch_plan(self) -> None:
        """NM (nm_addisfac) PATCH /plan → 403: SA-only gate."""
        token = tok(EMAIL_NM_A)
        if not token:
            skip_test(self.GROUP, "21.03 NM cannot PATCH /plan", "could not log in as nm_addisfac")
        r = api_patch(PLAN_URL, token, {"plan_tier": "STARTER"})
        check(self.GROUP, "21.03 NM cannot PATCH /plan → 403",
              r.status_code == 403,
              expected="403", actual=f"status={r.status_code}", body=r.text[:300])

    def test_2104_sa_patch_plan_to_growth(self) -> None:
        """SA PATCH T6P2T plan to GROWTH, max_warehouses=20, max_users=50 → 200."""
        r = api_patch(PLAN_URL, sa(), {
            "plan_tier": "GROWTH",
            "max_warehouses": 20,
            "max_users": 50,
        })
        data = jdata(r)
        check(self.GROUP, "21.04 SA PATCH plan to GROWTH → 200",
              r.status_code == 200 and isinstance(data, dict) and data.get("plan_tier") == "GROWTH",
              expected="200, plan_tier=GROWTH",
              actual=f"status={r.status_code} tier={data.get('plan_tier') if isinstance(data, dict) else data}",
              body=r.text[:300])

    def test_2105_skip_user_cap_enforcement(self) -> None:
        """User cap enforcement cannot be exercised: only TA can create users, TA bypasses plan checks."""
        skip_test(self.GROUP, "21.05 user cap enforcement",
                  "only TA can create users, TA bypasses plan checks — 402 unreachable in this path")

    def test_2106_ta_plan_reflects_growth(self) -> None:
        """TA reads /me/plan → plan_tier=GROWTH, max_warehouses=20 after SA change."""
        r = api_get(MY_PLAN_URL, ta())
        data = jdata(r)
        ok = (r.status_code == 200
              and isinstance(data, dict)
              and data.get("plan_tier") == "GROWTH"
              and data.get("max_warehouses") == 20)
        check(self.GROUP, "21.06 /me/plan reflects GROWTH tier",
              ok,
              expected="plan_tier=GROWTH, max_warehouses=20",
              actual=(f"tier={data.get('plan_tier') if isinstance(data, dict) else '?'}"
                      f" wh={data.get('max_warehouses') if isinstance(data, dict) else '?'}"),
              body=r.text[:300])

    def test_2107_skip_transfer_flag_not_wired(self) -> None:
        """TRANSFERS_SISTER feature flag not yet wired into transfer creation endpoint."""
        skip_test(self.GROUP, "21.07 TRANSFERS_SISTER flag enforcement",
                  "plan_middleware not yet wired into transfer creation endpoint")

    def test_2108_sa_patch_plan_to_starter_tight_cap(self) -> None:
        """SA sets T6P2T to STARTER, max_warehouses=3, max_users=2 → 200."""
        r = api_patch(PLAN_URL, sa(), {
            "plan_tier": "STARTER",
            "max_warehouses": 3,
            "max_users": 2,
        })
        check(self.GROUP, "21.08 SA PATCH plan to STARTER, max_warehouses=3",
              r.status_code == 200,
              expected="200", actual=f"status={r.status_code}", body=r.text[:300])

    def test_2109_ta_bypasses_warehouse_cap(self) -> None:
        """TA creates org node despite max_warehouses=3 (T6P2T has 16 nodes): TA bypass confirmed → 201."""
        r = api_post(NODES_URL, ta(), {
            "level_number": 3,
            "name": f"Test Node G21 {uniq()}",
            "parent_node_id": NODE_A_REG,
            "is_stock_holding": True,
        })
        data = jdata(r)
        node_id = data.get("id") if isinstance(data, dict) else None
        if node_id:
            STATE["g21"]["test_node_id"] = str(node_id)
        check(self.GROUP, "21.09 TA creates node despite warehouse cap (bypass) → 201",
              r.status_code == 201,
              expected="201 (TA bypasses plan cap)",
              actual=f"status={r.status_code}", body=r.text[:300])

    def test_2110_cleanup_restore_enterprise(self) -> None:
        """Cleanup: delete G21 test node + restore plan to ENTERPRISE with null limits."""
        test_node_id = STATE.get("g21", {}).get("test_node_id")
        node_ok = True
        if test_node_id:
            rd = api_delete(f"{NODES_URL}/{test_node_id}", ta())
            node_ok = rd.status_code in (200, 204, 404)

        r = api_patch(PLAN_URL, sa(), {
            "plan_tier": "ENTERPRISE",
            "max_warehouses": None,
            "max_users": None,
        })
        check(self.GROUP, "21.10 cleanup: restore ENTERPRISE + null caps",
              r.status_code == 200 and node_ok,
              expected="200, node deleted",
              actual=f"patch={r.status_code} node_cleanup={node_ok}",
              body=r.text[:300])


# ─────────────────────────────────────────────────────────────────────────────
# GROUP 22 — Hierarchy Level Lock (G3a) + Approval Coverage
# Tests: shrink blocked when nodes exist, grow always allowed, coverage endpoint,
#        clone-level-permissions, cleanup restore.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.integration
class TestGroup22HierarchyLevelLock:
    GROUP = "GROUP22"

    def test_2201_shrink_blocked_nodes_exist(self) -> None:
        """PUT hierarchy/config with 3 levels (T6P2T has active nodes at L4) → 422 LEVEL_COUNT_LOCKED."""
        if not have_base_state():
            skip_test(self.GROUP, "22.01 shrink blocked when nodes exist at L4", "missing base state")

        # Read current config to get the correct level structure
        rc = api_get(HIER_URL, ta())
        levels = jdata(rc)
        if not isinstance(levels, list) or len(levels) < 4:
            skip_test(self.GROUP, "22.01 shrink blocked when nodes exist at L4",
                      f"unexpected hierarchy config (expected ≥4 levels): {rc.text[:200]}")

        # Persist for later restore
        STATE["g22"]["original_levels"] = [
            {"level_number": lvl["level_number"], "level_name": lvl["level_name"],
             "is_stock_holding": lvl.get("is_stock_holding", True)}
            for lvl in levels
        ]

        three_levels = [item for item in STATE["g22"]["original_levels"] if item["level_number"] <= 3]
        r = api_put(HIER_URL, ta(), three_levels)
        check(self.GROUP, "22.01 shrink to 3 levels blocked (nodes at L4) → 422",
              r.status_code == 422 and err_code(r) == "LEVEL_COUNT_LOCKED",
              expected="422, LEVEL_COUNT_LOCKED",
              actual=f"status={r.status_code} code={err_code(r)}",
              body=r.text[:300])

    def test_2202_grow_to_five_levels_allowed(self) -> None:
        """PUT hierarchy/config with 5 levels (adding L5) → 200: grow always allowed."""
        saved = STATE.get("g22", {}).get("original_levels")
        if not saved or len(saved) != 4:
            skip_test(self.GROUP, "22.02 grow to 5 levels allowed",
                      "no 4-level original config saved from 22.01")

        five_levels = saved + [{"level_number": 5, "level_name": "Sub-Satellite",
                                 "is_stock_holding": True}]
        r = api_put(HIER_URL, ta(), five_levels)
        check(self.GROUP, "22.02 grow hierarchy to 5 levels → 200",
              r.status_code == 200,
              expected="200", actual=f"status={r.status_code}", body=r.text[:300])

    def test_2203_coverage_new_level_uncovered(self) -> None:
        """GET approval-coverage?level=5 for newly-added L5 → transfer_level_perms_exist=False."""
        r = api_get(COV_URL, ta(), params={"level": 5})
        data = jdata(r)
        check(self.GROUP, "22.03 approval-coverage level=5 → 200",
              r.status_code == 200 and isinstance(data, dict),
              expected="200, dict",
              actual=f"status={r.status_code}", body=r.text[:300])
        if r.status_code == 200 and isinstance(data, dict):
            soft_check(self.GROUP, "22.03b transfer_level_perms_exist=False for new L5",
                       data.get("transfer_level_perms_exist") is False,
                       expected="False",
                       actual=str(data.get("transfer_level_perms_exist")))

    def test_2204_create_node_at_level_5(self) -> None:
        """TA creates org node at L5 (child of SAT_WHA1) → 201; node_id saved for cleanup."""
        r = api_post(NODES_URL, ta(), {
            "level_number": 5,
            "name": f"SubSat G22 {uniq()}",
            "parent_node_id": NODE_SAT_WHA1,
            "is_stock_holding": True,
        })
        data = jdata(r)
        node_id = data.get("id") if isinstance(data, dict) else None
        if node_id:
            STATE["g22"]["test_node_id"] = str(node_id)
        check(self.GROUP, "22.04 create node at L5 → 201",
              r.status_code == 201 and node_id is not None,
              expected="201, id present",
              actual=f"status={r.status_code} id={node_id}",
              body=r.text[:300])

    def test_2205_clone_level_permissions(self) -> None:
        """POST clone-level-permissions for L5 node → 200 with cloned/from_level/to_level fields."""
        test_node_id = STATE.get("g22", {}).get("test_node_id")
        if not test_node_id:
            skip_test(self.GROUP, "22.05 clone level permissions", "no test_node_id from 22.04")
        r = api_post(f"{NODES_URL}/{test_node_id}/clone-level-permissions", ta())
        data = jdata(r)
        check(self.GROUP, "22.05 clone-level-permissions → 200",
              r.status_code == 200 and isinstance(data, dict) and "to_level" in data,
              expected="200, to_level present",
              actual=f"status={r.status_code} keys={list(data.keys()) if isinstance(data, dict) else data}",
              body=r.text[:300])

    def test_2206_coverage_after_clone(self) -> None:
        """GET approval-coverage?level=5 after clone — endpoint returns 200."""
        r = api_get(COV_URL, ta(), params={"level": 5})
        data = jdata(r)
        check(self.GROUP, "22.06 approval-coverage after clone → 200",
              r.status_code == 200 and isinstance(data, dict),
              expected="200, dict",
              actual=f"status={r.status_code}", body=r.text[:300])

    def test_2207_delete_test_node(self) -> None:
        """TA DELETE L5 test node → 200: soft-deletes it, clears the way for L5 level removal."""
        test_node_id = STATE.get("g22", {}).get("test_node_id")
        if not test_node_id:
            skip_test(self.GROUP, "22.07 delete L5 test node", "no test_node_id from 22.04")
        r = api_delete(f"{NODES_URL}/{test_node_id}", ta())
        check(self.GROUP, "22.07 delete L5 test node → 200",
              r.status_code in (200, 204),
              expected="200 or 204", actual=f"status={r.status_code}", body=r.text[:300])

    def test_2208_shrink_back_to_four_levels(self) -> None:
        """TA PUT hierarchy/config back to 4 levels → 200 (no active L5 nodes after deletion)."""
        saved = STATE.get("g22", {}).get("original_levels")
        if not saved:
            skip_test(self.GROUP, "22.08 restore 4-level hierarchy",
                      "no saved original_levels from 22.01")

        four_levels = [item for item in saved if item["level_number"] <= 4]
        r = api_put(HIER_URL, ta(), four_levels)
        check(self.GROUP, "22.08 restore hierarchy to 4 levels → 200",
              r.status_code == 200,
              expected="200", actual=f"status={r.status_code}", body=r.text[:300])

    def test_2209_verify_four_levels_restored(self) -> None:
        """GET hierarchy/config → exactly 4 active levels confirmed."""
        r = api_get(HIER_URL, ta())
        levels = jdata(r)
        active = [lvl for lvl in (levels if isinstance(levels, list) else [])
                  if lvl.get("is_active", True)]
        check(self.GROUP, "22.09 hierarchy restored to 4 levels",
              r.status_code == 200 and len(active) == 4,
              expected="200, 4 active levels",
              actual=f"status={r.status_code} active_levels={len(active)}",
              body=r.text[:300])


# ─────────────────────────────────────────────────────────────────────────────
# Utility tests — state persistence + summary
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.integration
class TestGroupEUtility:

    def test_91_persist_state(self) -> None:
        """Write updated STATE back to t6p2t_state.json for downstream test files."""
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(STATE, f, indent=2)
        print(f"\nState file updated at {STATE_FILE}")
        assert True

    def test_92_print_group_summary(self) -> None:
        print("\n" + "=" * 70)
        print("GROUP 21-22 SUMMARY (group_e)")
        print("=" * 70)
        print(f"{'GROUP':<10} {'TESTS':>6} {'PASS':>6} {'FAIL':>6} {'SKIP':>6}")
        totals: dict[str, int] = {"TESTS": 0, "PASS": 0, "FAIL": 0, "SKIP": 0}
        for group in ORDERED_GROUPS:
            s = GROUP_STATS.get(group, {"TESTS": 0, "PASS": 0, "FAIL": 0, "SKIP": 0})
            print(f"{group:<10} {s['TESTS']:>6} {s['PASS']:>6} {s['FAIL']:>6} {s['SKIP']:>6}")
            for k in totals:
                totals[k] += s[k]
        print("-" * 70)
        print(f"{'TOTAL':<10} {totals['TESTS']:>6} {totals['PASS']:>6} {totals['FAIL']:>6} {totals['SKIP']:>6}")
        print("=" * 70)

        if FAILURE_DETAILS:
            print("\nFAILURE DETAILS (group_e)")
            print("-" * 70)
            for fd in FAILURE_DETAILS:
                print(f"test:     {fd['test']}")
                print(f"expected: {fd['expected']}")
                print(f"actual:   {fd['actual']}")
                if fd["body"]:
                    print(f"body:     {fd['body']}")
                print("-" * 70)
