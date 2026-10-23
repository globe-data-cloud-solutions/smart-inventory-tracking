"""Opening stock: each warehouse manager receives into their own warehouse, through the real receive endpoint."""
import json, sys, uuid
from api import call
from build_org import step, results

WM_TO_WH = {"userWM1": "W1", "userWM2": "W2", "userWM3": "W3"}
PLAIN = ["PLAIN_FLOUR", "PLAIN_OIL", "PLAIN_SALT"]
LOT_TRACKED = {  # product key -> (lot A expiry, lot B expiry or None)
    "FEFO_YOGHURT": ("2026-12-31", "2027-06-30"),
    "FEFO_BISCUIT": ("2027-03-31", "2027-09-30"),
    "FIFO_SUGAR": (None, None),
    "FIFO_RICE": (None, None),
}

def build(code):
    org = json.load(open(f"org_{code}.json"))
    t = org["tenant_id"]
    for wm, wkey in WM_TO_WH.items():
        email = f"{wm}@{code}.com"
        wh_id = org["nodes"][wkey]["id"]
        for key in PLAIN:
            body = {"product_id": org["products"][key], "warehouse_id": wh_id, "quantity": "1500",
                    "unit_cost": "50.00", "idempotency_key": str(uuid.uuid4()), "source": "WEB"}
            s, d = call(email, "POST", "/inventory/receive/", body)
            step(f"{wm} receive {key} x1500", s, d)
        for key, (exp_a, exp_b) in LOT_TRACKED.items():
            lots = [("LOT-A-" + code.upper(), exp_a, "1000"), ("LOT-B-" + code.upper(), exp_b, "800")] if exp_a else [("LOT-A-" + code.upper(), None, "1000"), ("LOT-B-" + code.upper(), None, "800")]
            for lot_no, exp, qty in lots:
                body = {"product_id": org["products"][key], "warehouse_id": wh_id, "quantity": qty,
                        "unit_cost": "60.00", "lot_number": lot_no, "idempotency_key": str(uuid.uuid4()), "source": "WEB"}
                if exp: body["expiry_date"] = exp
                s, d = call(email, "POST", "/inventory/receive/", body)
                step(f"{wm} receive {key} lot {lot_no} x{qty}", s, d)

if __name__ == "__main__":
    build(sys.argv[1])
    print("FAILS", len([r for r in results if not r["ok"]]))
