"""Build the org structure, positions and users for one tenant through the real API."""
import json, sys
from api import call, tenant_id

PW = "smart1026"
results = []  # (step, status, ok, detail)
def step(name, status, data, expect=(200, 201)):
    ok = status in expect
    detail = "" if ok else json.dumps(data)[:300]
    results.append({"step": name, "status": status, "ok": ok, "detail": detail})
    print(("OK  " if ok else "FAIL"), status, name, detail)
    return data.get("data") if ok and isinstance(data, dict) else None

def build(code):
    ta = f"admin@{code}.com"
    t = tenant_id(ta)
    # 1) Levels (already set in the first pass; PUT is idempotent for config)
    levels = [
        {"level_number": 1, "level_name": "Factory", "default_role_code": "NM", "role_display_label": "National Manager", "is_stock_holding": True},
        {"level_number": 2, "level_name": "Region", "default_role_code": "RM", "role_display_label": "Regional Manager", "is_stock_holding": False},
        {"level_number": 3, "level_name": "Subregion", "default_role_code": "LM", "role_display_label": "Local Manager", "is_stock_holding": False},
        {"level_number": 4, "level_name": "Warehouse", "default_role_code": "WM", "role_display_label": "Warehouse Manager", "is_stock_holding": True},
    ]
    step("hierarchy levels PUT", *call(ta, "PUT", f"/tenants/{t}/hierarchy/config", levels)[:1], call(ta, "GET", f"/tenants/{t}/hierarchy/config")[1]) if False else None
    s, d = call(ta, "PUT", f"/tenants/{t}/hierarchy/config", levels); step("hierarchy levels PUT", s, d)

    # 2) Nodes (parent first)
    spec = [
        ("F1", "Factory A", 1, None),
        ("F2", "Factory B", 1, None),
        ("R1", "Region North", 2, "F1"),
        ("R2", "Region South", 2, "F2"),
        ("S1", "Subregion A1", 3, "R1"),
        ("S2", "Subregion B1", 3, "R2"),
        ("W1", "WH A1-1", 4, "S1"),
        ("W2", "WH A1-2", 4, "S1"),
        ("W3", "WH B1-1", 4, "S2"),
    ]
    nodes = {}
    for key, name, lvl, parent in spec:
        body = {"name": name, "level_number": lvl}
        if parent: body["parent_node_id"] = nodes[parent]["id"]
        s, d = call(ta, "POST", f"/tenants/{t}/nodes", body)
        nodes[key] = step(f"node {name}", s, d, expect=(200, 201)) or {}
    # 3) Positions: one per node, reporting to the node above (WM -> LM -> RM -> NM)
    pos_role = {"F1": "NM", "F2": "NM", "R1": "RM", "R2": "RM", "S1": "LM", "S2": "LM", "W1": "WM", "W2": "WM", "W3": "WM"}
    pos_title = {"F1": "National Manager Factory A", "F2": "National Manager Factory B",
                 "R1": "Regional Manager North", "R2": "Regional Manager South",
                 "S1": "Local Manager A1", "S2": "Local Manager B1",
                 "W1": "Warehouse Manager A1-1", "W2": "Warehouse Manager A1-2", "W3": "Warehouse Manager B1-1"}
    reports_to = {"R1": "F1", "R2": "F2", "S1": "R1", "S2": "R2", "W1": "S1", "W2": "S1", "W3": "S2"}
    positions = {}
    for key in ["F1", "F2", "R1", "R2", "S1", "S2", "W1", "W2", "W3"]:
        body = {"title": pos_title[key], "role_code": pos_role[key]}
        if key in reports_to: body["reports_to_position_id"] = positions[reports_to[key]]["id"]
        s, d = call(ta, "POST", f"/tenants/{t}/nodes/{nodes[key]['id']}/positions", body)
        positions[key] = step(f"position {pos_title[key]}", s, d) or {}
    # 4) Users with PRIMARY position (naming: userNW / userRM1 / userWM1 ...)
    people = [
        ("userNW", "National Manager Factory A", "F1"),
        ("userNW2", "National Manager Factory B", "F2"),
        ("userRM1", "Regional Manager North", "R1"),
        ("userRM2", "Regional Manager South", "R2"),
        ("userLM1", "Local Manager A1", "S1"),
        ("userLM2", "Local Manager B1", "S2"),
        ("userWM1", "Warehouse Manager A1-1", "W1"),
        ("userWM2", "Warehouse Manager A1-2", "W2"),
        ("userWM3", "Warehouse Manager B1-1", "W3"),
    ]
    users = {}
    for uname, _, key in people:
        email = f"{uname}@{code}.com"
        body = {"name": uname, "email": email, "password": PW, "position_id": positions[key]["id"]}
        s, d = call(ta, "POST", f"/tenants/{t}/users", body)
        users[uname] = step(f"user {email}", s, d) or {}
    # tenant-wide auditor
    s, d = call(ta, "POST", f"/tenants/{t}/users", {"name": "userAU1", "email": f"userAU1@{code}.com", "password": PW, "system_role": "AU"})
    users["userAU1"] = step(f"user userAU1@{code}.com (AU)", s, d) or {}
    out = {"tenant_id": t, "nodes": nodes, "positions": positions, "users": users}
    json.dump(out, open(f"org_{code}.json", "w"), indent=2, default=str)
    return results

if __name__ == "__main__":
    build(sys.argv[1])
    fails = [r for r in results if not r["ok"]]
    print("TOTAL", len(results), "FAILS", len(fails))
