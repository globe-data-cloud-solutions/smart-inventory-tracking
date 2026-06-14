"""TASK 1 — Fresh repro: TA sets PULL override (ALWAYS -> RM) on an
NM-created product vs a TA-created product. Report only — cleans up after.
"""
from __future__ import annotations
import subprocess, json, base64, uuid as _uuid, sys, io, os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE = "http://localhost:8000/api/v1"
PGPASS = {"PGPASSWORD": "smart_local_pass"}


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


def get_jwt(email, pw):
    c, d = curl("POST", "/auth/token", body={"dev_email": email, "dev_password": pw})
    tok = d.get("access_token", "")
    return tok, jwt_claims(tok)


def psql(sql):
    r = subprocess.run(["psql", "-U", "smart_user", "-d", "smart_dev", "-h", "127.0.0.1",
                        "-c", sql],
                       capture_output=True, text=True, env={**os.environ, **PGPASS})
    return r.stdout.strip(), r.stderr.strip()


# ════════════════════════════════════════════════════════════════════════
# SETUP
# ════════════════════════════════════════════════════════════════════════
print("#" * 70)
print("# SETUP — NM-created-product override repro tenant")
print("#" * 70)

SA_JWT, _ = get_jwt("smartadmin@smart-inventory.com", "Admin@2026")
if not SA_JWT:
    print("FATAL: cannot obtain SA JWT. Aborting.")
    raise SystemExit(1)

code, d = curl("POST", "/tenants/", SA_JWT, {
    "name": "NM Override Test", "slug": "nm-override-test",
    "organisation_type": "PRODUCER", "default_locale": "en",
    "admin_name": "NMOT Admin", "admin_email": "admin@nm-override-test.com",
    "admin_password": "NmOver@2026",
})
TENANT_ID = d.get("data", {}).get("id", "")
print(f"SETUP — Create tenant: HTTP {code}  tenant_id={TENANT_ID}")
if not TENANT_ID:
    print(f"FATAL: tenant creation failed: {json.dumps(d)[:400]}")
    raise SystemExit(1)

code, d = curl("POST", f"/tenants/{TENANT_ID}/users", SA_JWT, {
    "name": "NMOT Admin", "email": "admin@nm-override-test.com",
    "password": "NmOver@2026", "system_role": "TA",
})
print(f"SETUP — Create TA user: HTTP {code}")

TA_JWT, ta_c = get_jwt("admin@nm-override-test.com", "NmOver@2026")
print(f"SETUP — TA login: role={ta_c.get('role')}")

code, d = curl("PUT", f"/tenants/{TENANT_ID}/hierarchy/config", TA_JWT, [
    {"level_number": 1, "level_name": "HQ", "default_role_code": "NM",
     "role_display_label": "HQ Director", "is_stock_holding": True},
    {"level_number": 2, "level_name": "Region", "default_role_code": "RM",
     "role_display_label": "Region Manager", "is_stock_holding": True},
    {"level_number": 3, "level_name": "Warehouse", "default_role_code": "WM",
     "role_display_label": "Warehouse Manager", "is_stock_holding": True},
])
print(f"SETUP — Hierarchy config (3 levels): HTTP {code}  saved={len(d.get('data', []))}")

code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes", TA_JWT,
               {"name": "HQ", "level_number": 1, "parent_node_id": None, "is_stock_holding": True})
HQ_ID = d.get("data", {}).get("id", "")
code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes", TA_JWT,
               {"name": "Region", "level_number": 2, "parent_node_id": HQ_ID, "is_stock_holding": True})
REGION_ID = d.get("data", {}).get("id", "")
code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes", TA_JWT,
               {"name": "WH", "level_number": 3, "parent_node_id": REGION_ID, "is_stock_holding": True})
WH_ID = d.get("data", {}).get("id", "")
print(f"SETUP — Nodes: HQ={HQ_ID[:8]}  Region={REGION_ID[:8]}  WH={WH_ID[:8]}")

code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes/{HQ_ID}/positions", TA_JWT,
               {"title": "HQ Director", "role_code": "NM"})
NM_POS_ID = d.get("data", {}).get("id", "")
code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes/{REGION_ID}/positions", TA_JWT,
               {"title": "Region Manager", "role_code": "RM", "reports_to_position_id": NM_POS_ID})
