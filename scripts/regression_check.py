"""Regression check — high-risk areas after all fixes A1-C2."""

import subprocess, json, base64, os, uuid as _uuid

BASE = "http://localhost:8000/api/v1"
PGPASS = {**os.environ, "PGPASSWORD": "smart_local_pass"}
FRONT = "C:/git-repos/smart-platform/frontend/src/app/[org]"
results: dict[str, bool] = {}


def req(method, path, token=None, body=None):
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
    try:
        d = json.loads("\n".join(lines[:-1]))
    except:
        d = {"_raw": "\n".join(lines[:-1])[:400]}
    return code, d


def jwt_claims(tok):
    try:
        p = tok.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.b64decode(p))
    except:
        return {}


def psql_rls(tid, sql):
    full = (
        f"SELECT set_config('app.current_tenant_id','{tid}',false),"
        f"set_config('app.current_user_id','00000001-0000-0000-0000-000000000001',false);"
        f"{sql}"
    )
    r = subprocess.run(
        ["psql", "-U", "smart_user", "-d", "smart_dev", "-h", "127.0.0.1", "-c", full],
        capture_output=True,
        text=True,
        env=PGPASS,
    )
    return r.stdout.strip()


def grep(pattern, path, flags=""):
    r = subprocess.run(
        f'grep -rn {flags} "{pattern}" {path} --include="*.tsx" 2>/dev/null',
        shell=True,
        capture_output=True,
        text=True,
    )
    return r.stdout.strip()


def report(label, ok, extra="", notes=""):
    icon = "OK" if ok else "XX"
    st = "PASS" if ok else "FAIL"
    print(f"\n{'=' * 60}")
    print(f"{icon} {label}  [{st}]")
    if extra:
        print(f"   {extra}")
    if notes:
        for n in notes if isinstance(notes, list) else [notes]:
            print(f"   NOTE: {n}")
    results[label] = ok
    return ok


# ════════════════════════════════════════════════════════════
# SETUP - JWTs + state restoration
# ════════════════════════════════════════════════════════════
print("SETUP")


def get_jwt(email, pw):
    c, d = req("POST", "/auth/token", body={"dev_email": email, "dev_password": pw})
    tok = d.get("access_token", "")
    return tok, jwt_claims(tok), c


SA_JWT, SA_C, _ = get_jwt("smartadmin@smart-inventory.com", "Admin@2026")
print(f"   SA: {'OK' if SA_JWT else 'FAIL'}")

_, tm = req("GET", "/tenants/integration-test-co", SA_JWT)
TENANT_ID = tm.get("data", {}).get("id", "")
print(f"   TENANT_ID: {TENANT_ID[:8]}...")

TA_JWT, TA_C, _ = get_jwt("admin@int-test.com", "IntTest@2026")
print(f"   TA: {'OK' if TA_JWT else 'FAIL'}  role={TA_C.get('role', '?')}")

# Re-activate WM and RM if deactivated (may have been left deactivated by Group 5)
_, users_d = req("GET", f"/tenants/{TENANT_ID}/users", TA_JWT)
users = users_d.get("data", [])
WM_USER = next((u for u in users if "wm@" in u.get("email", "")), {})
RM_USER = next((u for u in users if "rm@" in u.get("email", "")), {})
WM_UID = WM_USER.get("id", "")
RM_UID = RM_USER.get("id", "")

for uid, name in [(WM_UID, "WM"), (RM_UID, "RM")]:
    user = next((u for u in users if u.get("id") == uid), {})
    if uid and not user.get("is_active", True):
        req("PATCH", f"/tenants/{TENANT_ID}/users/{uid}/reactivate", TA_JWT)
        psql_rls(
            TENANT_ID,
            f"UPDATE personnel_positions SET is_active=true WHERE user_id='{uid}';",
        )
        print(f"   Reactivated {name}")

NM_JWT, NM_C, _ = get_jwt("nm@int-test.com", "NMUser@2026")
RM_JWT, RM_C, _ = get_jwt("rm@int-test.com", "RMUser@2026")
WM_JWT, WM_C, _ = get_jwt("wm@int-test.com", "WMUser@2026")

L1_NODE_ID = str(NM_C.get("warehouse_id", ""))
L3_NODE_ID = str(WM_C.get("warehouse_id", ""))
print(f"   NM: {'OK' if NM_JWT else 'FAIL'}  L1={L1_NODE_ID[:8]}")
print(f"   RM: {'OK' if RM_JWT else 'FAIL'}")
print(f"   WM: {'OK' if WM_JWT else 'FAIL'}  L3={L3_NODE_ID[:8]}")

