"""P7 — Self-Approval Integration Test (P3+P4+P5+P6 end-to-end). Report only — cleans up after."""

from __future__ import annotations
import subprocess, json, base64, uuid as _uuid, sys, io

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
        env={**__import__("os").environ, **PGPASS},
    )
    return r.stdout.strip(), r.stderr.strip()


# ════════════════════════════════════════════════════════════════════════
# SETUP
# ════════════════════════════════════════════════════════════════════════
print("\n" + "#" * 70)
print("# SETUP — P7 Integration Test tenant")
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
        "name": "P7 Integration Test",
        "slug": "p7-test",
        "organisation_type": "PRODUCER",
        "default_locale": "en",
        "admin_name": "P7 Admin",
        "admin_email": "admin@p7-test.com",
        "admin_password": "P7Test@2026",
    },
)
TENANT_ID = d.get("data", {}).get("id", "")
print(f"SETUP — Create tenant: HTTP {code}  tenant_id={TENANT_ID}")
if not TENANT_ID:
    print(f"FATAL: tenant creation failed: {json.dumps(d)[:400]}")
    raise SystemExit(1)

# Create TA admin user explicitly (admin_* fields on tenant create are ignored)
code, d = curl(
    "POST",
    f"/tenants/{TENANT_ID}/users",
    SA_JWT,
    {
        "name": "P7 Admin",
        "email": "admin@p7-test.com",
        "password": "P7Test@2026",
        "system_role": "TA",
    },
)
print(f"SETUP — Create TA user: HTTP {code}")

TA_JWT, ta_c = get_jwt("admin@p7-test.com", "P7Test@2026")
print(f"SETUP — TA login: role={ta_c.get('role')}  must_reset={ta_c is not None}")

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

# Nodes: HQ -> Region -> WH ; plus WH2 (sibling of WH) for SISTER test
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
code, d = curl(
    "POST",
    f"/tenants/{TENANT_ID}/nodes",
    TA_JWT,
    {
        "name": "WH2",
        "level_number": 3,
        "parent_node_id": REGION_ID,
        "is_stock_holding": True,
    },
)
WH2_ID = d.get("data", {}).get("id", "")
print(
    f"SETUP — Nodes: HQ={HQ_ID[:8]}  Region={REGION_ID[:8]}  WH={WH_ID[:8]}  WH2={WH2_ID[:8]}"
)

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
code, d = curl(
    "POST",
    f"/tenants/{TENANT_ID}/nodes/{WH2_ID}/positions",
    TA_JWT,
    {
        "title": "Store Manager 2",
        "role_code": "WM",
        "reports_to_position_id": RM_POS_ID,
    },
)
WM2_POS_ID = d.get("data", {}).get("id", "")
print(
    f"SETUP — Positions: GM={GM_POS_ID[:8]}  RM={RM_POS_ID[:8]}  WM={WM_POS_ID[:8]}  WM2={WM2_POS_ID[:8]}"
)

# Users
code, d = curl(
    "POST",
    f"/tenants/{TENANT_ID}/users",
    TA_JWT,
    {
        "name": "GM User",
        "email": "gm@p7-test.com",
        "password": "P7Gm@2026",
        "position_id": GM_POS_ID,
    },
)
code, d = curl(
    "POST",
    f"/tenants/{TENANT_ID}/users",
    TA_JWT,
    {
        "name": "RM User",
        "email": "rm@p7-test.com",
        "password": "P7Rm@2026",
        "position_id": RM_POS_ID,
    },
)
code, d = curl(
    "POST",
    f"/tenants/{TENANT_ID}/users",
    TA_JWT,
    {
        "name": "WM User",
        "email": "wm@p7-test.com",
        "password": "P7Wm@2026",
        "position_id": WM_POS_ID,
    },
)
code, d = curl(
    "POST",
    f"/tenants/{TENANT_ID}/users",
    TA_JWT,
    {
        "name": "WM2 User",
        "email": "wm2@p7-test.com",
        "password": "P7Wm2@2026",
        "position_id": WM2_POS_ID,
    },
)
print("SETUP — Users created: gm, rm, wm, wm2")

GM_JWT, gm_c = get_jwt("gm@p7-test.com", "P7Gm@2026")
RM_JWT, rm_c = get_jwt("rm@p7-test.com", "P7Rm@2026")
WM_JWT, wm_c = get_jwt("wm@p7-test.com", "P7Wm@2026")
WM2_JWT, wm2_c = get_jwt("wm2@p7-test.com", "P7Wm2@2026")
print(
    f"SETUP — JWTs: GM(role={gm_c.get('role')},lvl={gm_c.get('level_number')}) "
    f"RM(role={rm_c.get('role')},lvl={rm_c.get('level_number')}) "
    f"WM(role={wm_c.get('role')},lvl={wm_c.get('level_number')}) "
    f"WM2(role={wm2_c.get('role')},lvl={wm2_c.get('level_number')})"
)

