"""Integration test — Dynamic tenant positions in approval routing (PARTS A-H).

Creates a fresh test tenant with a 3-level hierarchy and custom position titles,
configures adjustment approval rules using approver_position_id, and verifies:
  TEST 1: GET /positions/flat returns custom titles + display_label
  TEST 2: PUT adjustment-approval-rules saves with non-null approver_position_id
  TEST 3: Routing by quantity resolves to the correct position holder
  TEST 4: Renaming a position keeps routing correct and reflects new title
  TEST 5: Tab 5 transfer-rule dropdown data shows full display_label, not bare role code

Cleans up the test tenant afterward.
"""
import subprocess, json

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
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    lines = r.stdout.strip().split("\n")
    code = int(lines[-1])
    raw = "\n".join(lines[:-1])
    try:
        data = json.loads(raw)
    except Exception:
        data = {"_raw": raw}
    return code, data


def report(label, ok, extra=""):
    icon = "OK" if ok else "XX"
    status = "PASS" if ok else "FAIL"
    print(f"\n{'='*60}")
    print(f"{icon} {label}  [{status}]")
    if extra:
        print(f"   {extra}")
    results[label] = ok
    return ok


# ── SETUP: SA JWT ─────────────────────────────────────────────
code, d = curl("POST", "/auth/token", body={
    "dev_email": "smartadmin@smart-inventory.com",
    "dev_password": "Admin@2026"
})
SA_JWT = d.get("access_token", "")
if not SA_JWT:
    print("FATAL: cannot obtain SA JWT")
    raise SystemExit(1)

# ── SETUP: create test tenant ────────────────────────────────
code, d = curl("POST", "/tenants/", SA_JWT, {
    "name": "Positions Dynamic Test Co",
    "slug": "pos-dyn-test",
    "organisation_type": "PRODUCER",
    "default_locale": "en",
})
TENANT = d.get("data", {})
TENANT_ID = TENANT.get("id", "")
print(f"SETUP: tenant_id={TENANT_ID}  (HTTP {code})")
if not TENANT_ID:
    print("FATAL: cannot create test tenant")
    raise SystemExit(1)

# admin user
code, d = curl("POST", f"/tenants/{TENANT_ID}/users", SA_JWT, {
    "name": "Pos Dyn Admin", "email": "admin@pos-dyn-test.com",
    "password": "PosDyn@2026", "system_role": "TA",
})
code, d = curl("POST", "/auth/token", body={
    "dev_email": "admin@pos-dyn-test.com", "dev_password": "PosDyn@2026"
})
TA_JWT = d.get("access_token", "")
print(f"SETUP: TA login (HTTP {code})")

# hierarchy config: HQ (L1), Region (L2), WH (L3)
code, d = curl("PUT", f"/tenants/{TENANT_ID}/hierarchy/config", TA_JWT, [
    {"level_number": 1, "level_name": "HQ",       "default_role_code": "NM"},
    {"level_number": 2, "level_name": "Region",   "default_role_code": "RM"},
    {"level_number": 3, "level_name": "Warehouse","default_role_code": "WM"},
])
print(f"SETUP: hierarchy config (HTTP {code})")

# nodes
code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes", TA_JWT, {
    "name": "HQ", "level_number": 1, "parent_node_id": None, "is_stock_holding": True,
})
NODE_HQ = d.get("data", {}).get("id", "")
code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes", TA_JWT, {
    "name": "Region", "level_number": 2, "parent_node_id": NODE_HQ, "is_stock_holding": True,
})
NODE_REGION = d.get("data", {}).get("id", "")
code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes", TA_JWT, {
    "name": "WH", "level_number": 3, "parent_node_id": NODE_REGION, "is_stock_holding": True,
})
NODE_WH = d.get("data", {}).get("id", "")
print(f"SETUP: nodes HQ={NODE_HQ[:8]} Region={NODE_REGION[:8]} WH={NODE_WH[:8]}")

# positions with custom titles (Executive Director / Deputy Director / Area Coordinator / Branch Officer)
code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes/{NODE_HQ}/positions", TA_JWT, {
    "title": "Executive Director", "role_code": "NM",
})
POS_ED = d.get("data", {}).get("id", "")

code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes/{NODE_HQ}/positions", TA_JWT, {
    "title": "Deputy Director", "role_code": "NM", "reports_to_position_id": POS_ED,
})
POS_DD = d.get("data", {}).get("id", "")

code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes/{NODE_REGION}/positions", TA_JWT, {
    "title": "Area Coordinator", "role_code": "RM", "reports_to_position_id": POS_DD,
})
POS_AC = d.get("data", {}).get("id", "")

code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes/{NODE_WH}/positions", TA_JWT, {
    "title": "Branch Officer", "role_code": "WM", "reports_to_position_id": POS_AC,
})
POS_BO = d.get("data", {}).get("id", "")

