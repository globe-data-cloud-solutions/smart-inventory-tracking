# SMART ፕላትፎርም — የ SA (ሱፐር አድሚን) ኦፐሬሽንስ መመሪያ

**ተደራሽ ለ:** ሱፐር አድሚን (SA) ብቻ — ይህ ሰነድ ለ SA ውስጣዊ አገልግሎት ብቻ ነው።
**ሁኔታ:** ረቂቅ። እስካሁን በየትኛውም frontend route አልቀረበም — ወደ
`frontend/public/` (እዛ login ማረጋገጫ የለም) አትገልብጡት፣ እንዲሁም ወደ Help
manifest (`frontend/src/lib/help/manifest.ts`) አትጨምሩት። ለማንም ከመቅረቡ በፊት
authenticated backend route ማግኘት አለበት፣ በ`docs/claude/billing-and-tenants.md`
§S12 ውስጥ የተመዘገበው የታወቀ ክፍተት መሰረት።

---

## 1. የ SA ሚና

ሱፐር አድሚኑ የፕላትፎርም ኦፕሬተር ነው፣ የቴናንት ተጠቃሚ አይደለም። ከእያንዳንዱ ቴናንት በላይ
በትክክል አንድ የሚና ወሰን (role scope) አለ፦ SA በፕላትፎርም ላይ ላሉ ሁሉም ቴናንቶች ሙሉ፣
ያልተገደበ መዳረሻ አለው (“SA Tenant View” — ከዚህ በታች §2ን ይመልከቱ)። የ SA ድርጊቶች
ለቴናንት ራሱ የፈቃድ/ማጽደቅ ህጎች በፍጹም አይገደዱም።

SA-only የ UI ገፆች ለ non-SA session-ዎች ወጥነት ያለው inline “not authorised”
ዘይቤ ይጠቀማሉ (ቀላል የተገደበ መልዕክት፣ redirect የለም) — ይህ የፕሮጀክቱ ነባር ስምምነት ነው
ለ role-gated ገፆች፣ ለአንድ ገፅ ብቻ የተለየ አይደለም።

ቁልፍ SA-only ገፆች፦
- `[org]/dashboard` — የቴናንት መዝገብ (`GET /api/v1/tenants/sa/registry`)፣
  አሁን የቴናንት መምረጫ (picker) ሆኗል፤ አንድ ረድፍ መምረጥ የዛ ቴናንት settings ገፅ ይከፍታል።
- `[org]/settings/tenants/[tenantId]` — ለእያንዳንዱ ቴናንት የሚፈጸም እያንዳንዱ የ SA
  ድርጊት የሚገኝበት ብቸኛ ቦታ። ዘጠኝ ትርፎች (tabs)፦ Profile, Plan, Contract, Status,
  Levels (ወደ org-setup ያገናኛል), Contact, Features, Admin User, Activity.
- `[org]/settings/plans` — የጥቅል (package) ካታሎግ፣ ዋጋዎች፣ ተጨማሪ-አገልግሎቶች
  (add-ons) (በመላው ፕላትፎርም ላይ ያለ፣ ለአንድ ቴናንት ብቻ የተወሰነ አይደለም)።

## 2. SA Tenant View (SA የቴናንት እይታ)

ከመዝገቡ ላይ አንድ ቴናንት መክፈት (`[org]/settings/tenants/[tenantId]`) TA
በራሱ profile ላይ የሚያየውን ተመሳሳይ አምስት tenant-admin tab components
(`tenant-admin/components/*.tsx`) ይጠቀማል — `TabProps.tenantId` እያንዳንዱን
tab ከ`/api/v1/tenants/me/...` (የTA የራሱ ገፅ) ወደ by-tenant
`/api/v1/tenants/{tenantId}/...` endpoints (SA view) ይቀያየራል፣ እና ከላይ
SA-only መቆጣጠሪያዎችን ያሳየ ያል (በ Plan ላይ ደረሰኝ ማሳደግ/ተከፍሏል ምልክት ማድረግ/መሰረዝ፣
በ Features ላይ add-ons፣ ሙሉ contact CRUD፣ Status/Admin User/Activity tabs
ለ TA ተመጣጣኝ የሌላቸው)። ይህ SA ለየትኛውም ቴናንት ውቅር ሙሉ ታይነት እና ቁጥጥር ያለ የተለየ
codebase ወይም የተደገመ ገፅ እንዲያገኝ የሚያስችለው መንገድ ነው።

## 3. ቴናንቶችን መፍጠር

ሁለት መንገዶች አሉ፤ አንድ አይነት የቴናንት ቅርጽ ያስገኛሉ ነገር ግን ተመሳሳይ workflow
አይደሉም፦

### 3.1 SA onboarding — `POST /api/v1/tenants/`
UI: `frontend/src/app/onboard/page.tsx`። አንድ ጥሪ ቴናንቱን እና የTA አድሚን
ተጠቃሚውን በአንድ DB transaction ውስጥ በአንድ ጊዜ ይፍጥራል (`admin_name`,
`admin_email`, `admin_password` fields በ create request ላይ) — ለየብቻ
“ቴናንት ፍጠር ከዚያ አድሚን ፍጠር” ደረጅ የለም እና በከፊል ውድቀት ጊዜ ወደ ኋላ የሚመለስ ነገር
የለም።

ይህ ጥሪ በአንድ ጥያቄ ውስጥ የሚከተሉትን ይቀበላል እና ያስቀምጣል፦
- `organisation_type` (Producer / Retailer / Hybrid)
- plan tier/package → በ`apply_package_to_tenant()` ተግባር ይፈጸማል፣ ይህም
  `plan_tier`, `max_warehouses`, `max_users`, `sku_cap` ያስቀምጣል፣ እና
  `feature_flags`ን በጥቅሉ ሙሉ የ flag ስብስብ ይተካል
