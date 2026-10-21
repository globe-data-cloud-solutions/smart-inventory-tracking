"""Quick P6 verification after service restart — minimal tenant, Check 1 (transfer self-approval) + Check 2 (adjustment self-approval). Report only — cleans up after."""

from __future__ import annotations
import subprocess, json, base64, uuid as _uuid, sys, io, os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE = "http://localhost:8000/api/v1"
PGPASS = {"PGPASSWORD": "smart_local_pass"}
results: dict[str, bool] = {}


def curl(method, path, token=None, body=None):
    cmd = ["curl", "-s", "-w", "\n%{http_code}", f"{BASE}{path}"]
    if method != "GET":
        cmd += ["-X", method]
    if token:
        cmd += ["-H", f"Authorization: Bearer {token}"]
    if body is not None:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(body)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    lines = r.stdout.strip().split("\n")
    code = int(lines[-1])
    raw = "\n".join(lines[:-1])
    try:
        data = json.loads(raw)
    except Exception:
        data = {"_raw": raw}
    return code, data


def jwt_claims(token):
    try:
        p = token.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.b64decode(p))
    except Exception:
        return {}


def report(label, code, d, expect_code, extra=""):
    ok = code == expect_code
    icon = "OK" if ok else "XX"
    print(f"\n{'=' * 60}")
    print(f"{icon} {label}  ->  HTTP {code}  [{'PASS' if ok else 'FAIL'}]")
    if extra:
        print(f"   {extra}")
    if not ok:
        detail = d.get("detail", d.get("error", d.get("_raw", "")))
        print(f"   Error: {json.dumps(detail)[:300]}")
    results[label] = ok
    return ok


def get_jwt(email, pw):
    c, d = curl("POST", "/auth/token", body={"dev_email": email, "dev_password": pw})
    tok = d.get("access_token", "")
    return tok, jwt_claims(tok)


def stock_for(jwt, product_id, warehouse_id):
    c, d = curl("GET", "/inventory/analytics/stock", jwt)
    for row in d.get("data", []):
        if (
            row.get("product_id") == product_id
            and row.get("warehouse_id") == warehouse_id
        ):
            return row
    return {}


def psql(sql):
    full = (
        f"SELECT set_config('app.current_tenant_id','',false),"
        f"set_config('app.current_user_id','00000001-0000-0000-0000-000000000001',false);"
        f"{sql}"
    )
    r = subprocess.run(
        ["psql", "-U", "smart_user", "-d", "smart_dev", "-h", "127.0.0.1", "-c", full],
        capture_output=True,
        text=True,
        env={**os.environ, **PGPASS},
    )
    return r.stdout.strip(), r.stderr.strip()


# ════════════════════════════════════════════════════════════════════════
# SETUP
# ════════════════════════════════════════════════════════════════════════
print("\n" + "#" * 70)
print("# SETUP — Quick Verify tenant")
print("#" * 70)

SA_JWT, _ = get_jwt("smartadmin@smart-inventory.com", "Admin@2026")
if not SA_JWT:
    print("FATAL: cannot obtain SA JWT. Aborting.")
    raise SystemExit(1)

code, d = curl(
    "POST",
    "/tenants/",
    SA_JWT,
    {
        "name": "Quick Verify",
        "slug": "quick-verify",
        "organisation_type": "PRODUCER",
        "default_locale": "en",
        "admin_name": "QV Admin",
        "admin_email": "admin@qv-test.com",
        "admin_password": "QVTest@2026",
    },
)
TENANT_ID = d.get("data", {}).get("id", "")
print(f"SETUP — Create tenant: HTTP {code}  tenant_id={TENANT_ID}")
if not TENANT_ID:
    print(f"FATAL: tenant creation failed: {json.dumps(d)[:400]}")
    raise SystemExit(1)

code, d = curl(
    "POST",
    f"/tenants/{TENANT_ID}/users",
    SA_JWT,
    {
        "name": "QV Admin",
        "email": "admin@qv-test.com",
        "password": "QVTest@2026",
        "system_role": "TA",
    },
)
print(f"SETUP — Create TA user: HTTP {code}")