# Transfer types
PULL_LEVELS = [
    {"level_number": 1, "can_initiate": False, "can_receive": False},
    {"level_number": 2, "can_initiate": False, "can_receive": True},
    {"level_number": 3, "can_initiate": True, "can_receive": True},
]
PUSH_LEVELS = [
    {"level_number": 1, "can_initiate": True, "can_receive": False},
    {"level_number": 2, "can_initiate": True, "can_receive": True},
    {"level_number": 3, "can_initiate": False, "can_receive": True},
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
        {
            "underlying_type": "PUSH",
            "display_name": "Stock Dispatch",
            "description": "HQ/Region pushes stock",
            "is_active": True,
            "sort_order": 2,
            "level_permissions": PUSH_LEVELS,
        },
    ],
)
saved = d.get("data", [])
PULL_CFG_ID = next((t["id"] for t in saved if t.get("underlying_type") == "PULL"), "")
PUSH_CFG_ID = next((t["id"] for t in saved if t.get("underlying_type") == "PUSH"), "")
print(
    f"SETUP — Transfer types configured: HTTP {code}  PULL={PULL_CFG_ID[:8]}  PUSH={PUSH_CFG_ID[:8]}"
)

# Transfer approval rules
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
        {
            "transfer_type_config_id": PUSH_CFG_ID,
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
                    "resolution": "destination_parent_node",
                    "execution_mode": "SEQUENTIAL",
                    "sla_hours": 24,
                }
            ],
        },
    ],
)
print(f"SETUP — Transfer approval rules: HTTP {code}  rules={len(d.get('data', []))}")

# Self-approval policies
code, d = curl(
    "PUT",
    f"/tenants/{TENANT_ID}/self-approval-policies",
    TA_JWT,
    [
        {
            "role_code": "WM",
            "level_number": 3,
            "transfer_types": ["PULL", "PUSH"],
            "threshold_type": "QUANTITY",
            "qty_limit": 100,
            "is_active": True,
        },
        {
            "role_code": "NM",
            "level_number": 1,
            "transfer_types": ["PUSH"],
            "threshold_type": "VALUE",
            "value_limit": 5000,
            "is_active": True,
        },
    ],
)
print(f"SETUP — Self-approval policies: HTTP {code}  saved={len(d.get('data', []))}")

# Adjustment approval rules
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
        {
            "role_code": "WM",
            "level_number": 3,
            "mode": "PER_CODE",
            "reason_code": "THEFT",
            "threshold_type": "QUANTITY",
            "qty_limit": 0,
            "approver_role_code": "NM",
            "priority": 1,
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
        "name": "P7 Test Item",
        "type_code": "P7T",
        "unit": "KG",
        "units_per_package": 1,
        "sku_override": "P7T-001",
        "unit_price": 100.00,
        "currency": "ETB",
    },
)
PRODUCT_ID = d.get("data", {}).get("id", "")
print(
    f"SETUP — Product created: HTTP {code}  product_id={PRODUCT_ID[:8] if PRODUCT_ID else 'MISSING'}  "
    f"unit_price={d.get('data', {}).get('unit_price')}"
)

# Opening balances — receive at HQ (2000) and WH (500), via GM/WM JWTs
ik1 = f"p7-ob-hq-{_uuid.uuid4()}"
code, d = curl(
    "POST",
    "/inventory/receive/",
    GM_JWT,
    {
        "product_id": PRODUCT_ID,
        "warehouse_id": HQ_ID,
        "quantity": 2000,
        "source": "OPENING_BALANCE",
        "idempotency_key": ik1,
    },
)
print(
    f"SETUP — Receive 2000 @ HQ: HTTP {code}  tx={d.get('data', {}).get('transaction_id', '')[:8]}"
)

ik2 = f"p7-ob-wh-{_uuid.uuid4()}"
code, d = curl(
    "POST",
    "/inventory/receive/",
    WM_JWT,
    {
        "product_id": PRODUCT_ID,
        "warehouse_id": WH_ID,
        "quantity": 500,
        "source": "OPENING_BALANCE",
        "idempotency_key": ik2,
    },
)
print(
    f"SETUP — Receive 500 @ WH: HTTP {code}  tx={d.get('data', {}).get('transaction_id', '')[:8]}"
)

print(f"\nSETUP COMPLETE — TENANT_ID={TENANT_ID}  PRODUCT_ID={PRODUCT_ID}")
print(f"   HQ={HQ_ID}  Region={REGION_ID}  WH={WH_ID}  WH2={WH2_ID}")


# ════════════════════════════════════════════════════════════════════════
# TRANSFER TESTS
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# TRANSFER TESTS")
print("#" * 70)

# ── T1 — PULL within WM self-approval limit (qty=80, limit=100) ──────────
print("\n" + "-" * 60)
print("T1 — PULL within WM self-approval limit (qty=80)")
print("-" * 60)

ik = f"p7-t1-{_uuid.uuid4()}"
code, d = curl(
    "POST",
    "/inventory/transfers/",
    WM_JWT,
    {
        "transfer_type": "PULL",
        "from_warehouse_id": HQ_ID,
        "to_warehouse_id": WH_ID,
        "lines": [{"product_id": PRODUCT_ID, "quantity": 80}],
        "notes": "T1 within limit",
    },
)
T1_ID = d.get("data", {}).get("transfer_id", "")
report(
    "T1.1 WM creates PULL qty=80",
    code,
    d,
    201,
    f"transfer_id={T1_ID[:8] if T1_ID else 'NONE'}  status={d.get('data', {}).get('status')}",
)