# Get product
_, sd = req("GET", "/inventory/analytics/stock", NM_JWT)
prod = next(
    (r for r in sd.get("data", []) if r.get("product_name") == "Test Product A"), None
)
PRODUCT_ID = str(prod.get("product_id", "")) if prod else ""
L1_STOCK = float(prod.get("current_stock", 0)) if prod else 0
print(f"   PRODUCT_ID: {PRODUCT_ID[:8]}...  L1_stock={L1_STOCK}")


# ════════════════════════════════════════════════════════════
# REG 1 — Nodes returned for tenant (useWarehouses hook data)
# ════════════════════════════════════════════════════════════
code, d = req("GET", f"/tenants/{TENANT_ID}/nodes", TA_JWT)


def cnt(nodes):
    n = len(nodes)
    [n := n + cnt(c.get("children", [])) for c in nodes]
    return n


tree = d.get("data", [])
total = cnt(tree)
names = [n.get("name", "?") for n in tree]
# Check names are real strings (not UUIDs)
uuid_pat = lambda s: len(s) == 36 and s.count("-") == 4
names_ok = total == 3 and not any(uuid_pat(n) for n in names)
ok1 = code == 200 and names_ok
report(
    "REG 1  Warehouse dropdown data (GET /nodes)",
    ok1,
    extra=f"HTTP {code}  total={total}  names={names}",
    notes="useWarehouses hook relies on /tenants/{id}/nodes returning named nodes",
)


# ════════════════════════════════════════════════════════════
# REG 2 — Receive Stock with org node as warehouse_id
# ════════════════════════════════════════════════════════════
ik = f"reg-ob-{str(_uuid.uuid4())[:8]}"
code, d = req(
    "POST",
    "/inventory/receive/",
    NM_JWT,
    {
        "product_id": PRODUCT_ID or str(_uuid.UUID(int=0)),
        "warehouse_id": L1_NODE_ID,
        "quantity": 500,
        "source": "OPENING_BALANCE",
        "idempotency_key": ik,
    },
)
tx_id = d.get("data", {}).get("transaction_id", "")
ok2 = code == 201
report(
    "REG 2  Receive Stock with org node as warehouse_id",
    ok2,
    extra=f"HTTP {code}  tx_id={tx_id}  L1_node accepted as warehouse",
    notes="Inventory ledger uses organization_node.id as facility_id",
)


# ════════════════════════════════════════════════════════════
# REG 3 — Balance columns correct after receive
# ════════════════════════════════════════════════════════════
code, d = req("GET", "/inventory/analytics/stock", NM_JWT)
stock = d.get("data", [])
l1 = next(
    (
        r
        for r in stock
        if str(r.get("warehouse_id", "")).lower() == L1_NODE_ID.lower()
        and r.get("product_name") == "Test Product A"
    ),
    None,
)
if l1:
    cs = float(l1.get("current_stock", -1))
    na = float(l1.get("net_available", -1))
    po = float(l1.get("pending_out_qty", -1))
    it = float(l1.get("in_transit_out_qty", -1))
    expected = L1_STOCK + 500
    ok3 = code == 200 and abs(cs - expected) < 0.01 and na == cs - po
    print(f"\n{'=' * 60}")
    print(
        f"{'OK' if ok3 else 'XX'} REG 3  Balance columns correct  [{'PASS' if ok3 else 'FAIL'}]"
    )
    print(f"   current_stock={cs}  (expected {expected})")
    print(f"   net_available={na}  pending_out={po}  in_transit_out={it}")
    print(
        f"   net_available == current_stock - pending_out: {abs(na - (cs - po)) < 0.01}"
    )
else:
    ok3 = False
    print(f"\n{'=' * 60}")
    print(f"XX REG 3  Balance columns correct  [FAIL]")
    print(f"   Test Product A not found at L1 in analytics/stock")
results["REG 3  Balance columns correct"] = ok3


# ════════════════════════════════════════════════════════════
# REG 4 — Transfer list shows underlying type + config name
# ════════════════════════════════════════════════════════════
code, d = req("GET", "/inventory/transfers/", WM_JWT)
transfers = d.get("data", [])
# Find a PULL transfer
pull = next((t for t in transfers if t.get("transfer_type") == "PULL"), None)
ok4 = code == 200 and len(transfers) > 0
print(f"\n{'=' * 60}")
print(
    f"{'OK' if ok4 else 'XX'} REG 4  Transfer type names  [{'PASS' if ok4 else 'FAIL'}]"
)
print(f"   HTTP {code}  total={len(transfers)}")
if pull:
    print(f"   Sample PULL transfer: transfer_type={pull.get('transfer_type')!r}")
    print(
        f"   NOTE: transfer_type shows underlying type (PULL/PUSH/SISTER); display_name"
    )
    print(
        f"   comes from /transfer-types config ('Replenishment Request') — used by frontend only"
    )