TA_JWT, ta_c = get_jwt("admin@qv-test.com", "QVTest@2026")
print(f"SETUP — TA login: role={ta_c.get('role')}")

# Hierarchy config — 3 levels
code, d = curl(
    "PUT",
    f"/tenants/{TENANT_ID}/hierarchy/config",
    TA_JWT,
    [
        {
            "level_number": 1,
            "level_name": "HQ",
            "default_role_code": "NM",
            "role_display_label": "General Manager",
            "is_stock_holding": True,
        },
        {
            "level_number": 2,
            "level_name": "Region",
            "default_role_code": "RM",
            "role_display_label": "Regional Manager",
            "is_stock_holding": True,
        },
        {
            "level_number": 3,
            "level_name": "Warehouse",
            "default_role_code": "WM",
            "role_display_label": "Store Manager",
            "is_stock_holding": True,
        },
    ],
)
print(
    f"SETUP — Hierarchy config (3 levels): HTTP {code}  saved={len(d.get('data', []))}"
)

# Nodes: HQ -> Region -> WH
code, d = curl(
    "POST",
    f"/tenants/{TENANT_ID}/nodes",
    TA_JWT,
    {"name": "HQ", "level_number": 1, "parent_node_id": None, "is_stock_holding": True},
)
HQ_ID = d.get("data", {}).get("id", "")
code, d = curl(
    "POST",
    f"/tenants/{TENANT_ID}/nodes",
    TA_JWT,
    {
        "name": "Region",
        "level_number": 2,
        "parent_node_id": HQ_ID,
        "is_stock_holding": True,
    },
)
REGION_ID = d.get("data", {}).get("id", "")
code, d = curl(
    "POST",
    f"/tenants/{TENANT_ID}/nodes",
    TA_JWT,
    {
        "name": "WH",
        "level_number": 3,
        "parent_node_id": REGION_ID,
        "is_stock_holding": True,
    },
)
WH_ID = d.get("data", {}).get("id", "")
print(f"SETUP — Nodes: HQ={HQ_ID[:8]}  Region={REGION_ID[:8]}  WH={WH_ID[:8]}")

# Positions
code, d = curl(
    "POST",
    f"/tenants/{TENANT_ID}/nodes/{HQ_ID}/positions",
    TA_JWT,
    {"title": "General Manager", "role_code": "NM"},
)
GM_POS_ID = d.get("data", {}).get("id", "")
code, d = curl(
    "POST",
    f"/tenants/{TENANT_ID}/nodes/{REGION_ID}/positions",
    TA_JWT,
    {
        "title": "Regional Manager",
        "role_code": "RM",
        "reports_to_position_id": GM_POS_ID,
    },
)
RM_POS_ID = d.get("data", {}).get("id", "")
code, d = curl(
    "POST",
    f"/tenants/{TENANT_ID}/nodes/{WH_ID}/positions",
    TA_JWT,
    {"title": "Store Manager", "role_code": "WM", "reports_to_position_id": RM_POS_ID},
)
WM_POS_ID = d.get("data", {}).get("id", "")
print(f"SETUP — Positions: GM={GM_POS_ID[:8]}  RM={RM_POS_ID[:8]}  WM={WM_POS_ID[:8]}")

# Users
curl(
    "POST",
    f"/tenants/{TENANT_ID}/users",
    TA_JWT,
    {
        "name": "GM User",
        "email": "gm@qv-test.com",
        "password": "QvGm@2026",
        "position_id": GM_POS_ID,
    },
)
curl(
    "POST",
    f"/tenants/{TENANT_ID}/users",
    TA_JWT,
    {
        "name": "RM User",
        "email": "rm@qv-test.com",
        "password": "QvRm@2026",
        "position_id": RM_POS_ID,
    },
)
curl(
    "POST",
    f"/tenants/{TENANT_ID}/users",
    TA_JWT,
    {
        "name": "WM User",
        "email": "wm@qv-test.com",
        "password": "QvWm@2026",
        "position_id": WM_POS_ID,
    },
)
print("SETUP — Users created: gm, rm, wm")

