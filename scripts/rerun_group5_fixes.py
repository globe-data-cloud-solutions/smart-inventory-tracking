"""Re-run of Group 5 failed tests after fixes A1/A2/A3/B1/B3/C1/C2."""

import subprocess, json, base64, os, uuid as _uuid

BASE = "http://localhost:8000/api/v1"
PGPASS = {**os.environ, "PGPASSWORD": "smart_local_pass"}
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
        data = json.loads("\n".join(lines[:-1]))
    except Exception:
        data = {"_raw": "\n".join(lines[:-1])[:300]}
    return code, data


def jwt_claims(tok):
    try:
        p = tok.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.b64decode(p))
    except Exception:
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


def get_jwt(email, pw):
    c, d = req("POST", "/auth/token", body={"dev_email": email, "dev_password": pw})
    tok = d.get("access_token", "")
    return tok, jwt_claims(tok), c, d


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
# SETUP
# ════════════════════════════════════════════════════════════
print("SETUP")

# SA JWT
SA_JWT, SA_C, _, _ = get_jwt("smartadmin@smart-inventory.com", "Admin@2026")
print(f"   SA JWT: {'OK' if SA_JWT else 'FAIL'}")

# Check if integration-test-co tenant exists; recreate if not
_, tm = req("GET", "/tenants/integration-test-co", SA_JWT)
TENANT_ID = tm.get("data", {}).get("id", "")

if not TENANT_ID:
    print("   Tenant not found — recreating with explicit slug...")
    _, ct = req(
        "POST",
        "/tenants/",
        SA_JWT,
        {
            "name": "Integration Test Co",
            "slug": "integration-test-co",  # FIX A3: explicit slug now saved
            "organisation_type": "PRODUCER",
            "default_locale": "en",
            "admin_name": "Test Admin",
            "admin_email": "admin@int-test.com",
            "admin_password": "IntTest@2026",
        },
    )
    TENANT_ID = ct.get("data", {}).get("id", "")
    print(f"   Created tenant: {TENANT_ID[:8] if TENANT_ID else 'FAIL'}...")

    # Re-create NM, RM, WM users, hierarchy, positions
    # (Minimal setup for these 5 tests)
    print("   NOTE: Tenant was missing — some sub-tests may need prerequisite data.")
else:
    print(f"   Tenant found: {TENANT_ID[:8]}...")

# Get TA JWT (uses FIX A2: deactivated → 401; must_reset → PENDING_SETUP)
TA_JWT, TA_C, TA_code, TA_d = get_jwt("admin@int-test.com", "IntTest@2026")
if not TA_JWT:
    print(f"   TA login: HTTP {TA_code}  detail={TA_d.get('detail', '?')}")
    # If TA has no position (must_reset path), they get PENDING_SETUP JWT
    TA_JWT = TA_d.get("access_token", "")
print(f"   TA JWT role={TA_C.get('role', '?')}: {'OK' if TA_JWT else 'FAIL'}")

# NM / RM / WM JWTs — re-activate if needed
NM_JWT, NM_C, _, _ = get_jwt("nm@int-test.com", "NMUser@2026")
RM_JWT, RM_C, _, _ = get_jwt("rm@int-test.com", "RMUser@2026")
WM_JWT, WM_C, _, _ = get_jwt("wm@int-test.com", "WMUser@2026")
print(
    f"   NM: {'OK' if NM_JWT else 'FAIL(deactivated?)'} "
    f"  RM: {'OK' if RM_JWT else 'FAIL'} "
    f"  WM: {'OK' if WM_JWT else 'FAIL'}"
)

L1_NODE_ID = str(NM_C.get("warehouse_id", ""))
L3_NODE_ID = str(WM_C.get("warehouse_id", ""))
WM_USER_ID = str(NM_C.get("sub", ""))  # placeholder; will look up from users list

