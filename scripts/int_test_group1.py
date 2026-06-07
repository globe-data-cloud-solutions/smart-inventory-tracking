"""Integration Test Group 1 — Tenant creation, org hierarchy, positions, users."""
import subprocess, json, base64

BASE = "http://localhost:8000/api/v1"
results = {}

def curl(method, path, token=None, body=None):
    cmd = ["curl", "-s", "-w", "\n%{http_code}", f"{BASE}{path}"]
    if method != "GET":
        cmd += ["-X", method]
    if token:
        cmd += ["-H", f"Authorization: Bearer {token}"]
    if body:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(body)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
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
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.b64decode(payload))
    except Exception:
        return {}

def report(label, code, data, expect_code, extra=""):
    ok = code == expect_code
    status = "PASS" if ok else "FAIL"
    icon = "OK" if ok else "XX"
    print(f"\n{'='*60}")
    print(f"{icon} {label}  ->  HTTP {code}  [{status}]")
    if extra:
        print(f"   {extra}")
    if not ok:
        detail = data.get("detail", data.get("error", data.get("_raw", "")))
        print(f"   Error: {json.dumps(detail)[:300]}")
    results[label] = ok
    return ok


# ── SETUP: SA JWT ────────────────────────────────────────────
code, d = curl("POST", "/auth/token", body={
    "dev_email": "smartadmin@smart-inventory.com",
    "dev_password": "Admin@2026"
})
SA_JWT = d.get("access_token", "")
print(f"\nSETUP -- SA JWT: {'obtained ' + SA_JWT[:20] + '...' if SA_JWT else 'FAILED - no token'}")
if not SA_JWT:
    print("FATAL: cannot obtain SA JWT. Aborting.")
    raise SystemExit(1)


# ── TEST 1.1  Create tenant ──────────────────────────────────
code, d = curl("POST", "/tenants/", SA_JWT, {
    "name": "Integration Test Co",
    "slug": "int-test",
    "organisation_type": "PRODUCER",
    "default_locale": "en",
    "admin_name": "Test Admin",
    "admin_email": "admin@int-test.com",
    "admin_password": "IntTest@2026"
})
data1 = d.get("data", {})
TENANT_ID   = data1.get("id", "")
TENANT_SLUG = data1.get("slug", "")
report("TEST 1.1  Create tenant", code, d, 201,
       f"id={TENANT_ID}  slug={TENANT_SLUG}  org_type={data1.get('organisation_type')}")


# ── PREREQ: Create TA admin user ─────────────────────────────
# TEST 1.1 body has admin_* fields but the endpoint ignores them (not in TenantCreate schema).
# Create TA user explicitly so TEST 1.2 (TA login) has a valid account.
if TENANT_ID:
    pc, pd = curl("POST", f"/tenants/{TENANT_ID}/users", SA_JWT, {
        "name": "Test Admin",
        "email": "admin@int-test.com",
        "password": "IntTest@2026",
        "system_role": "TA"
    })
    print(f"   [prereq] Create TA user -> HTTP {pc}  id={pd.get('data',{}).get('id','')[:8]}...")


# ── TEST 1.2  TA login ───────────────────────────────────────
code, d = curl("POST", "/auth/token", body={
    "dev_email": "admin@int-test.com",
    "dev_password": "IntTest@2026"
})
TA_JWT = d.get("access_token", "")
ta_c = jwt_claims(TA_JWT)
report("TEST 1.2  TA login", code, d, 200,
       f"role={ta_c.get('role')}  tenant_id={str(ta_c.get('tenant_id',''))[:8]}...  must_reset={d.get('must_reset_password')}")


# ── TEST 1.3  Set hierarchy config (3 levels) ────────────────
code, d = curl("PUT", f"/tenants/{TENANT_ID}/hierarchy/config", TA_JWT, [
    {"level_number": 1, "level_name": "National",  "default_role_code": "NM"},
    {"level_number": 2, "level_name": "Regional",  "default_role_code": "RM"},
    {"level_number": 3, "level_name": "Warehouse", "default_role_code": "WM"}
])
levels = d.get("data", [])
report("TEST 1.3  Set hierarchy config (3 levels)", code, d, 200,
       f"saved={len(levels)} levels: {[l.get('level_name') for l in levels]}")


# ── TEST 1.4  Create root node (L1) ──────────────────────────
code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes", TA_JWT, {
    "name": "HQ National", "level_number": 1,
    "parent_node_id": None, "is_stock_holding": True
})
NODE1_ID = d.get("data", {}).get("id", "")
report("TEST 1.4  Create root node (L1)", code, d, 201,
       f"id={NODE1_ID}  code={d.get('data',{}).get('code')}  level={d.get('data',{}).get('hierarchy_level')}")