print(f"SETUP: positions ED={POS_ED[:8]} DD={POS_DD[:8]} AC={POS_AC[:8]} BO={POS_BO[:8]}")

# users + assign to positions
code, d = curl("POST", f"/tenants/{TENANT_ID}/users", TA_JWT, {
    "name": "Exec Director User", "email": "ed@pos-dyn-test.com",
    "password": "EdUser@2026", "position_id": POS_ED,
})
code, d = curl("POST", f"/tenants/{TENANT_ID}/users", TA_JWT, {
    "name": "Deputy Director User", "email": "dd@pos-dyn-test.com",
    "password": "DdUser@2026", "position_id": POS_DD,
})
code, d = curl("POST", f"/tenants/{TENANT_ID}/users", TA_JWT, {
    "name": "Area Coordinator User", "email": "ac@pos-dyn-test.com",
    "password": "AcUser@2026", "position_id": POS_AC,
})
code, d = curl("POST", f"/tenants/{TENANT_ID}/users", TA_JWT, {
    "name": "Branch Officer User", "email": "bo@pos-dyn-test.com",
    "password": "BoUser@2026", "position_id": POS_BO,
})
print(f"SETUP: 4 position-holder users created")


# ── TEST 1: GET /positions/flat ──────────────────────────────
def label_ok(dl, title, role, node, level):
    return (
        dl is not None
        and dl.startswith(f"{title} ({role})")
        and f"{node} (L{level})" in dl
        and dl != role
    )

code, d = curl("GET", f"/tenants/{TENANT_ID}/positions/flat", TA_JWT)
flat = d.get("data", [])
titles = {p.get("title") for p in flat}
expected_titles = {"Executive Director", "Deputy Director", "Area Coordinator", "Branch Officer"}
ed_row = next((p for p in flat if p.get("title") == "Executive Director"), None)
ok1 = (
    code == 200
    and len(flat) == 4
    and expected_titles.issubset(titles)
    and ed_row is not None
    and label_ok(ed_row.get("display_label"), "Executive Director", "NM", "HQ", 1)
)
report("TEST 1  GET /positions/flat returns 4 positions with custom titles", ok1,
       f"HTTP {code}  count={len(flat)}  titles={sorted(titles)}\n"
       f"   ED display_label={ed_row.get('display_label') if ed_row else None!r}")
for p in flat:
    print(f"     {p.get('display_label')}  reports_to={p.get('reports_to_title')}")


# ── TEST 2: PUT adjustment-approval-rules with position_id ───
# WM (Branch Officer, L3): within qty<=100 route to Area Coordinator position holder;
# above 100 -> default routing. Schema allows only ONE rule per
# (tenant, role_code, level_number, reason_code) — idx_adj_approval_unique.
adj_rules_body = [
    {
        "role_code": "WM", "level_number": 3, "mode": "GLOBAL",
        "reason_code": None,
        "threshold_type": "QUANTITY", "qty_limit": 100,
        "approver_role_code": "RM", "approver_position_id": POS_AC,
        "priority": 1, "is_active": True,
    },
]
code, d = curl("PUT", f"/tenants/{TENANT_ID}/adjustment-approval-rules", TA_JWT, adj_rules_body)
saved = d.get("data", [])
rule = saved[0] if saved else {}
ok2 = (
    code == 200
    and len(saved) == 1
    and rule.get("approver_position_id") is not None
    and rule.get("approver_position_title") == "Area Coordinator"
)
report("TEST 2  PUT adjustment-approval-rules saves non-null approver_position_id", ok2,
       f"HTTP {code}  rules={len(saved)}  position_id={str(rule.get('approver_position_id'))[:8]}  "
       f"position_title={rule.get('approver_position_title')}")


# ── TEST 3: Routing by quantity ──────────────────────────────
# Call check_adjustment_self_approval() directly (role=WM, level_number=3).
# qty=50 (within limit=100)  -> routes to Area Coordinator's PRIMARY holder
# qty=200 (exceeds limit=100) -> default routing (False, None, None)
proc = subprocess.run(
    ["python", "scripts/_check_adj_routing.py", TENANT_ID, "50", "200"],
    capture_output=True, text=True, timeout=30,
)
try:
    routing = json.loads(proc.stdout.strip().splitlines()[-1])
except Exception:
    routing = []
    print(f"   _check_adj_routing.py stdout={proc.stdout!r} stderr={proc.stderr!r}")

r50  = next((r for r in routing if r["qty"] == "50"), None)
r200 = next((r for r in routing if r["qty"] == "200"), None)

