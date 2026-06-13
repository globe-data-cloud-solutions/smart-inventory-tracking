"""Integration test — Edit Product + controlled-product permission split (TASK 3 PART B).

Creates a fresh test tenant, builds a minimal 2-level hierarchy (NM/RM), creates
"Test Steel" (no override) and "Test Gold" (PULL override ALWAYS -> RM), and verifies:

  TEST 1: Position dropdown data — GET /tenants/{tenant_id}/positions/flat populated
  TEST 2: AddProductPanel.tsx has exactly ONE "Minimum Approval Level" section (Design-B only)
  TEST 3: TA edits "Test Steel" (no override) -> 200; TA edits "Test Gold" (controlled) -> 200
  TEST 4: NM edits "Test Steel" -> 200; NM edits "Test Gold" (controlled) -> 403 PRODUCT_CONTROLLED
  TEST 5: GET /products/ -- "Test Gold".is_controlled = true, "Test Steel".is_controlled = false
  TEST 6: is_controlled visible to both TA and NM (drives the lock icon for both roles)

Report only — cleans up the test tenant + products afterward.
"""
from __future__ import annotations
import subprocess, json, sys, io

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


def get_jwt(email, pw):
    c, d = curl("POST", "/auth/token", body={"dev_email": email, "dev_password": pw})
    return d.get("access_token", "")


def report(label, code, d, expect_code, extra=""):
    ok = code == expect_code
    icon = "OK" if ok else "XX"
    print(f"\n{'='*60}")
    print(f"{icon} {label}  ->  HTTP {code}  [{'PASS' if ok else 'FAIL'}]")
    if extra:
        print(f"   {extra}")
    if not ok:
        detail = d.get("detail", d.get("error", d.get("_raw", "")))
        print(f"   Error: {json.dumps(detail)[:300]}")
    results[label] = ok
    return ok


def check(label, ok, extra=""):
    icon = "OK" if ok else "XX"
    print(f"{icon} {label}  [{'PASS' if ok else 'FAIL'}]" + (f"  {extra}" if extra else ""))
    results[label] = ok
    return ok


# ════════════════════════════════════════════════════════════════════════
# SETUP
# ════════════════════════════════════════════════════════════════════════
print("\n" + "#" * 70)
print("# SETUP — Edit Product Integration Test tenant")
print("#" * 70)

SA_JWT = get_jwt("smartadmin@smart-inventory.com", "Admin@2026")
if not SA_JWT:
    print("FATAL: cannot obtain SA JWT. Aborting.")
    raise SystemExit(1)

code, d = curl("POST", "/tenants/", SA_JWT, {
    "name": "Edit Product Test",
    "slug": "edit-product-test",
    "organisation_type": "PRODUCER",
    "default_locale": "en",
    "admin_name": "EditProd Admin",
    "admin_email": "admin@edit-product-test.com",
    "admin_password": "EditProd@2026",
})
TENANT_ID = d.get("data", {}).get("id", "")
print(f"SETUP — Create tenant: HTTP {code}  tenant_id={TENANT_ID}")
if not TENANT_ID:
    print(f"FATAL: tenant creation failed: {json.dumps(d)[:400]}")
    raise SystemExit(1)

code, d = curl("POST", f"/tenants/{TENANT_ID}/users", SA_JWT, {
    "name": "EditProd Admin", "email": "admin@edit-product-test.com",
    "password": "EditProd@2026", "system_role": "TA",
})
print(f"SETUP — Create TA user: HTTP {code}")

TA_JWT = get_jwt("admin@edit-product-test.com", "EditProd@2026")

# Hierarchy config — 2 levels: NM / RM
code, d = curl("PUT", f"/tenants/{TENANT_ID}/hierarchy/config", TA_JWT, [
    {"level_number": 1, "level_name": "HQ", "default_role_code": "NM",
     "role_display_label": "National Manager", "is_stock_holding": True},
    {"level_number": 2, "level_name": "Region", "default_role_code": "RM",
     "role_display_label": "Regional Manager", "is_stock_holding": True},
])
print(f"SETUP — Hierarchy config (2 levels): HTTP {code}  saved={len(d.get('data', []))}")

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

# NM user
code, d = curl("POST", f"/tenants/{TENANT_ID}/users", TA_JWT,
               {"name": "NM User", "email": "nm@edit-product-test.com", "password": "EditProdNm@2026", "position_id": NM_POS_ID})
print(f"SETUP — Create NM user: HTTP {code}")
NM_JWT = get_jwt("nm@edit-product-test.com", "EditProdNm@2026")