RM_POS_ID = d.get("data", {}).get("id", "")
code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes/{WH_ID}/positions", TA_JWT,
               {"title": "Warehouse Manager", "role_code": "WM", "reports_to_position_id": RM_POS_ID})
WM_POS_ID = d.get("data", {}).get("id", "")
print(f"SETUP — Positions: NM={NM_POS_ID[:8]}  RM={RM_POS_ID[:8]}  WM={WM_POS_ID[:8]}")

code, d = curl("POST", f"/tenants/{TENANT_ID}/users", TA_JWT,
               {"name": "HQ Director", "email": "nm@nm-override-test.com", "password": "NmOverNm@2026", "position_id": NM_POS_ID})
code, d = curl("POST", f"/tenants/{TENANT_ID}/users", TA_JWT,
               {"name": "Region Manager", "email": "rm@nm-override-test.com", "password": "NmOverRm@2026", "position_id": RM_POS_ID})
code, d = curl("POST", f"/tenants/{TENANT_ID}/users", TA_JWT,
               {"name": "Warehouse Manager", "email": "wm@nm-override-test.com", "password": "NmOverWm@2026", "position_id": WM_POS_ID})
print("SETUP — Users created: nm, rm, wm")

NM_JWT, nm_c = get_jwt("nm@nm-override-test.com", "NmOverNm@2026")
RM_JWT, rm_c = get_jwt("rm@nm-override-test.com", "NmOverRm@2026")
WM_JWT, wm_c = get_jwt("wm@nm-override-test.com", "NmOverWm@2026")
print(f"SETUP — JWTs: NM(role={nm_c.get('role')}) RM(role={rm_c.get('role')}) WM(role={wm_c.get('role')})")

PULL_LEVELS = [
    {"level_number": 1, "can_initiate": False, "can_receive": False},
    {"level_number": 2, "can_initiate": False, "can_receive": True},
    {"level_number": 3, "can_initiate": True,  "can_receive": True},
]
code, d = curl("PUT", f"/tenants/{TENANT_ID}/transfer-types", TA_JWT, [
    {"underlying_type": "PULL", "display_name": "Stock Request", "description": "WM requests stock",
     "is_active": True, "sort_order": 1, "level_permissions": PULL_LEVELS},
])
saved = d.get("data", [])
PULL_CFG_ID = next((t["id"] for t in saved if t.get("underlying_type") == "PULL"), "")
print(f"SETUP — PULL transfer type configured: HTTP {code}  PULL={PULL_CFG_ID[:8]}")

# WM self-approval policy: PULL up to qty 1000 -> WITHOUT an override, qty=500 self-approves.
code, d = curl("PUT", f"/tenants/{TENANT_ID}/self-approval-policies", TA_JWT, [
    {"role_code": "WM", "level_number": 3, "transfer_types": ["PULL"],
     "threshold_type": "EITHER", "qty_limit": 1000, "value_limit": 100000, "is_active": True},
])
print(f"SETUP — Self-approval policy (WM, PULL <= 1000 qty): HTTP {code}  saved={len(d.get('data', []))}")


# ════════════════════════════════════════════════════════════════════════
# STEP 1 — NM creates "NM-Created-Gold"
# ════════════════════════════════════════════════════════════════════════
print("\n" + "#" * 70)
print("# STEP 1 — NM creates product 'NM-Created-Gold'")
print("#" * 70)

code, d = curl("POST", "/products/", NM_JWT, {
    "name": "NM-Created-Gold", "type_code": "NMG", "unit": "EA",
    "units_per_package": 1, "sku_override": "NM-GOLD-001",
    "unit_price": 10.00, "currency": "ETB",
})
GOLD_ID = d.get("data", {}).get("id", "")
print(f"STEP1 — NM creates NM-Created-Gold: HTTP {code}  id={GOLD_ID}")
if not GOLD_ID:
    print(f"FATAL: product creation failed: {json.dumps(d)[:400]}")

# also TA-created comparison product
code, d = curl("POST", "/products/", TA_JWT, {
    "name": "TA-Created-Steel", "type_code": "TAS", "unit": "EA",
    "units_per_package": 1, "sku_override": "TA-STEEL-001",
    "unit_price": 10.00, "currency": "ETB",
})
STEEL_ID = d.get("data", {}).get("id", "")
print(f"STEP1b — TA creates TA-Created-Steel: HTTP {code}  id={STEEL_ID}")