GM_JWT, gm_c = get_jwt("gm@qv-test.com", "QvGm@2026")
RM_JWT, rm_c = get_jwt("rm@qv-test.com", "QvRm@2026")
WM_JWT, wm_c = get_jwt("wm@qv-test.com", "QvWm@2026")
print(
    f"SETUP — JWTs: GM(role={gm_c.get('role')},lvl={gm_c.get('level_number')}) "
    f"RM(role={rm_c.get('role')},lvl={rm_c.get('level_number')}) "
    f"WM(role={wm_c.get('role')},lvl={wm_c.get('level_number')})"
)

# Transfer types — minimal (PULL only needed for Check 1)
PULL_LEVELS = [
    {"level_number": 1, "can_initiate": False, "can_receive": False},
    {"level_number": 2, "can_initiate": False, "can_receive": True},
    {"level_number": 3, "can_initiate": True, "can_receive": True},
]
code, d = curl(
    "PUT",
    f"/tenants/{TENANT_ID}/transfer-types",
    TA_JWT,
    [
        {
            "underlying_type": "PULL",
            "display_name": "Stock Request",
            "description": "WM requests stock",
            "is_active": True,
            "sort_order": 1,
            "level_permissions": PULL_LEVELS,
        },
    ],
)
saved = d.get("data", [])
PULL_CFG_ID = next((t["id"] for t in saved if t.get("underlying_type") == "PULL"), "")
print(f"SETUP — Transfer types configured: HTTP {code}  PULL={PULL_CFG_ID[:8]}")

# Transfer approval rule — needed so over-limit PULLs have a route (not exercised here but required by config)
code, d = curl(
    "PUT",
    f"/tenants/{TENANT_ID}/transfer-approval-rules",
    TA_JWT,
    [
        {
            "transfer_type_config_id": PULL_CFG_ID,
            "source_level": 1,
            "destination_level": 3,
            "quantity_min": 0,
            "quantity_max": None,
            "threshold_type": "QUANTITY",
            "currency": "ETB",
            "priority": 1,
            "is_active": True,
            "approval_steps": [
                {
                    "sequence": 1,
                    "position_title": "Regional Manager",
                    "resolution": "source_parent_node",
                    "execution_mode": "SEQUENTIAL",
                    "sla_hours": 24,
                }
            ],
        },
    ],
)
print(f"SETUP — Transfer approval rules: HTTP {code}  rules={len(d.get('data', []))}")

# Self-approval policy — WM / level 3 / PULL / QUANTITY <= 100
code, d = curl(
    "PUT",
    f"/tenants/{TENANT_ID}/self-approval-policies",
    TA_JWT,
    [
        {
            "role_code": "WM",
            "level_number": 3,
            "transfer_types": ["PULL"],
            "threshold_type": "QUANTITY",
            "qty_limit": 100,
            "is_active": True,
        },
    ],
)
print(f"SETUP — Self-approval policies: HTTP {code}  saved={len(d.get('data', []))}")

# Adjustment approval rule — WM / level 3 / GLOBAL / QUANTITY <= 50 / self-approve
code, d = curl(
    "PUT",
    f"/tenants/{TENANT_ID}/adjustment-approval-rules",
    TA_JWT,
    [
        {
            "role_code": "WM",
            "level_number": 3,
            "mode": "GLOBAL",
            "reason_code": None,
            "threshold_type": "QUANTITY",
            "qty_limit": 50,
            "approver_role_code": None,
            "priority": 10,
            "is_active": True,
        },
    ],
)
print(f"SETUP — Adjustment approval rules: HTTP {code}  saved={len(d.get('data', []))}")

