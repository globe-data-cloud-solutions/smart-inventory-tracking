## 23. Performance Targets

These are pass/fail acceptance criteria, not aspirational goals.

| ID | Target | Test method |
|---|---|---|
| NFR-1 | Dashboard load < 2s P95 | Lighthouse CI |
| NFR-2 | API response < 500ms P95 | Locust load test |
| NFR-3 | Transaction processing < 300ms | pytest timing |
| NFR-4 | Uptime 99.9% monthly | CloudWatch alarm |
| NFR-SA-1 | SKU search < 200ms P95 @ 50k+ SKUs | Locust + 50k fixture |
| NFR-SA-2 | Ledger query < 500ms P95 @ 50M+ rows | pytest partition fixture |
| NFR-SA-3 | Dispatch lot selection < 300ms | pytest timing |
| NFR-SA-4 | Offline sync < 500ms P95 @ 200 devices | Locust concurrent |
| NFR-SA-5 | Onboarding wizard < 10 minutes | Playwright E2E |
| NFR-V4-1 | Outbox side effects < 5s P95 after transaction commit | Celery task timing |
| NFR-V4-2 | Outbox PENDING depth alert trigger | > 500 rows |
| NFR-V4-3 | Barcode scan recognition < 1s P90 (mid-range Android) | Manual device test |
| NFR-V4-4 | Language pack load < 200ms additional | Lighthouse |
| NFR-V4-5 | en/am/or character sets render on all targets without extra fonts | Manual cross-device test |


## 25. Phase 0 — Must Exist Before Any User Is Onboarded

These cannot be retrofitted after production data exists without significant downtime.

| Item | Why it cannot be deferred |
|---|---|
| `inventory_transactions` partitioned by `transaction_date` | Retrofitting partitioning on a large live table requires downtime and is very costly |
| `parent_tenant_id` column on tenants (nullable, unused) | Phase 4 franchise model needs this; adding it post-launch = live production migration |
| `outbox` table + NOTIFY trigger | Without the outbox table, async side effects cannot be processed |
| `dispatch_strategy_configs` table | FEFO cannot be enforced at transaction level without this table |
| PostgreSQL RLS on every tenant-scoped table | Added in same migration that creates each table — cannot add RLS to a table after it contains data without a rewrite |
| Tenant onboarding wizard | Without it: wrong feature flags, wrong approval thresholds, wrong role sets, no SKU caps |
| Three language packs (en.json, am.json, or.json) in S3 | Must exist before Phase 1 go-live. Oromifa pack requires native-speaker review |
| `warehouse_stock` table with `no_direct_stock_update` RULE | The computed read model and its write-protection rule must exist from Phase 0. Adding the RULE to a table with existing rows works but requires a brief lock; doing it after go-live is a production risk |
| Composite indexes with `tenant_id` leading | Tech lead reviews every new table's index strategy before it reaches production |
| `organization_node` + `org_node_hierarchy` tables | IMTS hierarchy is the foundation of all facility scoping, ABAC authority resolution, and multi-source supply logic — cannot be added after transfer data exists without a full migration |
| `tenant_hierarchy_config` table | Without it, the system assumes a fixed 3-tier structure; adding configurable levels post-launch requires rewriting all facility-scoped queries |
| `approval_rule` + `approval_history` tables | Approval routing and its audit trail must be configurable from the first transaction — hardcoded approval logic cannot be retrofitted |
| `stock_threshold` table with `preferred_source_id` and `secondary_source_id` | Multi-source suggestion algorithm requires preferred/secondary source references on the threshold record; adding columns after threshold data exists requires backfill |
| `parent_transfer_id` column on `inventory_transactions` | Split-request leg linking cannot be added post-launch without live ledger migration |
| `estimated_arrival_date` + `actual_arrival_date` on `inventory_transactions` | In Transit overdue alert logic requires these columns from the first ISSUED transaction |


## 26. Phase Roadmap

| Phase | Duration | Producer / Importer | Retailer / Distributor |
|---|---|---|---|
| **Phase 0 — Foundation** | Months 1–3 | Infrastructure only — no user onboarding. Multi-tenant core, RBAC+ABAC (156 actions), immutable ledger (partitioned), RLS, Transactional Outbox + Celery, onboarding wizard, dispatch config tables, PWA + service worker + IndexedDB, language packs (en/am/or), parent_tenant_id placeholder, GitHub Actions CI/CD, permission drift check. Terraform provisions all three AWS environments (dev/stage/prod). | Same foundation. Retailer profile: unlimited SKU flag, full role set, logistics module, Amazon OpenSearch (conditional) implemented. |
| **Phase 1 — Producer MVP** | Months 4–7 | Onboard first **4–6 Producer/Importer companies**. Receiving, transfer, issue, adjustment, stock count, batch/lot traceability, FEFO/FIFO dispatch engine, approval workflows (WM→RM→NM), state machines, low-stock + expiry alerts, role-scoped dashboards, offline (camera scanning, IndexedDB sync, conflict resolution), English + Amharic + Oromifa, full audit trail. | No Retailer tenants onboarded. Retailer features tested internally. |
| **Phase 2 — Retailer Onboarding** | Months 7–11 | Remaining Producer tenants settled. Supplier delivery analytics. Read replica routing validated. Additional language packs. | Onboard first **4–6 Retailer/Distributor companies**. Unlimited SKU + pg_trgm at scale, multi-branch dispatch, cycle count scheduling, SKU bulk import, Retailer dashboards, logistics module. Load test: 200-device concurrent offline sync. |
| **Phase 3 — AI & Scale** | Months 11–16 | Production Demand Forecast AI (PRODUCER cohort — needs 3–4 months history from Phase 1). Route optimisation. POS integration if grocery segment acceleration warranted. ElastiCache Streams evaluation if Celery fan-out shows limits. | Replenishment Recommendations AI (RETAILER cohort). Dead-stock detection. SKU-level forecast caching. POS integration. Flutter native app if scan reliability issues reported. |
| **Phase 4 — Expansion** | Month 16+ | Beyond founding 12 companies. Multi-currency valuation. Supplier EDI/ASN. Franchise umbrella model (parent_tenant_id activated). Advanced AI. | Buying-group umbrella model. Full EDI. Advanced BI. AI explainability. Amazon SQS evaluation for high-volume async if ElastiCache Streams shows limits. Additional language packs. |