# ── TEST 1.5  Create L2 child ────────────────────────────────
code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes", TA_JWT, {
    "name": "Addis Region", "level_number": 2,
    "parent_node_id": NODE1_ID, "is_stock_holding": True
})
NODE2_ID = d.get("data", {}).get("id", "")
report("TEST 1.5  Create L2 child node", code, d, 201,
       f"id={NODE2_ID}  parent={NODE1_ID[:8]}...")


# ── TEST 1.6  Create L3 child ────────────────────────────────
code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes", TA_JWT, {
    "name": "Bole Warehouse", "level_number": 3,
    "parent_node_id": NODE2_ID, "is_stock_holding": True
})
NODE3_ID = d.get("data", {}).get("id", "")
report("TEST 1.6  Create L3 child node", code, d, 201,
       f"id={NODE3_ID}  parent={NODE2_ID[:8]}...")


# ── TEST 1.7  GET nodes (verify tree) ────────────────────────
code, d = curl("GET", f"/tenants/{TENANT_ID}/nodes", TA_JWT)
def count_nodes(nodes):
    n = len(nodes)
    for nd in nodes:
        n += count_nodes(nd.get("children", []))
    return n
tree  = d.get("data", [])
total = count_nodes(tree)
ok    = (code == 200 and total == 3)
print(f"\n{'='*60}")
print(f"{'OK' if ok else 'XX'} TEST 1.7  GET nodes  ->  HTTP {code}  [{'PASS' if ok else 'FAIL'}]")
print(f"   Total nodes in tree: {total}  (expected 3)")
for n in tree:
    print(f"   L{n.get('hierarchy_level')} {n.get('name')!r}  children={len(n.get('children',[]))}")
    for c in n.get("children", []):
        print(f"     L{c.get('hierarchy_level')} {c.get('name')!r}  children={len(c.get('children',[]))}")
        for g in c.get("children", []):
            print(f"       L{g.get('hierarchy_level')} {g.get('name')!r}")
if not ok and code != 200:
    print(f"   Error: {json.dumps(d.get('detail', d.get('_raw','')))[:300]}")
results["TEST 1.7  GET nodes"] = ok


# ── TEST 1.8  Create position at L1 ──────────────────────────
code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes/{NODE1_ID}/positions", TA_JWT, {
    "title": "National Manager", "role_code": "NM"
})
POS1_ID = d.get("data", {}).get("id", "")
report("TEST 1.8  Create NM position (L1)", code, d, 201,
       f"id={POS1_ID}  title={d.get('data',{}).get('title')}  role={d.get('data',{}).get('role_code')}")


# ── TEST 1.9  Create position at L2 ──────────────────────────
code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes/{NODE2_ID}/positions", TA_JWT, {
    "title": "Regional Manager", "role_code": "RM"
})
POS2_ID = d.get("data", {}).get("id", "")
report("TEST 1.9  Create RM position (L2)", code, d, 201,
       f"id={POS2_ID}  title={d.get('data',{}).get('title')}  role={d.get('data',{}).get('role_code')}")


# ── TEST 1.10  Create position at L3 ─────────────────────────
code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes/{NODE3_ID}/positions", TA_JWT, {
    "title": "Warehouse Manager", "role_code": "WM"
})
POS3_ID = d.get("data", {}).get("id", "")
report("TEST 1.10 Create WM position (L3)", code, d, 201,
       f"id={POS3_ID}  title={d.get('data',{}).get('title')}  role={d.get('data',{}).get('role_code')}")


# ── TEST 1.11  GET positions (verify all 3) ───────────────────
code, d = curl("GET", f"/tenants/{TENANT_ID}/positions", TA_JWT)
groups    = d.get("data", [])
total_pos = sum(len(g.get("positions", [])) for g in groups)
ok = (code == 200 and total_pos == 3)
print(f"\n{'='*60}")
print(f"{'OK' if ok else 'XX'} TEST 1.11 GET positions  ->  HTTP {code}  [{'PASS' if ok else 'FAIL'}]")
print(f"   Total positions: {total_pos}  (expected 3)")
for g in groups:
    for pos in g.get("positions", []):
        print(f"   node={g.get('node_name')!r}  title={pos.get('title')!r}  role={pos.get('role_code')}")
if not ok and code != 200:
    print(f"   Error: {json.dumps(d.get('detail', d.get('_raw','')))[:300]}")
results["TEST 1.11 GET positions"] = ok