# Product
code, d = curl(
    "POST",
    "/products/",
    TA_JWT,
    {
        "name": "QV Test Item",
        "type_code": "QVT",
        "unit": "KG",
        "units_per_package": 1,
        "sku_override": "QVT-001",
        "unit_price": 100.00,
        "currency": "ETB",
    },
)
PRODUCT_ID = d.get("data", {}).get("id", "")
print(
    f"SETUP — Product created: HTTP {code}  product_id={PRODUCT_ID[:8] if PRODUCT_ID else 'MISSING'}  "
    f"unit_price={d.get('data', {}).get('unit_price')}"
)

# Opening balances — receive at WH (500) and HQ (1000)
ik1 = f"qv-ob-wh-{_uuid.uuid4()}"
code, d = curl(
    "POST",
    "/inventory/receive/",
    WM_JWT,
    {
        "product_id": PRODUCT_ID,
        "warehouse_id": WH_ID,
        "quantity": 500,
        "source": "OPENING_BALANCE",
        "idempotency_key": ik1,
    },
)
print(
    f"SETUP — Receive 500 @ WH: HTTP {code}  tx={d.get('data', {}).get('transaction_id', '')[:8]}"
)

ik2 = f"qv-ob-hq-{_uuid.uuid4()}"
code, d = curl(
    "POST",
    "/inventory/receive/",
    GM_JWT,
    {
        "product_id": PRODUCT_ID,
        "warehouse_id": HQ_ID,
        "quantity": 1000,
        "source": "OPENING_BALANCE",
        "idempotency_key": ik2,
    },
)
print(
    f"SETUP — Receive 1000 @ HQ: HTTP {code}  tx={d.get('data', {}).get('transaction_id', '')[:8]}"
)

print(f"\nSETUP COMPLETE — TENANT_ID={TENANT_ID}  PRODUCT_ID={PRODUCT_ID}")
print(f"   HQ={HQ_ID}  Region={REGION_ID}  WH={WH_ID}")


# ════════════════════════════════════════════════════════════════════════
# CHECK 1 — P5 Transfer self-approval
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# CHECK 1 — P5 Transfer self-approval (PULL qty=80, limit=100)")
print("#" * 70)

ik = f"qv-c1-{_uuid.uuid4()}"
code, d = curl(
    "POST",
    "/inventory/transfers/",
    WM_JWT,
    {
        "transfer_type": "PULL",
        "from_warehouse_id": HQ_ID,
        "to_warehouse_id": WH_ID,
        "lines": [{"product_id": PRODUCT_ID, "quantity": 80}],
        "notes": "Check1 within limit",
    },
)
C1_ID = d.get("data", {}).get("transfer_id", "")
report(
    "C1.0 WM creates PULL qty=80",
    code,
    d,
    201,
    f"transfer_id={C1_ID[:8] if C1_ID else 'NONE'}  status={d.get('data', {}).get('status')}",
)

if C1_ID:
    code, d = curl("POST", f"/inventory/transfers/{C1_ID}/submit", WM_JWT)
    c1_status = d.get("data", {}).get("status", "")
    c1_self_approved = d.get("data", {}).get("is_self_approved")
    ok_c1a = code == 200 and c1_status == "APPROVED" and c1_self_approved is True
    report(
        "C1.1 submit -> status=APPROVED, is_self_approved=true",
        code,
        d,
        200,
        f"status={c1_status}  is_self_approved={c1_self_approved}  expected status=APPROVED is_self_approved=true",
    )
    results["C1.1 submit -> status=APPROVED, is_self_approved=true"] = ok_c1a

    hq_stock = stock_for(GM_JWT, PRODUCT_ID, HQ_ID)
    hq_onhand = float(hq_stock.get("current_stock", -1))
    ok_oh = abs(hq_onhand - 920) < 0.001
    results["C1.2 HQ OnHand=920 (1000-80)"] = ok_oh
    print(
        f"\n{'=' * 60}\n{'OK' if ok_oh else 'XX'} C1.2 HQ OnHand=920 (1000-80)  -> actual={hq_onhand}  [{'PASS' if ok_oh else 'FAIL'}]"
    )

    code, d = curl("GET", f"/inventory/transfers/{C1_ID}", WM_JWT)
    get_self_approved = d.get("data", {}).get("is_self_approved")
    ok_get = code == 200 and get_self_approved is True
    results["C1.3 GET /transfers/{id} is_self_approved=true"] = ok_get
    print(
        f"\n{'=' * 60}\n{'OK' if ok_get else 'XX'} C1.3 GET transfer shows is_self_approved=true  ->  HTTP {code}  "
        f"is_self_approved={get_self_approved}  [{'PASS' if ok_get else 'FAIL'}]"
    )

    code, d = curl("GET", f"/audit-log/?action=transfer:self_approved", GM_JWT)
    logs = d.get("data", [])
    found_log = any(str(l.get("resource_id", "")) == C1_ID for l in logs)
    ok_audit = code == 200 and found_log
    results["C1.4 audit log transfer:self_approved exists"] = ok_audit
    print(
        f"\n{'=' * 60}\n{'OK' if ok_audit else 'XX'} C1.4 Audit log transfer:self_approved entry exists  ->  HTTP {code}  "
        f"matches={found_log}  total_entries={len(logs)}  [{'PASS' if ok_audit else 'FAIL'}]"
    )