ok3a = (
    r50 is not None and r50["can_self_approve"] is False
    and r50["info"] is not None
    and r50["info"].get("approver_position_title") == "Area Coordinator"
)
ok3b = r200 is not None and r200 == {"qty": "200", "can_self_approve": False, "approver_role": None, "info": None}
ok3 = ok3a and ok3b
report("TEST 3  Routing by quantity resolves to correct position", ok3,
       f"qty=50 -> {r50}; qty=200 -> {r200} (expected default routing)")


# ── TEST 4: Rename Area Coordinator -> Zone Lead ─────────────
code, d = curl("PATCH", f"/tenants/{TENANT_ID}/positions/{POS_AC}", TA_JWT, {
    "title": "Zone Lead",
})
renamed_ok = (code == 200 and d.get("data", {}).get("title") == "Zone Lead")

# re-fetch adjustment rules — title should now reflect "Zone Lead"
code, d = curl("GET", f"/tenants/{TENANT_ID}/adjustment-approval-rules", TA_JWT)
saved2 = d.get("data", [])
r2 = next((r for r in saved2 if r.get("approver_position_id") == POS_AC), None)

# re-run routing for qty=50 — should now resolve to "Zone Lead"
proc = subprocess.run(
    ["python", "scripts/_check_adj_routing.py", TENANT_ID, "50"],
    capture_output=True, text=True, timeout=30,
)
try:
    routing2 = json.loads(proc.stdout.strip().splitlines()[-1])
except Exception:
    routing2 = []
    print(f"   _check_adj_routing.py stdout={proc.stdout!r} stderr={proc.stderr!r}")
r50b = next((r for r in routing2 if r["qty"] == "50"), None)

ok4 = (
    renamed_ok
    and r2 is not None
    and r2.get("approver_position_title") == "Zone Lead"
    and r50b is not None
    and r50b["info"] is not None
    and r50b["info"].get("approver_position_title") == "Zone Lead"
)
report("TEST 4  Renaming position keeps routing correct + shows new title", ok4,
       f"rename HTTP {code}  rule.approver_position_title={r2.get('approver_position_title') if r2 else None}  "
       f"routing(qty=50).approver_position_title={r50b['info'].get('approver_position_title') if r50b and r50b['info'] else None}")


# ── TEST 5: GET /positions/flat shows full display_label ─────
code, d = curl("GET", f"/tenants/{TENANT_ID}/positions/flat", TA_JWT)
flat2 = d.get("data", [])
ed_row2 = next((p for p in flat2 if p.get("title") == "Executive Director"), None)
ok5 = (
    code == 200
    and ed_row2 is not None
    and label_ok(ed_row2.get("display_label"), "Executive Director", "NM", "HQ", 1)
)
report("TEST 5  Transfer-rule position dropdown shows full display_label, not bare role code", ok5,
       f"display_label={ed_row2.get('display_label') if ed_row2 else None!r}")


# ── CLEANUP ───────────────────────────────────────────────────
print(f"\n{'='*60}")
print("CLEANUP: deleting test tenant via direct SQL (FK-safe order)")
cleanup_sql = f"""
DELETE FROM inventory_transactions WHERE tenant_id = '{TENANT_ID}';
DELETE FROM transfer_order_lines WHERE transfer_order_id IN (SELECT id FROM transfer_orders WHERE tenant_id = '{TENANT_ID}');
DELETE FROM transfer_orders WHERE tenant_id = '{TENANT_ID}';
DELETE FROM transfer_approval_rules WHERE tenant_id = '{TENANT_ID}';
DELETE FROM transfer_type_level_permissions WHERE tenant_id = '{TENANT_ID}';
DELETE FROM transfer_type_config WHERE tenant_id = '{TENANT_ID}';
DELETE FROM adjustment_approval_rules WHERE tenant_id = '{TENANT_ID}';
DELETE FROM personnel_positions WHERE tenant_id = '{TENANT_ID}';
DELETE FROM positions WHERE tenant_id = '{TENANT_ID}';
DELETE FROM org_node_hierarchy WHERE tenant_id = '{TENANT_ID}';
DELETE FROM organization_node WHERE tenant_id = '{TENANT_ID}';
DELETE FROM tenant_hierarchy_config WHERE tenant_id = '{TENANT_ID}';
DELETE FROM users WHERE tenant_id = '{TENANT_ID}';
DELETE FROM tenants WHERE id = '{TENANT_ID}';
"""
with open("scripts/_cleanup_pos_dyn.sql", "w") as f:
    f.write(cleanup_sql)
print("   wrote scripts/_cleanup_pos_dyn.sql — run it against the dev DB to finish cleanup.")


# ── SUMMARY ───────────────────────────────────────────────────
passed = sum(1 for v in results.values() if v)
total  = len(results)
print(f"\n{'='*60}")
print(f"SUMMARY: PASSED {passed}/{total}")
for k, v in results.items():
    print(f"  {'OK' if v else 'XX'} {k}")