if T1_ID:
    code, d = curl("POST", f"/inventory/transfers/{T1_ID}/submit", WM_JWT)
    t1_status = d.get("data", {}).get("status", "")
    t1_self_approved = d.get("data", {}).get("is_self_approved")
    ok121 = code == 200 and t1_status == "APPROVED"
    report(
        "T1.2a WM submits → APPROVED (skips review/approval)",
        code,
        d,
        200,
        f"status={t1_status}  is_self_approved={t1_self_approved}",
    )
    results["T1.2b is_self_approved=true on submit response"] = t1_self_approved is True
    print(
        f"   {'OK' if t1_self_approved is True else 'XX'} T1.2b is_self_approved=true on submit response  "
        f"[{'PASS' if t1_self_approved is True else 'FAIL'}]  -> {t1_self_approved}"
    )

    hq_stock = stock_for(GM_JWT, PRODUCT_ID, HQ_ID)
    hq_onhand = float(hq_stock.get("current_stock", -1))
    hq_pending = float(hq_stock.get("pending_out_qty", -1))
    ok_oh = abs(hq_onhand - 1920) < 0.001
    ok_res = abs(hq_pending - 0) < 0.001
    results["T1.2c HQ OnHand=1920 after self-approve"] = ok_oh
    results["T1.2d HQ Reserved/pending_out=0"] = ok_res
    print(
        f"   {'OK' if ok_oh else 'XX'} T1.2c HQ OnHand=1920  -> actual={hq_onhand}  [{'PASS' if ok_oh else 'FAIL'}]"
    )
    print(
        f"   {'OK' if ok_res else 'XX'} T1.2d HQ Reserved=0  -> actual={hq_pending}  [{'PASS' if ok_res else 'FAIL'}]"
    )

    code, d = curl("GET", f"/inventory/transfers/{T1_ID}", WM_JWT)
    get_self_approved = d.get("data", {}).get("is_self_approved")
    ok_get = code == 200 and get_self_approved is True
    results["T1.3 GET /transfers/{id} is_self_approved=true"] = ok_get
    print(
        f"\n{'=' * 60}\n{'OK' if ok_get else 'XX'} T1.3 GET transfer shows is_self_approved=true  ->  HTTP {code}  "
        f"is_self_approved={get_self_approved}  [{'PASS' if ok_get else 'FAIL'}]"
    )

    code, d = curl(
        "GET", f"/inventory/audit-log/?action=transfer:self_approved", GM_JWT
    )
    logs = d.get("data", [])
    found_log = any(str(l.get("resource_id", "")) == T1_ID for l in logs)
    ok_audit = code == 200 and found_log
    results["T1.4 audit log transfer:self_approved exists"] = ok_audit
    print(
        f"\n{'=' * 60}\n{'OK' if ok_audit else 'XX'} T1.4 Audit log transfer:self_approved entry exists  ->  HTTP {code}  "
        f"matches={found_log}  total_entries={len(logs)}  [{'PASS' if ok_audit else 'FAIL'}]"
    )

    code, d = curl(
        "PATCH", f"/inventory/transfers/{T1_ID}", GM_JWT, {"next_status": "ISSUED"}
    )
    t1_status = d.get("data", {}).get("status", "")
    report(
        "T1.5 GM (source/HQ mgr) issues → ISSUED", code, d, 200, f"status={t1_status}"
    )

    code, d = curl(
        "PATCH", f"/inventory/transfers/{T1_ID}", GM_JWT, {"next_status": "IN_TRANSIT"}
    )
    t1_status = d.get("data", {}).get("status", "")
    report("T1.6 GM dispatches → IN_TRANSIT", code, d, 200, f"status={t1_status}")

    code, d = curl("POST", f"/inventory/transfers/{T1_ID}/receive", WM_JWT)
    t1_status = d.get("data", {}).get("status", "")
    ok17 = report("T1.7a WM receives → RECEIVED", code, d, 200, f"status={t1_status}")

    wh_stock = stock_for(WM_JWT, PRODUCT_ID, WH_ID)
    wh_onhand = float(wh_stock.get("current_stock", -1))
    ok_wh = abs(wh_onhand - 580) < 0.001
    results["T1.7b WH OnHand=580 after receive"] = ok_wh
    print(
        f"   {'OK' if ok_wh else 'XX'} T1.7b WH OnHand=580 (500+80)  -> actual={wh_onhand}  [{'PASS' if ok_wh else 'FAIL'}]"
    )
else:
    for k in [
        "T1.2a WM submits → APPROVED (skips review/approval)",
        "T1.2b is_self_approved=true on submit response",
        "T1.2c HQ OnHand=1920 after self-approve",
        "T1.2d HQ Reserved/pending_out=0",
        "T1.3 GET /transfers/{id} is_self_approved=true",
        "T1.4 audit log transfer:self_approved exists",
        "T1.5 GM (source/HQ mgr) issues → ISSUED",
        "T1.6 GM dispatches → IN_TRANSIT",
        "T1.7a WM receives → RECEIVED",
        "T1.7b WH OnHand=580 after receive",
    ]:
        results[k] = False
    print("XX T1 — SKIPPED (transfer creation failed)")


# ── T2 — PULL exceeds WM self-approval limit (qty=150) ───────────────────
print("\n" + "-" * 60)
print("T2 — PULL exceeds WM self-approval limit (qty=150)")
print("-" * 60)

code, d = curl(
    "POST",
    "/inventory/transfers/",
    WM_JWT,
    {
        "transfer_type": "PULL",
        "from_warehouse_id": HQ_ID,
        "to_warehouse_id": WH_ID,
        "lines": [{"product_id": PRODUCT_ID, "quantity": 150}],
        "notes": "T2 over limit",
    },
)
T2_ID = d.get("data", {}).get("transfer_id", "")
report(
    "T2.1 WM creates PULL qty=150",
    code,
    d,
    201,
    f"transfer_id={T2_ID[:8] if T2_ID else 'NONE'}  status={d.get('data', {}).get('status')}",
)

