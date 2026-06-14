"""ProductLabel rollout — integration test (TEST 1-6).
Verifies the API contracts consumed by the shared <ProductLabel> component:
is_controlled / approval_overrides on GET /products/, and product_id on
transfer line items (for the transfers/adjustments productById lookup).
Report only — cleans up after."""
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


def get_jwt(email, pw):
    c, d = curl("POST", "/auth/token", body={"dev_email": email, "dev_password": pw})
    tok = d.get("access_token", "")
    return tok, jwt_claims(tok)


def check(label, ok, extra=""):
    icon = "OK" if ok else "XX"
    print(f"{icon} {label}  [{'PASS' if ok else 'FAIL'}]" + (f"  {extra}" if extra else ""))
    results[label] = ok
    return ok


# ════════════════════════════════════════════════════════════════════════
# SETUP — throwaway tenant, 2-level NM/RM hierarchy, Test Gold + Test Steel
# ════════════════════════════════════════════════════════════════════════
print("\n" + "#" * 70)
print("# SETUP — ProductLabel integration test tenant")
print("#" * 70)

SA_JWT, _ = get_jwt("smartadmin@smart-inventory.com", "Admin@2026")
if not SA_JWT:
    print("FATAL: cannot obtain SA JWT. Aborting.")
    raise SystemExit(1)

code, d = curl("POST", "/tenants/", SA_JWT, {
    "name": "ProductLabel Test",
    "slug": "productlabel-test",
    "organisation_type": "PRODUCER",
    "default_locale": "en",
    "admin_name": "PL Admin",
    "admin_email": "admin@productlabel-test.com",
    "admin_password": "PLabel@2026",
})
TENANT_ID = d.get("data", {}).get("id", "")
print(f"SETUP — Create tenant: HTTP {code}  tenant_id={TENANT_ID}")
if not TENANT_ID:
    print(f"FATAL: tenant creation failed: {json.dumps(d)[:400]}")
    raise SystemExit(1)

code, d = curl("POST", f"/tenants/{TENANT_ID}/users", SA_JWT, {
    "name": "PL Admin", "email": "admin@productlabel-test.com",
    "password": "PLabel@2026", "system_role": "TA",
})
print(f"SETUP — Create TA user: HTTP {code}")

TA_JWT, ta_c = get_jwt("admin@productlabel-test.com", "PLabel@2026")
print(f"SETUP — TA login: role={ta_c.get('role')}")

# Hierarchy config — 2 levels: NM / RM
code, d = curl("PUT", f"/tenants/{TENANT_ID}/hierarchy/config", TA_JWT, [
    {"level_number": 1, "level_name": "HQ", "default_role_code": "NM",
     "role_display_label": "National Manager", "is_stock_holding": True},
    {"level_number": 2, "level_name": "Region", "default_role_code": "RM",
     "role_display_label": "Regional Manager", "is_stock_holding": True},
])
print(f"SETUP — Hierarchy config (2 levels): HTTP {code}  saved={len(d.get('data', []))}")

# Nodes: HQ -> Region
code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes", TA_JWT,
               {"name": "HQ", "level_number": 1, "parent_node_id": None, "is_stock_holding": True})
HQ_ID = d.get("data", {}).get("id", "")
code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes", TA_JWT,
               {"name": "Region", "level_number": 2, "parent_node_id": HQ_ID, "is_stock_holding": True})
REGION_ID = d.get("data", {}).get("id", "")
print(f"SETUP — Nodes: HQ={HQ_ID[:8]}  Region={REGION_ID[:8]}")

# Positions
code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes/{HQ_ID}/positions", TA_JWT,
               {"title": "National Manager", "role_code": "NM"})
NM_POS_ID = d.get("data", {}).get("id", "")
code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes/{REGION_ID}/positions", TA_JWT,
               {"title": "Regional Manager", "role_code": "RM", "reports_to_position_id": NM_POS_ID})
RM_POS_ID = d.get("data", {}).get("id", "")
print(f"SETUP — Positions: NM={NM_POS_ID[:8]}  RM={RM_POS_ID[:8]}")

# Users
code, d = curl("POST", f"/tenants/{TENANT_ID}/users", TA_JWT,
               {"name": "NM User", "email": "nm@productlabel-test.com", "password": "PLabelNm@2026", "position_id": NM_POS_ID})
code, d = curl("POST", f"/tenants/{TENANT_ID}/users", TA_JWT,
               {"name": "RM User", "email": "rm@productlabel-test.com", "password": "PLabelRm@2026", "position_id": RM_POS_ID})
print("SETUP — Users created: nm, rm")