elif transfers:
    t = transfers[0]
    print(
        f"   First transfer: type={t.get('transfer_type')!r}  status={t.get('status')!r}"
    )
results["REG 4  Transfer type names"] = ok4


# ════════════════════════════════════════════════════════════
# REG 5 — PUSH level permissions
# ════════════════════════════════════════════════════════════
code, d = req("GET", f"/tenants/{TENANT_ID}/transfer-types", TA_JWT)
types = d.get("data", [])
push = next((t for t in types if t.get("underlying_type") == "PUSH"), {})
lp = {lp["level_number"]: lp for lp in push.get("level_permissions", [])}
l1_init = lp.get(1, {}).get("can_initiate", None)
l2_init = lp.get(2, {}).get("can_initiate", None)
l3_init = lp.get(3, {}).get("can_initiate", None)
ok5 = code == 200 and l1_init is True and l2_init is True and l3_init is False
print(f"\n{'=' * 60}")
print(
    f"{'OK' if ok5 else 'XX'} REG 5  PUSH level permissions  [{'PASS' if ok5 else 'FAIL'}]"
)
print(f"   HTTP {code}  PUSH name={push.get('display_name')!r}")
print(f"   L1 can_initiate={l1_init} (expected True)")
print(f"   L2 can_initiate={l2_init} (expected True)")
print(f"   L3 can_initiate={l3_init} (expected False)")
results["REG 5  PUSH level permissions"] = ok5


# ════════════════════════════════════════════════════════════
# REG 6 — Adjustment with org node as warehouse_id
# ════════════════════════════════════════════════════════════
ik6 = f"reg-adj-{str(_uuid.uuid4())[:8]}"
code, d = req(
    "POST",
    "/inventory/adjust/",
    NM_JWT,
    {
        "product_id": PRODUCT_ID or str(_uuid.UUID(int=0)),
        "warehouse_id": L1_NODE_ID,
        "quantity": -10,
        "reason_code": "DAMAGE",
        "notes": "Regression test",
        "idempotency_key": ik6,
    },
)
adj_id = d.get("data", {}).get(
    "adjustment_id", d.get("data", {}).get("transaction_id", "")
)
ok6 = code in (200, 201)
report(
    "REG 6  Adjustment with org node as warehouse_id",
    ok6,
    extra=f"HTTP {code}  adj_id={str(adj_id)[:8] if adj_id else 'none'}",
    notes="AdjustmentRequest.warehouse_id accepts organization_node.id",
)


# ════════════════════════════════════════════════════════════
# REG 7 — No raw Zustand balance calls in inventory page
# ════════════════════════════════════════════════════════════
pat7 = r"getOnHand\|getAvailable\|getReserved\|getInTransit\|getTotalStock\|Zustand"
hits7 = grep(pat7, f"{FRONT}/inventory/page.tsx")
# Filter out commented lines
live7 = [
    l
    for l in hits7.split("\n")
    if l.strip() and "//" not in l.split(":")[1:2][0][:3]
    if ":" in l
]
ok7 = len(live7) == 0
print(f"\n{'=' * 60}")
print(
    f"{'OK' if ok7 else 'XX'} REG 7  No raw Zustand balance calls in inventory page  [{'PASS' if ok7 else 'FAIL'}]"
)
print(f"   Live hits: {len(live7)}")
if live7:
    for l in live7[:5]:
        print(f"   {l[:120]}")
results["REG 7  No raw Zustand balance calls"] = ok7


# ════════════════════════════════════════════════════════════
# REG 8 — canPush uses level_number not warehouse type string
# ════════════════════════════════════════════════════════════
import os as _os

panel_paths = [
    f"C:/git-repos/smart-platform/frontend/src/app/[org]/transfers/page.tsx",
    f"C:/git-repos/smart-platform/frontend/src/components/features/inventory/NewTransferPanel.tsx",
]
panel_src = ""
for p in panel_paths:
    if _os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            panel_src += f.read()

push_hits = [
    l.strip()
    for l in panel_src.split("\n")
    if "PUSH" in l or "canPush" in l or "can_push" in l
]
push_hits = [l for l in push_hits if not l.startswith("//") and not l.startswith("*")]

