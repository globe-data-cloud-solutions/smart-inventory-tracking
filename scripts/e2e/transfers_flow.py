"""Run transfer lifecycles through the real API and record each step."""
import json, sys
from api import call
from build_org import step, results

def flow(code, label, ttype, src, dst, lines, requester, approvers, dispatcher, receiver):
    org = json.load(open(f"org_{code}.json"))
    n, p, ttid = org["nodes"], org["products"], org["transfer_type_ids"]
    ta_email = lambda k: f"{k}@{code}.com"
    body = {"transfer_type": ttype, "from_warehouse_id": n[src]["id"], "to_warehouse_id": n[dst]["id"],
            "lines": [{"product_id": p[k], "quantity": str(q)} for k, q in lines],
            "notes": f"e2e {label}", "transfer_type_config_id": ttid[ttype]}
    s, d = call(ta_email(requester), "POST", "/inventory/transfers/", body)
    t = step(f"{label}: create by {requester}", s, d)
    if not t: return None
    tid = t["transfer_id"]
    s, d = call(ta_email(requester), "POST", f"/inventory/transfers/{tid}/submit"); step(f"{label}: submit", s, d)
    if ttype == "SISTER":
        s, d = call(ta_email(requester), "PATCH", f"/inventory/transfers/{tid}", {"next_status": "PENDING_DEST_CONFIRM"}); step(f"{label}: source confirm by {requester}", s, d)
        s, d = call(ta_email(receiver), "PATCH", f"/inventory/transfers/{tid}", {"next_status": "PENDING_APPROVAL"}); step(f"{label}: destination confirm by {receiver}", s, d)
    else:
        s, d = call(ta_email(approvers[0]), "POST", f"/inventory/transfers/{tid}/review", {}); step(f"{label}: review by {approvers[0]}", s, d)
    for a in approvers:
        s, d = call(ta_email(a), "POST", f"/inventory/transfers/{tid}/approve", {})
        step(f"{label}: approve by {a}", s, d)
        if s != 200: break
        if d["data"]["status"] == "APPROVED": break
    s, d = call(ta_email(dispatcher), "POST", f"/inventory/transfers/{tid}/dispatch"); step(f"{label}: dispatch by {dispatcher}", s, d)
    s, d = call(ta_email(dispatcher), "PATCH", f"/inventory/transfers/{tid}", {"next_status": "IN_TRANSIT"}); step(f"{label}: in transit by {dispatcher}", s, d)
    s, d = call(ta_email(receiver), "POST", f"/inventory/transfers/{tid}/receive"); step(f"{label}: receive by {receiver}", s, d)
    return tid

if __name__ == "__main__":
    code = sys.argv[1]
    tids = {}
    tids["pull_small"] = flow(code, "PULL small", "PULL", "W2", "W1", [("PLAIN_FLOUR", 50)], "userWM1", ["userRM1"], "userWM2", "userWM1")
    tids["pull_large"] = flow(code, "PULL large", "PULL", "W3", "W1", [("PLAIN_FLOUR", 1200)], "userWM1", ["userRM1", "userNW"], "userWM3", "userWM1")
    tids["sister"] = flow(code, "SISTER", "SISTER", "W1", "W2", [("PLAIN_SALT", 100)], "userWM1", ["userRM1"], "userWM1", "userWM2")
    tids["pull_fefo"] = flow(code, "PULL FEFO yoghurt", "PULL", "W2", "W1", [("FEFO_YOGHURT", 300)], "userWM1", ["userRM1"], "userWM2", "userWM1")
    json.dump(tids, open(f"transfers_{code}.json", "w"), indent=2)
    print("FAILS", len([r for r in results if not r["ok"]]))
