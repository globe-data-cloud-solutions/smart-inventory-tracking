"""Integration Test Group 3 — Products and inventory.
Requires Groups 1-2 tenant (Integration Test Co).
DO NOT fix anything. Report only.
"""
import subprocess, json, base64, uuid as _uuid

BASE = "http://localhost:8000/api/v1"
results = {}


def curl(method, path, token=None, body=None):
    cmd = ["curl", "-s", "-w", "\n%{http_code}", f"{BASE}{path}"]
    if method != "GET":
        cmd += ["-X", method]
    if token:
        cmd += ["-H", f"Authorization: Bearer {token}"]
    if body is not None:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(body)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    lines = r.stdout.strip().split("\n")
    code = int(lines[-1])
    raw  = "\n".join(lines[:-1])
    try:
        data = json.loads(raw)
    except Exception:
        data = {"_raw": raw}
    return code, data


def jwt_claims(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.b64decode(payload))
    except Exception:
        return {}


def report(label, code, data, expect_code, extra="", note=""):
    ok = code == expect_code
    icon   = "OK" if ok else "XX"
    status = "PASS" if ok else "FAIL"
    print(f"\n{'='*60}")
    print(f"{icon} {label}  ->  HTTP {code}  [{status}]")
    if extra:
        print(f"   {extra}")
    if note:
        print(f"   NOTE: {note}")
    if not ok:
        detail = data.get("detail", data.get("error", data.get("_raw", "")))
        print(f"   Error: {json.dumps(detail)[:500]}")
    results[label] = ok
    return ok


# ── SETUP ────────────────────────────────────────────────────
print("SETUP")

def get_jwt(email, password, label):
    c, d = curl("POST", "/auth/token",
                body={"dev_email": email, "dev_password": password})
    tok = d.get("access_token", "")
    cl  = jwt_claims(tok)
    print(f"   {label}: role={cl.get('role')}  "
          f"{'obtained ' + tok[:20] + '...' if tok else 'FAILED'}")
    return tok, cl

TA_JWT, TA_C = get_jwt("admin@int-test.com", "IntTest@2026", "TA JWT")
NM_JWT, NM_C = get_jwt("nm@int-test.com",    "NMUser@2026",  "NM JWT")
WM_JWT, WM_C = get_jwt("wm@int-test.com",    "WMUser@2026",  "WM JWT")

# Resolve tenant + WM warehouse_id from JWTs
_, tm = curl("GET", "/tenants/integration-test-co", TA_JWT)
TENANT_ID    = tm.get("data", {}).get("id", "")
WH_NODE_ID   = WM_C.get("warehouse_id", "")   # L3 node (Bole Warehouse)

print(f"   TENANT_ID:  {TENANT_ID}")
print(f"   WH_NODE_ID: {WH_NODE_ID}  (WM's warehouse from JWT)")

if not TENANT_ID:
    print("\nFATAL: No tenant found. Was Group 1 run?")
    raise SystemExit(1)


# ── TEST 3.1  Create product ─────────────────────────────────
# Body sent EXACTLY as specified in the test prompt.
# Expected schema: requires type_code; sku -> sku_override; no batch_tracking/unit_price/currency fields.
PRODUCT_BODY_AS_SPECIFIED = {
    "name":          "Test Product A",
    "sku":           "TPA-001",          # WRONG field name (schema: sku_override)
    "unit":          "KG",
    "pack_size":     1,                  # WRONG field name (schema: units_per_package)
    "batch_tracking": False,             # field not in schema
    "unit_price":    100.00,             # field not in schema
    "currency":      "ETB",             # field not in schema
                                         # MISSING: type_code (required, min_length=2)
}
code, d = curl("POST", "/products/", TA_JWT, PRODUCT_BODY_AS_SPECIFIED)
PRODUCT_ID = d.get("data", {}).get("id", "")
report("TEST 3.1  Create product (body as specified)", code, d, 201,
       extra=f"product_id={PRODUCT_ID}  sku={d.get('data',{}).get('sku')}",
       note="Schema requires 'type_code' (missing); 'sku' should be 'sku_override'; "
            "'pack_size','batch_tracking','unit_price','currency' are not schema fields — expect 422")


# ── TEST 3.2  GET products list ──────────────────────────────
code, d = curl("GET", "/products/", TA_JWT)
products = d.get("data", [])
found = any(p.get("name") == "Test Product A" for p in products)
ok = code == 200 and found
print(f"\n{'='*60}")
print(f"{'OK' if ok else 'XX'} TEST 3.2  GET products list  ->  HTTP {code}  [{'PASS' if ok else 'FAIL'}]")
print(f"   Products returned: {len(products)}")
for p in products[:5]:
    print(f"   {p.get('sku')} | {p.get('name')} | unit={p.get('unit')}")
if code == 200 and not found:
    print("   NOTE: 'Test Product A' not found (product creation in 3.1 failed)")
results["TEST 3.2  GET products list"] = ok