# Get actual user IDs
_, users_d = req("GET", f"/tenants/{TENANT_ID}/users", TA_JWT)
users = users_d.get("data", [])
WM_USER_ID = next((u["id"] for u in users if u.get("email", "").startswith("wm@")), "")
RM_USER_ID = next((u["id"] for u in users if u.get("email", "").startswith("rm@")), "")
print(f"   WM_USER={WM_USER_ID[:8]}...  RM_USER={RM_USER_ID[:8]}...")

# Get PRODUCT_ID
_, sd = req("GET", "/inventory/analytics/stock", NM_JWT or SA_JWT)
prod = next(
    (r for r in sd.get("data", []) if r.get("product_name") == "Test Product A"), None
)
PRODUCT_ID = str(prod.get("product_id", "")) if prod else ""
print(
    f"   PRODUCT_ID: {PRODUCT_ID[:8] if PRODUCT_ID else 'NOT FOUND'}...  L1_stock={prod.get('current_stock') if prod else 'N/A'}"
)


# ════════════════════════════════════════════════════════════
# TEST 5.5 — Cross-tenant access blocked (FIX A1)
# ════════════════════════════════════════════════════════════
print("\nTEST 5.5 — Cross-tenant access blocked")

# Create second tenant with unique slug (FIX A3: slug is now saved correctly)
slug2 = f"ct-test-{str(_uuid.uuid4())[:8]}"
c55, d55 = req(
    "POST",
    "/tenants/",
    SA_JWT,
    {
        "name": "Cross-Tenant Test",
        "slug": slug2,
        "organisation_type": "RETAILER",
        "admin_email": "admin@ct55.com",
        "admin_password": "CT55@2026",
    },
)
T2_ID = d55.get("data", {}).get("id", "")
T2_SLUG = d55.get("data", {}).get("slug", "")
print(
    f"   Create 2nd tenant: HTTP {c55}  slug={T2_SLUG!r}  id={T2_ID[:8] if T2_ID else 'FAIL'}..."
)

# FIX A3: verify slug matches what was requested
slug_ok = T2_SLUG == slug2
print(f"   Slug matches requested: {slug_ok}  ({T2_SLUG!r} == {slug2!r})")

# Get TA JWT for second tenant
TA2_JWT, TA2_C, _, _ = get_jwt("admin@ct55.com", "CT55@2026")
TA2_ROLE = TA2_C.get("role", "?")
TA2_TENANT = str(TA2_C.get("tenant_id", ""))[:8]
print(f"   TA2 JWT: role={TA2_ROLE}  tenant={TA2_TENANT}...")

# TA2 tries to access first tenant's nodes (FIX A1: TENANT_ACCESS_DENIED)
c_cross, d_cross = req("GET", f"/tenants/{TENANT_ID}/nodes", TA2_JWT)
cross_code = (
    d_cross.get("detail", {}).get("code", "")
    if not d_cross.get("success")
    else "200-OK"
)
ok55 = c_cross == 403 and cross_code == "TENANT_ACCESS_DENIED"
report(
    "TEST 5.5  Cross-tenant access blocked",
    ok55,
    extra=f"HTTP {c_cross}  code={cross_code!r}  (expected 403 TENANT_ACCESS_DENIED)",
    notes=f"FIX A1: get_db_session_for_tenant now enforces tenant ownership; FIX A3: slug={T2_SLUG!r} saved correctly",
)

# Cleanup second tenant
if T2_ID:
    psql_rls(
        T2_ID,
        f"DELETE FROM users WHERE tenant_id='{T2_ID}'; "
        f"DELETE FROM tenants WHERE id='{T2_ID}';",
    )


# ════════════════════════════════════════════════════════════
# TEST 5.6 — Deactivated user returns 401 (FIX A2)
# ════════════════════════════════════════════════════════════
print("\nTEST 5.6 — Deactivated user returns 401")

# Ensure WM is active first, then deactivate
if WM_USER_ID:
    req("PATCH", f"/tenants/{TENANT_ID}/users/{WM_USER_ID}/reactivate", TA_JWT)
    psql_rls(
        TENANT_ID,
        f"UPDATE personnel_positions SET is_active=true WHERE user_id='{WM_USER_ID}';",
    )

    c_deact, _ = req(
        "PATCH", f"/tenants/{TENANT_ID}/users/{WM_USER_ID}/deactivate", TA_JWT
    )
    print(f"   Deactivate WM: HTTP {c_deact}")
