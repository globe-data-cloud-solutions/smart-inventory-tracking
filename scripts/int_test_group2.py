"""Integration Test Group 2 — Transfer types and approval rules.
Requires Group 1 tenant (Integration Test Co / admin@int-test.com) to exist.
"""
import subprocess, json, base64

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

def report(label, code, data, expect_code, extra=""):
    ok = code == expect_code
    icon   = "OK" if ok else "XX"
    status = "PASS" if ok else "FAIL"
    print(f"\n{'='*60}")
    print(f"{icon} {label}  ->  HTTP {code}  [{status}]")
    if extra:
        print(f"   {extra}")
    if not ok:
        detail = data.get("detail", data.get("error", data.get("_raw", "")))
        print(f"   Error: {json.dumps(detail)[:400]}")
    results[label] = ok
    return ok


# ── SETUP: Get JWTs ──────────────────────────────────────────
print("SETUP")

def get_jwt(email, password, label):
    c, d = curl("POST", "/auth/token", body={"dev_email": email, "dev_password": password})
    tok = d.get("access_token", "")
    cl  = jwt_claims(tok)
    print(f"   {label}: role={cl.get('role')}  {'obtained ' + tok[:20] + '...' if tok else 'FAILED'}")
    return tok

TA_JWT = get_jwt("admin@int-test.com", "IntTest@2026", "TA JWT")
NM_JWT = get_jwt("nm@int-test.com",    "NMUser@2026",  "NM JWT")
WM_JWT = get_jwt("wm@int-test.com",    "WMUser@2026",  "WM JWT")

# Resolve tenant ID from slug (accept both UUID or slug)
_, tm = curl("GET", "/tenants/integration-test-co", TA_JWT)
TENANT_ID = tm.get("data", {}).get("id", "")
print(f"   TENANT_ID: {TENANT_ID}")

if not TENANT_ID:
    print("\nFATAL: Cannot resolve tenant. Was Group 1 run successfully?")
    raise SystemExit(1)

NM_CLAIMS = jwt_claims(NM_JWT)
WM_CLAIMS = jwt_claims(WM_JWT)
NM_LEVEL  = NM_CLAIMS.get("level_number")  # 1
WM_LEVEL  = WM_CLAIMS.get("level_number")  # 3


# ── TEST 2.1  Configure transfer types ───────────────────────
# PULL = WM (L3) initiates, NM (L1) cannot initiate
# PUSH = NM (L1) initiates, WM (L3) cannot initiate
PULL_LEVELS = [
    {"level_number": 1, "can_initiate": False, "can_receive": False},
    {"level_number": 2, "can_initiate": False, "can_receive": True},
    {"level_number": 3, "can_initiate": True,  "can_receive": False},
]
PUSH_LEVELS = [
    {"level_number": 1, "can_initiate": True,  "can_receive": False},
    {"level_number": 2, "can_initiate": False,  "can_receive": True},
    {"level_number": 3, "can_initiate": False, "can_receive": True},
]
code, d = curl("PUT", f"/tenants/{TENANT_ID}/transfer-types", TA_JWT, [
    {
        "underlying_type": "PULL",
        "display_name":    "Replenishment Request",
        "description":     "WM requests stock from higher level",
        "is_active":       True,
        "sort_order":      1,
        "level_permissions": PULL_LEVELS,
    },
    {
        "underlying_type": "PUSH",
        "display_name":    "Stock Allocation",
        "description":     "NM pushes stock down to lower levels",
        "is_active":       True,
        "sort_order":      2,
        "level_permissions": PUSH_LEVELS,
    },
])
saved = d.get("data", [])
names = [t.get("display_name") for t in saved]
report("TEST 2.1  Configure transfer types (PULL+PUSH)", code, d, 200,
       f"saved {len(saved)} types: {names}")