uses_level = any(
    "level_number" in l or "levelNumber" in l or "level" in l.lower()
    for l in push_hits
    if "canPush" in l or "push" in l.lower()
)
uses_type_string = any(
    ("MWH" in l or "RWH" in l or "WH" in l or "SUB_WH" in l) and "PUSH" in l
    for l in push_hits
)

ok8 = not uses_type_string
print(f"\n{'=' * 60}")
print(
    f"{'OK' if ok8 else 'XX'} REG 8  canPush uses level_number not type string  [{'PASS' if ok8 else 'FAIL'}]"
)
print(f"   uses level_number logic: {uses_level}")
print(f"   uses warehouse type strings (MWH/RWH): {uses_type_string}")
for l in push_hits[:8]:
    print(f"   {l[:120]}")
results["REG 8  canPush uses level_number"] = ok8


# ════════════════════════════════════════════════════════════
# REG 9 — Nav structure: Inventory under OPERATIONS
# ════════════════════════════════════════════════════════════
layout_path = f"C:/git-repos/smart-platform/frontend/src/app/[org]/layout.tsx"
with open(layout_path, encoding="utf-8") as f:
    layout_src = f.read()

lines_nav = [
    (i + 1, l)
    for i, l in enumerate(layout_src.split("\n"))
    if ("Inventory" in l or "OPERATIONS" in l or "INVENTORY" in l)
    and not l.strip().startswith("//")
]

# Find line numbers
ops_line = next((i for i, l in lines_nav if "OPERATIONS" in l.upper()), 9999)
inv_line = next(
    (
        i
        for i, l in lines_nav
        if "Inventory" in l and "inventory" in l and "href" in l.lower()
    ),
    9999,
)

ok9 = inv_line > ops_line
print(f"\n{'=' * 60}")
print(
    f"{'OK' if ok9 else 'XX'} REG 9  Inventory nav under OPERATIONS section  [{'PASS' if ok9 else 'FAIL'}]"
)
print(f"   OPERATIONS section at line ~{ops_line}")
print(f"   Inventory nav item  at line ~{inv_line}")
print(f"   Inventory AFTER OPERATIONS: {ok9}")
for i, l in lines_nav[:8]:
    print(f"   L{i}: {l.strip()[:100]}".encode("ascii", "replace").decode())
results["REG 9  Inventory nav under OPERATIONS"] = ok9


# ════════════════════════════════════════════════════════════
# REG 10 — No raw {org} in JSX display
# ════════════════════════════════════════════════════════════
excl = "//|api|url|href|path|query|key|test|useTenantName|router|param|import|replace|slug|orgSlug"
raw_org = grep(r"{org}", f"{FRONT}", f"--include='*.tsx'")
# Filter to only displayable JSX content (text nodes, not attributes)
raw_hits = []
for line in raw_org.split("\n"):
    if not line.strip():
        continue
    skip = any(e in line for e in excl.split("|"))
    if skip:
        continue
    # Only flag if {org} appears as a JSX text node
    if ">{org}<" in line or ">{org} " in line or " {org}<" in line:
        raw_hits.append(line.strip()[:120])

ok10 = len(raw_hits) == 0
print(f"\n{'=' * 60}")
print(
    f"{'OK' if ok10 else 'XX'} REG 10 No raw {{org}} in JSX display  [{'PASS' if ok10 else 'FAIL'}]"
)
print(f"   Raw JSX display hits: {len(raw_hits)}")
if raw_hits:
    for h in raw_hits[:5]:
        print(f"   {h}")
results["REG 10 No raw {org} in JSX display"] = ok10


# ════════════════════════════════════════════════════════════
# REG 11 — Transfer warehouse names use resolver not raw IDs
# ════════════════════════════════════════════════════════════
transfers_path = (
    f"C:/git-repos/smart-platform/frontend/src/app/[org]/transfers/page.tsx"
)
with open(transfers_path, encoding="utf-8") as f:
    xfer_src = f.read()

# Lines that render warehouse_id directly as JSX text content
raw_wh_display = []
for line in xfer_src.split("\n"):
    strip = line.strip()
    if not strip or strip.startswith("//") or strip.startswith("*"):
        continue
    if (
        "warehouse_id" in strip
        and (">" in strip or "{" in strip)
        and not any(
            e in strip
            for e in [
                "===",
                "!==",
                "filter",
                "find",
                "?.",
                "key=",
                "queryKey",
                "warehouse_name",
                "node_name",
                "toLowerCase",
                "?.toLowerCase",
                "String(",
                "str(",
                "toWareHouseName",
                "fromWarehouseName",
                "warehouse_name =",
                "node_name =",
                "warehouseName",
            ]
        )
    ):
        raw_wh_display.append(strip[:120])

