"""Design-B Integration Test — per-product approval overrides (Gold Bar / Steel Rod / Specialty Alloy).
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


def get_jwt(email, pw):
    c, d = curl("POST", "/auth/token", body={"dev_email": email, "dev_password": pw})
    tok = d.get("access_token", "")
    return tok, jwt_claims(tok)


def psql(sql):
    full = (f"SELECT set_config('app.current_tenant_id','{TENANT_ID}',false),"
            f"set_config('app.current_user_id','00000001-0000-0000-0000-000000000001',false);"
            f"{sql}")
    r = subprocess.run(["psql", "-U", "smart_user", "-d", "smart_dev", "-h", "127.0.0.1",
                        "-t", "-A", "-c", full],
                       capture_output=True, text=True, env={**__import__("os").environ, **PGPASS})
    return r.stdout.strip(), r.stderr.strip()


def transfer_flags(transfer_id):
    """Returns (status, is_self_approved, product_override_applied) for a transfer."""
    out, _ = psql(
        f"SELECT status, is_self_approved, product_override_applied "
        f"FROM transfer_orders WHERE id = '{transfer_id}';"
    )
    # last non-empty line is the data row (first line is the set_config no-op result)
    lines = [l for l in out.splitlines() if l.strip()]
    if not lines:
        return None, None, None
    parts = lines[-1].split("|")
    status = parts[0].strip()
    is_self = parts[1].strip() if len(parts) > 1 else ""
    override_applied = parts[2].strip() if len(parts) > 2 else ""
    return status, (is_self == "t"), (override_applied == "t")


# ════════════════════════════════════════════════════════════════════════
# SETUP
# ════════════════════════════════════════════════════════════════════════
print("\n" + "#" * 70)
print("# SETUP — Design-B Integration Test tenant")
print("#" * 70)

SA_JWT, _ = get_jwt("smartadmin@smart-inventory.com", "Admin@2026")
if not SA_JWT:
    print("FATAL: cannot obtain SA JWT. Aborting.")
    raise SystemExit(1)

code, d = curl("POST", "/tenants/", SA_JWT, {
    "name": "Design B Test",
    "slug": "design-b-test",
    "organisation_type": "PRODUCER",
    "default_locale": "en",
    "admin_name": "DesignB Admin",
    "admin_email": "admin@designb-test.com",
    "admin_password": "DesignB@2026",
})
TENANT_ID = d.get("data", {}).get("id", "")
print(f"SETUP — Create tenant: HTTP {code}  tenant_id={TENANT_ID}")
if not TENANT_ID:
    print(f"FATAL: tenant creation failed: {json.dumps(d)[:400]}")
    raise SystemExit(1)

code, d = curl("POST", f"/tenants/{TENANT_ID}/users", SA_JWT, {
    "name": "DesignB Admin", "email": "admin@designb-test.com",
    "password": "DesignB@2026", "system_role": "TA",
})
print(f"SETUP — Create TA user: HTTP {code}")

TA_JWT, ta_c = get_jwt("admin@designb-test.com", "DesignB@2026")
print(f"SETUP — TA login: role={ta_c.get('role')}")

# Hierarchy config — 3 levels: NM / RM / WM
code, d = curl("PUT", f"/tenants/{TENANT_ID}/hierarchy/config", TA_JWT, [
    {"level_number": 1, "level_name": "HQ", "default_role_code": "NM",
     "role_display_label": "National Manager", "is_stock_holding": True},
    {"level_number": 2, "level_name": "Region", "default_role_code": "RM",
     "role_display_label": "Regional Manager", "is_stock_holding": True},
    {"level_number": 3, "level_name": "Warehouse", "default_role_code": "WM",
     "role_display_label": "Warehouse Manager", "is_stock_holding": True},
])
print(f"SETUP — Hierarchy config (3 levels): HTTP {code}  saved={len(d.get('data', []))}")

# Nodes: HQ -> Region -> WH
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

# Positions
code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes/{HQ_ID}/positions", TA_JWT,
               {"title": "National Manager", "role_code": "NM"})
NM_POS_ID = d.get("data", {}).get("id", "")
code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes/{REGION_ID}/positions", TA_JWT,
               {"title": "Regional Manager", "role_code": "RM", "reports_to_position_id": NM_POS_ID})
RM_POS_ID = d.get("data", {}).get("id", "")
code, d = curl("POST", f"/tenants/{TENANT_ID}/nodes/{WH_ID}/positions", TA_JWT,
               {"title": "Warehouse Manager", "role_code": "WM", "reports_to_position_id": RM_POS_ID})
WM_POS_ID = d.get("data", {}).get("id", "")
print(f"SETUP — Positions: NM={NM_POS_ID[:8]}  RM={RM_POS_ID[:8]}  WM={WM_POS_ID[:8]}")

# Users
code, d = curl("POST", f"/tenants/{TENANT_ID}/users", TA_JWT,
               {"name": "NM User", "email": "nm@designb-test.com", "password": "DesignBNm@2026", "position_id": NM_POS_ID})
code, d = curl("POST", f"/tenants/{TENANT_ID}/users", TA_JWT,
               {"name": "RM User", "email": "rm@designb-test.com", "password": "DesignBRm@2026", "position_id": RM_POS_ID})
code, d = curl("POST", f"/tenants/{TENANT_ID}/users", TA_JWT,
               {"name": "WM User", "email": "wm@designb-test.com", "password": "DesignBWm@2026", "position_id": WM_POS_ID})
print("SETUP — Users created: nm, rm, wm")

NM_JWT, nm_c = get_jwt("nm@designb-test.com", "DesignBNm@2026")
RM_JWT, rm_c = get_jwt("rm@designb-test.com", "DesignBRm@2026")
WM_JWT, wm_c = get_jwt("wm@designb-test.com", "DesignBWm@2026")
print(f"SETUP — JWTs: NM(role={nm_c.get('role')}) RM(role={rm_c.get('role')}) WM(role={wm_c.get('role')})")

# Transfer types — PULL only needed
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
print(f"SETUP — Transfer types configured: HTTP {code}  PULL={PULL_CFG_ID[:8]}")

# Transfer approval rules — PULL routes to RM
code, d = curl("PUT", f"/tenants/{TENANT_ID}/transfer-approval-rules", TA_JWT, [
    {"transfer_type_config_id": PULL_CFG_ID, "source_level": 1, "destination_level": 3,
     "quantity_min": 0, "quantity_max": None, "threshold_type": "QUANTITY", "currency": "ETB",
     "priority": 1, "is_active": True,
     "approval_steps": [{"sequence": 1, "position_title": "Regional Manager",
                         "resolution": "source_parent_node", "execution_mode": "SEQUENTIAL", "sla_hours": 24}]},
])
print(f"SETUP — Transfer approval rules: HTTP {code}  rules={len(d.get('data', []))}")

# Self-approval policy — WM up to qty 1000 for PULL
code, d = curl("PUT", f"/tenants/{TENANT_ID}/self-approval-policies", TA_JWT, [
    {"role_code": "WM", "level_number": 3, "transfer_types": ["PULL"],
     "threshold_type": "QUANTITY", "qty_limit": 1000, "is_active": True},
])
print(f"SETUP — Self-approval policies: HTTP {code}  saved={len(d.get('data', []))}")

# Products
code, d = curl("POST", "/products/", TA_JWT, {
    "name": "Gold Bar", "type_code": "GLD", "unit": "EA",
    "units_per_package": 1, "sku_override": "GOLD-001",
    "unit_price": 50000.00, "currency": "ETB",
})
GOLD_ID = d.get("data", {}).get("id", "")
print(f"SETUP — Product Gold Bar: HTTP {code}  id={GOLD_ID[:8] if GOLD_ID else 'MISSING'}")

code, d = curl("POST", "/products/", TA_JWT, {
    "name": "Steel Rod", "type_code": "STL", "unit": "EA",
    "units_per_package": 1, "sku_override": "STEEL-001",
    "unit_price": 50.00, "currency": "ETB",
})
STEEL_ID = d.get("data", {}).get("id", "")
print(f"SETUP — Product Steel Rod: HTTP {code}  id={STEEL_ID[:8] if STEEL_ID else 'MISSING'}")

code, d = curl("POST", "/products/", TA_JWT, {
    "name": "Specialty Alloy", "type_code": "ALY", "unit": "EA",
    "units_per_package": 1, "sku_override": "ALLOY-001",
    "unit_price": 200.00, "currency": "ETB",
})
ALLOY_ID = d.get("data", {}).get("id", "")
print(f"SETUP — Product Specialty Alloy: HTTP {code}  id={ALLOY_ID[:8] if ALLOY_ID else 'MISSING'}")

# Opening balances — receive plenty at HQ for each product, via NM
for pid, qty, name in [(GOLD_ID, 1000, "Gold Bar"), (STEEL_ID, 1000, "Steel Rod"), (ALLOY_ID, 1000, "Specialty Alloy")]:
    ik = f"designb-ob-hq-{_uuid.uuid4()}"
    code, d = curl("POST", "/inventory/receive/", NM_JWT, {
        "product_id": pid, "warehouse_id": HQ_ID, "quantity": qty,
        "source": "OPENING_BALANCE", "idempotency_key": ik,
    })
    print(f"SETUP — Receive {qty} {name} @ HQ: HTTP {code}  tx={d.get('data', {}).get('transaction_id', '')[:8]}")

print(f"\nSETUP COMPLETE — TENANT_ID={TENANT_ID}")
print(f"   HQ={HQ_ID}  Region={REGION_ID}  WH={WH_ID}")
print(f"   GOLD_ID={GOLD_ID}  STEEL_ID={STEEL_ID}  ALLOY_ID={ALLOY_ID}")
print(f"   RM_POS_ID={RM_POS_ID}")


# ════════════════════════════════════════════════════════════════════════
# CONFIGURE DESIGN-B OVERRIDES (TA)
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# CONFIGURE DESIGN-B OVERRIDES (TA-only PUT /products/{id}/approval-minimums)")
print("#" * 70)

# Gold Bar — PULL, ALWAYS -> RM
code, d = curl("PUT", f"/products/{GOLD_ID}/approval-minimums", TA_JWT, {
    "entries": [
        {"transaction_type": "PULL", "override_enabled": True, "threshold_type": "ALWAYS",
         "approver_position_id": RM_POS_ID, "note": "Gold Bar always needs RM sign-off"},
    ]
})
report("Configure Gold Bar PULL override (ALWAYS -> RM)", code, d, 200,
       f"minimums={len(d.get('data', {}).get('minimums', []))}")

# Specialty Alloy — PULL, QUANTITY >= 50 -> RM
code, d = curl("PUT", f"/products/{ALLOY_ID}/approval-minimums", TA_JWT, {
    "entries": [
        {"transaction_type": "PULL", "override_enabled": True, "threshold_type": "QUANTITY",
         "qty_threshold": 50, "approver_position_id": RM_POS_ID, "note": "Large alloy pulls need RM"},
    ]
})
report("Configure Specialty Alloy PULL override (QUANTITY>=50 -> RM)", code, d, 200,
       f"minimums={len(d.get('data', {}).get('minimums', []))}")

# Steel Rod — no override (sanity: empty entries should be a no-op / 200)
code, d = curl("PUT", f"/products/{STEEL_ID}/approval-minimums", TA_JWT, {"entries": []})
report("Configure Steel Rod (no override, empty entries)", code, d, 200)


# ════════════════════════════════════════════════════════════════════════
# TEST 1 — Gold Bar PULL tiny qty -> override forces away from self-approval
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# TEST 1 — Gold Bar PULL qty=1 (override ALWAYS -> RM, ignores WM 1000 limit)")
print("#" * 70)

code, d = curl("POST", "/inventory/transfers/", WM_JWT, {
    "transfer_type": "PULL", "from_warehouse_id": HQ_ID, "to_warehouse_id": WH_ID,
    "lines": [{"product_id": GOLD_ID, "quantity": 1}], "notes": "TEST1 Gold Bar tiny qty",
})
T1_ID = d.get("data", {}).get("transfer_id", "")
report("TEST1.1 WM creates PULL Gold Bar qty=1", code, d, 201,
       f"transfer_id={T1_ID[:8] if T1_ID else 'NONE'}")

if T1_ID:
    code, d = curl("POST", f"/inventory/transfers/{T1_ID}/submit", WM_JWT)
    t1_status = d.get("data", {}).get("status", "")
    t1_self_approved = d.get("data", {}).get("is_self_approved")
    report("TEST1.2 WM submits Gold Bar qty=1", code, d, 200,
           f"status={t1_status}  is_self_approved={t1_self_approved}")

    check("TEST1.3 status != APPROVED (self-approval bypassed)", t1_status != "APPROVED",
          f"-> status={t1_status}")
    check("TEST1.4 is_self_approved is not True", t1_self_approved is not True,
          f"-> is_self_approved={t1_self_approved}")

    db_status, db_self, db_override = transfer_flags(T1_ID)
    check("TEST1.5 product_override_applied=true in DB", db_override is True,
          f"-> db_status={db_status} db_self={db_self} db_override={db_override}")

    # RM reviews -> PENDING_APPROVAL, then approves -> APPROVED
    code, d = curl("POST", f"/inventory/transfers/{T1_ID}/review", RM_JWT)
    t1_status2 = d.get("data", {}).get("status", "")
    report("TEST1.6 RM reviews -> PENDING_APPROVAL", code, d, 200, f"status={t1_status2}")

    code, d = curl("GET", f"/inventory/transfers/{T1_ID}/approval-info", RM_JWT)
    info = d.get("data", {})
    report("TEST1.7 approval-info: RM is named approver, can_approve=true", code, d, 200,
           f"position={info.get('current_approver_position_title')!r}  can_approve={info.get('can_approve')}")
    check("TEST1.7b can_approve is True for RM", info.get("can_approve") is True)

    code, d = curl("POST", f"/inventory/transfers/{T1_ID}/approve", RM_JWT)
    t1_status3 = d.get("data", {}).get("status", "")
    report("TEST1.8 RM approves -> APPROVED", code, d, 200, f"status={t1_status3}")
else:
    for k in ["TEST1.2 WM submits Gold Bar qty=1", "TEST1.3 status != APPROVED (self-approval bypassed)",
              "TEST1.4 is_self_approved is not True", "TEST1.5 product_override_applied=true in DB",
              "TEST1.6 RM reviews -> PENDING_APPROVAL", "TEST1.7 approval-info: RM is named approver, can_approve=true",
              "TEST1.7b can_approve is True for RM", "TEST1.8 RM approves -> APPROVED"]:
        results[k] = False
    print("XX TEST1 — SKIPPED (transfer creation failed)")


# ════════════════════════════════════════════════════════════════════════
# TEST 2 — Steel Rod normal self-approval (no override)
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# TEST 2 — Steel Rod PULL qty=1 (no override, normal self-approval)")
print("#" * 70)

code, d = curl("POST", "/inventory/transfers/", WM_JWT, {
    "transfer_type": "PULL", "from_warehouse_id": HQ_ID, "to_warehouse_id": WH_ID,
    "lines": [{"product_id": STEEL_ID, "quantity": 1}], "notes": "TEST2 Steel Rod normal flow",
})
T2_ID = d.get("data", {}).get("transfer_id", "")
report("TEST2.1 WM creates PULL Steel Rod qty=1", code, d, 201,
       f"transfer_id={T2_ID[:8] if T2_ID else 'NONE'}")

if T2_ID:
    code, d = curl("POST", f"/inventory/transfers/{T2_ID}/submit", WM_JWT)
    t2_status = d.get("data", {}).get("status", "")
    t2_self_approved = d.get("data", {}).get("is_self_approved")
    report("TEST2.2 WM submits Steel Rod qty=1 -> APPROVED (self-approved)", code, d, 200,
           f"status={t2_status}  is_self_approved={t2_self_approved}")
    check("TEST2.3 status == APPROVED", t2_status == "APPROVED", f"-> status={t2_status}")
    check("TEST2.4 is_self_approved is True", t2_self_approved is True, f"-> {t2_self_approved}")

    db_status, db_self, db_override = transfer_flags(T2_ID)
    check("TEST2.5 product_override_applied is not true in DB", db_override is not True,
          f"-> db_override={db_override}")
else:
    for k in ["TEST2.2 WM submits Steel Rod qty=1 -> APPROVED (self-approved)", "TEST2.3 status == APPROVED",
              "TEST2.4 is_self_approved is True", "TEST2.5 product_override_applied is not true in DB"]:
        results[k] = False
    print("XX TEST2 — SKIPPED (transfer creation failed)")


# ════════════════════════════════════════════════════════════════════════
# TEST 3 — GET /products/ exposes approval_overrides
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# TEST 3 — GET /products/ approval_overrides field")
print("#" * 70)

code, d = curl("GET", "/products/", TA_JWT)
products = d.get("data", [])
report("TEST3.1 GET /products/", code, d, 200, f"count={len(products)}")

gold = next((p for p in products if p.get("id") == GOLD_ID), {})
steel = next((p for p in products if p.get("id") == STEEL_ID), {})
alloy = next((p for p in products if p.get("id") == ALLOY_ID), {})

gold_ov = (gold.get("approval_overrides") or {}).get("PULL")
steel_ov = (steel.get("approval_overrides") or {}).get("PULL")
alloy_ov = (alloy.get("approval_overrides") or {}).get("PULL")

check("TEST3.2 Gold Bar has PULL override, mode=ALWAYS", gold_ov is not None and gold_ov.get("mode") == "ALWAYS",
      f"-> {gold_ov}")
check("TEST3.3 Steel Rod has no PULL override", steel_ov is None, f"-> {steel_ov}")
check("TEST3.4 Specialty Alloy has PULL override, mode=QUANTITY threshold=50",
      alloy_ov is not None and alloy_ov.get("mode") == "QUANTITY" and str(alloy_ov.get("threshold")) in ("50", "50.0000", "50.00"),
      f"-> {alloy_ov}")
check("TEST3.5 Gold Bar override approver_label mentions Regional Manager",
      gold_ov is not None and "Regional Manager" in (gold_ov.get("approver_label") or ""),
      f"-> {gold_ov.get('approver_label') if gold_ov else None}")


# ════════════════════════════════════════════════════════════════════════
# TEST 4 — TA-only configuration enforcement
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# TEST 4 — TA-only PUT /products/{id}/approval-minimums (NM 403, TA 200)")
print("#" * 70)

code, d = curl("PUT", f"/products/{STEEL_ID}/approval-minimums", NM_JWT, {
    "entries": [{"transaction_type": "PULL", "override_enabled": True, "threshold_type": "ALWAYS",
                 "approver_position_id": RM_POS_ID}]
})
report("TEST4.1 NM PUT approval-minimums -> 403 RBAC_DENIED", code, d, 403)

code, d = curl("GET", f"/products/{STEEL_ID}/approval-minimums", NM_JWT)
report("TEST4.2 NM GET approval-minimums -> 200 (read-only allowed)", code, d, 200)

code, d = curl("PUT", f"/products/{STEEL_ID}/approval-minimums", TA_JWT, {"entries": []})
report("TEST4.3 TA PUT approval-minimums -> 200", code, d, 200)


# ════════════════════════════════════════════════════════════════════════
# TEST 5 — Specialty Alloy quantity-threshold mode
# ════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 70)
print("# TEST 5 — Specialty Alloy PULL: below threshold self-approves, at/above routes to RM")
print("#" * 70)

# 5a — qty=10 (< 50) -> self-approved (no override fires; within WM 1000 limit)
code, d = curl("POST", "/inventory/transfers/", WM_JWT, {
    "transfer_type": "PULL", "from_warehouse_id": HQ_ID, "to_warehouse_id": WH_ID,
    "lines": [{"product_id": ALLOY_ID, "quantity": 10}], "notes": "TEST5a below threshold",
})
T5A_ID = d.get("data", {}).get("transfer_id", "")
report("TEST5a.1 WM creates PULL Specialty Alloy qty=10", code, d, 201,
       f"transfer_id={T5A_ID[:8] if T5A_ID else 'NONE'}")

if T5A_ID:
    code, d = curl("POST", f"/inventory/transfers/{T5A_ID}/submit", WM_JWT)
    t5a_status = d.get("data", {}).get("status", "")
    t5a_self = d.get("data", {}).get("is_self_approved")
    report("TEST5a.2 WM submits qty=10 -> APPROVED (self-approved, below threshold)", code, d, 200,
           f"status={t5a_status}  is_self_approved={t5a_self}")
    check("TEST5a.3 status == APPROVED", t5a_status == "APPROVED", f"-> {t5a_status}")
    check("TEST5a.4 is_self_approved is True", t5a_self is True, f"-> {t5a_self}")

    db_status, db_self, db_override = transfer_flags(T5A_ID)
    check("TEST5a.5 product_override_applied is not true (below threshold)", db_override is not True,
          f"-> db_override={db_override}")
else:
    for k in ["TEST5a.2 WM submits qty=10 -> APPROVED (self-approved, below threshold)", "TEST5a.3 status == APPROVED",
              "TEST5a.4 is_self_approved is True", "TEST5a.5 product_override_applied is not true (below threshold)"]:
        results[k] = False
    print("XX TEST5a — SKIPPED (transfer creation failed)")

# 5b — qty=60 (>= 50) -> override fires, routed to RM
code, d = curl("POST", "/inventory/transfers/", WM_JWT, {
    "transfer_type": "PULL", "from_warehouse_id": HQ_ID, "to_warehouse_id": WH_ID,
    "lines": [{"product_id": ALLOY_ID, "quantity": 60}], "notes": "TEST5b at/over threshold",
})
T5B_ID = d.get("data", {}).get("transfer_id", "")
report("TEST5b.1 WM creates PULL Specialty Alloy qty=60", code, d, 201,
       f"transfer_id={T5B_ID[:8] if T5B_ID else 'NONE'}")

if T5B_ID:
    code, d = curl("POST", f"/inventory/transfers/{T5B_ID}/submit", WM_JWT)
    t5b_status = d.get("data", {}).get("status", "")
    t5b_self = d.get("data", {}).get("is_self_approved")
    report("TEST5b.2 WM submits qty=60 -> override fires, not self-approved", code, d, 200,
           f"status={t5b_status}  is_self_approved={t5b_self}")
    check("TEST5b.3 status != APPROVED (override bypasses self-approval)", t5b_status != "APPROVED",
          f"-> {t5b_status}")
    check("TEST5b.4 is_self_approved is not True", t5b_self is not True, f"-> {t5b_self}")

    db_status, db_self, db_override = transfer_flags(T5B_ID)
    check("TEST5b.5 product_override_applied=true in DB", db_override is True,
          f"-> db_status={db_status} db_override={db_override}")

    code, d = curl("POST", f"/inventory/transfers/{T5B_ID}/review", RM_JWT)
    t5b_status2 = d.get("data", {}).get("status", "")
    report("TEST5b.6 RM reviews -> PENDING_APPROVAL", code, d, 200, f"status={t5b_status2}")

    code, d = curl("POST", f"/inventory/transfers/{T5B_ID}/approve", RM_JWT)
    t5b_status3 = d.get("data", {}).get("status", "")
    report("TEST5b.7 RM approves -> APPROVED", code, d, 200, f"status={t5b_status3}")
else:
    for k in ["TEST5b.2 WM submits qty=60 -> override fires, not self-approved",
              "TEST5b.3 status != APPROVED (override bypasses self-approval)",
              "TEST5b.4 is_self_approved is not True", "TEST5b.5 product_override_applied=true in DB",
              "TEST5b.6 RM reviews -> PENDING_APPROVAL", "TEST5b.7 RM approves -> APPROVED"]:
        results[k] = False
    print("XX TEST5b — SKIPPED (transfer creation failed)")


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
    ("Setup / override configuration:", [
        ("  Configure Gold Bar override:    ", "Configure Gold Bar"),
        ("  Configure Alloy override:       ", "Configure Specialty Alloy"),
        ("  Configure Steel Rod (none):     ", "Configure Steel Rod"),
    ]),
    ("TEST 1 (Gold Bar ALWAYS -> RM):", [("  ", "TEST1")]),
    ("TEST 2 (Steel Rod normal self-approval):", [("  ", "TEST2")]),
    ("TEST 3 (approval_overrides field):", [("  ", "TEST3")]),
    ("TEST 4 (TA-only enforcement):", [("  ", "TEST4")]),
    ("TEST 5 (Specialty Alloy quantity threshold):", [
        ("  5a below threshold: ", "TEST5a"),
        ("  5b at/over threshold: ", "TEST5b"),
    ]),
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
    # Phase 0
    "adjustment_orders", "audit_logs", "count_sessions", "dispatch_override_logs",
    "dispatch_strategy_configs", "inventory_balances",
    "inventory_transactions_2026_05", "inventory_transactions_2026_06",
    "inventory_transactions_2026_07", "inventory_transactions",
    "outbox", "product_uoms", "tenant_hierarchy_config",
    # Phase 1
    "org_node_hierarchy", "transfer_approval_rules", "personnel_positions",
    "approval_rule", "product_approval_minimums", "transfer_requests",
    "transfer_order_lines", "transfer_type_level_permissions",
    "adjustment_approval_rules", "self_approval_policies",
    # Phase 2
    "positions", "products", "warehouses", "transfer_orders", "users",
    # Phase 3
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
                     "-c", "SELECT count(*) FROM tenants WHERE slug = 'design-b-test';"],
                    capture_output=True, text=True, env={**__import__("os").environ, **PGPASS})
print(f"\nVerify 0 rows remain (slug='design-b-test'):\n{r.stdout.strip()}")
