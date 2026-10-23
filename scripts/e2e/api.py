"""Thin client for the walkthrough. Talks only to the gateway on localhost (refuses other hosts
unless E2E_ALLOW_REMOTE=1). Test accounts use the shared password smart1026 and must never be
used outside a developer machine."""
import json, os
from urllib.parse import urlparse
import httpx

BASE = os.environ.get("E2E_API_BASE", "http://127.0.0.1:8000/api/v1")
_host = urlparse(BASE).hostname
if _host not in ("localhost", "127.0.0.1") and os.environ.get("E2E_ALLOW_REMOTE") != "1":
    raise SystemExit(f"Refusing to run the walkthrough against {_host}. Set E2E_ALLOW_REMOTE=1 only for a throwaway environment.")
_tokens = {}
def login(email, password="smart1026"):
    r = httpx.post(f"{BASE}/auth/token", json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    d = r.json()
    tok = d["data"]["access_token"] if "data" in d else d["access_token"]
    _tokens[email] = tok
    return tok
def call(email, method, path, body=None):
    tok = _tokens.get(email) or login(email)
    r = httpx.request(method, f"{BASE}{path}", json=body, headers={"Authorization": f"Bearer {tok}"}, timeout=60)
    try: data = r.json()
    except Exception: data = {"raw": r.text[:300]}
    return r.status_code, data
import base64
def tenant_id(email):
    tok = _tokens.get(email) or login(email)
    payload = tok.split(".")[1] + "=="
    return json.loads(base64.urlsafe_b64decode(payload))["tenant_id"]