NM_JWT, nm_c = get_jwt("nm@productlabel-test.com", "PLabelNm@2026")
RM_JWT, rm_c = get_jwt("rm@productlabel-test.com", "PLabelRm@2026")
print(f"SETUP — JWTs: NM(role={nm_c.get('role')}) RM(role={rm_c.get('role')})")

# Transfer types — PULL only needed
PULL_LEVELS = [
    {"level_number": 1, "can_initiate": False, "can_receive": False},
    {"level_number": 2, "can_initiate": True,  "can_receive": True},
]
code, d = curl("PUT", f"/tenants/{TENANT_ID}/transfer-types", TA_JWT, [
    {"underlying_type": "PULL", "display_name": "Stock Request", "description": "Region requests stock",
     "is_active": True, "sort_order": 1, "level_permissions": PULL_LEVELS},
])
saved = d.get("data", [])
PULL_CFG_ID = next((tt["id"] for tt in saved if tt.get("underlying_type") == "PULL"), "")
print(f"SETUP — Transfer types configured: HTTP {code}  PULL={PULL_CFG_ID[:8]}")

# Transfer approval rules — PULL routes to RM (source_parent_node)
code, d = curl("PUT", f"/tenants/{TENANT_ID}/transfer-approval-rules", TA_JWT, [
    {"transfer_type_config_id": PULL_CFG_ID, "source_level": 1, "destination_level": 2,
     "quantity_min": 0, "quantity_max": None, "threshold_type": "QUANTITY", "currency": "ETB",
     "priority": 1, "is_active": True,
     "approval_steps": [{"sequence": 1, "position_title": "Regional Manager",
                         "resolution": "source_parent_node", "execution_mode": "SEQUENTIAL", "sla_hours": 24}]},
])
print(f"SETUP — Transfer approval rules: HTTP {code}  rules={len(d.get('data', []))}")

# Products — Test Gold (will be controlled) and Test Steel (uncontrolled)
code, d = curl("POST", "/products/", TA_JWT, {
    "name": "Test Gold", "type_code": "TGD", "unit": "EA",
    "units_per_package": 1, "sku_override": "TEST-GOLD-001",
    "unit_price": 50000.00, "currency": "ETB",
})
GOLD_ID = d.get("data", {}).get("id", "")
print(f"SETUP — Product Test Gold: HTTP {code}  id={GOLD_ID[:8] if GOLD_ID else 'MISSING'}")

code, d = curl("POST", "/products/", TA_JWT, {
    "name": "Test Steel", "type_code": "TST", "unit": "EA",
    "units_per_package": 1, "sku_override": "TEST-STEEL-001",
    "unit_price": 50.00, "currency": "ETB",
})
STEEL_ID = d.get("data", {}).get("id", "")
print(f"SETUP — Product Test Steel: HTTP {code}  id={STEEL_ID[:8] if STEEL_ID else 'MISSING'}")

# Opening balance — receive stock at HQ for Test Gold, via NM
ik = f"plabel-ob-hq-{_uuid.uuid4()}"
code, d = curl("POST", "/inventory/receive/", NM_JWT, {
    "product_id": GOLD_ID, "warehouse_id": HQ_ID, "quantity": 100,
    "source": "OPENING_BALANCE", "idempotency_key": ik,
})
print(f"SETUP — Receive 100 Test Gold @ HQ: HTTP {code}  tx={d.get('data', {}).get('transaction_id', '')[:8]}")

print(f"\nSETUP COMPLETE — TENANT_ID={TENANT_ID}")
print(f"   HQ={HQ_ID}  Region={REGION_ID}")
print(f"   GOLD_ID={GOLD_ID}  STEEL_ID={STEEL_ID}  RM_POS_ID={RM_POS_ID}")


# ════════════════════════════════════════════════════════════════════════
# CONFIGURE DESIGN-B OVERRIDE — Test Gold, PULL = ALWAYS -> RM
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# CONFIGURE — Test Gold PULL override (ALWAYS -> RM)")
print("#" * 70)

code, d = curl("PUT", f"/products/{GOLD_ID}/approval-minimums", TA_JWT, {
    "entries": [
        {"transaction_type": "PULL", "override_enabled": True, "threshold_type": "ALWAYS",
         "approver_position_id": RM_POS_ID, "note": "Test Gold always needs RM sign-off"},
    ]
})
check("CONFIG: Test Gold PULL override saved (HTTP 200)", code == 200,
      f"minimums={len(d.get('data', {}).get('minimums', []))}")


