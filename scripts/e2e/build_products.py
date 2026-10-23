"""Products of several natures, with lot/expiry tracking and FEFO/FIFO dispatch, via the real API."""
import json, sys
from api import call
from build_org import step, results

PRODUCTS = [
    # key, name, type_code, unit, unit_price, reorder, lot: (batch, expiry, strategy) or None
    ("PLAIN_FLOUR", "Maize Flour 1kg", "FL", "pcs", "85.00", "200", None),
    ("PLAIN_OIL", "Cooking Oil 5L", "OL", "pcs", "890.00", "50", None),
    ("PLAIN_SALT", "Iodised Salt 1kg", "SA", "pcs", "35.00", "300", None),
    ("FEFO_YOGHURT", "Yoghurt 500g", "YG", "pcs", "120.00", "150", (True, True, "FEFO")),
    ("FEFO_BISCUIT", "Cream Biscuit 200g", "BS", "pcs", "65.00", "400", (True, True, "FEFO")),
    ("FIFO_SUGAR", "Sugar 50kg", "SG", "bag", "2400.00", "40", (True, False, "FIFO")),
    ("FIFO_RICE", "Rice 25kg", "RC", "bag", "1850.00", "60", (True, False, "FIFO")),
]

def build(code):
    ta = f"admin@{code}.com"
    org = json.load(open(f"org_{code}.json"))
    ids = {}
    for key, name, tc, unit, price, reorder, lot in PRODUCTS:
        body = {"name": name, "type_code": tc, "unit": unit, "unit_price": price, "reorder_point": reorder, "currency": "ETB"}
        s, d = call(ta, "POST", "/products/", body)
        p = step(f"product {name}", s, d)
        if not p: continue
        pid = p.get("id") or p.get("product_id")
        ids[key] = pid
        if lot:
            batch, expiry, strat = lot
            s, d = call(ta, "PUT", f"/inventory/products/{pid}/lot-settings",
                        {"batch_tracking": batch, "expiry_tracking": expiry, "dispatch_strategy": strat})
            step(f"lot settings {name} ({strat}, batch={batch}, expiry={expiry})", s, d)
    org["products"] = ids
    json.dump(org, open(f"org_{code}.json", "w"), indent=2, default=str)

if __name__ == "__main__":
    build(sys.argv[1])
    print("FAILS", len([r for r in results if not r["ok"]]))