# ── TEST 3.3  Receive opening balance (as WM) ────────────────
# Body sent EXACTLY as specified.
# Schema: requires idempotency_key (missing); reason_code is not a field.
RECEIVE_BODY_AS_SPECIFIED = {
    "product_id":   PRODUCT_ID or "00000000-0000-0000-0000-000000000000",
    "warehouse_id": WH_NODE_ID or "00000000-0000-0000-0000-000000000000",
    "quantity":     1000,
    "reason_code":  "OPENING_BALANCE",   # field not in ReceiveStockRequest schema
                                          # MISSING: idempotency_key (required)
}
code, d = curl("POST", "/inventory/receive/", WM_JWT, RECEIVE_BODY_AS_SPECIFIED)
TX_ID = d.get("data", {}).get("transaction_id", "")
report("TEST 3.3  Receive opening balance (body as specified)", code, d, 201,
       extra=f"transaction_id={TX_ID}",
       note="Schema requires 'idempotency_key' (missing); 'reason_code' is not a schema field — expect 422")


# ── TEST 3.4  GET inventory analytics/stock ──────────────────
code, d = curl("GET", "/inventory/analytics/stock", WM_JWT)
stock_rows = d.get("data", [])
# Look for Test Product A (if product was created)
match = next((r for r in stock_rows
              if r.get("product_name") == "Test Product A"), None)
ok = code == 200 and match is not None and float(match.get("current_stock", 0)) == 1000
print(f"\n{'='*60}")
print(f"{'OK' if ok else 'XX'} TEST 3.4  GET inventory analytics/stock  ->  HTTP {code}  [{'PASS' if ok else 'FAIL'}]")
print(f"   Stock rows returned: {len(stock_rows)}")
if match:
    print(f"   Test Product A: current_stock={match.get('current_stock')}  "
          f"net_available={match.get('net_available')}  "
          f"warehouse={match.get('warehouse_name')}")
else:
    print("   Test Product A: NOT FOUND in stock  "
          "(product never created or stock never received)")
for r in stock_rows[:3]:
    print(f"   {r.get('product_sku')} | {r.get('product_name')} | "
          f"qty={r.get('current_stock')} | wh={r.get('warehouse_name')}")
results["TEST 3.4  GET analytics/stock"] = ok


# ── TEST 3.5  GET analytics/warehouses ───────────────────────
# Expects WH node (Bole Warehouse) to appear. Queries organization_node + warehouses tables.
code, d = curl("GET", "/inventory/analytics/warehouses", WM_JWT)
wh_list = d.get("data", [])
bole = next((w for w in wh_list if "Bole" in (w.get("name") or "")), None)
ok   = code == 200 and len(wh_list) > 0
print(f"\n{'='*60}")
print(f"{'OK' if ok else 'XX'} TEST 3.5  GET analytics/warehouses  ->  HTTP {code}  [{'PASS' if ok else 'FAIL'}]")
print(f"   Warehouses returned: {len(wh_list)}")
for w in wh_list:
    print(f"   id={str(w.get('id',''))[:8]}...  name={w.get('name')!r}  type={w.get('warehouse_type')}")
if not bole:
    print("   NOTE: 'Bole Warehouse' not explicitly found by name")
if not ok and code != 200:
    detail = d.get("detail", d.get("_raw", ""))
    print(f"   Error: {json.dumps(detail)[:300]}")
results["TEST 3.5  GET analytics/warehouses"] = ok


# ── TEST 3.6  GET nodes as warehouses ────────────────────────
code, d = curl("GET", f"/tenants/{TENANT_ID}/nodes", TA_JWT)
def count_nodes(nodes):
    n = len(nodes)
    for nd in nodes: n += count_nodes(nd.get("children", []))
    return n
tree  = d.get("data", [])
total = count_nodes(tree)
ok    = code == 200 and total == 3
print(f"\n{'='*60}")
print(f"{'OK' if ok else 'XX'} TEST 3.6  GET tenant nodes  ->  HTTP {code}  [{'PASS' if ok else 'FAIL'}]")
print(f"   Total nodes in tree: {total}  (expected 3)")
for n in tree:
    print(f"   L{n.get('hierarchy_level')} {n.get('name')!r}  children={len(n.get('children',[]))}")
    for c in n.get("children", []):
        print(f"     L{c.get('hierarchy_level')} {c.get('name')!r}  children={len(c.get('children',[]))}")
        for g in c.get("children", []):
            print(f"       L{g.get('hierarchy_level')} {g.get('name')!r}")
results["TEST 3.6  GET tenant nodes"] = ok


# ── SUMMARY ──────────────────────────────────────────────────
passed = sum(1 for v in results.values() if v)
total  = len(results)
failed = [k for k, v in results.items() if not v]

print(f"\n{'='*60}")
print("SUMMARY")
print(f"PASSED: {passed}/{total}")
print(f"FAILED: {total - passed}/{total}")
if failed:
    print("FAILURES:")
    for f in failed:
        print(f"  XX {f}")
else:
    print("All tests passed.")