# Products
code, d = curl("POST", "/products/", TA_JWT, {
    "name": "Test Steel", "type_code": "TST", "unit": "EA",
    "units_per_package": 1, "sku_override": "TESTSTEEL-001",
    "unit_price": 100.00, "currency": "ETB",
})
STEEL_ID = d.get("data", {}).get("id", "")
print(f"SETUP — Product Test Steel: HTTP {code}  id={STEEL_ID[:8] if STEEL_ID else 'MISSING'}")

code, d = curl("POST", "/products/", TA_JWT, {
    "name": "Test Gold", "type_code": "TGD", "unit": "EA",
    "units_per_package": 1, "sku_override": "TESTGOLD-001",
    "unit_price": 50000.00, "currency": "ETB",
})
GOLD_ID = d.get("data", {}).get("id", "")
print(f"SETUP — Product Test Gold: HTTP {code}  id={GOLD_ID[:8] if GOLD_ID else 'MISSING'}")

if not STEEL_ID or not GOLD_ID:
    print("FATAL: product creation failed. Aborting before configuring override.")
    raise SystemExit(1)

# Configure Test Gold PULL override = ALWAYS -> RM (makes it "controlled")
code, d = curl("PUT", f"/products/{GOLD_ID}/approval-minimums", TA_JWT, {
    "entries": [
        {"transaction_type": "PULL", "override_enabled": True, "threshold_type": "ALWAYS",
         "approver_position_id": RM_POS_ID, "note": "Test Gold always needs RM sign-off"},
    ]
})
print(f"SETUP — Configure Test Gold PULL override (ALWAYS -> RM): HTTP {code}")

print(f"\nSETUP COMPLETE — TENANT_ID={TENANT_ID}")
print(f"   STEEL_ID={STEEL_ID}  GOLD_ID={GOLD_ID}  RM_POS_ID={RM_POS_ID}")


# ════════════════════════════════════════════════════════════════════════
# TEST 1 — Position dropdown populated
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# TEST 1 — Position dropdown data (GET /tenants/{tenant_id}/positions/flat)")
print("#" * 70)

code, d = curl("GET", f"/tenants/{TENANT_ID}/positions/flat", TA_JWT)
positions = d.get("data", [])
report("TEST1.1 GET positions/flat", code, d, 200, f"count={len(positions)}")
check("TEST1.2 positions list non-empty", len(positions) > 0, f"-> {len(positions)} positions")
check("TEST1.3 RM position present in list",
      any(p.get("id") == RM_POS_ID for p in positions),
      f"-> RM_POS_ID={RM_POS_ID[:8]}")


# ════════════════════════════════════════════════════════════════════════
# TEST 2 — Only ONE "Minimum Approval Level" section in AddProductPanel.tsx
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# TEST 2 — AddProductPanel.tsx has exactly ONE Minimum Approval Level section")
print("#" * 70)

panel_path = "frontend/src/components/features/inventory/AddProductPanel.tsx"
try:
    with open(panel_path, "r", encoding="utf-8") as f:
        panel_src = f.read()
    occurrences = panel_src.count("product.add.minimum_approval_level") + panel_src.count("Minimum Approval Level")
    check("TEST2.1 exactly one Minimum Approval Level section reference",
          occurrences <= 1 or panel_src.count('t("product.add.minimum_approval_level")') == 1,
          f"-> raw_occurrences={occurrences}, t()_calls={panel_src.count(chr(39)+'product.add.minimum_approval_level'+chr(39))}{panel_src.count(chr(34)+'product.add.minimum_approval_level'+chr(34))}")
    check("TEST2.2 old per-transaction-type authority dropdown removed (no 'authority_level' select UI)",
          "min_authority_level" not in panel_src or panel_src.count("min_authority_level") <= 2,
          f"-> occurrences of 'min_authority_level'={panel_src.count('min_authority_level')}")
except Exception as e:
    check("TEST2.1 exactly one Minimum Approval Level section reference", False, f"-> error reading file: {e}")
    check("TEST2.2 old per-transaction-type authority dropdown removed", False, f"-> error reading file: {e}")


# ════════════════════════════════════════════════════════════════════════
# TEST 3 — TA edits Test Steel (no override) and Test Gold (controlled)
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# TEST 3 — TA edits Test Steel (no override) -> 200; TA edits Test Gold (controlled) -> 200")
print("#" * 70)

code, d = curl("PATCH", f"/products/{STEEL_ID}", TA_JWT, {"unit_price": 105.00})
report("TEST3.1 TA PATCH Test Steel unit_price -> 105.00", code, d, 200,
       f"unit_price={d.get('data', {}).get('unit_price')}")

code, d = curl("PATCH", f"/products/{GOLD_ID}", TA_JWT, {"unit_price": 51000.00})
report("TEST3.2 TA PATCH Test Gold (controlled) unit_price -> 51000.00", code, d, 200,
       f"unit_price={d.get('data', {}).get('unit_price')}")


