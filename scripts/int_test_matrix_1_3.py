"""MATRIX 1 / 2 / 2B / 3 / 3B / 4 — FIX1 (ADJUSTMENT required-approver gate) +
FIX2 (creator==approver escalation for PUSH/PULL Design-B overrides).
Report only — cleans up after."""

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


def check(label, ok, extra=""):
    icon = "OK" if ok else "XX"
    print(
        f"{icon} {label}  [{'PASS' if ok else 'FAIL'}]"
        + (f"  {extra}" if extra else "")
    )
    results[label] = ok
    return ok


def get_jwt(email, pw):
    c, d = curl("POST", "/auth/token", body={"dev_email": email, "dev_password": pw})
    tok = d.get("access_token", "")
    return tok, jwt_claims(tok)


def psql(sql):
    full = (
        f"SELECT set_config('app.current_tenant_id','{TENANT_ID}',false),"
        f"set_config('app.current_user_id','00000001-0000-0000-0000-000000000001',false);"
        f"{sql}"
    )
    r = subprocess.run(
        [
            "psql",
            "-U",
            "smart_user",
            "-d",
            "smart_dev",
            "-h",
            "127.0.0.1",
            "-t",
            "-A",
            "-c",
            full,
        ],
        capture_output=True,
        text=True,
        env={**os.environ, **PGPASS},
    )
    return r.stdout.strip(), r.stderr.strip()


def transfer_flags(transfer_id):
    """Returns (status, is_self_approved, product_override_applied) for a transfer."""
    out, _ = psql(
        f"SELECT status, is_self_approved, product_override_applied "
        f"FROM transfer_orders WHERE id = '{transfer_id}';"
    )
    lines = [l for l in out.splitlines() if l.strip()]
    if not lines:
        return None, None, None
    parts = lines[-1].split("|")
    status = parts[0].strip()
    is_self = parts[1].strip() if len(parts) > 1 else ""
    override_applied = parts[2].strip() if len(parts) > 2 else ""
    return status, (is_self == "t"), (override_applied == "t")


def adjustment_flags(adjustment_id):
    """Returns (status, product_override_applied, required_approver_name, approver_escalated)."""
    out, _ = psql(
        f"SELECT status, product_override_applied, required_approver_name, approver_escalated "
        f"FROM adjustment_orders WHERE id = '{adjustment_id}';"
    )
    lines = [l for l in out.splitlines() if l.strip()]
    if not lines:
        return None, None, None, None
    parts = lines[-1].split("|")
    status = parts[0].strip()
    override_applied = parts[1].strip() if len(parts) > 1 else ""
    required_name = parts[2].strip() if len(parts) > 2 else ""
    escalated = parts[3].strip() if len(parts) > 3 else ""
    return status, (override_applied == "t"), required_name, (escalated == "t")


# ════════════════════════════════════════════════════════════════════════
# SETUP
# ════════════════════════════════════════════════════════════════════════
print("\n" + "#" * 70)
print("# SETUP — Matrix 1/2/2B/3/3B/4 Integration Test tenant")
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
        "name": "Matrix Test 13",
        "slug": "matrix-test-13",
        "organisation_type": "PRODUCER",
        "default_locale": "en",
        "admin_name": "Matrix13 Admin",
        "admin_email": "admin@matrix13-test.com",
        "admin_password": "Matrix13@2026",
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
        "name": "Matrix13 Admin",
        "email": "admin@matrix13-test.com",
        "password": "Matrix13@2026",
        "system_role": "TA",
    },
)
print(f"SETUP — Create TA user: HTTP {code}")

TA_JWT, ta_c = get_jwt("admin@matrix13-test.com", "Matrix13@2026")
print(f"SETUP — TA login: role={ta_c.get('role')}")