# extract IDs for later
PULL_CONFIG_ID = next((t["id"] for t in saved if t.get("underlying_type") == "PULL"), "")
PUSH_CONFIG_ID = next((t["id"] for t in saved if t.get("underlying_type") == "PUSH"), "")
print(f"   PULL_CONFIG_ID={PULL_CONFIG_ID[:8]}...  PUSH_CONFIG_ID={PUSH_CONFIG_ID[:8]}...")


# ── TEST 2.2  GET transfer types ─────────────────────────────
code, d = curl("GET", f"/tenants/{TENANT_ID}/transfer-types", TA_JWT)
types_list = d.get("data", [])
ok = code == 200 and len(types_list) == 2

# Validate display names and key level permissions
pull_type = next((t for t in types_list if t.get("underlying_type") == "PULL"), {})
push_type = next((t for t in types_list if t.get("underlying_type") == "PUSH"), {})

pull_lp = {lp["level_number"]: lp for lp in pull_type.get("level_permissions", [])}
push_lp = {lp["level_number"]: lp for lp in push_type.get("level_permissions", [])}

pull_name_ok  = pull_type.get("display_name") == "Replenishment Request"
push_name_ok  = push_type.get("display_name") == "Stock Allocation"
pull_l3_init  = pull_lp.get(3, {}).get("can_initiate", False)   # WM can initiate PULL
push_l1_init  = push_lp.get(1, {}).get("can_initiate", False)   # NM can initiate PUSH
pull_l1_noinit = not pull_lp.get(1, {}).get("can_initiate", True)  # NM cannot initiate PULL
push_l3_noinit = not push_lp.get(3, {}).get("can_initiate", True)  # WM cannot initiate PUSH

all_ok = ok and pull_name_ok and push_name_ok

print(f"\n{'='*60}")
print(f"{'OK' if all_ok else 'XX'} TEST 2.2  GET transfer types  ->  HTTP {code}  [{'PASS' if all_ok else 'FAIL'}]")
print(f"   Types returned: {len(types_list)}")
print(f"   PULL display_name={pull_type.get('display_name')!r}  name_ok={pull_name_ok}")
print(f"   PUSH display_name={push_type.get('display_name')!r}  name_ok={push_name_ok}")
print(f"   PULL level_permissions: {[{lp['level_number']:lp.get('can_initiate')} for lp in pull_type.get('level_permissions',[])[:5]]}")
print(f"   PUSH level_permissions: {[{lp['level_number']:lp.get('can_initiate')} for lp in push_type.get('level_permissions',[])[:5]]}")
if not all_ok and code != 200:
    print(f"   Error: {json.dumps(d.get('detail', d.get('_raw','')))[:300]}")
results["TEST 2.2  GET transfer types"] = all_ok


# ── TEST 2.3  Configure approval rules ───────────────────────
# PULL from L3 (Warehouse) -> L1 (National): RM at step 1
if not PULL_CONFIG_ID:
    print(f"\n{'='*60}")
    print("XX TEST 2.3  Configure approval rules  ->  SKIPPED (no PULL config ID from 2.1)")
    results["TEST 2.3  Configure approval rules"] = False
else:
    code, d = curl("PUT", f"/tenants/{TENANT_ID}/transfer-approval-rules", TA_JWT, [
        {
            "transfer_type_config_id": PULL_CONFIG_ID,
            "source_level":      3,
            "destination_level": 1,
            "quantity_min":      0,
            "quantity_max":      None,
            "threshold_type":    "QUANTITY",
            "currency":          "ETB",
            "priority":          1,
            "is_active":         True,
            "approval_steps": [
                {
                    "sequence":       1,
                    "position_title": "Regional Manager",
                    "resolution":     "ANY",
                    "execution_mode": "SEQUENTIAL",
                    "sla_hours":      24,
                }
            ],
        }
    ])
    rules = d.get("data", [])
    rule0 = rules[0] if rules else {}
    steps = rule0.get("approval_steps", [])
    report("TEST 2.3  Configure approval rules", code, d, 200,
           f"rules={len(rules)}  src_level={rule0.get('source_level')}->dst_level={rule0.get('destination_level')}  "
           f"steps={len(steps)}  step1_title={steps[0].get('position_title') if steps else 'none'}")