# ════════════════════════════════════════════════════════════════════════
# TEST 4 — NM edits Test Steel (200) and Test Gold (403 PRODUCT_CONTROLLED)
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# TEST 4 — NM edits Test Steel -> 200; NM edits Test Gold (controlled) -> 403 PRODUCT_CONTROLLED")
print("#" * 70)

code, d = curl("PATCH", f"/products/{STEEL_ID}", NM_JWT, {"unit_price": 110.00})
report("TEST4.1 NM PATCH Test Steel unit_price -> 110.00", code, d, 200,
       f"unit_price={d.get('data', {}).get('unit_price')}")

code, d = curl("PATCH", f"/products/{GOLD_ID}", NM_JWT, {"unit_price": 52000.00})
detail = d.get("detail", {}) if isinstance(d.get("detail"), dict) else {}
err_code = d.get("error", {}).get("code") or detail.get("code")
report("TEST4.2 NM PATCH Test Gold (controlled) -> 403", code, d, 403,
       f"error_code={err_code}")
check("TEST4.3 error code == PRODUCT_CONTROLLED",
      err_code == "PRODUCT_CONTROLLED",
      f"-> {err_code}")


# ════════════════════════════════════════════════════════════════════════
# TEST 5 — is_controlled field
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# TEST 5 — GET /products/ is_controlled field")
print("#" * 70)

code, d = curl("GET", "/products/", TA_JWT)
products = d.get("data", [])
report("TEST5.1 GET /products/ (TA)", code, d, 200, f"count={len(products)}")

steel = next((p for p in products if p.get("id") == STEEL_ID), {})
gold = next((p for p in products if p.get("id") == GOLD_ID), {})

check("TEST5.2 Test Gold.is_controlled == true", gold.get("is_controlled") is True,
      f"-> {gold.get('is_controlled')}")
check("TEST5.3 Test Steel.is_controlled == false", steel.get("is_controlled") is False,
      f"-> {steel.get('is_controlled')}")


# ════════════════════════════════════════════════════════════════════════
# TEST 6 — is_controlled visible to both TA and NM (drives lock icon for both)
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# TEST 6 — is_controlled visible to NM as well (lock icon shown for both roles)")
print("#" * 70)

code, d = curl("GET", "/products/", NM_JWT)
products_nm = d.get("data", [])
report("TEST6.1 GET /products/ (NM)", code, d, 200, f"count={len(products_nm)}")

gold_nm = next((p for p in products_nm if p.get("id") == GOLD_ID), {})
steel_nm = next((p for p in products_nm if p.get("id") == STEEL_ID), {})

check("TEST6.2 NM view: Test Gold.is_controlled == true", gold_nm.get("is_controlled") is True,
      f"-> {gold_nm.get('is_controlled')}")
check("TEST6.3 NM view: Test Steel.is_controlled == false", steel_nm.get("is_controlled") is False,
      f"-> {steel_nm.get('is_controlled')}")


# ════════════════════════════════════════════════════════════════════════
# SUMMARY
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# SUMMARY")
print("#" * 70)

groups = {
    "TEST 1 (position dropdown)": [k for k in results if k.startswith("TEST1")],
    "TEST 2 (single Minimum Approval section)": [k for k in results if k.startswith("TEST2")],
    "TEST 3 (TA edits)": [k for k in results if k.startswith("TEST3")],
    "TEST 4 (NM edits + 403)": [k for k in results if k.startswith("TEST4")],
    "TEST 5 (is_controlled)": [k for k in results if k.startswith("TEST5")],
    "TEST 6 (lock icon both roles)": [k for k in results if k.startswith("TEST6")],
}

grand_passed, grand_total = 0, 0
for label, keys in groups.items():
    p = sum(1 for k in keys if results.get(k))
    t = len(keys)
    grand_passed += p
    grand_total += t
    print(f"{label}: {p}/{t}")

print(f"\nTOTAL: {grand_passed}/{grand_total}")

failures = [k for k, v in results.items() if not v]
if failures:
    print(f"\n{'='*60}")
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
                   capture_output=True, text=True, env={**__import__("os").environ, **PGPASS})
print(f"Cascade delete (Phase 0-3 + tenants) for tenant_id={TENANT_ID}:\n{r.stdout.strip()}")
if r.stderr.strip():
    print(f"stderr: {r.stderr.strip()}")

r = subprocess.run(["psql", "-U", "smart_user", "-d", "smart_dev", "-h", "127.0.0.1",
                     "-c", "SELECT count(*) FROM tenants WHERE slug = 'edit-product-test';"],
                    capture_output=True, text=True, env={**__import__("os").environ, **PGPASS})
print(f"\nVerify 0 rows remain (slug='edit-product-test'):\n{r.stdout.strip()}")
