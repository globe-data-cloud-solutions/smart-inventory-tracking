"""Transfer types (PULL/PUSH/SISTER) and a mixed approval set, through the real API."""
import json, sys
from api import call
from build_org import step, results

def build(code):
    ta = f"admin@{code}.com"
    org = json.load(open(f"org_{code}.json"))
    t, pos = org["tenant_id"], org["positions"]
    types = [
        {"underlying_type": "PULL", "display_name": "Pull", "description": "Warehouse requests stock from a factory or warehouse",
         "is_active": True, "sort_order": 1,
         "level_permissions": [{"level_number": 4, "can_initiate": True, "can_receive": True},
                               {"level_number": 1, "can_initiate": False, "can_receive": False}]},
        {"underlying_type": "PUSH", "display_name": "Push", "description": "Factory pushes stock to a warehouse",
         "is_active": True, "sort_order": 2,
         "level_permissions": [{"level_number": 1, "can_initiate": True, "can_receive": False},
                               {"level_number": 4, "can_initiate": False, "can_receive": True}]},
        {"underlying_type": "SISTER", "display_name": "Sister", "description": "Warehouse to warehouse, same subregion",
         "is_active": True, "sort_order": 3,
         "level_permissions": [{"level_number": 4, "can_initiate": True, "can_receive": True}]},
    ]
    s, d = call(ta, "PUT", f"/tenants/{t}/transfer-types", types)
    cfg = step("transfer types PUT", s, d) or []
    cfg_id = {c["underlying_type"]: c["id"] for c in cfg} if cfg else {}
    if not cfg_id: return
    def step_(seq, key): return {"sequence": seq, "position_id": pos[key]["id"], "position_title": pos[key]["title"], "resolution": "ANY", "execution_mode": "SEQUENTIAL", "sla_hours": 48}
    rules = [
        # PULL: small quantities -> local manager only
        {"transfer_type_config_id": cfg_id["PULL"], "quantity_min": 0, "quantity_max": 999.99, "threshold_type": "QUANTITY",
         "currency": "ETB", "approval_steps": [step_(1, "R1")]},
        # PULL: large quantities -> local manager, then regional manager
        {"transfer_type_config_id": cfg_id["PULL"], "quantity_min": 1000, "quantity_max": None, "threshold_type": "QUANTITY",
         "currency": "ETB", "approval_steps": [step_(1, "R1"), step_(2, "F1")]},
        # PUSH: regional then national
        {"transfer_type_config_id": cfg_id["PUSH"], "quantity_min": 0, "quantity_max": None, "threshold_type": "QUANTITY",
         "currency": "ETB", "approval_steps": [step_(1, "R1"), step_(2, "F1")]},
        # SISTER: local manager only
        {"transfer_type_config_id": cfg_id["SISTER"], "quantity_min": 0, "quantity_max": None, "threshold_type": "QUANTITY",
         "currency": "ETB", "approval_steps": [step_(1, "R1")]},
    ]
    s, d = call(ta, "PUT", f"/tenants/{t}/transfer-approval-rules", rules)
    step("transfer approval rules PUT", s, d)
    org["transfer_type_ids"] = cfg_id
    json.dump(org, open(f"org_{code}.json", "w"), indent=2, default=str)

if __name__ == "__main__":
    build(sys.argv[1])
    print("FAILS", len([r for r in results if not r["ok"]]))