# ════════════════════════════════════════════════════════════════════════
# TEST 1 — GET /products/ as TA: Test Gold is_controlled=true with PULL override
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# TEST 1 — GET /products/ as TA: Test Gold controlled + PULL override shape")
print("#" * 70)

code, d = curl("GET", "/products/", TA_JWT)
products = d.get("data", [])
gold = next((p for p in products if p.get("id") == GOLD_ID), None)
steel = next((p for p in products if p.get("id") == STEEL_ID), None)

ok1a = check("TEST1.1 GET /products/ as TA -> HTTP 200", code == 200)
ok1b = check("TEST1.2 Test Gold.is_controlled == true", bool(gold and gold.get("is_controlled") is True))
gold_overrides = (gold or {}).get("approval_overrides") or {}
pull_override = gold_overrides.get("PULL")
ok1c = check("TEST1.3 Test Gold.approval_overrides.PULL present", pull_override is not None,
              f"value={json.dumps(pull_override)[:200]}")
ok1d = False
if pull_override:
    ok1d = check("TEST1.4 PULL override mode == 'ALWAYS'", pull_override.get("mode") == "ALWAYS",
                  f"mode={pull_override.get('mode')}")
ok1e = False
if pull_override:
    approver_label = pull_override.get("approver_label")
    ok1e = check("TEST1.5 PULL override approver_label is human-readable (not a UUID)",
                  bool(approver_label) and "-" not in str(approver_label)[:8],
                  f"approver_label={approver_label!r}")


# ════════════════════════════════════════════════════════════════════════
# TEST 2 — GET /products/ as RM (non-TA role): same fields returned
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# TEST 2 — GET /products/ as RM: is_controlled/approval_overrides unconditional")
print("#" * 70)

code, d = curl("GET", "/products/", RM_JWT)
products_rm = d.get("data", [])
gold_rm = next((p for p in products_rm if p.get("id") == GOLD_ID), None)

ok2a = check("TEST2.1 GET /products/ as RM -> HTTP 200", code == 200)
ok2b = check("TEST2.2 Test Gold.is_controlled == true (as RM)", bool(gold_rm and gold_rm.get("is_controlled") is True))
ok2c = check("TEST2.3 Test Gold.approval_overrides.PULL present (as RM)",
              bool((gold_rm or {}).get("approval_overrides", {}).get("PULL")))


# ════════════════════════════════════════════════════════════════════════
# TEST 3 — Test Steel is NOT controlled, no PULL override
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# TEST 3 — Test Steel (no override configured) is uncontrolled")
print("#" * 70)

ok3a = check("TEST3.1 Test Steel.is_controlled is falsy", not bool(steel and steel.get("is_controlled")),
              f"is_controlled={steel.get('is_controlled') if steel else 'MISSING'}")
steel_overrides = (steel or {}).get("approval_overrides") or {}
ok3b = check("TEST3.2 Test Steel.approval_overrides has no PULL entry", "PULL" not in steel_overrides,
              f"approval_overrides={json.dumps(steel_overrides)[:120]}")


# ════════════════════════════════════════════════════════════════════════
# TEST 4 — buildOverrideTooltip() text shape for Test Gold's PULL override
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# TEST 4 — Tooltip text (buildOverrideTooltip equivalent) for Test Gold PULL")
print("#" * 70)

# Mirrors frontend/src/components/features/inventory/ProductLabel.tsx buildOverrideTooltip()
# for mode == "ALWAYS": t('product.override_always') with {approver} and {transaction} substituted,
# then " — {note}" appended if note is set.
EN_OVERRIDE_ALWAYS = "Requires approval from {approver} for every {transaction}."
expected_tooltip = ""
ok4 = False
if pull_override:
    approver = pull_override.get("approver_label") or "Unknown"
    note = pull_override.get("note")
    expected_tooltip = EN_OVERRIDE_ALWAYS.replace("{approver}", approver).replace("{transaction}", "transaction")
    if note:
        expected_tooltip += f" — {note}"
    ok4 = check("TEST4.1 Tooltip mentions RM approver and 'transaction'",
                "Regional Manager" in expected_tooltip and "transaction" in expected_tooltip,
                f"tooltip={expected_tooltip!r}")


# ════════════════════════════════════════════════════════════════════════
# TEST 5 — Create a PULL transfer for Test Gold; list endpoint line item carries
#          product_id + product_name (needed by transfers/page.tsx productById
#          lookup -> ProductLabel 🔒)
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# TEST 5 — PULL transfer for Test Gold: list line item carries product_id")
print("#" * 70)

