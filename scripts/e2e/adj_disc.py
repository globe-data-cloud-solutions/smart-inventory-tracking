"""Adjustments (with approval and scope checks) and a short-receipt discrepancy with resolution."""
import json, sys, uuid
from api import call
from build_org import step, results

def adjust(code, label, wm, wh_key, prod_key, delta, reason, approver, lot_number=None, notes=""):
    org = json.load(open(f"org_{code}.json")); n, p = org["nodes"], org["products"]
    body = {"warehouse_id": n[wh_key]["id"], "product_id": p[prod_key], "quantity_delta": str(delta),
            "reason_code": reason, "idempotency_key": str(uuid.uuid4()), "notes": notes or f"e2e {label}"}
    if lot_number:
        s0, d0 = call(f"{wm}@{code}.com", "GET", f"/inventory/lots?product_id={p[prod_key]}&warehouse_id={n[wh_key]['id']}")
        body["lot_id"] = [x for x in d0["data"] if x["lot_number"] == lot_number][0]["lot_id"]
    s, d = call(f"{wm}@{code}.com", "POST", "/inventory/adjustments/", body)
    a = step(f"adjust {label}: create by {wm}", s, d)
    if not a: return
    aid = a["adjustment_id"] if "adjustment_id" in a else a["id"]
    s, d = call(f"{wm}@{code}.com", "POST", f"/inventory/adjustments/{aid}/submit"); step(f"adjust {label}: submit", s, d)
    s, d = call(f"{approver}@{code}.com", "POST", f"/inventory/adjustments/{aid}/approve", {})
    step(f"adjust {label}: approve by {approver}", s, d, expect=(403,) if "scope test" in label else (200,))
    return aid

def discrepancy(code):
    org = json.load(open(f"org_{code}.json")); tt = org["transfer_type_ids"]; n, p = org["nodes"], org["products"]
    body = {"transfer_type": "PULL", "from_warehouse_id": n["W2"]["id"], "to_warehouse_id": n["W1"]["id"],
            "lines": [{"product_id": p["PLAIN_SALT"], "quantity": "100"}], "notes": "e2e discrepancy", "transfer_type_config_id": tt["PULL"]}
    s, d = call(f"userWM1@{code}.com", "POST", "/inventory/transfers/", body); tid = step("discrepancy: create PULL 100 salt", s, d)["transfer_id"]
    call(f"userWM1@{code}.com", "POST", f"/inventory/transfers/{tid}/submit")
    call(f"userRM1@{code}.com", "POST", f"/inventory/transfers/{tid}/review", {})
    s, d = call(f"userRM1@{code}.com", "POST", f"/inventory/transfers/{tid}/approve", {}); step("discrepancy: approve by userRM1", s, d)
    s, d = call(f"userWM2@{code}.com", "POST", f"/inventory/transfers/{tid}/dispatch"); step("discrepancy: dispatch by userWM2", s, d)
    call(f"userWM2@{code}.com", "PATCH", f"/inventory/transfers/{tid}", {"next_status": "IN_TRANSIT"})
    s, d = call(f"userWM1@{code}.com", "GET", f"/inventory/transfers/{tid}")
    line_id = d["data"]["lines"][0].get("line_id") or d["data"]["lines"][0].get("id")
    body = {"lines": [{"line_id": line_id, "received_quantity": "90", "reason": "SHORT", "note": "10 units short"}]}
    s, d = call(f"userWM1@{code}.com", "POST", f"/inventory/transfers/{tid}/receive", body); step("discrepancy: partial receive 90 of 100", s, d)
    s, d = call(f"userWM1@{code}.com", "GET", f"/inventory/transfers/{tid}")
    discs = d["data"].get("discrepancies", []) if s == 200 else []
    step(f"discrepancy: open discrepancies after receipt = {len(discs)}", 200, {}) 
    if discs:
        did = discs[0].get("id") or discs[0].get("discrepancy_id")
        s, d = call(f"userRM1@{code}.com", "POST", f"/inventory/transfers/{tid}/discrepancies/{did}/resolve", {"resolution": "WRITTEN_OFF", "note": "agreed write-off"})
        step("discrepancy: resolve WRITTEN_OFF by userRM1", s, d)
    return tid

if __name__ == "__main__":
    code = sys.argv[1]
    adjust(code, "DAMAGE -20 oil @W1", "userWM1", "W1", "PLAIN_OIL", -20, "DAMAGE", "userRM1")
    adjust(code, "COUNT +15 salt @W2 (RM1, same region)", "userWM2", "W2", "PLAIN_SALT", 15, "COUNT_DISCREPANCY", "userRM1")
    adjust(code, "EXPIRY -40 yoghurt lot A @W1", "userWM1", "W1", "FEFO_YOGHURT", -40, "EXPIRY", "userNW", lot_number=f"LOT-A-{code.upper()}")
    # scope check (should be refused): RM2 (South) approving a Region North adjustment
    aid = adjust(code, "COUNT -5 salt @W1 (scope test: RM2 must be refused)", "userWM1", "W1", "PLAIN_SALT", -5, "COUNT_DISCREPANCY", "userRM2")
    discrepancy(code)
    print("FAILS", len([r for r in results if not r["ok"]]))