- `billing_period` (`MONTHLY`/`ANNUAL`, default `ANNUAL`)
- አማራጭ `contract_start` / `contract_end` — ከተሰጡ፣ እነሱ ሙሉ በሙሉ ያሸንፋሉ፤
  `contract_start` ብቻ ከተሰጠ፣ `contract_end` ወደ subscription-ው የራሱ
  የተሰላ period end ዲፋልት ይሆናል። የ contract ቀናት እና የ billing period
  እርስ በርስ ነጻ ናቸው (ለ2-ዓመት contract በ monthly billing ላይ ሊሆን ይችላል) —
  §8ን ይመልከቱ።
- `account_owner` — በዚያው ጥሪ የተፈጠረው የTA አድሚን የ account owner ይሆናል
  (`users.is_account_owner = true`)።

የተለየ `POST /api/v1/tenants/{tenant_id}/wizard` endpoint አለ፣ ነገር ግን
**ምንም frontend ገፅ አይደውልም** (2026-10 ሁኔታ) — እሱ `organisation_type`,
`approval_thresholds`, እና `default_locale` ብቻ ያስቀምጣል። Plan tier እና
feature flags የሚቀመጡት አንድ ጊዜ፣ ቴናንት በሚፈጠርበት ጊዜ፣ በ
`apply_package_to_tenant()` ነው — በwizard በፍጹም አይደለም።

`DELETE /{tenant_id}` ሁልጊዜ `409 USE_DEACTIVATE` ይመልሳል — ቴናንቶች
በ API አማካኝነት በፍጹም hard-delete አይደረጉም (§9ን ይመልከቱ)።

### 3.2 የቴናንት ራስ-ምዝገባ (self sign-up) — `POST /api/v1/tenants/public/signup`
UI: `frontend/src/app/(auth)/signup/page.tsx`፣ የህዝብ፣ authentication
የማይፈልግ ባለ-ሶስት-ደረጅ ፍሰት (package እና billing period → የድርጅት/አድሚን
ዝርዝሮች → ማጠቃለያ)። የተመዘገበው ሰው TA እና account owner ይሆናል። በአንድ DB
transaction ውስጥ፦ tenant insert (`signup_source = 'SELF_SIGNUP'`) →
`apply_package_to_tenant()` → TA user insert (`is_account_owner =
true`) → primary contact insert → `start_subscription(status="PENDING_PAYMENT")`
→ terms acceptance insert → activity-log insert → verification token
ይወጣል። የማረጋገጫ ኢሜይል የሚላከው ከcommit በ**ኋላ ብቻ** ነው — የኢሜይል መላክ ውድቀት
ምዝገባውን በፍጹም ወደ ኋላ አይመልስም።

`PENDING_PAYMENT` subscription ወዲያውኑ ሙሉ በሙሉ ጥቅም ላይ ይውላል — እስካሁን
ምንም የክፍያ ማስገደድ የትም የለም (§7ን ይመልከቱ)። በ IP 5 signups/ሰዓት ይገደባል
(`signup` bucket)።

### 3.3 ሁለቱን መንገዶች የሚለያቸው ምንድን ነው
- `signup_source`: `SELF_SIGNUP` በተቃራኒ unset/SA-created — በ
  `GET /sa/registry` ይታያል።
- ራስ-ምዝገባ ሁልጊዜ በ`PENDING_PAYMENT` ይጀምራል፤ SA onboarding contract
  ቀናትን በቀጥታ ማስቀመጥ ይችላል እና በየትኛውም የተወሰነ subscription status
  መጀመር አያስፈልገውም።
- ራስ-ምዝገባ በምዝገባ ጊዜ `terms_acceptances` ረድፍ ይጽፋል፤ SA-የፈጠረው ቴናንት
  አይጽፍም — የእሱ account owner በመጀመሪያ login ላይ እንዲቀበል ይጠየቃል (§10ን
  ይመልከቱ)።

## 4. ፕላኖች እና ዋጋዎች

የጥቅል ካታሎግ ለplan ነባሪዎች ብቸኛ የመረጃ ምንጭ ነው — በ backend ወይም frontend
በሌላ ቦታ ምንም hardcode የለም። `backend/shared/plans/catalog.py` እሱን
የሚያነብ ወይም የሚጽፍ ብቸኛ ቦታ ነው (`platform_tier_config` ለገደቦች/flags፣
append-only `package_prices` ለዋጋዎች፣ append-only `platform_config_log`
ለሁሉም SA edit ለሁለቱም)።

### ካታሎጉን ማስተካከል — `[org]/settings/plans` (SA-only)
- **`PATCH /platform/tier-config`** — በቲየር የተከፈለ ከፊል ዝመና፦ በጥያቄው
  body ውስጥ ያሉ fields ብቻ ይቀየራሉ (ያልተጠቀሰ field አልተነካም ይቀራል)።
  ሊስተካከል የሚችል፦ `max_warehouses`, `max_users`, `display_name`,
  `sku_cap` (int ≥1፣ ወይም null = ያልተገደበ)፣ `is_public`, `sort_order`,
  `feature_flags` (ሙሉ ምላሽ — እያንዳንዱ key የታወቀ flag code መሆን አለበት፣
  የማይታወቅ key ይከለከላል)። በመላው ካታሎግ ላይ ቢያንስ አንድ tier `is_public=true`
  መሆን አለበት፣ ይህ ከመጻፍ በፊት ይጣራል። የተቀየረ እያንዳንዱ field ከ`reason` ጋር
  (ካልተሰጠ ዲፋልት፦ `"SA tier-config edit"`) ወደ `platform_config_log`
  ይመዘገባል።
  **የካታሎግ ማስተካከያዎች ለአዲስ ቴናንት ፍጥረት እና ለተፈጻዊ የፕላን ለውጦች ብቻ ይተገበራሉ —
  የነባር ቴናንቶች የተፈጻሚ ገደቦች/flags በፍጹም ወደ ኋላ ተመልሶ አይቀየሩም።**