# Hierarchy config — 3 levels: NM "HQ Director" / RM "Region Manager" / WM "Warehouse Manager"
code, d = curl(
    "PUT",
    f"/tenants/{TENANT_ID}/hierarchy/config",
    TA_JWT,
    [
        {
            "level_number": 1,
            "level_name": "HQ",
            "default_role_code": "NM",
            "role_display_label": "HQ Director",
            "is_stock_holding": True,
        },
        {
            "level_number": 2,
            "level_name": "Region",
            "default_role_code": "RM",
            "role_display_label": "Region Manager",
            "is_stock_holding": True,
        },
        {
            "level_number": 3,
            "level_name": "Warehouse",
            "default_role_code": "WM",
            "role_display_label": "Warehouse Manager",
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
    {"title": "HQ Director", "role_code": "NM"},
)
NM_POS_ID = d.get("data", {}).get("id", "")
code, d = curl(
    "POST",
    f"/tenants/{TENANT_ID}/nodes/{REGION_ID}/positions",
    TA_JWT,
    {"title": "Region Manager", "role_code": "RM", "reports_to_position_id": NM_POS_ID},
)
RM_POS_ID = d.get("data", {}).get("id", "")
code, d = curl(
    "POST",
    f"/tenants/{TENANT_ID}/nodes/{WH_ID}/positions",
    TA_JWT,
    {
        "title": "Warehouse Manager",
        "role_code": "WM",
        "reports_to_position_id": RM_POS_ID,
    },
)
WM_POS_ID = d.get("data", {}).get("id", "")
print(f"SETUP — Positions: NM={NM_POS_ID[:8]}  RM={RM_POS_ID[:8]}  WM={WM_POS_ID[:8]}")

# Users
code, d = curl(
    "POST",
    f"/tenants/{TENANT_ID}/users",
    TA_JWT,
    {
        "name": "HQ Director",
        "email": "nm@matrix13-test.com",
        "password": "Matrix13Nm@2026",
        "position_id": NM_POS_ID,
    },
)
code, d = curl(
    "POST",
    f"/tenants/{TENANT_ID}/users",
    TA_JWT,
    {
        "name": "Region Manager",
        "email": "rm@matrix13-test.com",
        "password": "Matrix13Rm@2026",
        "position_id": RM_POS_ID,
    },
)
code, d = curl(
    "POST",
    f"/tenants/{TENANT_ID}/users",
    TA_JWT,
    {
        "name": "Warehouse Manager",
        "email": "wm@matrix13-test.com",
        "password": "Matrix13Wm@2026",
        "position_id": WM_POS_ID,
    },
)
print("SETUP — Users created: nm, rm, wm")

NM_JWT, nm_c = get_jwt("nm@matrix13-test.com", "Matrix13Nm@2026")
RM_JWT, rm_c = get_jwt("rm@matrix13-test.com", "Matrix13Rm@2026")
WM_JWT, wm_c = get_jwt("wm@matrix13-test.com", "Matrix13Wm@2026")
print(
    f"SETUP — JWTs: NM(role={nm_c.get('role')}, wh={nm_c.get('warehouse_id', '')[:8]}) "
    f"RM(role={rm_c.get('role')}, wh={rm_c.get('warehouse_id', '')[:8]}) "
    f"WM(role={wm_c.get('role')}, wh={wm_c.get('warehouse_id', '')[:8]})"
)

# Transfer types — PULL (WM/L3 initiates) and PUSH (NM/L1 initiates)
PULL_LEVELS = [
    {"level_number": 1, "can_initiate": False, "can_receive": False},
    {"level_number": 2, "can_initiate": False, "can_receive": True},
    {"level_number": 3, "can_initiate": True, "can_receive": True},
]
PUSH_LEVELS = [
    {"level_number": 1, "can_initiate": True, "can_receive": False},
    {"level_number": 2, "can_initiate": False, "can_receive": True},
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
            "display_name": "Stock Allocation",
            "description": "NM pushes stock down",
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

# Self-approval policies — WM (L3) up to qty 1000 for PULL/PUSH;
# NM (L1) up to qty 1000 / value 100000 for PUSH (MATRIX 3B normal flow)
code, d = curl(
    "PUT",
    f"/tenants/{TENANT_ID}/self-approval-policies",
    TA_JWT,
    [
        {
            "role_code": "WM",
            "level_number": 3,
            "transfer_types": ["PULL", "PUSH"],
            "threshold_type": "EITHER",
            "qty_limit": 1000,
            "value_limit": 100000,
            "is_active": True,
        },
        {
            "role_code": "NM",
            "level_number": 1,
            "transfer_types": ["PUSH"],
            "threshold_type": "EITHER",
            "qty_limit": 1000,
            "value_limit": 100000,
            "is_active": True,
        },
    ],
)
print(f"SETUP — Self-approval policies: HTTP {code}  saved={len(d.get('data', []))}")

# Products — 3 products with Design-B overrides
code, d = curl(
    "POST",
    "/products/",
    TA_JWT,
    {
        "name": "CtrlProduct-Always",
        "type_code": "CTA",
        "unit": "EA",
        "units_per_package": 1,
        "sku_override": "CTRL-ALWAYS-001",
        "unit_price": 10.00,
        "currency": "ETB",
    },
)
ALWAYS_ID = d.get("data", {}).get("id", "")
print(
    f"SETUP — Product CtrlProduct-Always: HTTP {code}  id={ALWAYS_ID[:8] if ALWAYS_ID else 'MISSING'}"
)

code, d = curl(
    "POST",
    "/products/",
    TA_JWT,
    {
        "name": "CtrlProduct-Qty",
        "type_code": "CTQ",
        "unit": "EA",
        "units_per_package": 1,
        "sku_override": "CTRL-QTY-001",
        "unit_price": 10.00,
        "currency": "ETB",
    },
)
QTY_ID = d.get("data", {}).get("id", "")
print(
    f"SETUP — Product CtrlProduct-Qty: HTTP {code}  id={QTY_ID[:8] if QTY_ID else 'MISSING'}"
)

code, d = curl(
    "POST",
    "/products/",
    TA_JWT,
    {
        "name": "CtrlProduct-Value",
        "type_code": "CTV",
        "unit": "EA",
        "units_per_package": 1,
        "sku_override": "CTRL-VALUE-001",
        "unit_price": 100.00,
        "currency": "ETB",
    },
)
VALUE_ID = d.get("data", {}).get("id", "")
print(
    f"SETUP — Product CtrlProduct-Value: HTTP {code}  id={VALUE_ID[:8] if VALUE_ID else 'MISSING'}"
)

# Opening balances — 2000 @ HQ (NM) + 500 @ WH (WM) for each product
for pid, name in [
    (ALWAYS_ID, "CtrlProduct-Always"),
    (QTY_ID, "CtrlProduct-Qty"),
    (VALUE_ID, "CtrlProduct-Value"),
]:
    ik = f"matrix13-ob-hq-{_uuid.uuid4()}"
    code, d = curl(
        "POST",
        "/inventory/receive/",
        NM_JWT,
        {
            "product_id": pid,
            "warehouse_id": HQ_ID,
            "quantity": 2000,
            "source": "OPENING_BALANCE",
            "idempotency_key": ik,
        },
    )
    print(
        f"SETUP — Receive 2000 {name} @ HQ: HTTP {code}  tx={d.get('data', {}).get('transaction_id', '')[:8]}"
    )

    ik = f"matrix13-ob-wh-{_uuid.uuid4()}"
    code, d = curl(
        "POST",
        "/inventory/receive/",
        WM_JWT,
        {
            "product_id": pid,
            "warehouse_id": WH_ID,
            "quantity": 500,
            "source": "OPENING_BALANCE",
            "idempotency_key": ik,
        },
    )
    print(
        f"SETUP — Receive 500 {name} @ WH: HTTP {code}  tx={d.get('data', {}).get('transaction_id', '')[:8]}"
    )

print(f"\nSETUP COMPLETE — TENANT_ID={TENANT_ID}")
print(f"   HQ={HQ_ID}  Region={REGION_ID}  WH={WH_ID}")
print(f"   ALWAYS_ID={ALWAYS_ID}  QTY_ID={QTY_ID}  VALUE_ID={VALUE_ID}")
print(f"   NM_POS_ID={NM_POS_ID}  RM_POS_ID={RM_POS_ID}  WM_POS_ID={WM_POS_ID}")


# ════════════════════════════════════════════════════════════════════════
# CONFIGURE DESIGN-B OVERRIDES (TA)
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# CONFIGURE DESIGN-B OVERRIDES (TA-only PUT /products/{id}/approval-minimums)")
print("#" * 70)

# CtrlProduct-Always — ADJUSTMENT, ALWAYS -> NM_POS (HQ Director)
code, d = curl(
    "PUT",
    f"/products/{ALWAYS_ID}/approval-minimums",
    TA_JWT,
    {
        "entries": [
            {
                "transaction_type": "ADJUSTMENT",
                "override_enabled": True,
                "threshold_type": "ALWAYS",
                "approver_position_id": NM_POS_ID,
                "note": "All adjustments to this product need HQ Director sign-off",
            },
        ]
    },
)
report(
    "Configure CtrlProduct-Always ADJUSTMENT override (ALWAYS -> NM)",
    code,
    d,
    200,
    f"minimums={len(d.get('data', {}).get('minimums', []))}",
)

# CtrlProduct-Qty — PULL, QUANTITY >= 50 -> RM_POS (Region Manager)
code, d = curl(
    "PUT",
    f"/products/{QTY_ID}/approval-minimums",
    TA_JWT,
    {
        "entries": [
            {
                "transaction_type": "PULL",
                "override_enabled": True,
                "threshold_type": "QUANTITY",
                "qty_threshold": 50,
                "approver_position_id": RM_POS_ID,
                "note": "Large pulls need RM sign-off",
            },
        ]
    },
)
report(
    "Configure CtrlProduct-Qty PULL override (QUANTITY>=50 -> RM)",
    code,
    d,
    200,
    f"minimums={len(d.get('data', {}).get('minimums', []))}",
)

# CtrlProduct-Value — PUSH, VALUE >= 5000 -> NM_POS (HQ Director)
code, d = curl(
    "PUT",
    f"/products/{VALUE_ID}/approval-minimums",
    TA_JWT,
    {
        "entries": [
            {
                "transaction_type": "PUSH",
                "override_enabled": True,
                "threshold_type": "VALUE",
                "value_threshold": 5000,
                "approver_position_id": NM_POS_ID,
                "note": "High-value pushes need HQ Director sign-off",
            },
        ]
    },
)
report(
    "Configure CtrlProduct-Value PUSH override (VALUE>=5000 -> NM)",
    code,
    d,
    200,
    f"minimums={len(d.get('data', {}).get('minimums', []))}",
)


# ════════════════════════════════════════════════════════════════════════
# MATRIX 1 — ADJUSTMENT ALWAYS -> L1 (CtrlProduct-Always)
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# MATRIX 1 — ADJUSTMENT ALWAYS -> L1 (CtrlProduct-Always)")
print("#" * 70)

ik = f"matrix1-adj-{_uuid.uuid4()}"
code, d = curl(
    "POST",
    "/inventory/adjustments/",
    WM_JWT,
    {
        "warehouse_id": WH_ID,
        "product_id": ALWAYS_ID,
        "quantity_delta": -10,
        "reason_code": "COUNT_DISCREPANCY",
        "idempotency_key": ik,
        "notes": "MATRIX1 adjustment",
    },
)
M1_ID = d.get("data", {}).get("adjustment_id", "")
report(
    "M1.1 WM creates ADJUSTMENT for CtrlProduct-Always (qty_delta=-10)",
    code,
    d,
    201,
    f"adjustment_id={M1_ID[:8] if M1_ID else 'NONE'}",
)

if M1_ID:
    code, d = curl("POST", f"/inventory/adjustments/{M1_ID}/submit", WM_JWT)
    m1_status = d.get("data", {}).get("status", "")
    report("M1.2 WM submits -> PENDING_APPROVAL", code, d, 200, f"status={m1_status}")
    check(
        "M1.3 status == PENDING_APPROVAL",
        m1_status == "PENDING_APPROVAL",
        f"-> {m1_status}",
    )

    db_status, db_override, db_required_name, db_escalated = adjustment_flags(M1_ID)
    check(
        "M1.4 product_override_applied=true in DB",
        db_override is True,
        f"-> db_status={db_status} db_override={db_override} required={db_required_name!r} escalated={db_escalated}",
    )
    check(
        "M1.5 required_approver_name == HQ Director",
        db_required_name == "HQ Director",
        f"-> required_approver_name={db_required_name!r}",
    )

    code, d = curl("GET", f"/inventory/adjustments/{M1_ID}/approval-info", NM_JWT)
    info = d.get("data", {})
    report(
        "M1.6 approval-info: NM is named approver, can_approve=true",
        code,
        d,
        200,
        f"required_approver_name={info.get('required_approver_name')!r}  can_approve={info.get('can_approve')}",
    )
    check("M1.6b can_approve is True for NM", info.get("can_approve") is True)

    # RM attempts approve -> 403 NOT_REQUIRED_APPROVER
    code, d = curl("POST", f"/inventory/adjustments/{M1_ID}/approve", RM_JWT)
    report(
        "M1.7 RM attempts approve -> 403 NOT_REQUIRED_APPROVER",
        code,
        d,
        403,
        f"error={d.get('detail', d.get('error'))}",
    )
    detail = d.get("detail", d.get("error", {}))
    check(
        "M1.7b error code == NOT_REQUIRED_APPROVER",
        (detail.get("code") if isinstance(detail, dict) else None)
        == "NOT_REQUIRED_APPROVER",
        f"-> {detail}",
    )

    # NM (HQ Director) approves -> 200, POSTED
    code, d = curl("POST", f"/inventory/adjustments/{M1_ID}/approve", NM_JWT)
    m1_status2 = d.get("data", {}).get("status", "")
    report("M1.8 NM approves -> 200, POSTED", code, d, 200, f"status={m1_status2}")
    check("M1.9 status == POSTED", m1_status2 == "POSTED", f"-> {m1_status2}")
else:
    for k in [
        "M1.2 WM submits -> PENDING_APPROVAL",
        "M1.3 status == PENDING_APPROVAL",
        "M1.4 product_override_applied=true in DB",
        "M1.5 required_approver_name == HQ Director",
        "M1.6 approval-info: NM is named approver, can_approve=true",
        "M1.6b can_approve is True for NM",
        "M1.7 RM attempts approve -> 403 NOT_REQUIRED_APPROVER",
        "M1.7b error code == NOT_REQUIRED_APPROVER",
        "M1.8 NM approves -> 200, POSTED",
        "M1.9 status == POSTED",
    ]:
        results[k] = False
    print("XX MATRIX1 — SKIPPED (adjustment creation failed)")


# ════════════════════════════════════════════════════════════════════════
# MATRIX 2 — PULL QTY>=50 -> L2 (CtrlProduct-Qty)
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# MATRIX 2 — PULL QTY>=50 -> L2 (CtrlProduct-Qty, qty=60)")
print("#" * 70)

code, d = curl(
    "POST",
    "/inventory/transfers/",
    WM_JWT,
    {
        "transfer_type": "PULL",
        "from_warehouse_id": HQ_ID,
        "to_warehouse_id": WH_ID,
        "lines": [{"product_id": QTY_ID, "quantity": 60}],
        "notes": "MATRIX2 PULL qty=60",
    },
)
M2_ID = d.get("data", {}).get("transfer_id", "")
report(
    "M2.1 WM creates PULL CtrlProduct-Qty qty=60",
    code,
    d,
    201,
    f"transfer_id={M2_ID[:8] if M2_ID else 'NONE'}",
)

if M2_ID:
    code, d = curl("POST", f"/inventory/transfers/{M2_ID}/submit", WM_JWT)
    m2_status = d.get("data", {}).get("status", "")
    m2_self = d.get("data", {}).get("is_self_approved")
    report(
        "M2.2 WM submits -> PENDING_REVIEW (override fires)",
        code,
        d,
        200,
        f"status={m2_status}  is_self_approved={m2_self}",
    )
    check(
        "M2.3 status == PENDING_REVIEW",
        m2_status == "PENDING_REVIEW",
        f"-> {m2_status}",
    )
    check("M2.4 is_self_approved is not True", m2_self is not True, f"-> {m2_self}")

    db_status, db_self, db_override = transfer_flags(M2_ID)
    check(
        "M2.5 product_override_applied=true in DB",
        db_override is True,
        f"-> db_status={db_status} db_self={db_self} db_override={db_override}",
    )

    code, d = curl("POST", f"/inventory/transfers/{M2_ID}/review", RM_JWT)
    m2_status2 = d.get("data", {}).get("status", "")
    report("M2.6 RM reviews -> PENDING_APPROVAL", code, d, 200, f"status={m2_status2}")
    check(
        "M2.7 status == PENDING_APPROVAL",
        m2_status2 == "PENDING_APPROVAL",
        f"-> {m2_status2}",
    )

    # NM attempts approve -> 403 NOT_ASSIGNED_APPROVER
    code, d = curl("POST", f"/inventory/transfers/{M2_ID}/approve", NM_JWT)
    report(
        "M2.8 NM attempts approve -> 403 NOT_ASSIGNED_APPROVER",
        code,
        d,
        403,
        f"error={d.get('detail', d.get('error'))}",
    )
    detail = d.get("detail", d.get("error", {}))
    check(
        "M2.8b error code == NOT_ASSIGNED_APPROVER",
        (detail.get("code") if isinstance(detail, dict) else None)
        == "NOT_ASSIGNED_APPROVER",
        f"-> {detail}",
    )

    # RM approves -> 200 APPROVED
    code, d = curl("POST", f"/inventory/transfers/{M2_ID}/approve", RM_JWT)
    m2_status3 = d.get("data", {}).get("status", "")
    report("M2.9 RM approves -> 200, APPROVED", code, d, 200, f"status={m2_status3}")
    check("M2.10 status == APPROVED", m2_status3 == "APPROVED", f"-> {m2_status3}")
else:
    for k in [
        "M2.2 WM submits -> PENDING_REVIEW (override fires)",
        "M2.3 status == PENDING_REVIEW",
        "M2.4 is_self_approved is not True",
        "M2.5 product_override_applied=true in DB",
        "M2.6 RM reviews -> PENDING_APPROVAL",
        "M2.7 status == PENDING_APPROVAL",
        "M2.8 NM attempts approve -> 403 NOT_ASSIGNED_APPROVER",
        "M2.8b error code == NOT_ASSIGNED_APPROVER",
        "M2.9 RM approves -> 200, APPROVED",
        "M2.10 status == APPROVED",
    ]:
        results[k] = False
    print("XX MATRIX2 — SKIPPED (transfer creation failed)")


# ════════════════════════════════════════════════════════════════════════
# MATRIX 2B — PULL below QTY threshold (CtrlProduct-Qty, qty=10)
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print(
    "# MATRIX 2B — PULL below QTY threshold (CtrlProduct-Qty, qty=10) -> normal self-approval"
)
print("#" * 70)

code, d = curl(
    "POST",
    "/inventory/transfers/",
    WM_JWT,
    {
        "transfer_type": "PULL",
        "from_warehouse_id": HQ_ID,
        "to_warehouse_id": WH_ID,
        "lines": [{"product_id": QTY_ID, "quantity": 10}],
        "notes": "MATRIX2B PULL qty=10",
    },
)
M2B_ID = d.get("data", {}).get("transfer_id", "")
report(
    "M2B.1 WM creates PULL CtrlProduct-Qty qty=10",
    code,
    d,
    201,
    f"transfer_id={M2B_ID[:8] if M2B_ID else 'NONE'}",
)

if M2B_ID:
    code, d = curl("POST", f"/inventory/transfers/{M2B_ID}/submit", WM_JWT)
    m2b_status = d.get("data", {}).get("status", "")
    m2b_self = d.get("data", {}).get("is_self_approved")
    report(
        "M2B.2 WM submits -> APPROVED (self-approved, below threshold)",
        code,
        d,
        200,
        f"status={m2b_status}  is_self_approved={m2b_self}",
    )
    check("M2B.3 status == APPROVED", m2b_status == "APPROVED", f"-> {m2b_status}")
    check("M2B.4 is_self_approved is True", m2b_self is True, f"-> {m2b_self}")

    db_status, db_self, db_override = transfer_flags(M2B_ID)
    check(
        "M2B.5 product_override_applied is not true in DB",
        db_override is not True,
        f"-> db_override={db_override}",
    )
else:
    for k in [
        "M2B.2 WM submits -> APPROVED (self-approved, below threshold)",
        "M2B.3 status == APPROVED",
        "M2B.4 is_self_approved is True",
        "M2B.5 product_override_applied is not true in DB",
    ]:
        results[k] = False
    print("XX MATRIX2B — SKIPPED (transfer creation failed)")


# ════════════════════════════════════════════════════════════════════════
# MATRIX 3 — PUSH VALUE>=5000 -> L1, creator=L1 (CtrlProduct-Value, qty=50, value=5000)
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print(
    "# MATRIX 3 — PUSH VALUE>=5000 -> L1, creator=NM (CtrlProduct-Value, qty=50, value=5000)"
)
print("#" * 70)

code, d = curl(
    "POST",
    "/inventory/transfers/",
    NM_JWT,
    {
        "transfer_type": "PUSH",
        "from_warehouse_id": HQ_ID,
        "to_warehouse_id": WH_ID,
        "lines": [{"product_id": VALUE_ID, "quantity": 50}],
        "notes": "MATRIX3 PUSH qty=50 value=5000",
    },
)
M3_ID = d.get("data", {}).get("transfer_id", "")
report(
    "M3.1 NM creates PUSH CtrlProduct-Value qty=50 (value=5000)",
    code,
    d,
    201,
    f"transfer_id={M3_ID[:8] if M3_ID else 'NONE'}",
)

if M3_ID:
    code, d = curl("POST", f"/inventory/transfers/{M3_ID}/submit", NM_JWT)
    m3_status = d.get("data", {}).get("status", "")
    m3_self = d.get("data", {}).get("is_self_approved")
    report(
        "M3.2 NM submits -> PENDING_APPROVAL (override fires, escalated)",
        code,
        d,
        200,
        f"status={m3_status}  is_self_approved={m3_self}",
    )
    check(
        "M3.3 status == PENDING_APPROVAL",
        m3_status == "PENDING_APPROVAL",
        f"-> {m3_status}",
    )
    check("M3.4 is_self_approved is not True", m3_self is not True, f"-> {m3_self}")

    db_status, db_self, db_override = transfer_flags(M3_ID)
    check(
        "M3.5 product_override_applied=true in DB",
        db_override is True,
        f"-> db_status={db_status} db_override={db_override}",
    )

    out, _ = psql(
        f"SELECT resolved_approval_steps::text FROM transfer_orders WHERE id = '{M3_ID}';"
    )
    steps_line = [l for l in out.splitlines() if l.strip()][-1] if out.strip() else ""
    check(
        "M3.6 resolved_approval_steps[0].escalated == true",
        '"escalated": true' in steps_line or '"escalated":true' in steps_line,
        f"-> {steps_line[:200]}",
    )

    # NM (creator) attempts approve -> 403 CANNOT_APPROVE_OWN_TRANSFER
    code, d = curl("POST", f"/inventory/transfers/{M3_ID}/approve", NM_JWT)
    report(
        "M3.7 NM (creator) attempts approve -> 403 CANNOT_APPROVE_OWN_TRANSFER",
        code,
        d,
        403,
        f"error={d.get('detail', d.get('error'))}",
    )
    detail = d.get("detail", d.get("error", {}))
    check(
        "M3.7b error code == CANNOT_APPROVE_OWN_TRANSFER",
        (detail.get("code") if isinstance(detail, dict) else None)
        == "CANNOT_APPROVE_OWN_TRANSFER",
        f"-> {detail}",
    )

    # TA approves -> 200 APPROVED
    code, d = curl("POST", f"/inventory/transfers/{M3_ID}/approve", TA_JWT)
    m3_status2 = d.get("data", {}).get("status", "")
    report("M3.8 TA approves -> 200, APPROVED", code, d, 200, f"status={m3_status2}")
    check("M3.9 status == APPROVED", m3_status2 == "APPROVED", f"-> {m3_status2}")
else:
    for k in [
        "M3.2 NM submits -> PENDING_APPROVAL (override fires, escalated)",
        "M3.3 status == PENDING_APPROVAL",
        "M3.4 is_self_approved is not True",
        "M3.5 product_override_applied=true in DB",
        "M3.6 resolved_approval_steps[0].escalated == true",
        "M3.7 NM (creator) attempts approve -> 403 CANNOT_APPROVE_OWN_TRANSFER",
        "M3.7b error code == CANNOT_APPROVE_OWN_TRANSFER",
        "M3.8 TA approves -> 200, APPROVED",
        "M3.9 status == APPROVED",
    ]:
        results[k] = False
    print("XX MATRIX3 — SKIPPED (transfer creation failed)")


# ════════════════════════════════════════════════════════════════════════
# MATRIX 3B — PUSH below VALUE threshold (CtrlProduct-Value, qty=10, value=1000)
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print(
    "# MATRIX 3B — PUSH below VALUE threshold (CtrlProduct-Value, qty=10, value=1000) -> normal flow"
)
print("#" * 70)

code, d = curl(
    "POST",
    "/inventory/transfers/",
    NM_JWT,
    {
        "transfer_type": "PUSH",
        "from_warehouse_id": HQ_ID,
        "to_warehouse_id": WH_ID,
        "lines": [{"product_id": VALUE_ID, "quantity": 10}],
        "notes": "MATRIX3B PUSH qty=10 value=1000",
    },
)
M3B_ID = d.get("data", {}).get("transfer_id", "")
report(
    "M3B.1 NM creates PUSH CtrlProduct-Value qty=10 (value=1000)",
    code,
    d,
    201,
    f"transfer_id={M3B_ID[:8] if M3B_ID else 'NONE'}",
)

if M3B_ID:
    code, d = curl("POST", f"/inventory/transfers/{M3B_ID}/submit", NM_JWT)
    m3b_status = d.get("data", {}).get("status", "")
    m3b_self = d.get("data", {}).get("is_self_approved")
    report(
        "M3B.2 NM submits -> APPROVED (self-approved, below threshold)",
        code,
        d,
        200,
        f"status={m3b_status}  is_self_approved={m3b_self}",
    )
    check("M3B.3 status == APPROVED", m3b_status == "APPROVED", f"-> {m3b_status}")
    check("M3B.4 is_self_approved is True", m3b_self is True, f"-> {m3b_self}")

    db_status, db_self, db_override = transfer_flags(M3B_ID)
    check(
        "M3B.5 product_override_applied is not true in DB",
        db_override is not True,
        f"-> db_override={db_override}",
    )
else:
    for k in [
        "M3B.2 NM submits -> APPROVED (self-approved, below threshold)",
        "M3B.3 status == APPROVED",
        "M3B.4 is_self_approved is True",
        "M3B.5 product_override_applied is not true in DB",
    ]:
        results[k] = False
    print("XX MATRIX3B — SKIPPED (transfer creation failed)")


# ════════════════════════════════════════════════════════════════════════
# MATRIX 4 — multiple overrides, no cross-contamination
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# MATRIX 4 — multiple overrides, no cross-contamination")
print("#" * 70)

# 4a — ADJUSTMENT on CtrlProduct-Qty (only has a PULL override) -> no ADJUSTMENT override fires
ik = f"matrix4a-adj-{_uuid.uuid4()}"
code, d = curl(
    "POST",
    "/inventory/adjustments/",
    WM_JWT,
    {
        "warehouse_id": WH_ID,
        "product_id": QTY_ID,
        "quantity_delta": -5,
        "reason_code": "COUNT_DISCREPANCY",
        "idempotency_key": ik,
        "notes": "MATRIX4a adjustment",
    },
)
M4A_ID = d.get("data", {}).get("adjustment_id", "")
report(
    "M4a.1 WM creates ADJUSTMENT for CtrlProduct-Qty (qty_delta=-5)",
    code,
    d,
    201,
    f"adjustment_id={M4A_ID[:8] if M4A_ID else 'NONE'}",
)

if M4A_ID:
    code, d = curl("POST", f"/inventory/adjustments/{M4A_ID}/submit", WM_JWT)
    m4a_status = d.get("data", {}).get("status", "")
    report(
        "M4a.2 WM submits -> 200 (no ADJUSTMENT override on this product)",
        code,
        d,
        200,
        f"status={m4a_status}",
    )

    db_status, db_override, db_required_name, db_escalated = adjustment_flags(M4A_ID)
    check(
        "M4a.3 product_override_applied is not true in DB (PULL override does not leak into ADJUSTMENT)",
        db_override is not True,
        f"-> db_status={db_status} db_override={db_override} required={db_required_name!r}",
    )

    # NM approves via normal RBAC (no required-approver gate, since no override fired)
    code, d = curl("POST", f"/inventory/adjustments/{M4A_ID}/approve", NM_JWT)
    m4a_status2 = d.get("data", {}).get("status", "")
    report(
        "M4a.4 NM approves via normal RBAC -> 200, POSTED",
        code,
        d,
        200,
        f"status={m4a_status2}",
    )
    check("M4a.5 status == POSTED", m4a_status2 == "POSTED", f"-> {m4a_status2}")
else:
    for k in [
        "M4a.2 WM submits -> 200 (no ADJUSTMENT override on this product)",
        "M4a.3 product_override_applied is not true in DB (PULL override does not leak into ADJUSTMENT)",
        "M4a.4 NM approves via normal RBAC -> 200, POSTED",
        "M4a.5 status == POSTED",
    ]:
        results[k] = False
    print("XX MATRIX4a — SKIPPED (adjustment creation failed)")

# 4b — PULL on CtrlProduct-Always (only has an ADJUSTMENT override) -> no PULL override fires
code, d = curl(
    "POST",
    "/inventory/transfers/",
    WM_JWT,
    {
        "transfer_type": "PULL",
        "from_warehouse_id": HQ_ID,
        "to_warehouse_id": WH_ID,
        "lines": [{"product_id": ALWAYS_ID, "quantity": 5}],
        "notes": "MATRIX4b PULL qty=5",
    },
)
M4B_ID = d.get("data", {}).get("transfer_id", "")
report(
    "M4b.1 WM creates PULL CtrlProduct-Always qty=5",
    code,
    d,
    201,
    f"transfer_id={M4B_ID[:8] if M4B_ID else 'NONE'}",
)

if M4B_ID:
    code, d = curl("POST", f"/inventory/transfers/{M4B_ID}/submit", WM_JWT)
    m4b_status = d.get("data", {}).get("status", "")
    m4b_self = d.get("data", {}).get("is_self_approved")
    report(
        "M4b.2 WM submits -> APPROVED (self-approved, no ADJUSTMENT override leaks into PULL)",
        code,
        d,
        200,
        f"status={m4b_status}  is_self_approved={m4b_self}",
    )
    check("M4b.3 status == APPROVED", m4b_status == "APPROVED", f"-> {m4b_status}")
    check("M4b.4 is_self_approved is True", m4b_self is True, f"-> {m4b_self}")

    db_status, db_self, db_override = transfer_flags(M4B_ID)
    check(
        "M4b.5 product_override_applied is not true in DB (ADJUSTMENT override does not leak into PULL)",
        db_override is not True,
        f"-> db_override={db_override}",
    )
else:
    for k in [
        "M4b.2 WM submits -> APPROVED (self-approved, no ADJUSTMENT override leaks into PULL)",
        "M4b.3 status == APPROVED",
        "M4b.4 is_self_approved is True",
        "M4b.5 product_override_applied is not true in DB (ADJUSTMENT override does not leak into PULL)",
    ]:
        results[k] = False
    print("XX MATRIX4b — SKIPPED (transfer creation failed)")


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
        "Setup / override configuration:",
        [
            (
                "  Configure CtrlProduct-Always override: ",
                "Configure CtrlProduct-Always",
            ),
            ("  Configure CtrlProduct-Qty override:     ", "Configure CtrlProduct-Qty"),
            (
                "  Configure CtrlProduct-Value override:   ",
                "Configure CtrlProduct-Value",
            ),
        ],
    ),
    ("MATRIX 1 (ADJUSTMENT ALWAYS -> L1):", [("  ", "M1")]),
    ("MATRIX 2 (PULL QTY>=50 -> L2):", [("  ", "M2.")]),
    ("MATRIX 2B (PULL below threshold):", [("  ", "M2B")]),
    (
        "MATRIX 3 (PUSH VALUE>=5000 -> L1, creator==approver escalation):",
        [("  ", "M3.")],
    ),
    ("MATRIX 3B (PUSH below threshold):", [("  ", "M3B")]),
    (
        "MATRIX 4 (no cross-contamination):",
        [
            ("  4a ADJUSTMENT (no override leak):  ", "M4a"),
            ("  4b PULL (no override leak):        ", "M4b"),
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

CASCADE_TABLES = [
    # Phase 0
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
    # Phase 1
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

r = subprocess.run(
    [
        "psql",
        "-U",
        "smart_user",
        "-d",
        "smart_dev",
        "-h",
        "127.0.0.1",
        "-c",
        " ".join(sql_lines),
    ],
    capture_output=True,
    text=True,
    env={**os.environ, **PGPASS},
)
print(
    f"Cascade delete (Phase 0-3 + tenants) for tenant_id={TENANT_ID}:\n{r.stdout.strip()}"
)
if r.stderr.strip():
    print(f"stderr: {r.stderr.strip()}")

r = subprocess.run(
    [
        "psql",
        "-U",
        "smart_user",
        "-d",
        "smart_dev",
        "-h",
        "127.0.0.1",
        "-c",
        "SELECT count(*) FROM tenants WHERE slug = 'matrix-test-13';",
    ],
    capture_output=True,
    text=True,
    env={**os.environ, **PGPASS},
)
print(f"\nVerify 0 rows remain (slug='matrix-test-13'):\n{r.stdout.strip()}")