if T2_ID:
    code, d = curl("POST", f"/inventory/transfers/{T2_ID}/submit", WM_JWT)
    t2_status = d.get("data", {}).get("status", "")
    t2_self_approved = d.get("data", {}).get("is_self_approved")
    ok221 = code == 200 and t2_status == "PENDING_REVIEW"
    report(
        "T2.2a WM submits → PENDING_REVIEW (over limit)",
        code,
        d,
        200,
        f"status={t2_status}",
    )
    results["T2.2b is_self_approved=false"] = (
        t2_self_approved is False or t2_self_approved is None
    )
    print(
        f"   {'OK' if (t2_self_approved in (False, None)) else 'XX'} T2.2b is_self_approved=false  -> {t2_self_approved}  "
        f"[{'PASS' if (t2_self_approved in (False, None)) else 'FAIL'}]"
    )

    hq_stock = stock_for(GM_JWT, PRODUCT_ID, HQ_ID)
    hq_pending = float(hq_stock.get("pending_out_qty", -1))
    ok_res0 = abs(hq_pending - 0) < 0.001
    results["T2.2c HQ Reserved=0 at PENDING_REVIEW"] = ok_res0
    print(
        f"   {'OK' if ok_res0 else 'XX'} T2.2c HQ Reserved=0 (no reservation yet)  -> actual={hq_pending}  "
        f"[{'PASS' if ok_res0 else 'FAIL'}]"
    )

    code, d = curl("POST", f"/inventory/transfers/{T2_ID}/review", RM_JWT)
    t2_status = d.get("data", {}).get("status", "")
    report("T2.3a RM reviews → PENDING_APPROVAL", code, d, 200, f"status={t2_status}")

    hq_stock = stock_for(GM_JWT, PRODUCT_ID, HQ_ID)
    hq_pending = float(hq_stock.get("pending_out_qty", -1))
    ok_res150 = abs(hq_pending - 150) < 0.001
    results["T2.3b HQ Reserved=150 at PENDING_APPROVAL"] = ok_res150
    print(
        f"   {'OK' if ok_res150 else 'XX'} T2.3b HQ Reserved=150  -> actual={hq_pending}  [{'PASS' if ok_res150 else 'FAIL'}]"
    )

    code, d = curl("GET", f"/inventory/transfers/{T2_ID}/approval-info", RM_JWT)
    info = d.get("data", {})
    can_approve = info.get("can_approve")
    pos_title = info.get("current_approver_position_title")
    ok24 = code == 200 and can_approve is True
    results["T2.4 RM is approver, can_approve=true"] = ok24
    print(
        f"\n{'=' * 60}\n{'OK' if ok24 else 'XX'} T2.4 approval-info: RM is approver, can_approve=true  ->  HTTP {code}  "
        f"position={pos_title!r}  can_approve={can_approve}  [{'PASS' if ok24 else 'FAIL'}]"
    )

    code, d = curl("POST", f"/inventory/transfers/{T2_ID}/approve", RM_JWT)
    t2_status = d.get("data", {}).get("status", "")
    report("T2.5 RM approves → APPROVED", code, d, 200, f"status={t2_status}")

    code, d = curl(
        "PATCH", f"/inventory/transfers/{T2_ID}", GM_JWT, {"next_status": "ISSUED"}
    )
    t2_status = d.get("data", {}).get("status", "")
    report("T2.6 GM issues → ISSUED", code, d, 200, f"status={t2_status}")

    code, d = curl(
        "PATCH", f"/inventory/transfers/{T2_ID}", GM_JWT, {"next_status": "IN_TRANSIT"}
    )
    t2_status = d.get("data", {}).get("status", "")
    report("T2.7 GM dispatches → IN_TRANSIT", code, d, 200, f"status={t2_status}")

    code, d = curl("POST", f"/inventory/transfers/{T2_ID}/receive", WM_JWT)
    t2_status = d.get("data", {}).get("status", "")
    report("T2.8a WM receives → RECEIVED", code, d, 200, f"status={t2_status}")

    wh_stock = stock_for(WM_JWT, PRODUCT_ID, WH_ID)
    wh_onhand = float(wh_stock.get("current_stock", -1))
    ok_wh2 = abs(wh_onhand - 730) < 0.001
    results["T2.8b WH OnHand=730 after receive"] = ok_wh2
    print(
        f"   {'OK' if ok_wh2 else 'XX'} T2.8b WH OnHand=730 (580+150)  -> actual={wh_onhand}  [{'PASS' if ok_wh2 else 'FAIL'}]"
    )
else:
    for k in [
        "T2.2a WM submits → PENDING_REVIEW (over limit)",
        "T2.2b is_self_approved=false",
        "T2.2c HQ Reserved=0 at PENDING_REVIEW",
        "T2.3a RM reviews → PENDING_APPROVAL",
        "T2.3b HQ Reserved=150 at PENDING_APPROVAL",
        "T2.4 RM is approver, can_approve=true",
        "T2.5 RM approves → APPROVED",
        "T2.6 GM issues → ISSUED",
        "T2.7 GM dispatches → IN_TRANSIT",
        "T2.8a WM receives → RECEIVED",
        "T2.8b WH OnHand=730 after receive",
    ]:
        results[k] = False
    print("XX T2 — SKIPPED (transfer creation failed)")