- **`GET /platform/packages/prices[?tier=]`** — የወቅቱ፣ የተያዘ (future
  `effective_from`)፣ እና ሙሉ ታሪክ፣ በ tier + billing period።
- **`POST /platform/packages/{tier}/prices`** — አዲስ፣ append-only የዋጋ
  ረድፍ ይለጥፋል። `reason` ያስፈልጋል። `effective_from` ዲፋልት ወደ አሁን ነው እና
  ከ5 ደቂቃ ያለፈ ጊዜ ወደ ኋላ ሊሆን አይችልም። **የተሳሳተ የተያዘ ዋጋን ለማስተካከል**፣ ተመሳሳይ
  `effective_from` ባለው አዲስ ረድፍ ይለጥፉ — ያ `effective_from` ሲደርስ አዲሱ
  (በ`created_at`) ረድፍ “current” ሆኖ ያሸንፋል። የዋጋ ለውጥ ለነባር subscription
  እስከ next renewal ድረስ በፍጹም ተፅዕኖ አያደርግም።
- **`GET /platform/config-log?entity_type=&entity_key=&limit=`** —
  ለሁሉም catalog/price/add-on ለውጥ የ audit trail፣ አዲሱ መጀመሪያ።

### ተ.እ.ታ (VAT)
ሁሉም ዋጋዎች ከ subtotal ተለይተው **15% VAT** ጨምረው ይታያሉ፣ ዋጋ በሚታይበት ሁሉም
ቦታ (signup, invoices, proration previews)።

### ተጨማሪ-አገልግሎቶች (Add-ons) (platform ካታሎግ)
`[org]/settings/plans` እንዲሁም Add-ons tab አለው (ካታሎግ + ዋጋ፣ ከpackages
ጋር ተመሳሳይ append-only price-history ዘይቤ)። አንድ ግራንት ለአንድ ቴናንት
እንደሚተገበር ለማየት §5ን ይመልከቱ።

### የእውቂያ ዝርዝሮች፦ በ SA settings → Contact ያስተካክሉ፤ እያንዳንዱ ለውጥ `reason`
ይፈልጋል እና ይመዘገባል

## 5. የፕላን ለውጦች (SA-only)

**TA የራሱን ፕላን መቀየር አይችልም።** `PATCH /api/v1/tenants/me/profile`
የትኛውንም plan/billing field (`plan_tier`, `max_warehouses`,
`max_users`, `sku_cap`, `feature_flags`, `billing_period`)
በ`403 PLAN_CHANGE_SA_ONLY` ይከለክላል። የTA የራሱ Plan tab “Contact SMART
to change your plan” የሚል ጽሑፍ ብቻ ያሳያል — click ሊደረግ የሚመስል button
የለም። TA ፕላኑን፣ subscription-ውን፣ invoices-ን እና add-ons-ን ማየት ይችላል፤
ለውጥ ማድረግ የሚችለው SA ብቻ ነው።

SA በቴናንቱ ራሱ settings ገፅ (`[org]/settings/tenants/[tenantId]` →
Plan tab) ወይም `PATCH /{tenant_id}/plan` በኩል የቴናንት ፕላን ይቀይራል።

### ማሻገር (Upgrades)
ተፈጻምነቶች (ገደቦች፣ feature flags) **ወዲያውኑ** ይቀየራሉ —
`apply_package_to_tenant()` እንደ ተመሳሳይ ጥሪ ክፍል ይሰራል። አዲሱ ዋጋ
ከ**next invoice** ጀምሮ ይከፈላል፣ ወደ ኋላ ተመልሶ በፍጹም አይደለም።

- **Monthly billing:** ለቀረው የወቅቱ ወር ምንም ተጨማሪ ክፍያ አይኖርም።
- **Annual billing:** ለውጡ የተፈጸመበት ቀሪ ወር ነጻ ነው። ሁለተኛ፣ አውቶማቲክ
  PENDING invoice (`invoice_kind='PRORATION'`) በዛው transaction ውስጥ
  ይወጣል፣ ይህም **የቀሩትን ሙሉ የክፍያ ወራት** ይሸፍናል (ከ subscription-ው
  `current_period_start` ጀምሮ በ+1-ወር ደረጆች ይቆጠራል፣ በካላንደር ቀናት
  አይደለም — ስለዚህ ቀን-29/30/31 መነሻ በፍጹም አይዘምትም)፦
  `(new_annual_price − old_annual_price_snapshot) × remaining_months / 12`፣
  VAT ከላይ ይደመራል። ይህ በቴናንቱ invoice list ውስጥ እንደ **Proration**
  invoice ይታያል።
- አንድ subscription ለ PENDING period invoice ካለው ፈጽሞ ይከለከላል
  (`409 INVOICE_PENDING_SETTLE_FIRST`) ምንም ጽሕፈት ሳይፈጽም — pending
  PRORATION invoice ምንም ነገር በፍጹም አያግድም።
- ከመፈጸም በፊት ቅድመ-ዕይታ፦ `GET /{tenant_id}/proration-preview?tier=`
  (SA) `{remaining_months, free_until, period_end, old_amount,
  new_amount, subtotal, vat, total, currency, will_invoice,
  blocked_code}` ይመልሳል።

