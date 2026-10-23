"""Run the org, product, stock, transfer, adjustment, discrepancy and issue phases for the three tenants.
Sign-up and email verification happen first (UI scripts). Every call goes through the gateway API."""
import json, sys, uuid
from build_org import build as build_org_, results, step
from build_transfer_cfg import build as build_cfg
from build_products import build as build_products
from build_stock import build as build_stock
from transfers_flow import flow
from adj_disc import adjust, discrepancy
from api import call

TENANTS = ["tc01", "tc02", "tc03"]

def issues(code):
    org = json.load(open(f"org_{code}.json")); P, N = org["products"], org["nodes"]
    for who, wh, prod, qty in [("userWM1", "W1", "FEFO_YOGHURT", "100"), ("userWM2", "W2", "PLAIN_FLOUR", "25")]:
        body = {"product_id": P[prod], "warehouse_id": N[wh]["id"], "quantity": qty, "reason_code": "SAMPLE",
                "issued_to": "Customer demo", "notes": "e2e issue", "idempotency_key": str(uuid.uuid4()), "source": "WEB"}
        s, d = call(f"{who}@{code}.com", "POST", "/inventory/issues/", body)
        step(f"issue {prod} {qty} from {wh} by {who}", s, d)

def run(code):
    build_org_(code)
    build_cfg(code)
    build_products(code)
    build_stock(code)
    tids = {}
    tids["pull_small"] = flow(code, "PULL small", "PULL", "W2", "W1", [("PLAIN_FLOUR", 50)], "userWM1", ["userRM1"], "userWM2", "userWM1")
    tids["pull_large"] = flow(code, "PULL large", "PULL", "W3", "W1", [("PLAIN_FLOUR", 1200)], "userWM1", ["userRM1", "userNW"], "userWM3", "userWM1")
    tids["sister"] = flow(code, "SISTER", "SISTER", "W1", "W2", [("PLAIN_SALT", 100)], "userWM1", ["userRM1"], "userWM1", "userWM2")
    tids["pull_fefo"] = flow(code, "PULL FEFO yoghurt", "PULL", "W2", "W1", [("FEFO_YOGHURT", 300)], "userWM1", ["userRM1"], "userWM2", "userWM1")
    adjust(code, "DAMAGE -20 oil @W1", "userWM1", "W1", "PLAIN_OIL", -20, "DAMAGE", "userRM1")
    adjust(code, "COUNT +15 salt @W2 (RM1, same region)", "userWM2", "W2", "PLAIN_SALT", 15, "COUNT_DISCREPANCY", "userRM1")
    adjust(code, "EXPIRY -40 yoghurt lot A @W1", "userWM1", "W1", "FEFO_YOGHURT", -40, "EXPIRY", "userNW", lot_number=f"LOT-A-{code.upper()}")
    adjust(code, "COUNT -5 salt @W1 (scope test: RM2 must be refused)", "userWM1", "W1", "PLAIN_SALT", -5, "COUNT_DISCREPANCY", "userRM2")
    discrepancy(code)
    issues(code)
    json.dump(tids, open(f"transfers_{code}.json", "w"), indent=2)

if __name__ == "__main__":
    for code in (sys.argv[1:] or TENANTS):
        run(code)
    fails = [r for r in results if not r["ok"]]
    json.dump(results, open("e2e_report.json", "w"), indent=2)
    print("STEPS", len(results), "OK", len(results) - len(fails), "FAIL", len(fails))
    for r in fails: print("FAIL:", r["step"], r["status"], r["detail"][:160])