# ── T3 — PUSH within NM (GM) self-approval value limit (qty=40, value=4000) ──
print("\n" + "-" * 60)
print("T3 — PUSH within NM self-approval value limit (qty=40, value=4000 ETB)")
print("-" * 60)

hq_before = stock_for(GM_JWT, PRODUCT_ID, HQ_ID)
hq_onhand_before_t3 = float(hq_before.get("current_stock", -1))

code, d = curl(
    "POST",
    "/inventory/transfers/",
    GM_JWT,
    {
        "transfer_type": "PUSH",
        "from_warehouse_id": HQ_ID,
        "to_warehouse_id": WH_ID,
        "lines": [{"product_id": PRODUCT_ID, "quantity": 40}],
        "notes": "T3 within value limit",
    },
)
T3_ID = d.get("data", {}).get("transfer_id", "")
report(
    "T3.1 GM creates PUSH qty=40 (value=4000)",
    code,
    d,
    201,
    f"transfer_id={T3_ID[:8] if T3_ID else 'NONE'}  total_value={d.get('data', {}).get('total_value')}",
)

if T3_ID:
    code, d = curl("POST", f"/inventory/transfers/{T3_ID}/submit", GM_JWT)
    t3_status = d.get("data", {}).get("status", "")
    t3_self_approved = d.get("data", {}).get("is_self_approved")
    ok321 = code == 200 and t3_status == "APPROVED"
    report(
        "T3.2a GM submits → APPROVED directly",
        code,
        d,
        200,
        f"status={t3_status}  is_self_approved={t3_self_approved}",
    )
    results["T3.2b is_self_approved=true"] = t3_self_approved is True
    print(
        f"   {'OK' if t3_self_approved is True else 'XX'} T3.2b is_self_approved=true  -> {t3_self_approved}  "
        f"[{'PASS' if t3_self_approved is True else 'FAIL'}]"
    )

    hq_after = stock_for(GM_JWT, PRODUCT_ID, HQ_ID)
    hq_onhand_after = float(hq_after.get("current_stock", -1))
    ok_delta = abs((hq_onhand_before_t3 - hq_onhand_after) - 40) < 0.001
    results["T3.2c HQ OnHand reduced by 40"] = ok_delta
    print(
        f"   {'OK' if ok_delta else 'XX'} T3.2c HQ OnHand reduced by 40  -> before={hq_onhand_before_t3}  "
        f"after={hq_onhand_after}  delta={hq_onhand_before_t3 - hq_onhand_after}  [{'PASS' if ok_delta else 'FAIL'}]"
    )
else:
    for k in [
        "T3.2a GM submits → APPROVED directly",
        "T3.2b is_self_approved=true",
        "T3.2c HQ OnHand reduced by 40",
    ]:
        results[k] = False
    print("XX T3 — SKIPPED (transfer creation failed)")


# ── T4 — PUSH exceeds NM (GM) value limit (qty=60, value=6000) ───────────
print("\n" + "-" * 60)
print("T4 — PUSH exceeds NM self-approval value limit (qty=60, value=6000 ETB)")
print("-" * 60)

code, d = curl(
    "POST",
    "/inventory/transfers/",
    GM_JWT,
    {
        "transfer_type": "PUSH",
        "from_warehouse_id": HQ_ID,
        "to_warehouse_id": WH_ID,
        "lines": [{"product_id": PRODUCT_ID, "quantity": 60}],
        "notes": "T4 over value limit",
    },
)
T4_ID = d.get("data", {}).get("transfer_id", "")
report(
    "T4.1 GM creates PUSH qty=60 (value=6000)",
    code,
    d,
    201,
    f"transfer_id={T4_ID[:8] if T4_ID else 'NONE'}  total_value={d.get('data', {}).get('total_value')}",
)

if T4_ID:
    code, d = curl("POST", f"/inventory/transfers/{T4_ID}/submit", GM_JWT)
    t4_status = d.get("data", {}).get("status", "")
    t4_self_approved = d.get("data", {}).get("is_self_approved")
    ok421 = code == 200 and t4_status == "PENDING_APPROVAL"
    report(
        "T4.2a GM submits → PENDING_APPROVAL (over value limit)",
        code,
        d,
        200,
        f"status={t4_status}  is_self_approved={t4_self_approved}",
    )
    results["T4.2b is_self_approved=false"] = t4_self_approved in (False, None)
    print(
        f"   {'OK' if (t4_self_approved in (False, None)) else 'XX'} T4.2b is_self_approved=false  -> {t4_self_approved}  "
        f"[{'PASS' if (t4_self_approved in (False, None)) else 'FAIL'}]"
    )
else:
    for k in [
        "T4.2a GM submits → PENDING_APPROVAL (over value limit)",
        "T4.2b is_self_approved=false",
    ]:
        results[k] = False
    print("XX T4 — SKIPPED (transfer creation failed)")


# ── T5 — SISTER not covered by self-approval policy ──────────────────────
print("\n" + "-" * 60)
print("T5 — SISTER excluded from WM self-approval policy (PULL+PUSH only)")
print("-" * 60)

code, d = curl(
    "POST",
    "/inventory/transfers/",
    WM_JWT,
    {
        "transfer_type": "SISTER",
        "from_warehouse_id": WH_ID,
        "to_warehouse_id": WH2_ID,
        "lines": [{"product_id": PRODUCT_ID, "quantity": 20}],
        "notes": "T5 sister excluded",
    },
)
T5_ID = d.get("data", {}).get("transfer_id", "")
report(
    "T5.1 WM creates SISTER qty=20",
    code,
    d,
    201,
    f"transfer_id={T5_ID[:8] if T5_ID else 'NONE'}  status={d.get('data', {}).get('status')}",
)