### ተጨማሪ-አገልግሎቶች (Add-ons)
በቴናንቱ package ውስጥ ያልተካተተ ባህሪ በራሱ ሊሰጥ ይችላል፦
- `OVERRIDE` — ነጻ፣ `amount=0`፣ ማስታወሻ (note) ያስፈልጋል።
- `PURCHASED` — ከቴናንቱ ቀጥታ subscription-ው billing period ይዋጀል፣
  ከ upgrade ጋር ተመሳሳይ proration formula
  (`addon_annual_price × remaining_months / 12` በ annual billing፣
  ለቀሪው የወቅቱ ወር ነጻ፤ በ monthly billing ከ package ጋር ከ next invoice
  ይከፈላል)።

አንድ add-on **በፕላን ለውጥ ይተርፋል** — `apply_package_to_tenant()` በፕላን
ለውጥ ላይ `tenants.feature_flags`ን ሙሉ በሙሉ ይተካል ነገር ግን
`tenant_addons`ን በፍጹም አይነካውም፤ ተፈጻሚ flags ሁልጊዜ የ package flags
ከእያንዳንዱ አሁን-ነቅ add-on grant ጋር OR ተደርገው ናቸው፣ ስለዚህ tier ሲቀየር ግራንት
በፍጹም በጭጋግ ተደብቆ አይጠፋም። ግራንት በፍጹም አይጠፋም፣ ይሰረዝ ብቻ ነው (`status =
CANCELLED`)፤ መሰረዝ ወዲያውኑ ያቆመዋል፣ ምንም refund የለም።

Endpoints: `POST`/`GET /{tenant_id}/addons`, `POST
/{tenant_id}/addons/{id}/cancel`.

## 6. ማውረድ (Downgrades) እና ተመላሽ ገንዘብ (Refunds)

> በተከፈለ subscription ላይ ያለ downgrade ይያዛል (scheduled)፦ ቴናንቱ እስከ
> renewal ድረስ የወቅቱን tier ይይዛል፤ የ renewal invoice በዝቅተኛው tier
> ይከፈላል፤ መለወጡ የሚከሰተው SA የዛን renewal invoice ክፍያ ሲመዘግብ ነው (ቀድሞ
> መመዝገብ = ቀድሞ መቀየር)። ለ monthly እና annual አንድ ህግ ነው። በፍጹም-ያልተከፈሉ
> subscription-ዎች ወዲያውኑ downgrade ያደርጋሉ። SA በደንበኛ ጥያቄ downgrade-ን
> ወዲያውኑ ማስፈጸም ይችላል (ምንም refund፣ ምንም credit የለም)። downgrade ተይዞ
> እያለ upgrade ቢመጣ downgrade-ውን ያሰርዛል፤ SA በግልጽ ደግሞ ሊሰርዘው ይችላል።
> ለ downgrades ምንም refund እና ምንም account credit የለም፤ account
> credit የኢትዮጲያ VAT credit-note አያያዝን accountant እስኪያረጋግጥ ድረስ
> ለተወሰነ ጊዜ ቆሟል። ከአዲሱ ፕላን ገደብ በላይ ያለ ውሂብ ይቆያል፤ አዲስ ፍጥረት ብቻ ይከለከላል።
> በአንድ billing period ውስጥ የቴናንትን tier ወደ ታች ከዚያ ወደ ላይ ማቀያየርን
> ያስቀርቱ — ድጋሚ-ማሻገር (re-upgrade) ሙሉ ይከፈላል።

ለ SA መቆጣጠሪያዎችን የሚያሰራ ዘዴ፦
- `PATCH /{tenant_id}/plan` የ`effective: "RENEWAL" (default) |
  "IMMEDIATE"` ይወስዳል። `RENEWAL` በቢያንስ-አንድ-ጊዜ-የተከፈለ subscription
  downgrade ላይ ብቻ ይይዘዋል (`subscriptions.scheduled_tier`/
  `scheduled_at`) — renewal invoice እስኪከፈል ድረስ ምንም ነገር አይቀየርም።
- ራሱ መለወጡ የሚከሰተው በ`mark_paid()` ውስጥ ነው፦ የተከፈለው invoice package
  መስመር በ`scheduled_tier` ዋጋ ከተሰላ፣ የ subscription-ው tier/price/period
  ይዘምናል እና schedule-ው በዛው ጽሕፈት ይጸዳል።
- `DELETE /{tenant_id}/plan/scheduled` የ pending schedule-ን በግልጽ
  ይሰርዛል (ምንም ከሌለ `404 NO_SCHEDULED_CHANGE`)። የትኛውም upgrade፣ ወይም
  `effective=IMMEDIATE`፣ ወይም የወቅቱን tier ድጋሚ-ማስቀመጥ፣ pending
  schedule-ንም እንደ side effect ያጸዳል።
- `PATCH /{tenant_id}/profile` የ plan-tier መንገድ `effective` override
  የለውም — በዚያ route የተከፈለ downgrade ሁልጊዜ ይያዛል፤ አሁኑኑ downgrade
  ለማድረግ `PATCH /{tenant_id}/plan?effective=IMMEDIATE` ይጠቀሙ።
- በፍጹም-ያልተከፈለ subscription (ገና `PENDING_PAYMENT`) ከ`effective`
  ነጻ ሆኖ ሁልጊዜ ወዲያውኑ downgrade ያደርጋል።

## 7. ደረሰኞች (Invoices) እና ክፍያዎች (Payments)

`[org]/settings/tenants/[tenantId]` → Plan tab (SA) / TA የራሱ Plan
tab (ለማንበብ-ብቻ + ለ pending invoice “How to pay”)።