# Confirm created_by in DB
out, _ = psql(
    f"SELECT id, name, created_by, "
    f"(SELECT system_role FROM users WHERE id = products.created_by) AS creator_role "
    f"FROM products WHERE id IN ('{GOLD_ID}','{STEEL_ID}');"
)
print(f"\nSTEP1c — products.created_by check:\n{out}")


# ════════════════════════════════════════════════════════════════════════
# STEP 2 — TA sets PULL override ALWAYS -> RM for BOTH products
# ════════════════════════════════════════════════════════════════════════
print("\n" + "#" * 70)
print("# STEP 2 — TA sets PULL override ALWAYS -> RM for both products")
print("#" * 70)

code, d = curl("PUT", f"/products/{GOLD_ID}/approval-minimums", TA_JWT, {
    "entries": [
        {"transaction_type": "PULL", "override_enabled": True, "threshold_type": "ALWAYS",
         "approver_position_id": RM_POS_ID, "note": "All PULLs of NM-Created-Gold need RM sign-off"},
    ]
})
print(f"STEP2 — TA sets override on NM-Created-Gold: HTTP {code}")
print(f"   response: {json.dumps(d.get('data', d))[:500]}")

code, d = curl("PUT", f"/products/{STEEL_ID}/approval-minimums", TA_JWT, {
    "entries": [
        {"transaction_type": "PULL", "override_enabled": True, "threshold_type": "ALWAYS",
         "approver_position_id": RM_POS_ID, "note": "All PULLs of TA-Created-Steel need RM sign-off"},
    ]
})
print(f"STEP2b — TA sets override on TA-Created-Steel: HTTP {code}")
print(f"   response: {json.dumps(d.get('data', d))[:500]}")


# ════════════════════════════════════════════════════════════════════════
# STEP 3 — Query product_approval_minimums immediately after
# ════════════════════════════════════════════════════════════════════════
print("\n" + "#" * 70)
print("# STEP 3/4/5 — Inspect product_approval_minimums rows for both products")
print("#" * 70)

out, _ = psql(
    f"SELECT product_id, transaction_type, threshold_type, qty_threshold, "
    f"value_threshold, approver_position_id, is_active, note "
    f"FROM product_approval_minimums "
    f"WHERE product_id IN ('{GOLD_ID}','{STEEL_ID}') AND transaction_type='PULL';"
)
print(f"product_approval_minimums rows:\n{out}")


# ════════════════════════════════════════════════════════════════════════
# Opening balances — receive 600 of each product at HQ (so WM can PULL 500)
# ════════════════════════════════════════════════════════════════════════
print("\n" + "#" * 70)
print("# Opening balances")
print("#" * 70)

for pid, name in [(GOLD_ID, "NM-Created-Gold"), (STEEL_ID, "TA-Created-Steel")]:
    ik = f"nmover-ob-hq-{_uuid.uuid4()}"
    code, d = curl("POST", "/inventory/receive/", NM_JWT, {
        "product_id": pid, "warehouse_id": HQ_ID, "quantity": 600,
        "source": "OPENING_BALANCE", "idempotency_key": ik,
    })
    print(f"  Receive 600 {name} @ HQ: HTTP {code}  tx={d.get('data', {}).get('transaction_id', '')[:8]}")


# ════════════════════════════════════════════════════════════════════════
# STEP 6 — WM creates PULL qty=500 for NM-Created-Gold
# ════════════════════════════════════════════════════════════════════════
print("\n" + "#" * 70)
print("# STEP 6 — WM PULL qty=500 for NM-Created-Gold (override should fire)")
print("#" * 70)

code, d = curl("POST", "/inventory/transfers/", WM_JWT, {
    "transfer_type": "PULL", "from_warehouse_id": HQ_ID, "to_warehouse_id": WH_ID,
    "lines": [{"product_id": GOLD_ID, "quantity": 500}], "notes": "Repro PULL qty=500 NM-Created-Gold",
})
GOLD_TR_ID = d.get("data", {}).get("transfer_id", "")
print(f"  Create PULL (NM-Created-Gold): HTTP {code}  transfer_id={GOLD_TR_ID}")