if T5_ID:
    code, d = curl("POST", f"/inventory/transfers/{T5_ID}/submit", WM_JWT)
    t5_status = d.get("data", {}).get("status", "")
    t5_self_approved = d.get("data", {}).get("is_self_approved")
    ok521 = code == 200 and t5_status == "PENDING_SOURCE_CONFIRM"
    report(
        "T5.2a WM submits → PENDING_SOURCE_CONFIRM (no self-approval for SISTER)",
        code,
        d,
        200,
        f"status={t5_status}  is_self_approved={t5_self_approved}",
    )
    results["T5.2b is_self_approved=false"] = t5_self_approved in (False, None)
    print(
        f"   {'OK' if (t5_self_approved in (False, None)) else 'XX'} T5.2b is_self_approved=false  -> {t5_self_approved}  "
        f"[{'PASS' if (t5_self_approved in (False, None)) else 'FAIL'}]"
    )
else:
    for k in [
        "T5.2a WM submits → PENDING_SOURCE_CONFIRM (no self-approval for SISTER)",
        "T5.2b is_self_approved=false",
    ]:
        results[k] = False
    print("XX T5 — SKIPPED (transfer creation failed)")


# ════════════════════════════════════════════════════════════════════════
# ADJUSTMENT TESTS
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# ADJUSTMENT TESTS")
print("#" * 70)


def create_adjustment(jwt, qty_delta, reason_code, label):
    ik = f"p7-adj-{_uuid.uuid4()}"
    c, dd = curl(
        "POST",
        "/inventory/adjustments/",
        jwt,
        {
            "warehouse_id": WH_ID,
            "product_id": PRODUCT_ID,
            "quantity_delta": qty_delta,
            "reason_code": reason_code,
            "idempotency_key": ik,
            "notes": label,
        },
    )
    return c, dd, dd.get("data", {}).get("adjustment_id", "")


# ── A1 — DAMAGE -30 within WM self-approve limit (50) ────────────────────
print("\n" + "-" * 60)
print("A1 — Adjustment within WM self-approval (DAMAGE -30, limit=50)")
print("-" * 60)

wh_before_a1 = stock_for(WM_JWT, PRODUCT_ID, WH_ID)
wh_onhand_before_a1 = float(wh_before_a1.get("current_stock", -1))

code, d, A1_ID = create_adjustment(WM_JWT, -30, "DAMAGE", "A1 within limit")
report(
    "A1.1 WM creates adjustment DAMAGE -30",
    code,
    d,
    201,
    f"adjustment_id={A1_ID[:8] if A1_ID else 'NONE'}  status={d.get('data', {}).get('status')}",
)

if A1_ID:
    code, d = curl("POST", f"/inventory/adjustments/{A1_ID}/submit", WM_JWT)
    a1_status = d.get("data", {}).get("status", "")
    a1_self_approved = d.get("data", {}).get("is_self_approved")
    a1_total_value = d.get("data", {}).get("total_value")
    ok112 = code == 200 and a1_status == "POSTED"
    report(
        "A1.2a WM submits → POSTED directly",
        code,
        d,
        200,
        f"status={a1_status}  is_self_approved={a1_self_approved}  total_value={a1_total_value}",
    )
    results["A1.2b is_self_approved=true"] = a1_self_approved is True
    print(
        f"   {'OK' if a1_self_approved is True else 'XX'} A1.2b is_self_approved=true  -> {a1_self_approved}  "
        f"[{'PASS' if a1_self_approved is True else 'FAIL'}]"
    )

    wh_after_a1 = stock_for(WM_JWT, PRODUCT_ID, WH_ID)
    wh_onhand_after_a1 = float(wh_after_a1.get("current_stock", -1))
    ok_delta_a1 = abs((wh_onhand_before_a1 - wh_onhand_after_a1) - 30) < 0.001
    results["A1.2c WH OnHand reduced by 30"] = ok_delta_a1
    print(
        f"   {'OK' if ok_delta_a1 else 'XX'} A1.2c WH OnHand reduced by 30  -> before={wh_onhand_before_a1}  "
        f"after={wh_onhand_after_a1}  [{'PASS' if ok_delta_a1 else 'FAIL'}]"
    )

    ok_tv = a1_total_value is not None and abs(float(a1_total_value) - 3000) < 0.001
    results["A1.2d total_value=3000 (30×100)"] = ok_tv
    print(
        f"   {'OK' if ok_tv else 'XX'} A1.2d total_value=3000 (30×100)  -> actual={a1_total_value}  "
        f"[{'PASS' if ok_tv else 'FAIL'}]"
    )

    code, d = curl(
        "GET", f"/inventory/audit-log/?action=adjustment:self_approved", GM_JWT
    )
    logs = d.get("data", [])
    found_log_a1 = any(str(l.get("resource_id", "")) == A1_ID for l in logs)
    ok_audit_a1 = code == 200 and found_log_a1
    results["A1.3 audit log adjustment:self_approved exists"] = ok_audit_a1
    print(
        f"\n{'=' * 60}\n{'OK' if ok_audit_a1 else 'XX'} A1.3 Audit log adjustment:self_approved entry exists  ->  HTTP {code}  "
        f"matches={found_log_a1}  total_entries={len(logs)}  [{'PASS' if ok_audit_a1 else 'FAIL'}]"
    )