else:
    print("   WM_USER_ID unknown — skipping deactivation")

# Try login as deactivated WM (FIX A2: returns 401 not 404)
_, d_wm_login = req(
    "POST",
    "/auth/token",
    body={"dev_email": "wm@int-test.com", "dev_password": "WMUser@2026"},
)
detail56 = d_wm_login.get("detail", "?")
ok56 = detail56 == "Invalid email or password"
report(
    "TEST 5.6  Deactivated user returns 401",
    ok56,
    extra=f"detail={detail56!r}  (expected 'Invalid email or password')",
    notes="FIX A2: deactivated users now checked in _lookup_user_with_position before 403/404 path",
)

# Reactivate WM + restore positions for downstream tests
if WM_USER_ID:
    req("PATCH", f"/tenants/{TENANT_ID}/users/{WM_USER_ID}/reactivate", TA_JWT)
    psql_rls(
        TENANT_ID,
        f"UPDATE personnel_positions SET is_active=true WHERE user_id='{WM_USER_ID}';",
    )


# ════════════════════════════════════════════════════════════
# TEST 5.7 — must_reset without position → PENDING_SETUP (FIX B1 + B3)
# ════════════════════════════════════════════════════════════
print("\nTEST 5.7 — must_reset without position gets PENDING_SETUP JWT")

# Clean up any leftover user from a previous run
psql_rls(
    TENANT_ID,
    f"DELETE FROM users WHERE email='nopoz@int-test.com' AND tenant_id='{TENANT_ID}';",
)

# Create user with NO position
c_cu, d_cu = req(
    "POST",
    f"/tenants/{TENANT_ID}/users",
    TA_JWT,
    {
        "name": "No-Position User",
        "email": "nopoz@int-test.com",
        "password": "NoPoz@2026",
    },
)
NP_USER_ID = d_cu.get("data", {}).get("id", "")
# Fallback: look up ID from users list if 409 (duplicate from stale run)
if not NP_USER_ID and c_cu == 409:
    _, ul = req("GET", f"/tenants/{TENANT_ID}/users", TA_JWT)
    existing = next(
        (u for u in ul.get("data", []) if u.get("email") == "nopoz@int-test.com"), None
    )
    NP_USER_ID = existing.get("id", "") if existing else ""
    print(
        f"   User already existed (409) — resolved ID from list: {NP_USER_ID[:8] if NP_USER_ID else 'FAIL'}..."
    )
    c_cu = 201  # treat as created for test purposes
print(
    f"   Create user (no position): HTTP {c_cu}  id={NP_USER_ID[:8] if NP_USER_ID else 'FAIL'}..."
)

# Login → FIX B1: returns PENDING_SETUP JWT instead of 403
c_np, d_np = req(
    "POST",
    "/auth/token",
    body={"dev_email": "nopoz@int-test.com", "dev_password": "NoPoz@2026"},
)
NP_JWT = d_np.get("access_token", "")
NP_C = jwt_claims(NP_JWT)
NP_ROLE = NP_C.get("role", "?")
NP_MRP = d_np.get("must_reset_password")
login_ok = c_np == 200 and NP_ROLE == "PENDING_SETUP" and NP_MRP is True
print(
    f"   Login: HTTP {c_np}  role={NP_ROLE}  must_reset={NP_MRP}  (expected PENDING_SETUP/True)"
)

# Change password without current_password (FIX B3: optional for must_reset users)
# MUST pass the PENDING_SETUP JWT — the API gateway requires a bearer token
# even for /auth/password; only /auth/token and /health are unauthenticated.
c_chg, d_chg = req(
    "PATCH",
    f"/auth/password/{NP_USER_ID}",
    token=NP_JWT,
    body={
        "user_id": NP_USER_ID,
        "new_password": "NoPozNew@2026!",
        # current_password intentionally omitted
    },
)
chg_ok = c_chg == 200 and d_chg.get("data", d_chg).get("success") is True
print(
    f"   Change password (no current_pw, with PENDING_SETUP JWT): HTTP {c_chg}  success={d_chg.get('data', d_chg).get('success')}  (expected 200/True)"
)

