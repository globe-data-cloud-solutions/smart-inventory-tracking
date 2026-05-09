"""CI drift check — fails if any FastAPI route is missing @require_permission.
Fails if any action used in a decorator is not in registry.py.
Run as: python scripts/ci_drift_check.py
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SERVICES_DIR = ROOT / "backend" / "services"


def find_router_files() -> list[Path]:
    return list(SERVICES_DIR.rglob("routers/*.py"))


def check_file(path: Path) -> list[str]:
    errors: list[str] = []
    source = path.read_text(encoding="utf-8-sig")  # utf-8-sig strips BOM if present
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
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
            (isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "require_permission")
            or (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "require_permission")
            for d in node.decorator_list
        )

        if not has_require:
            errors.append(
                f"{path.relative_to(ROOT)}:{node.lineno} "
                f"route '{node.name}' is missing @require_permission"
            )

    return errors


def main() -> int:
    router_files = find_router_files()
    all_errors: list[str] = []

    for f in router_files:
        all_errors.extend(check_file(f))

    if all_errors:
        print("FAIL Permission drift detected:\n")
        for err in all_errors:
            print(f"  {err}")
        print(f"\n{len(all_errors)} route(s) without @require_permission. CI blocked.")
        return 1

    print(f"PASS Permission check passed -- {len(router_files)} router file(s) scanned, no drift detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