# ── TEST 2.4  GET approval rules ─────────────────────────────
code, d = curl("GET", f"/tenants/{TENANT_ID}/transfer-approval-rules", TA_JWT)
rules = d.get("data", [])
rule0 = rules[0] if rules else {}
steps = rule0.get("approval_steps", [])

ok = (
    code == 200
    and len(rules) == 1
    and rule0.get("source_level") == 3
    and rule0.get("destination_level") == 1
    and len(steps) == 1
    and (steps[0].get("position_title") == "Regional Manager" if steps else False)
)
print(f"\n{'='*60}")
print(f"{'OK' if ok else 'XX'} TEST 2.4  GET approval rules  ->  HTTP {code}  [{'PASS' if ok else 'FAIL'}]")
print(f"   Rules returned: {len(rules)}")
if rule0:
    print(f"   Rule: type={rule0.get('transfer_type_name')!r}  "
          f"L{rule0.get('source_level')}->{rule0.get('destination_level')}  "
          f"({rule0.get('source_level_name')} -> {rule0.get('dest_level_name')})")
    print(f"   approval_steps: {json.dumps(steps)}")
if not ok and code != 200:
    print(f"   Error: {json.dumps(d.get('detail', d.get('_raw','')))[:300]}")
results["TEST 2.4  GET approval rules"] = ok


# ── TEST 2.5  Verify level permissions ───────────────────────
# Check level_permissions in the GET response to confirm:
#   WM (L3) can_initiate PULL   = True
#   WM (L3) can_initiate PUSH   = False
#   NM (L1) can_initiate PUSH   = True
#   NM (L1) can_initiate PULL   = False

# Use the data already fetched in TEST 2.2
check_wm_pull  = pull_lp.get(3, {}).get("can_initiate", "missing")
check_wm_push  = push_lp.get(3, {}).get("can_initiate", "missing")
check_nm_push  = push_lp.get(1, {}).get("can_initiate", "missing")
check_nm_pull  = pull_lp.get(1, {}).get("can_initiate", "missing")

wm_pull_ok  = check_wm_pull  is True
wm_push_ok  = check_wm_push  is False
nm_push_ok  = check_nm_push  is True
nm_pull_ok  = check_nm_pull  is False
all_checks  = wm_pull_ok and wm_push_ok and nm_push_ok and nm_pull_ok

# Also confirm JWT level numbers match expected hierarchy
nm_level_ok = (NM_LEVEL == 1)
wm_level_ok = (WM_LEVEL == 3)

ok = all_checks and nm_level_ok and wm_level_ok
print(f"\n{'='*60}")
print(f"{'OK' if ok else 'XX'} TEST 2.5  Verify level permissions  ->  [{'PASS' if ok else 'FAIL'}]")
print(f"   NM JWT level={NM_LEVEL}  (expected 1)  {'OK' if nm_level_ok else 'FAIL'}")
print(f"   WM JWT level={WM_LEVEL}  (expected 3)  {'OK' if wm_level_ok else 'FAIL'}")
print(f"   WM (L3) can_initiate PULL  = {check_wm_pull}  expected True   {'OK' if wm_pull_ok  else 'FAIL'}")
print(f"   WM (L3) can_initiate PUSH  = {check_wm_push}  expected False  {'OK' if wm_push_ok  else 'FAIL'}")
print(f"   NM (L1) can_initiate PUSH  = {check_nm_push}  expected True   {'OK' if nm_push_ok  else 'FAIL'}")
print(f"   NM (L1) can_initiate PULL  = {check_nm_pull}  expected False  {'OK' if nm_pull_ok  else 'FAIL'}")
results["TEST 2.5  Verify level permissions"] = ok


# ── SUMMARY ───────────────────────────────────────────────────
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
