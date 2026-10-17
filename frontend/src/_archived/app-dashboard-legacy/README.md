# Legacy /dashboard tree (archived session 18)

Pre-multi-tenant routes (`/dashboard`, `/dashboard/inventory`, `/dashboard/products`,
`/dashboard/tenants/[tenantId]`) that predate the org-scoped app under `app/[org]/`.
Nothing imported or linked to them (the live dashboard is `/${org}/dashboard`), and the
inventory page used the also-archived `ReceiveStock.tsx` (replaced by `ReceiveStockPanel`).

Files carry an `.archived` suffix so Next.js and tsc ignore them. Kept for history only.