- **ክፍያ መመዝገብ፦** SA በቴናንቱ ገፅ ላይ `POST .../payments/{id}/mark-paid`
  ይጠቀማል። ይህ idempotent ነው — ቀድሞ-የተከፈለ ክፍያን ድጋሚ ምልክት ማድረግ
  `already_paid: true` ይመልሳል እና ምንም ሌላ ነገር አይቀይርም። ይህ
  `tenants.contract_end`ን ወደ ፊት ብቻ ያስገፋል (`GREATEST(old, new)` —
  ወደ ኋላ በፍጹም)፣ እና `contract_start`ን ያስቀምጣል ገና unset ከነበረ ብቻ።
- **ያለችውን pending invoice መሰረዝ፦** `POST .../payments/{id}/cancel`
  — ማስታወሻ ያስፈልጋል።
- **የሚጠበቁ renewal invoices፦** አንድ subscription በአንድ ጊዜ ቢበዛ አንድ
  PENDING `invoice_kind='PERIOD'` invoice አለው። የተያዘ downgrade (§6)
  downgrade-ው ከመያዙ በፊት የተነሳ ከሆነ አሁንም በ OLD tier የተሰላ PENDING period
  invoice ሊተው ይችላል — ያ invoice እንደ መደበኛ same-tier renewal ይከፈላል
  እና downgrade switch-ን **አያስነሳም**፤ SA በአዲሱ tier ያለው renewal
  በትክክል ሲደርስ ያንን ድጋሚ-ያስነሳ ወይም ይሰርዘው።
- **የክፍያ አቅራቢ (payment provider)፦** ገና እውነተኛ payment gateway
  አልተገናኘም። `MANUAL` (SA በእጅ ይከፍላል ምልክት ያደርጋል — እስካሁን እውነተኛ
  ጥቅም ላይ ያለው ብቸኛ provider) እና `STUB` (የ webhook path ብቻ ለመሞከር
  የተሰራ ሃሰተኛ gateway) ተፈጽሞ ያለው ሁለት providers ናቸው። ቴናንት ምንም ክፍያ
  ከመፈጸም ወይም ከመመዝገብ በፊት ሙሉ በሙሉ ጥቅም ላይ ይውላል — **በዚህ ምዕራፍ ላይ ላልተከፈለ
  ክፍያ ምንም የተታገደ ወይም የተገደበ ነገር የለም** (§8ን ይመልከቱ)።
- **ለ TA የሚታዩ የባንክ/የክፍያ መመሪያዎች** (“How to pay” በ pending invoice
  ላይ)፦ **ያልተወሰነ — Alex።** የወቅቱ UI ጽሑፍ አጠቃላይ የማስያ ይዘት ያለው እውነተኛ
  የባንክ ዝርዝር የለውም።

## 8. የኮንትራት ቀናት እና ማብቂያ

ኮንትራቱ (`tenants.contract_start`/`contract_end`) የንግድ ስምምነት ነው፤
ከ subscription-ው billing period (§3.1) ነጻ ነው። `PATCH
/{tenant_id}/contract` ኮንትራቱን ብቻ ነው ፈጽሞ የሚነካ፣ subscription-ውን
በፍጹም አይደለም።

**SA በዚህ ሁሉ ላይ በፍጹም አይገደብም።** የኮንትራት ደረጅ እና ከዚህ በታች ያለው
read-only gate ለቴናንቱ የራሱ staff ብቻ ይተገበራል — የ SA session ሁልጊዜ
ሙሉ መዳረሻ ነው፣ የትኛውም ቴናንት ኮንትራት ሁኔታ ቢሆንም።

### የኮንትራት ደረጆች

ከ`tenants.contract_end` በራስ-ሰር የተገኙ አራት ደረጆች (የተከማቸ status
column የለም — ሁልጊዜ ትኩስ ሆኖ ይሰላል)፦

| ደረጅ | መቼ | መዳረሻ |
|---|---|---|
| **Active (ነቅ)** | የኮንትራት ቀን ያልተቀመጠ፣ ወይም ከ14 ቀን በላይ ቀርቷል | ሙሉ መዳረሻ |
| **Expiring (ወደ ማብቂያው የቀረበ)** | ≤14 ቀን ቀርቷል | ሙሉ መዳረሻ፤ የማስጠንቀቂያ banners |
| **Grace (የምሕረት ጊዜ)** | `contract_end`ን ያለፈ ≤14 ቀን | ሙሉ መዳረሻ፤ banners |
| **Read-only (ለማንበብ-ብቻ)** | `contract_end`ን ያለፈ ከ14 ቀን በላይ | ዕይታ + export ብቻ፤ ሁሉም ለውጦች ይከለከላሉ |

**Read-only እውነተኛ፣ አውቶማቲክ ገደብ ነው** — ማሳወቂያ ብቻ አይደለም። ቴናንት
Read-only ውስጥ ከገባ በኋላ፣ ከዛ ቴናንት staff የሚመጣ እያንዳንዱ የመጻፍ ጥያቄ
በ`402 CONTRACT_EXPIRED_READ_ONLY` ይከለከላል፣ ከጠባብ አሁንም የተፈቀደ ስብስብ
በስተቀር፦ የራስ ፓስወርድ ለውጥ፣ የ Terms መቀበል፣ contacts ማስተዳደር፣ renewal
ጥያቄ መላክ፣ staff password reset፣ እና staff deactivation (የወጪ ሰው
መዳረሻ አሁንም መሰረዝ መቻል አለበት፣ እና ተገድቦ-የቀረ staff member አሁንም መመለስ
መቻል አለበት፣ ቴናንቱ ራሱ read-only ሆኖ እያለም)።