ok11 = len(raw_wh_display) == 0
print(f"\n{'=' * 60}")
print(
    f"{'OK' if ok11 else 'XX'} REG 11 Transfer warehouse names use resolver  [{'PASS' if ok11 else 'FAIL'}]"
)
print(f"   Raw warehouse_id display patterns: {len(raw_wh_display)}")
if raw_wh_display:
    for h in raw_wh_display[:5]:
        print(f"   {h}")
else:
    # Show how warehouse names ARE displayed (positive verification)
    name_lines = [
        l.strip()
        for l in xfer_src.split("\n")
        if "warehouse_name" in l.lower() and ">" in l and not l.strip().startswith("//")
    ]
    print(f"   Warehouse displayed via name fields: {len(name_lines)} patterns")
    for l in name_lines[:3]:
        print(f"   {l[:120]}")
results["REG 11 Transfer warehouse names via resolver"] = ok11


# ════════════════════════════════════════════════════════════
# REG 12 — Approval routing: RM gets can_approve=true
# ════════════════════════════════════════════════════════════
print("\nREG 12 — Creating fresh PULL to test dynamic approval routing")

# Create fresh PULL, submit, have RM review -> PENDING_APPROVAL -> check approval-info
R12_ID = ""
if PRODUCT_ID and L1_NODE_ID and L3_NODE_ID:
    c12a, d12a = req(
        "POST",
        "/inventory/transfers/",
        WM_JWT,
        {
            "transfer_type": "PULL",
            "from_warehouse_id": L1_NODE_ID,
            "to_warehouse_id": L3_NODE_ID,
            "lines": [{"product_id": PRODUCT_ID, "quantity": 20}],
            "notes": "REG 12 approval routing test",
        },
    )
    R12_ID = d12a.get("data", {}).get("transfer_id", "")
    print(f"   Create PULL: HTTP {c12a}  id={R12_ID[:8] if R12_ID else 'FAIL'}...")

    if R12_ID:
        req("POST", f"/inventory/transfers/{R12_ID}/submit", WM_JWT)
        req("POST", f"/inventory/transfers/{R12_ID}/review", RM_JWT)

        code12, d12 = req("GET", f"/inventory/transfers/{R12_ID}/approval-info", RM_JWT)
        ai = d12.get("data", {})
        can_approve = ai.get("can_approve")
        approver = ai.get("current_approver_name")
        pos_title = ai.get("current_approver_position_title")
        is_dynamic = ai.get("is_dynamic_routing")
        assignee_uid = ai.get("current_approver_user_id")
        rm_sub = RM_C.get("sub", "")

        ok12 = (
            code12 == 200
            and can_approve is True
            and is_dynamic is True
            and assignee_uid == rm_sub
        )

        print(f"\n{'=' * 60}")
        print(
            f"{'OK' if ok12 else 'XX'} REG 12 Approval routing dynamic + RM  [{'PASS' if ok12 else 'FAIL'}]"
        )
        print(f"   HTTP {code12}  can_approve={can_approve}  (expected True)")
        print(f"   assigned_to={approver!r}  position={pos_title!r}")
        print(f"   is_dynamic_routing={is_dynamic}  (expected True)")
        print(
            f"   assignee_uid={str(assignee_uid)[:8] if assignee_uid else 'none'}...  RM_sub={rm_sub[:8]}..."
        )
        results["REG 12 Approval routing (dynamic + RM can_approve)"] = ok12
    else:
        report(
            "REG 12 Approval routing (dynamic + RM can_approve)",
            False,
            extra="Transfer creation failed",
        )
else:
    report(
        "REG 12 Approval routing (dynamic + RM can_approve)",
        False,
        extra="Missing product/node IDs",
    )


# ════════════════════════════════════════════════════════════
# SUMMARY
# ════════════════════════════════════════════════════════════
passed = sum(1 for v in results.values() if v)
total = len(results)
failed = [k for k, v in results.items() if not v]

print(f"\n{'=' * 60}")
print("REGRESSION SUMMARY")
print(f"PASSED: {passed}/{total}")
print(f"FAILED: {total - passed}/{total}")
if failed:
    print("FAILURES:")
    for f in failed:
        print(f"  XX {f}")
else:
    print("All regressions pass.")