else:
    for k in [
        "C1.1 submit -> status=APPROVED, is_self_approved=true",
        "C1.2 HQ OnHand=920 (1000-80)",
        "C1.3 GET /transfers/{id} is_self_approved=true",
        "C1.4 audit log transfer:self_approved exists",
    ]:
        results[k] = False
    print("XX CHECK 1 — SKIPPED (transfer creation failed)")


# ════════════════════════════════════════════════════════════════════════
# CHECK 2 — P6 Adjustment self-approval
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# CHECK 2 — P6 Adjustment self-approval (DAMAGE -30, limit=50)")
print("#" * 70)

wh_before = stock_for(WM_JWT, PRODUCT_ID, WH_ID)
wh_onhand_before = float(wh_before.get("current_stock", -1))

ik = f"qv-adj-001-{_uuid.uuid4()}"
code, d = curl(
    "POST",
    "/inventory/adjustments/",
    WM_JWT,
    {
        "product_id": PRODUCT_ID,
        "warehouse_id": WH_ID,
        "quantity_delta": -30,
        "reason_code": "DAMAGE",
        "notes": "Quick verify test",
        "idempotency_key": ik,
    },
)
C2_ID = d.get("data", {}).get("adjustment_id", "")
report(
    "C2.0 WM creates adjustment DAMAGE -30",
    code,
    d,
    201,
    f"adjustment_id={C2_ID[:8] if C2_ID else 'NONE'}  status={d.get('data', {}).get('status')}",
)

if C2_ID:
    code, d = curl("POST", f"/inventory/adjustments/{C2_ID}/submit", WM_JWT)
    c2_status = d.get("data", {}).get("status", "")
    c2_self_approved = d.get("data", {}).get("is_self_approved")
    c2_total_value = d.get("data", {}).get("total_value")
    ok_c2a = code == 200 and c2_status == "POSTED" and c2_self_approved is True
    report(
        "C2.1 submit -> status=POSTED, is_self_approved=true",
        code,
        d,
        200,
        f"status={c2_status}  is_self_approved={c2_self_approved}  total_value={c2_total_value}  "
        f"expected status=POSTED is_self_approved=true total_value=3000",
    )
    results["C2.1 submit -> status=POSTED, is_self_approved=true"] = ok_c2a

    ok_tv = c2_total_value is not None and abs(float(c2_total_value) - 3000) < 0.001
    results["C2.2 total_value=3000 (30x100)"] = ok_tv
    print(
        f"\n{'=' * 60}\n{'OK' if ok_tv else 'XX'} C2.2 total_value=3000 (30x100)  -> actual={c2_total_value}  [{'PASS' if ok_tv else 'FAIL'}]"
    )

    wh_after = stock_for(WM_JWT, PRODUCT_ID, WH_ID)
    wh_onhand_after = float(wh_after.get("current_stock", -1))
    ok_delta = abs((wh_onhand_before - wh_onhand_after) - 30) < 0.001
    results["C2.3 WH OnHand reduced by 30"] = ok_delta
    print(
        f"\n{'=' * 60}\n{'OK' if ok_delta else 'XX'} C2.3 WH OnHand reduced by 30  -> before={wh_onhand_before}  "
        f"after={wh_onhand_after}  [{'PASS' if ok_delta else 'FAIL'}]"
    )

    code, d = curl("GET", f"/audit-log/?action=adjustment:self_approved", GM_JWT)
    logs = d.get("data", [])
    found_log2 = any(str(l.get("resource_id", "")) == C2_ID for l in logs)
    ok_audit2 = code == 200 and found_log2
    results["C2.4 audit log adjustment:self_approved exists"] = ok_audit2
    print(
        f"\n{'=' * 60}\n{'OK' if ok_audit2 else 'XX'} C2.4 Audit log adjustment:self_approved entry exists  ->  HTTP {code}  "
        f"matches={found_log2}  total_entries={len(logs)}  [{'PASS' if ok_audit2 else 'FAIL'}]"
    )