**Renewal read-only-ን ወዲያውኑ ያነሳል።** Renewal ማለት SA ክፍያ መዝግቧል
(`POST .../payments/{id}/mark-paid`, §7) ወይም በሌላ መንገድ
`contract_end`ን አስፍቷል (`PATCH /{tenant_id}/contract`) — ሁለቱም
`contract_end`ን ወደ ፊት ያስገፋሉ፣ እና በቀጥታ የሚመጣው ጥያቄ ደረጁን ከአዲሱ ቀን
ድጋሚ ያገኛል፣ ስለዚህ የተለየ “ዳግም-ያድሱ ያግኙ” ደረጅ የለም። **Suspension የተለየ፣
በእጅ የ SA ውሳኔ ይቀራል** (§9) — read-only እና Suspended እርስ በርስ ነጻ
ሁኔታዎች ናቸው፤ read-only ቴናንትን ማዳስ suspension-ን አይነካም፣ ቴናንትን
suspend ማድረግ ከኮንትራት ደረጁ ጋር ምንም ግንኙነት የለውም።

**የማብቂያ ማስጠንቀቂያዎች አሁንም ወደ server logs ብቻ ይደርሳሉ** (CloudWatch፣
በ outbox `ContractExpiryAlert` handler በኩል) — እስካሁን ኢሜይል የለም።
በኢሜይል የሚላኩ የማብቂያ ማስታወሻዎች `EMAIL_DELIVERY_MODE=ses` ስራ ላይ
መዋልን እና ያ handler ከ notification-service ጋር መገናኘትን ይጠብቃሉ (§11)፤
እስከዚያ ድረስ ለደንበኛ ኢሜይል ማስታወሻ እንደሚመጣ አትንገሩ።

### Renewals tab — `[org]/dashboard` → Renewals (SA-only, deep link
`?tab=renewals`)

- **የደረጅ ቁጥሮች** — Expiring / Grace / Read-only፣ በመላው ቴናንት።
- **የኮንትራት ዝርዝር** — በነዚህ ሶስት ደረጆች ውስጥ አሁን ያለ የማይነቃ (deactivated)
  ያልሆነ እያንዳንዱ ቴናንት፣ ቀድሞ-የሚያበቃው መጀመሪያ፣ ከአሁኑ ክፍት renewal ጥያቄ
  ጋር (ካለ)።
- **ክፍት ጥያቄዎች ረድፍ (queue)** — TA ከራሱ Plan tab ያቀረባቸው renewal
  ጥያቄዎች (በየትኛውም የኮንትራት ደረጅ፣ Read-only ጨምሮ — እዛ አሁንም ከተፈቀዱት
  የመጻፍ ድርጊቶች አንዱ ነው)። በአንድ ጊዜ በቴናንት አንድ ክፍት ጥያቄ ብቻ፤ ክፍት ጥያቄ
  እያለ TA ሁለተኛ ጥያቄ ቢያቀርብ ነባሩ ብቻ ይታየዋል፣ ድብልቅ አይፈጠርም።
- **Mark handled / Cancel** — ጥያቄ ይፈታል (ሁለቱም አጭር ማስታወሻ
  ያስፈልጋቸዋል)። ይህ ራሱ ኮንትራቱን አይቀይርም ወይም ምንም አያድስም — SA አሁንም
  እውነተኛውን ክፍያ/ማስፈፊያ (§7) እንደ የተለየ ደረጅ ይመዘግባል፤ ጥያቄን handled
  ምልክት ማድረግ ለ queue-ው የሂሳብ ስራ ነው፣ ራሱ renewal ድርጊት አይደለም።

## 9. ቴናንትን ማገድ / ማቦዝን (Suspending / Deactivating)

በ`tenants.status` ላይ ሶስት ሁኔታዎች፦ `ACTIVE`, `SUSPENDED`,
`DEACTIVATED` (እና `is_active` ያልACTIVE-ን እንደ `false` የሚያንፃባርቅ)።
ሽግግሮች SA-only ናቸው (`PATCH
/{tenant_id}/suspend|deactivate|reactivate`፣ በቴናንቱ Status tab ላይ)፦

- **Suspend (ማገድ)** — ጊዜያዊ። ያው ሁኔታ ላይ ከሆነ ወይም ቀድሞ ከተቦዘነ
  (reactivate ማድረግ ያስፈልጋል) በ`422 ALREADY_SUSPENDED` /
  `TENANT_DEACTIVATED` ይከለከላል። ያ ቴናንት ያሉት ነቅ login tokens ሁሉ
  ወዲያውኑ ይሰረዛሉ (`revoke_tenant_tokens()`) — ለዛ ቴናንት ያለ ሁሉም non-SA
  session በአንድ ጊዜ ይወጣል፣ በሚቀጥለው login ላይ መገደብ ብቻ አይደለም።
- **Deactivate (ማቦዝን)** — እንደ ረዘም ያለ-ጊዜ/soft-delete ሁኔታ የታሰበ፤
  ውሂቡ ይቆያል፣ በፍጹም አይጣልም። እንዲሁም ሁሉንም የቴናንት tokens ወዲያውኑ ይሰረዛል።
- **Reactivate (ዳግም ማንቃት)** — ከ`SUSPENDED` ወይም `DEACTIVATED`
  `ACTIVE`ን ይመልሳል። ቀድሞ ነቅ ከሆነ `422 ALREADY_ACTIVE` ይከለከላል። ራሱ
  tokens ድጋሚ አያወጣም — ተጠቃሚዎች በቀላሉ መደበኛ login ያደርጋሉ።
- በ login ደረጅ (`POST /auth/token`)፣ `SUSPENDED` ቴናንት
  `403 TENANT_SUSPENDED` የሚመለሰው ፓስወርድ **ከተረጋገጠ በኋላ** ብቻ ነው — ይህ
  ሆን ተብሎ ትክክለኛ ፓስወርድ የማያውቅ ሰው የቴናንት መኖር/መቦዘን እንዳያረጋግጥ ነው።
