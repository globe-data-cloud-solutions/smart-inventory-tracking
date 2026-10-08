"""Consistency check: every route scripts/ci_drift_check.py allowlists as
public (no @require_permission — because no SMART JWT exists yet) must also
be reachable through api-gateway WITHOUT a Bearer token, i.e. its full path
must be in UNAUTHENTICATED_PATHS. A route missing from one list but not the
other is exactly the class of bug fixed in this commit (forgot/reset-password
401'd at the gateway despite being deliberately public at the service layer).

Router files are parsed with ast (not imported) — same technique
ci_drift_check.py itself uses — so this needs no DB and no running service.
"""
import ast
import importlib.util
import os

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

# Mirrors each service's app.include_router(..., prefix=...) in its main.py.
# If a router's prefix ever changes there, update it here too.
ROUTER_PREFIXES = {
    "backend/services/auth-service/routers/auth.py": "/api/v1/auth",
    "backend/services/tenant-service/routers/public_signup.py": "/api/v1/tenants",
    "backend/services/tenant-service/routers/billing.py": "/api/v1/tenants",
}

# Parameterized paths (contain a {...} segment) can never be exact-matched in
# UNAUTHENTICATED_PATHS — the gateway only does exact string lookups. Each
# entry here must be a route that's genuinely unreachable without one of its
# path params, not just something inconvenient to add.
SKIP_PARAMETERIZED = {
    # PATCH /api/v1/auth/password/{user_id} — local-dev-only password change,
    # gated by ENVIRONMENT=local inside the handler, not by the gateway.
    ("backend/services/auth-service/routers/auth.py", "change_password_by_id"),
}


def _load_ci_drift_check():
    spec = importlib.util.spec_from_file_location(
        "ci_drift_check_for_gateway_consistency_test",
        os.path.join(ROOT, "scripts", "ci_drift_check.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_gateway_unauthenticated_paths() -> set[str]:
    spec = importlib.util.spec_from_file_location(
        "api_gateway_main_for_consistency_test",
        os.path.join(os.path.dirname(__file__), "..", "main.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.UNAUTHENTICATED_PATHS


def _route_path(tree: ast.AST, func_name: str) -> tuple[str, str] | None:
    """Return (METHOD, path) for the @router.<method>("path", ...) decorator
    on `func_name`, or None if not found."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name != func_name:
            continue
        for d in node.decorator_list:
            if (
                isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and isinstance(d.func.value, ast.Name)
                and d.func.value.id == "router"
                and d.func.attr in ("get", "post", "patch", "delete", "put")
            ):
                if d.args and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str):
                    return d.func.attr.upper(), d.args[0].value
    return None


def _allowlisted_full_paths() -> list[tuple[str, str, str]]:
    """(rel_path, func_name, full_path) for every allowlisted route that is
    NOT in SKIP_PARAMETERIZED, built by parsing the router file's AST and
    joining with its known gateway prefix."""
    ci_drift_check = _load_ci_drift_check()
    out: list[tuple[str, str, str]] = []
    for rel_path, func_names in ci_drift_check.ALLOWLISTED_PUBLIC_ROUTES.items():
        prefix = ROUTER_PREFIXES[rel_path]
        source = open(os.path.join(ROOT, rel_path), encoding="utf-8-sig").read()
        tree = ast.parse(source)
        for func_name in func_names:
            if (rel_path, func_name) in SKIP_PARAMETERIZED:
                continue
            route = _route_path(tree, func_name)
            assert route is not None, f"{rel_path}::{func_name} has no @router.<method>(...) decorator"
            _, sub_path = route
            full_path = prefix + sub_path
            assert "{" not in full_path, (
                f"{rel_path}::{func_name} -> {full_path} is parameterized — "
                "add it to SKIP_PARAMETERIZED with a comment, not here"
            )
            out.append((rel_path, func_name, full_path))
    return out


@pytest.mark.parametrize(
    "rel_path,func_name,full_path",
    _allowlisted_full_paths(),
    ids=lambda v: v if isinstance(v, str) and v.startswith("/") else None,
)
def test_allowlisted_public_route_is_gateway_unauthenticated(
    rel_path: str, func_name: str, full_path: str
) -> None:
    unauthenticated_paths = _load_gateway_unauthenticated_paths()
    assert full_path in unauthenticated_paths, (
        f"{rel_path}::{func_name} is allowlisted as public (no @require_permission) "
        f"but {full_path} is missing from api-gateway's UNAUTHENTICATED_PATHS — "
        "anonymous callers would get 401 at the gateway before ever reaching it."
    )