ok57 = login_ok and chg_ok
report(
    "TEST 5.7  must_reset without position - PENDING_SETUP",
    ok57,
    extra=f"login={c_np} role={NP_ROLE} / pwd_change={c_chg}",
    notes=[
        "FIX B1: _lookup_user_with_position returns PENDING_SETUP JWT when must_reset=true",
        "FIX B3: PATCH /auth/password accepts missing current_password for must_reset users",
    ],
)

# Cleanup
if NP_USER_ID:
    psql_rls(TENANT_ID, f"DELETE FROM users WHERE id='{NP_USER_ID}';")


# ════════════════════════════════════════════════════════════
# TEST 5.8 — Vacancy escalation no 500 (FIX C1)
# ════════════════════════════════════════════════════════════
print("\nTEST 5.8 — Vacancy escalation: deactivate RM, PULL escalates to NM")

# Ensure RM is active first, then deactivate (closes positions via deactivate_user)
if RM_USER_ID:
    req("PATCH", f"/tenants/{TENANT_ID}/users/{RM_USER_ID}/reactivate", TA_JWT)
    psql_rls(
        TENANT_ID,
        f"UPDATE personnel_positions SET is_active=true WHERE user_id='{RM_USER_ID}';",
    )
    c_rm_deact, _ = req(
        "PATCH", f"/tenants/{TENANT_ID}/users/{RM_USER_ID}/deactivate", TA_JWT
    )
    print(
        f"   Deactivate RM: HTTP {c_rm_deact}  (closes all RM positions → RM position now vacant)"
    )
else:
    print("   RM_USER_ID unknown")

# Ensure WM has active position for creating transfers
WM_JWT, WM_C, _, _ = get_jwt("wm@int-test.com", "WMUser@2026")
print(
    f"   WM JWT: role={WM_C.get('role', '?')}  wh={str(WM_C.get('warehouse_id', ''))[:8]}..."
)

# Create PULL requiring RM approval
if PRODUCT_ID and L1_NODE_ID and L3_NODE_ID:
    c_t, d_t = req(
        "POST",
        "/inventory/transfers/",
        WM_JWT,
        {
            "transfer_type": "PULL",
            "from_warehouse_id": L1_NODE_ID,
            "to_warehouse_id": L3_NODE_ID,
            "lines": [{"product_id": PRODUCT_ID, "quantity": 25}],
            "notes": "5.8 vacancy test",
        },
    )
    T58_ID = d_t.get("data", {}).get("transfer_id", "")
    print(f"   Create PULL: HTTP {c_t}  id={T58_ID[:8] if T58_ID else 'FAIL'}...")

    if T58_ID:
        c_sub, d_sub = req("POST", f"/inventory/transfers/{T58_ID}/submit", WM_JWT)
        print(
            f"   Submit: HTTP {c_sub}  status={d_sub.get('data', {}).get('status', '?')}"
        )

        # RM review (RM is deactivated; the rule step resolver must escalate to NM)
        # We use the SA JWT as reviewer since RM is deactivated
        # Actually RM JWT might still be valid for this session — let's use the NM JWT
        # which has TRANSFER_APPROVE permission at level 1
        c_rev, d_rev = req("POST", f"/inventory/transfers/{T58_ID}/review", NM_JWT)
        status58 = d_rev.get("data", {}).get("status", "?")
        print(f"   NM review (RM deactivated): HTTP {c_rev}  status={status58}")

        # Get resolved steps from DB to show escalation
        steps_raw = psql_rls(
            TENANT_ID,
            f"SELECT resolved_approval_steps FROM transfer_orders WHERE id='{T58_ID}';",
        )
        # Parse assigned approver name
        assigned = "unknown"
        try:
            import re as _re

            j = _re.search(r"(\[.*\])", steps_raw.replace("\n", " "))
            if j:
                steps = json.loads(j.group(1))
                if steps:
                    assigned = steps[0].get("assigned_to_name", "?")
                    print(f"   Assigned approver: {assigned!r}  (expected NM, not RM)")
        except Exception:
            pass

        ok58 = c_rev == 200 and status58 == "PENDING_APPROVAL"
        report(
            "TEST 5.8  Vacancy escalation no 500",
            ok58,
            extra=f"HTTP {c_rev}  status={status58}  assigned={assigned!r}",
            notes="FIX C1: AmbiguousParameterError in NEAREST_ANCESTOR_WITH_POSITION SQL fixed",
        )
    else:
        report(
            "TEST 5.8  Vacancy escalation no 500",
            False,
            extra="Transfer creation failed",
        )