- እያንዳንዱ ሽግግር ወደ `tenant_activity_log` ይጻፋል (action
  `SUSPEND`/`DEACTIVATE`/`REACTIVATE`፣ old/new value) — የ log ጽሕፈት
  ውድቀት ራሱ status ለውጥን በፍጹም ወደ ኋላ አይመልስም።

ቴናንቶች በ API በኩል **በፍጹም hard-delete አይደረጉም** (`DELETE
/{tenant_id}` ሁልጊዜ `409 USE_DEACTIVATE` ይመልሳል)። Local-dev-ብቻ hard
purge በ`scripts/delete_tenant.py` በኩል አለ (መጀመሪያ dry-run፣ የተጻፈ
`YES` ማረጋገጫ ይፈልጋል፣ የAlex `pg_dump` ቀድሞ ተወስዷል) — `CLAUDE.md` §8ን
ይመልከቱ። **በ staging ወይም prod ላይ ቴናንትን በፍጹም hard-delete አያድርጉ።**

## 10. ተጠቃሚዎች እና ደህንነት

- **ተጠቃሚዎችን መፍጠር፦** በTA በራሱ ቴናንት ውስጥ ይከናወናል (Org Setup →
  Personnel)፣ በ SA አይደለም። SA በ SA onboarding (§3.1) ክፍል ከተፈጠረው
  አንድ TA አድሚን ውጪ የቴናንት ተጠቃሚዎችን በግል አይፈጥርም።
- **የፓስወርድ reset — ሁለት መንገዶች፦**
  - ራስ-አገልግሎት፦ `POST /auth/forgot-password` (ሁልጊዜ 202፣ account
    enumeration የለም) → `POST /auth/reset-password` ነጠላ-ጥቅም፣
    SHA-256-የተመሳቀለ፣ 60-ደቂቃ-TTL token ይጠቀማል። ከተሳካ፦ አዲስ password
    hash፣ `must_reset_password=false`፣ unset ከነበረ `email_verified_at`
    ይቀመጣል፣ እና ለዛ ኢሜይል የ failed-login lockout counter ይጸዳል። አዲስ
    reset token ማውጣት የተጠቃሚውን ቀድሞ ያልተጠቀሙ ተሰርዝ ያደርጋል። ስኬታማ
    reset ላይ የተጠቃሚው ነባር login tokens ሁሉ ይሰረዛሉ
    (`revoke_user_tokens()`)፣ ስለዚህ ክፍት session ሁሉ ይወጣል።
  - TA-የጀመረው፦ TA ከ Personnel tab ተጠቃሚ password ይጠራል (ጊዜያዊ
    password, በሚቀጥለው login ላይ ግዴታ ለውጥ)፤ ይህ ደግሞ የዛ ተጠቃሚ
    login-lockout counter ወዲያውኑ ያጸዳል።
  - ሌሎች የተጠቃሚ tokens የሚሰረዙ TA ድርጊቶች (`personnel_v2.py`,
    `revoke_user_tokens()`)፦ በPersonnel → edit user (~መስመር 815)
    በኩል ለተጠቃሚ አዲስ password ማስቀመጥ፤ ተጠቃሚን ማቦዝን (~መስመር 601)፤
    እና SA የተጠቃሚን ብቸኛ PRIMARY position በግድ ሲያስወግድ፣ ይህ እንደ side
    effect ተጠቃሚውን ያቦዝናል (~መስመር 525)።
- **የመለያ መገደብ (Account lockout)፦** እውነተኛ እና አውቶማቲክ ነው፣ rate
  limit ብቻ አይደለም። ለአንድ ኢሜይል 5 የወደቁ login ሙከራዎች ከሆነ፣ ተጨማሪ
  ሙከራዎች ለዛ ኢሜይል በ`429 TOO_MANY_ATTEMPTS` ለ15 ደቂቃ ከ**መጀመሪያው**
  ያልተሳካ ሙከራ window ይከለከላሉ (የ counter TTL የሚቀመጠው በመጀመሪያው ውድቀት
  ብቻ ነው፣ ስለዚህ ቀጥሎ ያሉ ውድቀቶች ቆጠራውን ያስፋፋሉ፣ window-ውን አይደለም)።
  Lockout-ው ከ15 ደቂቃ በኋላ፣ ወይም ስኬታማ password reset ላይ ወዲያውኑ
  በራስ-ሰር ይጸዳል። ለማጽዳት ምንም admin ድርጊት አያስፈልግም፣ ነገር ግን TA reset
  ደግሞ ያጸዳል።
- **Login rate limiting (ከ account lockout የተለየ)፦** `login` bucket፣
  20 ሙከራዎች / 15 ደቂቃ **በ IP**፣ በ api-gateway ላይ ለ email/password
  መንገድ ብቻ ይተገበራል (በ local-dev `dev_email` shortcut ላይ በፍጹም
  አይደለም)። ይህ ከላይ ካለው per-email lockout ነጻ ነው — ሁለቱም ሊነሱ ይችላሉ።
- **Terms ድጋሚ-መቀበል፦** `TERMS_VERSION` ሲቀየር፣ የቴናንቱ **account
  owner** ብቻ (`users.is_account_owner`፣ ሁሉም TA/user አይደለም) በ
  frontend-ብቻ gate (API-አጠቃላይ ገደብ አይደለም) በሚቀጥለው login ላይ ድጋሚ
  ለመቀበል ይገደዳል። SA-የፈጠረው ቴናንት owner (`public_signup.py` ረድፍ
  የሌለው) ልክ እንደ ላጀ version ተቆጥሮ የመጀመሪያ login-ውም ላይ ይቀበላል።

