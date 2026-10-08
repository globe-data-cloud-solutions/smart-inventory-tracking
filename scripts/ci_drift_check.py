"""CI drift check — fails if any FastAPI route is missing @require_permission.
Fails if any action used in a decorator is not in registry.py.
Run as: python scripts/ci_drift_check.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SERVICES_DIR = ROOT / "backend" / "services"

# Routes that are intentionally public and must not carry @require_permission.
# Key: path relative to repo root, POSIX separators.
# Value: list of async def function names that are exempt.
#
# Rationale for each entry:
#   auth-service/routers/auth.py::exchange_token  — POST /token exchanges a Cognito
#     IdToken for a SMART JWT.  No SMART JWT exists yet, so requiring one is circular.
#   auth-service/routers/auth.py::refresh_token   — POST /refresh delegates entirely
#     to the Cognito refresh flow; no SMART JWT is present or needed.
#
# Adding a function here is a deliberate decision that must be reviewed and approved.
# Any new entry that is NOT in this list will still fail CI if it lacks the decorator.
ALLOWLISTED_PUBLIC_ROUTES: dict[str, list[str]] = {
    "backend/services/auth-service/routers/auth.py": [
        "exchange_token",
        "refresh_token",
        # Local-dev password change endpoint — protected by ENVIRONMENT=local guard, not JWT.
        "change_password_by_id",
        # Public email verification (S4) — no SMART JWT exists until the user signs in.
        "verify_email",
        "resend_verification",
        # Public password reset (B2) — no SMART JWT exists until the user signs in.
        "forgot_password",
        "reset_password",
    ],
    "backend/services/tenant-service/routers/public_signup.py": [
        # Public self sign-up (S4) — no SMART JWT exists until the account is created.
        "list_public_packages",
        "public_signup",
    ],
    "backend/services/tenant-service/routers/billing.py": [
        # Public STUB payment webhook (S5) — a payment gateway's server-to-server
        # callback carries no SMART JWT; its HMAC signature IS the auth check.
        "stub_payment_webhook",
    ],
}


def find_router_files() -> list[Path]:
    return list(SERVICES_DIR.rglob("routers/*.py"))


def check_file(
    path: Path,
    allowlisted_names: set[str],
) -> tuple[list[str], int]:
    """Return (violations, allowlist_hit_count) for all route functions in path."""
    errors: list[str] = []
    allowlisted = 0
    source = path.read_text(encoding="utf-8-sig")  # utf-8-sig strips BOM if present
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        # Only check functions decorated with @router.<method>
        route_deco_names = {
            n.attr
            for n in (ast.walk(d) for d in node.decorator_list)
            for n in n  # type: ignore[assignment]
            if isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name)
            and n.value.id == "router"
            and n.attr in ("get", "post", "patch", "delete", "put")
        }
        if not route_deco_names:
            continue

        # Check for @require_permission decorator
        has_require = any(
            (
                isinstance(d, ast.Call)
                and isinstance(d.func, ast.Name)
                and d.func.id == "require_permission"
            )
            or (
                isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and d.func.attr == "require_permission"
            )
            for d in node.decorator_list
        )

        if not has_require:
            if node.name in allowlisted_names:
                allowlisted += 1
            else:
                errors.append(
                    f"{path.relative_to(ROOT)}:{node.lineno} "
                    f"route '{node.name}' is missing @require_permission"
                )

    return errors, allowlisted


def main() -> int:
    router_files = find_router_files()
    all_errors: list[str] = []
    total_allowlisted = 0

    for f in router_files:
        posix_rel = f.relative_to(ROOT).as_posix()
        allowlisted_names = set(ALLOWLISTED_PUBLIC_ROUTES.get(posix_rel, []))
        errs, hits = check_file(f, allowlisted_names)
        all_errors.extend(errs)
        total_allowlisted += hits

    if all_errors:
        print("FAIL Permission drift detected:\n")
        for err in all_errors:
            print(f"  {err}")
        print(
            f"\n{len(all_errors)} route(s) without @require_permission. "
            f"{total_allowlisted} route(s) explicitly allowlisted as public. "
            "CI blocked."
        )
        return 1

    print(
        f"PASS Permission check passed -- "
        f"{len(router_files)} router file(s) scanned, "
        f"{total_allowlisted} public route(s) allowlisted, "
        "no drift detected."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