# ── TEST 1.12  Create NM user with position ───────────────────
code, d = curl("POST", f"/tenants/{TENANT_ID}/users", TA_JWT, {
    "name": "National Manager", "email": "nm@int-test.com",
    "password": "NMUser@2026", "position_id": POS1_ID
})
NM_USER_ID = d.get("data", {}).get("id", "")
pp = d.get("data", {}).get("primary_position")
report("TEST 1.12 Create NM user", code, d, 201,
       f"id={NM_USER_ID}  pos={pp.get('role_code') if pp else 'NONE'}@{pp.get('node_name') if pp else '?'}  must_reset={d.get('data',{}).get('must_reset_password')}")


# ── TEST 1.13  Create RM user with position ───────────────────
code, d = curl("POST", f"/tenants/{TENANT_ID}/users", TA_JWT, {
    "name": "Regional Manager", "email": "rm@int-test.com",
    "password": "RMUser@2026", "position_id": POS2_ID
})
RM_USER_ID = d.get("data", {}).get("id", "")
pp = d.get("data", {}).get("primary_position")
report("TEST 1.13 Create RM user", code, d, 201,
       f"id={RM_USER_ID}  pos={pp.get('role_code') if pp else 'NONE'}@{pp.get('node_name') if pp else '?'}")


# ── TEST 1.14  Create WM user with position ───────────────────
code, d = curl("POST", f"/tenants/{TENANT_ID}/users", TA_JWT, {
    "name": "Warehouse Manager", "email": "wm@int-test.com",
    "password": "WMUser@2026", "position_id": POS3_ID
})
WM_USER_ID = d.get("data", {}).get("id", "")
pp = d.get("data", {}).get("primary_position")
report("TEST 1.14 Create WM user", code, d, 201,
       f"id={WM_USER_ID}  pos={pp.get('role_code') if pp else 'NONE'}@{pp.get('node_name') if pp else '?'}")


# ── TEST 1.15  GET users (verify all 3) ──────────────────────
code, d = curl("GET", f"/tenants/{TENANT_ID}/users", TA_JWT)
users = d.get("data", [])
ok    = (code == 200 and len(users) >= 3)
print(f"\n{'='*60}")
print(f"{'OK' if ok else 'XX'} TEST 1.15 GET users  ->  HTTP {code}  [{'PASS' if ok else 'FAIL'}]")
print(f"   Total users returned: {len(users)}  (expected >=3)")
for u in users:
    pp = u.get("primary_position")
    print(f"   {u.get('email')}  role={u.get('role')}  pos={pp.get('role_code') if pp else 'none'}  active={u.get('is_active')}")
if not ok and code != 200:
    print(f"   Error: {json.dumps(d.get('detail', d.get('_raw','')))[:300]}")
results["TEST 1.15 GET users"] = ok


# ── TEST 1.16  NM login ───────────────────────────────────────
code, d = curl("POST", "/auth/token", body={
    "dev_email": "nm@int-test.com", "dev_password": "NMUser@2026"
})
nm_c = jwt_claims(d.get("access_token", ""))
report("TEST 1.16 NM login", code, d, 200,
       f"role={nm_c.get('role')}  warehouse_id={str(nm_c.get('warehouse_id',''))[:8]}...  "
       f"level={nm_c.get('level_number')}  must_reset={d.get('must_reset_password')}")


# ── TEST 1.17  RM login ───────────────────────────────────────
code, d = curl("POST", "/auth/token", body={
    "dev_email": "rm@int-test.com", "dev_password": "RMUser@2026"
})
rm_c = jwt_claims(d.get("access_token", ""))
report("TEST 1.17 RM login", code, d, 200,
       f"role={rm_c.get('role')}  warehouse_id={str(rm_c.get('warehouse_id',''))[:8]}...  "
       f"level={rm_c.get('level_number')}  must_reset={d.get('must_reset_password')}")


# ── TEST 1.18  WM login ───────────────────────────────────────
code, d = curl("POST", "/auth/token", body={
    "dev_email": "wm@int-test.com", "dev_password": "WMUser@2026"
})
wm_c = jwt_claims(d.get("access_token", ""))
report("TEST 1.18 WM login", code, d, 200,
       f"role={wm_c.get('role')}  warehouse_id={str(wm_c.get('warehouse_id',''))[:8]}...  "
       f"level={wm_c.get('level_number')}  must_reset={d.get('must_reset_password')}")


# ── SUMMARY ───────────────────────────────────────────────────
passed = sum(1 for v in results.values() if v)
total  = len(results)
failed = [k for k, v in results.items() if not v]

print(f"\n{'='*60}")
print(f"SUMMARY")
print(f"PASSED: {passed}/{total}")
print(f"FAILED: {total - passed}/{total}")
if failed:
    print("FAILURES:")
    for f in failed:
        print(f"  XX {f}")
else:
    print("All tests passed.")