## 11. ኢሜይል

- ሁሉም የሲስተም ኢሜይሎች (ማረጋገጫ፣ password reset) **በእንግሊዝኛ ብቻ** ናቸው።
- Sender address: `no-reply@<domain>` — **domain ያልተወሰነ — Alex**
  (ከ`EMAIL_DELIVERY_MODE=ses` ጥቅም ላይ ከመዋል በፊት SES-የተረጋገጠ domain
  መሆን አለበት)።
- `EMAIL_DELIVERY_MODE`: `log` (dev ብቻ — ከመላክ ፈንታ ሊንኩን በ WARNING
  ወደ service log ይጽፋል) በተቃራኒ `ses` (በ stage/prod ያስፈልጋል — the
  startup config guard ከዚህ ውጭ ያለ ማንኛውንም ነገር ባለው stage/prod
  service መጀመርን ይከለክላል)። unset ሲሆን ዲፋልት፦ `ENVIRONMENT=local` ብቻ
  ከሆነ `log`፣ ካልሆነ `disabled` (ዝም ብሎ ለመላክ ከመክሸፍ ይልቅ ያነሳል)።

## 12. Go-Live Checklist (SA)

- [ ] ከ public landing page (`frontend/src/app/page.tsx`)
  `#credentials` ክፍልን አስወግድ እና ከ`frontend/src/lib/demo-data.ts`
  `SA_USER.password`ን አስወግድ (ሁለቱም አሁንም አሉ)።
- [ ] በ development ጊዜ ጥቅም ላይ የዋለውን SA password ወደ አዲስ፣ ጠንካራ
  credential ድጋሚ ያስቀምጡ።
- [ ] ቅርንጫፍ ጥበቃ (branch protection) / review ፍላጎቶችን ያረጋግጡ —
  **አሁን ያለው እውነታ (2026-08)፦ ሁለቱም repos server-side branch
  protection የላቸውም** (private repos በ free GitHub plan ላይ)፤
  ለ`main` ቀጥታ ግፋፊ (direct push) በሁለቱም ይፈቀዳል። ይህ ንጥል **ያልተወሰነ —
  Alex** ነው (go-live ከመድረስ በፊት GitHub plan-ን ማሻገር ወይም የወቅቱን
  no-protection ሁኔታ መቀበል ይወሰናል)።
- [ ] `EMAIL_DELIVERY_MODE=ses` እና እውነተኛ `EMAIL_FROM` በ stage/prod
  ውስጥ መሆናቸውን ያረጋግጡ (startup guard ያለበለዚያ መጀመርን አስቀድሞ ይከለክላል —
  ይህ ፍተሻ ነው፣ ጥገና አይደለም)።
- [ ] ለክፍያ ስብሰባ invoices ላይ ከመመርኮዝ በፊት እውነተኛ የባንክ/የክፍያ መመሪያዎች
  መቅረባቸውን ያረጋግጡ (§7)።
- [ ] የአገልግሎት ውሎች/የግላዊነት ፖሊሲ ጽሑፍ መጠናቀቁን ያረጋግጡ — `/terms` እና
  `/privacy` አሁን የAlex ረቂቅ v0.2 (`docs/legal/*.md`) ያቀርባሉ፣ አሁንም
  DRAFT ተብሎ ምልክት የተደረገባቸው ክፍት COUNSEL NOTE ንጥሎች ያላቸው (data
  localisation, ዋጋ/VAT, SLA, liability cap, arbitration, የአማርኛ
  ትርጉም)፤ እስካሁን በጠበቃ አልተገመገመም ወይም እንደ መጨረሻ ለመቀበል ዝግጁ አይደለም።

## 13. ክፍት ንጥሎች / ያልተወሰኑ ዝርዝር

- በ pending invoice ላይ የሚታዩ የባንክ/የክፍያ መመሪያዎች — **ያልተወሰነ —
  Alex**።
- ለ`EMAIL_FROM` የኢሜይል sender domain — **ያልተወሰነ — Alex**።
- ለ branch protection ከ go-live በፊት GitHub plan ማሻገር ወይ አለማሻገር —
  **ያልተወሰነ — Alex**።
- የአገልግሎት ውሎች / የግላዊነት ፖሊሲ — የረቂቅ v0.2 ጽሑፍ በ`/terms` እና
  `/privacy` (`docs/legal/*.md`) ላይ ነቅ ነው፣ ነገር ግን በነዚያ ረቂቆች ውስጥ
  ባሉ ክፍት COUNSEL NOTE ንጥሎች ላይ አሁንም **ያልተወሰነ — የኢትዮጲያ ጠበቃ እና GDC
  management** ነው (በ PDP Proclamation ስር ያለ data localisation
  ከፍተኛ-ቅድሚያ ተብሎ ምልክት ተደርጎበታል)፣ ይህ ከመጨረሻ ታሳታፏ (published)
  ከመሆኑ በፊት።
- ለ downgrades የ account credit / የኢትዮጲያ VAT credit-note አያያዝ —
  **ያልተወሰነ — accountant**፤ ዛሬ ምንም ሁኔታ ቢሆን credit አይሰጥም።
- የክፍያ gateway (Chapa, Telebirr, ወይም ተመሳሳይ) integration — አልተጀመረም፤
  `MANUAL` እና `STUB` ዛሬ ተፈጽመው ያሉት ብቸኛ providers ናቸው።
- የዚህ ሰነድ የራሱ publishing route — **ያልተወሰነ** (authenticated backend
  route ያስፈልገዋል፤ በ`frontend/public/` ወይም Help manifest በኩል መሆን
  የለበትም)።