else:
    for k in [
        "A1.2a WM submits → POSTED directly",
        "A1.2b is_self_approved=true",
        "A1.2c WH OnHand reduced by 30",
        "A1.2d total_value=3000 (30×100)",
        "A1.3 audit log adjustment:self_approved exists",
    ]:
        results[k] = False
    print("XX A1 — SKIPPED (adjustment creation failed)")


# ── A2 — EXPIRY -60 exceeds WM self-approve limit (50) ───────────────────
print("\n" + "-" * 60)
print("A2 — Adjustment exceeds WM self-approval (EXPIRY -60, limit=50)")
print("-" * 60)

code, d, A2_ID = create_adjustment(WM_JWT, -60, "EXPIRY", "A2 over limit")
report(
    "A2.1 WM creates adjustment EXPIRY -60",
    code,
    d,
    201,
    f"adjustment_id={A2_ID[:8] if A2_ID else 'NONE'}  status={d.get('data', {}).get('status')}",
)

if A2_ID:
    code, d = curl("POST", f"/inventory/adjustments/{A2_ID}/submit", WM_JWT)
    a2_status = d.get("data", {}).get("status", "")
    a2_self_approved = d.get("data", {}).get("is_self_approved")
    ok221a = code == 200 and a2_status == "PENDING_APPROVAL"
    report(
        "A2.2a WM submits → PENDING_APPROVAL (over limit)",
        code,
        d,
        200,
        f"status={a2_status}  is_self_approved={a2_self_approved}",
    )
    results["A2.2b is_self_approved=false"] = a2_self_approved in (False, None)
    print(
        f"   {'OK' if (a2_self_approved in (False, None)) else 'XX'} A2.2b is_self_approved=false  -> {a2_self_approved}  "
        f"[{'PASS' if (a2_self_approved in (False, None)) else 'FAIL'}]"
    )

    wh_before_a2_post = stock_for(WM_JWT, PRODUCT_ID, WH_ID)
    wh_onhand_before_a2_post = float(wh_before_a2_post.get("current_stock", -1))

    code, d = curl("POST", f"/inventory/adjustments/{A2_ID}/approve", GM_JWT)
    a2_status = d.get("data", {}).get("status", "")
    ok23 = report("A2.3a NM/GM approves → POSTED", code, d, 200, f"status={a2_status}")

    wh_after_a2 = stock_for(WM_JWT, PRODUCT_ID, WH_ID)
    wh_onhand_after_a2 = float(wh_after_a2.get("current_stock", -1))
    ok_delta_a2 = abs((wh_onhand_before_a2_post - wh_onhand_after_a2) - 60) < 0.001
    results["A2.3b WH OnHand reduced by 60"] = ok_delta_a2
    print(
        f"   {'OK' if ok_delta_a2 else 'XX'} A2.3b WH OnHand reduced by 60  -> before={wh_onhand_before_a2_post}  "
        f"after={wh_onhand_after_a2}  [{'PASS' if ok_delta_a2 else 'FAIL'}]"
    )
else:
    for k in [
        "A2.2a WM submits → PENDING_APPROVAL (over limit)",
        "A2.2b is_self_approved=false",
        "A2.3a NM/GM approves → POSTED",
        "A2.3b WH OnHand reduced by 60",
    ]:
        results[k] = False
    print("XX A2 — SKIPPED (adjustment creation failed)")


# ── A3 — THEFT always routes to NM (priority rule overrides global) ──────
print("\n" + "-" * 60)
print("A3 — THEFT always routes to NM regardless of qty (priority rule)")
print("-" * 60)

code, d, A3_ID = create_adjustment(WM_JWT, -5, "THEFT", "A3 theft routes to NM")
report(
    "A3.1 WM creates adjustment THEFT -5 (under global limit 50)",
    code,
    d,
    201,
    f"adjustment_id={A3_ID[:8] if A3_ID else 'NONE'}  status={d.get('data', {}).get('status')}",
)

if A3_ID:
    code, d = curl("POST", f"/inventory/adjustments/{A3_ID}/submit", WM_JWT)
    a3_status = d.get("data", {}).get("status", "")
    a3_self_approved = d.get("data", {}).get("is_self_approved")
    ok321a = code == 200 and a3_status == "PENDING_APPROVAL"
    report(
        "A3.2a WM submits → PENDING_APPROVAL (THEFT priority overrides GLOBAL)",
        code,
        d,
        200,
        f"status={a3_status}  is_self_approved={a3_self_approved}",
    )
    results["A3.2b is_self_approved=false"] = a3_self_approved in (False, None)
    print(
        f"   {'OK' if (a3_self_approved in (False, None)) else 'XX'} A3.2b is_self_approved=false  -> {a3_self_approved}  "
        f"[{'PASS' if (a3_self_approved in (False, None)) else 'FAIL'}]"
    )

    code, d = curl("GET", f"/inventory/adjustments/", GM_JWT)
    items = d.get("data", [])
    a3_item = next((i for i in items if i.get("adjustment_id") == A3_ID), {})
    routed_role = a3_item.get("approval_required_role")
    ok_route = routed_role == "NM"
    results["A3.3 routed to NM approver"] = ok_route
    print(
        f"\n{'=' * 60}\n{'OK' if ok_route else 'XX'} A3.3 Routed to NM approver  ->  HTTP {code}  "
        f"approval_required_role={routed_role!r}  [{'PASS' if ok_route else 'FAIL'}]"
    )