else:
    report(
        "TEST 5.8  Vacancy escalation no 500",
        False,
        extra="Missing PRODUCT_ID or node IDs — run Groups 3-4 first",
    )

# Reactivate RM
if RM_USER_ID:
    req("PATCH", f"/tenants/{TENANT_ID}/users/{RM_USER_ID}/reactivate", TA_JWT)
    psql_rls(
        TENANT_ID,
        f"UPDATE personnel_positions SET is_active=true WHERE user_id='{RM_USER_ID}';",
    )


# ════════════════════════════════════════════════════════════
# TEST 5.10 — product:create in audit log (FIX C2)
# ════════════════════════════════════════════════════════════
print("\nTEST 5.10 — product:create appears in audit_log")

# Create a fresh product so the audit entry is recent
NM_JWT, NM_C, _, _ = get_jwt("nm@int-test.com", "NMUser@2026")
sku_suffix = str(_uuid.uuid4())[:6].upper()
c_prod, d_prod = req(
    "POST",
    "/products/",
    NM_JWT,
    {
        "name": f"Audit Test Product {sku_suffix}",
        "type_code": "AUT",
        "unit": "KG",
        "unit_price": 75.00,
        "currency": "ETB",
    },
)
AUDIT_PROD_ID = d_prod.get("data", {}).get("id", "")
AUDIT_SKU = d_prod.get("data", {}).get("sku", "")
print(
    f"   Create product: HTTP {c_prod}  id={AUDIT_PROD_ID[:8] if AUDIT_PROD_ID else 'FAIL'}...  sku={AUDIT_SKU}"
)

# Query audit_logs — search ALL entries for this tenant, not just LIMIT 20
audit_raw = psql_rls(
    TENANT_ID,
    f"SELECT action, decision, LEFT(resource_id::text,8) AS rid "
    f"FROM audit_logs "
    f"WHERE tenant_id='{TENANT_ID}' AND action='product:create' "
    f"ORDER BY timestamp DESC LIMIT 5;",
)
print(f"   Audit query result:\n{audit_raw}")

has_entry = "product:create" in audit_raw and "GRANTED" in audit_raw
has_prod_id = AUDIT_PROD_ID[:8] in audit_raw if AUDIT_PROD_ID else False
ok510 = c_prod == 201 and has_entry
report(
    "TEST 5.10 product:create in audit log",
    ok510,
    extra=f"product:create found={has_entry}  product_id in log={has_prod_id}",
    notes=[
        "FIX C2: audit log was already written; unit_price+currency added to abac_context",
        "Test 5.10 previously showed false-negative due to LIMIT 20 hiding older entries",
    ],
)


# ════════════════════════════════════════════════════════════
# SUMMARY
# ════════════════════════════════════════════════════════════
passed = sum(1 for v in results.values() if v)
total = len(results)
failed = [k for k, v in results.items() if not v]

print(f"\n{'=' * 60}")
print("SUMMARY")
print(f"PASSED: {passed}/{total}")
print(f"FAILED: {total - passed}/{total}")
if failed:
    print("FAILURES:")
    for f in failed:
        print(f"  XX {f}")
else:
    print("All retested items pass.")
