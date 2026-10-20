"""Routes allowed to have no @require_permission (D7).

Every entry is a public path from api-gateway's UNAUTHENTICATED_PATHS or a
function in scripts/ci_drift_check.py ALLOWLISTED_PUBLIC_ROUTES. Adding one is
a reviewed decision — each carries a one-line reason.

Key: (METHOD, path as declared on the service app). Value: reason.
"""

from __future__ import annotations

# Any service's /health: matched on every app.
HEALTH_PATH = "/health"
HEALTH_REASON = "liveness probe, no data"

ALLOWLIST: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/auth/token"): "login — no SMART JWT exists yet",
    (
        "PATCH",
        "/api/v1/auth/password/{user_id}",
    ): "local-dev password change, ENVIRONMENT=local guard in handler",
    ("POST", "/api/v1/auth/verify-email"): "public email verification — user not signed in yet",
    (
        "POST",
        "/api/v1/auth/resend-verification",
    ): "public resend of verification email — user not signed in yet",
    (
        "POST",
        "/api/v1/auth/forgot-password",
    ): "public password reset request — user not signed in yet",
    ("POST", "/api/v1/auth/reset-password"): "public password reset — user not signed in yet",
    ("GET", "/api/v1/tenants/public/packages"): "public sign-up package catalog",
    ("POST", "/api/v1/tenants/public/signup"): "public self sign-up — account does not exist yet",
    ("GET", "/api/v1/tenants/public/contact"): "public platform contact details",
    (
        "POST",
        "/api/v1/tenants/public/payments/webhook/stub",
    ): "payment gateway callback, HMAC signature is the auth",
}