if GOLD_TR_ID:
    code, d = curl("POST", f"/inventory/transfers/{GOLD_TR_ID}/submit", WM_JWT)
    print(f"  Submit PULL (NM-Created-Gold): HTTP {code}")
    print(f"    status={d.get('data', {}).get('status')}  "
          f"is_self_approved={d.get('data', {}).get('is_self_approved')}")

    out, _ = psql(
        f"SELECT status, is_self_approved, product_override_applied "
        f"FROM transfer_orders WHERE id = '{GOLD_TR_ID}';"
    )
    print(f"  DB row (NM-Created-Gold transfer): {out}")


# ════════════════════════════════════════════════════════════════════════
# STEP 7 — Repeat for TA-Created-Steel
# ════════════════════════════════════════════════════════════════════════
print("\n" + "#" * 70)
print("# STEP 7 — WM PULL qty=500 for TA-Created-Steel (override should fire)")
print("#" * 70)

code, d = curl("POST", "/inventory/transfers/", WM_JWT, {
    "transfer_type": "PULL", "from_warehouse_id": HQ_ID, "to_warehouse_id": WH_ID,
    "lines": [{"product_id": STEEL_ID, "quantity": 500}], "notes": "Repro PULL qty=500 TA-Created-Steel",
})
STEEL_TR_ID = d.get("data", {}).get("transfer_id", "")
print(f"  Create PULL (TA-Created-Steel): HTTP {code}  transfer_id={STEEL_TR_ID}")

if STEEL_TR_ID:
    code, d = curl("POST", f"/inventory/transfers/{STEEL_TR_ID}/submit", WM_JWT)
    print(f"  Submit PULL (TA-Created-Steel): HTTP {code}")
    print(f"    status={d.get('data', {}).get('status')}  "
          f"is_self_approved={d.get('data', {}).get('is_self_approved')}")

    out, _ = psql(
        f"SELECT status, is_self_approved, product_override_applied "
        f"FROM transfer_orders WHERE id = '{STEEL_TR_ID}';"
    )
    print(f"  DB row (TA-Created-Steel transfer): {out}")


print(f"\n\nTENANT_ID={TENANT_ID}")
print(f"GOLD_ID={GOLD_ID}  STEEL_ID={STEEL_ID}")
print(f"GOLD_TR_ID={GOLD_TR_ID}  STEEL_TR_ID={STEEL_TR_ID}")


# ════════════════════════════════════════════════════════════════════════
# CLEANUP
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# CLEANUP")
print("#" * 70)

CASCADE_TABLES = [
    "adjustment_orders", "audit_logs", "count_sessions", "dispatch_override_logs",
    "dispatch_strategy_configs", "inventory_balances",
    "inventory_transactions_2026_05", "inventory_transactions_2026_06",
    "inventory_transactions_2026_07", "inventory_transactions",
    "outbox", "product_uoms", "tenant_hierarchy_config",
    "org_node_hierarchy", "transfer_approval_rules", "personnel_positions",
    "approval_rule", "product_approval_minimums", "transfer_requests",
    "transfer_order_lines", "transfer_type_level_permissions",
    "adjustment_approval_rules", "self_approval_policies",
    "positions", "products", "warehouses", "transfer_orders", "users",
    "organization_node", "product_brands", "product_categories",
    "product_packaging_types", "product_type_codes", "transfer_type_config",
]

sql_lines = [
    f"SELECT set_config('app.current_tenant_id','{TENANT_ID}',false),"
    f"set_config('app.current_user_id','00000001-0000-0000-0000-000000000001',false);"
]
for t in CASCADE_TABLES:
    sql_lines.append(f"DELETE FROM {t} WHERE tenant_id = '{TENANT_ID}';")
sql_lines.append(f"DELETE FROM tenants WHERE id = '{TENANT_ID}';")

r = subprocess.run(["psql", "-U", "smart_user", "-d", "smart_dev", "-h", "127.0.0.1", "-c", " ".join(sql_lines)],
                   capture_output=True, text=True, env={**os.environ, **PGPASS})
print(f"Cascade delete for tenant_id={TENANT_ID}:\n{r.stdout.strip()}")
if r.stderr.strip():
    print(f"stderr: {r.stderr.strip()}")

r = subprocess.run(["psql", "-U", "smart_user", "-d", "smart_dev", "-h", "127.0.0.1",
                     "-c", "SELECT count(*) FROM tenants WHERE slug = 'nm-override-test';"],
                    capture_output=True, text=True, env={**os.environ, **PGPASS})
print(f"\nVerify 0 rows remain (slug='nm-override-test'):\n{r.stdout.strip()}")