else:
    for k in [
        "C2.1 submit -> status=POSTED, is_self_approved=true",
        "C2.2 total_value=3000 (30x100)",
        "C2.3 WH OnHand reduced by 30",
        "C2.4 audit log adjustment:self_approved exists",
    ]:
        results[k] = False
    print("XX CHECK 2 — SKIPPED (adjustment creation failed)")


# ════════════════════════════════════════════════════════════════════════
# SUMMARY
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# SUMMARY")
print("#" * 70)


def grp(prefix):
    keys = [k for k in results if k.startswith(prefix)]
    passed = sum(1 for k in keys if results[k])
    return passed, len(keys)


c1p, c1n = grp("C1.")
c2p, c2n = grp("C2.")
print(f"\nCheck 1 Transfer:   {c1p}/{c1n}")
print(f"Check 2 Adjustment: {c2p}/{c2n}")
print(f"\nTOTAL: {c1p + c2p}/{c1n + c2n}")

fails = [k for k, v in results.items() if not v]
print(f"\n{'=' * 60}\nFAILURES ({len(fails)}):")
for f in fails:
    print(f"  XX {f}")


# ════════════════════════════════════════════════════════════════════════
# CLEANUP
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# CLEANUP")
print("#" * 70)

CASCADE_TABLES = [
    "adjustment_orders",
    "audit_logs",
    "count_sessions",
    "dispatch_override_logs",
    "dispatch_strategy_configs",
    "inventory_balances",
    "inventory_transactions_2026_05",
    "inventory_transactions_2026_06",
    "inventory_transactions_2026_07",
    "inventory_transactions",
    "outbox",
    "product_uoms",
    "tenant_hierarchy_config",
    "org_node_hierarchy",
    "transfer_approval_rules",
    "personnel_positions",
    "approval_rule",
    "product_approval_minimums",
    "transfer_requests",
    "transfer_order_lines",
    "transfer_type_level_permissions",
    "adjustment_approval_rules",
    "self_approval_policies",
    "positions",
    "products",
    "warehouses",
    "transfer_orders",
    "users",
    "organization_node",
    "product_brands",
    "product_categories",
    "product_packaging_types",
    "product_type_codes",
    "transfer_type_config",
]
sql_lines = [
    f"SELECT set_config('app.current_tenant_id','{TENANT_ID}',false),"
    f"set_config('app.current_user_id','00000001-0000-0000-0000-000000000001',false);"
]
for t in CASCADE_TABLES:
    sql_lines.append(f"DELETE FROM {t} WHERE tenant_id = '{TENANT_ID}';")
sql_lines.append(f"DELETE FROM tenants WHERE id = '{TENANT_ID}';")
out, err = psql(" ".join(sql_lines))
print(f"Cascade delete for tenant_id={TENANT_ID}:")
print(out)
if err:
    print(f"STDERR: {err}")

out2, _ = psql("SELECT count(*) FROM tenants WHERE slug='quick-verify';")
print(f"\nVerify 0 rows remain (slug='quick-verify'):")
print(out2)