else:
    for k in [
        "A3.2a WM submits → PENDING_APPROVAL (THEFT priority overrides GLOBAL)",
        "A3.2b is_self_approved=false",
        "A3.3 routed to NM approver",
    ]:
        results[k] = False
    print("XX A3 — SKIPPED (adjustment creation failed)")


# ── A4 — Positive adjustment self-approves (COUNT_DISCREPANCY +20) ───────
print("\n" + "-" * 60)
print("A4 — Positive adjustment self-approves (COUNT_DISCREPANCY +20, limit=50)")
print("-" * 60)

wh_before_a4 = stock_for(WM_JWT, PRODUCT_ID, WH_ID)
wh_onhand_before_a4 = float(wh_before_a4.get("current_stock", -1))

code, d, A4_ID = create_adjustment(
    WM_JWT, 20, "COUNT_DISCREPANCY", "A4 positive self-approve"
)
report(
    "A4.1 WM creates adjustment COUNT_DISCREPANCY +20",
    code,
    d,
    201,
    f"adjustment_id={A4_ID[:8] if A4_ID else 'NONE'}  status={d.get('data', {}).get('status')}",
)

if A4_ID:
    code, d = curl("POST", f"/inventory/adjustments/{A4_ID}/submit", WM_JWT)
    a4_status = d.get("data", {}).get("status", "")
    a4_self_approved = d.get("data", {}).get("is_self_approved")
    ok421a = code == 200 and a4_status == "POSTED"
    report(
        "A4.2a WM submits → POSTED directly",
        code,
        d,
        200,
        f"status={a4_status}  is_self_approved={a4_self_approved}",
    )
    results["A4.2b is_self_approved=true"] = a4_self_approved is True
    print(
        f"   {'OK' if a4_self_approved is True else 'XX'} A4.2b is_self_approved=true  -> {a4_self_approved}  "
        f"[{'PASS' if a4_self_approved is True else 'FAIL'}]"
    )

    wh_after_a4 = stock_for(WM_JWT, PRODUCT_ID, WH_ID)
    wh_onhand_after_a4 = float(wh_after_a4.get("current_stock", -1))
    ok_delta_a4 = abs((wh_onhand_after_a4 - wh_onhand_before_a4) - 20) < 0.001
    results["A4.2c WH OnHand increased by 20"] = ok_delta_a4
    print(
        f"   {'OK' if ok_delta_a4 else 'XX'} A4.2c WH OnHand increased by 20  -> before={wh_onhand_before_a4}  "
        f"after={wh_onhand_after_a4}  [{'PASS' if ok_delta_a4 else 'FAIL'}]"
    )
else:
    for k in [
        "A4.2a WM submits → POSTED directly",
        "A4.2b is_self_approved=true",
        "A4.2c WH OnHand increased by 20",
    ]:
        results[k] = False
    print("XX A4 — SKIPPED (adjustment creation failed)")


# ════════════════════════════════════════════════════════════════════════
# FINAL SUMMARY
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# FINAL SUMMARY")
print("#" * 70)


def grp(prefix):
    keys = [k for k in results if k.upper().startswith(prefix.upper())]
    passed = sum(1 for k in keys if results[k])
    return passed, len(keys)


groups = [
    (
        "Transfer tests:",
        [
            ("  T1 PULL within limit:    ", "T1"),
            ("  T2 PULL over limit:      ", "T2"),
            ("  T3 PUSH value within:    ", "T3"),
            ("  T4 PUSH value over:      ", "T4"),
            ("  T5 SISTER excluded:      ", "T5"),
        ],
    ),
    (
        "Adjustment tests:",
        [
            ("  A1 Within limit -> POSTED: ", "A1"),
            ("  A2 Over limit -> route:    ", "A2"),
            ("  A3 THEFT -> NM always:     ", "A3"),
            ("  A4 Positive self-approve:  ", "A4"),
        ],
    ),
]

grand_passed = 0
grand_total = 0
for title, rows in groups:
    print(f"\n{title}")
    for label, prefix in rows:
        p, t = grp(prefix)
        grand_passed += p
        grand_total += t
        print(f"{label}{p}/{t}")

print(f"\nTOTAL: {grand_passed}/{grand_total}")

failures = [k for k, v in results.items() if not v]
if failures:
    print(f"\n{'=' * 60}")
    print(f"FAILURES ({len(failures)}):")
    for f in failures:
        print(f"  XX {f}")
else:
    print("\nAll integration tests passed.")


# ════════════════════════════════════════════════════════════════════════
# CLEANUP
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# CLEANUP")
print("#" * 70)

# Cascade delete in FK-dependency order (child tables before parent tables) —
# the tenants FK graph is mostly ON DELETE NO ACTION, so a bare DELETE FROM tenants fails.
CASCADE_TABLES = [
    # Phase 0 — no FK ties to other tenant-scoped tables
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
    # Phase 1 — leaves referencing phase-2/3 tables
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
    # Phase 2
    "positions",
    "products",
    "warehouses",
    "transfer_orders",
    "users",
    # Phase 3
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
print(f"Cascade delete (Phase 0-3 + tenants) for tenant_id={TENANT_ID}:\n{out}")
if err:
    print(f"stderr: {err}")

out, err = psql(f"SELECT count(*) FROM tenants WHERE slug = 'p7-test';")
print(f"\nVerify 0 rows remain (slug='p7-test'):\n{out}")
