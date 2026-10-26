"""403 body for a refused permission check.

check_permission() reasons such as "ABAC_DENIED: warehouse scope" used to be
returned whole as detail.code, which matched no errors.<CODE> key, so the user
saw a generic message. The code is now the part before the colon and the
qualifier sits in detail.reason. Audit rows keep the full reason.
"""

from __future__ import annotations

import pytest

from shared.permissions.middleware import _denial_detail

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("ABAC_DENIED: warehouse scope", {"code": "ABAC_DENIED", "reason": "warehouse scope"}),
        ("ABAC_DENIED: platform_only", {"code": "ABAC_DENIED", "reason": "platform_only"}),
        ("ABAC_DENIED: tenant mismatch", {"code": "ABAC_DENIED", "reason": "tenant mismatch"}),
        ("RBAC_DENIED", {"code": "RBAC_DENIED"}),
        ("TENANT_ACCESS_DENIED", {"code": "TENANT_ACCESS_DENIED"}),
        (None, {"code": "FORBIDDEN"}),
    ],
)
def test_code_is_the_part_before_the_colon(reason: str | None, expected: dict) -> None:
    assert _denial_detail(reason, "transfer:view") == {**expected, "action": "transfer:view"}


def test_every_denial_code_has_a_locale_entry() -> None:
    """The bare codes must map to errors.<CODE> in every locale."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    for lang in ("en", "am", "or"):
        errors = json.loads((root / "locales" / f"{lang}.json").read_text(encoding="utf-8"))[
            "errors"
        ]
        for code in ("ABAC_DENIED", "RBAC_DENIED", "TENANT_ACCESS_DENIED"):
            assert code in errors, (lang, code)