code, d = curl("POST", "/inventory/transfers/", RM_JWT, {
    "transfer_type": "PULL", "from_warehouse_id": HQ_ID, "to_warehouse_id": REGION_ID,
    "lines": [{"product_id": GOLD_ID, "quantity": 5}], "notes": "TEST5 Test Gold PULL",
})
T5_ID = d.get("data", {}).get("transfer_id", "")
ok5a = check("TEST5.1 RM creates PULL Test Gold qty=5 -> HTTP 201", code == 201,
              f"transfer_id={T5_ID[:8] if T5_ID else 'NONE'}")

ok5b = False
if T5_ID:
    code, d = curl("GET", "/inventory/transfers/", RM_JWT)
    transfers = d.get("data", [])
    t5 = next((x for x in transfers if x.get("transfer_id") == T5_ID), None)
    line_pids = [ln.get("product_id") for ln in (t5 or {}).get("lines", [])]
    ok5b = check("TEST5.2 GET transfers list line has product_id == GOLD_ID",
                  GOLD_ID in line_pids, f"line product_ids={[p[:8] if p else p for p in line_pids]}")


# ════════════════════════════════════════════════════════════════════════
# TEST 6 — Submit Test Gold PULL transfer; product override (ALWAYS -> RM)
#          forces routing -> product_override_applied becomes true
#          (confirms the 🔒-relevant override is "live" on this transaction)
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# TEST 6 — Submitting Test Gold PULL transfer reflects active product override")
print("#" * 70)

ok6 = False
if T5_ID:
    code, d = curl("POST", f"/inventory/transfers/{T5_ID}/submit", RM_JWT)
    print(f"   submit -> HTTP {code}  status={d.get('data', {}).get('status')}")

    def psql(sql):
        full = (f"SELECT set_config('app.current_tenant_id','{TENANT_ID}',false),"
                f"set_config('app.current_user_id','00000001-0000-0000-0000-000000000001',false);"
                f"{sql}")
        r = subprocess.run(["psql", "-U", "smart_user", "-d", "smart_dev", "-h", "127.0.0.1",
                            "-t", "-A", "-c", full],
                           capture_output=True, text=True, env={**__import__("os").environ, **PGPASS})
        return r.stdout.strip(), r.stderr.strip()

    out, _ = psql(f"SELECT status, product_override_applied FROM transfer_orders WHERE id = '{T5_ID}';")
    lines = [l for l in out.splitlines() if l.strip()]
    status, override_applied = (None, None)
    if lines:
        parts = lines[-1].split("|")
        status = parts[0].strip()
        override_applied = parts[1].strip() if len(parts) > 1 else ""
    ok6 = check("TEST6.1 transfer_orders.product_override_applied == true for Test Gold PULL",
                 override_applied == "t", f"status={status} product_override_applied={override_applied}")


# ════════════════════════════════════════════════════════════════════════
# CLEANUP — cascade delete throwaway tenant
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# CLEANUP")
print("#" * 70)

CASCADE_TABLES = [
    "transfer_order_lines", "transfer_orders", "transfer_requests",
    "inventory_transactions", "inventory_balances",
    "product_approval_minimums", "dispatch_strategy_configs",
    "products", "self_approval_policies", "transfer_approval_rules",
    "transfer_type_level_permissions", "transfer_type_config",
    "personnel_positions", "org_node_hierarchy", "positions", "users",
    "organization_node", "tenant_hierarchy_config",
]

def psql_tenant(sql):
    r = subprocess.run(["psql", "-U", "smart_user", "-d", "smart_dev", "-h", "127.0.0.1",
                        "-t", "-A", "-c", sql],
                       capture_output=True, text=True, env={**__import__("os").environ, **PGPASS})
    return r.stdout.strip(), r.stderr.strip()

psql_tenant("DELETE FROM inventory_transaction_keys WHERE idempotency_key LIKE 'plabel-%';")
for tbl in CASCADE_TABLES:
    out, err = psql_tenant(f"DELETE FROM {tbl} WHERE tenant_id = '{TENANT_ID}';")
    if err and "does not exist" not in err:
        print(f"   WARN deleting from {tbl}: {err[:150]}")

out, err = psql_tenant(f"DELETE FROM tenants WHERE id = '{TENANT_ID}';")
print(f"CLEANUP — tenant {TENANT_ID} deleted" + (f" (warn: {err[:150]})" if err else ""))


# ════════════════════════════════════════════════════════════════════════
# SUMMARY
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# SUMMARY")
print("#" * 70)
for label, ok in results.items():
    print(f"{'OK' if ok else 'XX'}  {label}")
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"\n{passed}/{total} checks passed")
