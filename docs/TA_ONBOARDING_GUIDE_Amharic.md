# SMART ኢንቬንተሪ — የTA (Tenant Administrator) ኦንቦርዲንግ መመሪያ

**ቅጂ:** 1.7 | **የተዘመነበት ቀን:** ጥቅምት 2026 | **ተደራሽ ለ:** Tenant Administrators እና Organisation Managers

**v1.7 የለውጥ ማስታወሻ፦** Step 1 (Organisation Levels) እና Step 2 (Organisation Tree) አሁን ቀድሞ-የተቀመጠ level ወይም ነባር ቦታ ላይ “Holds stock” (ክምችት ይይዛል) የሚለውን ማቀያየር እና ያንን ማቀያየር የሚያግደውን ይሸፍናሉ።

**v1.6 የለውጥ ማስታወሻ፦** Step 1 (Organisation Levels) እና “Can I change org levels later?” FAQ አሁን ከመጀመሪያ save በኋላ ከ bottom level በታች level መጨመር ወይም ባዶ ሆኖ ሲቀር bottom level-ን ማስወገድ የሚቻልበትን አቅም ያንጸባርቃሉ።

**ክፍል 2 ከ 2 — የስራ ቦታዎን ማዋቀር።** አዲስ ነዎት? መጀመሪያ
[Getting Started](GETTING_STARTED.md) (ክፍል 1)ን ያንብቡ — ከመጀመርዎ በፊት፣ መለያዎን ማግኘት፣ ኢሜይልዎን ማረጋገጥ፣ login፣ የሲስተም ሚናዎች፣ የማዋቀር ቅደም ተከተል፣ እና የፕላን ደረጆች ሁሉ እዛ ይገኛሉ።

> **ከመጀመር በፊት ማስታወሻ፦** ከደንበኞች ጋር ከማጋራትዎ በፊት ሁሉንም `[SCREENSHOT PLACEHOLDER]` ማስታወሻዎችን በእውነተኛ screenshots ይተኩ።

---

## ይህን መመሪያ እንዴት መጠቀም እንደሚቻል

ይህ መመሪያ ሁለት ተደራሾችን ይሸፍናል፦

| ተደራሽ | ክፍሎች |
|----------|----------|
| **ሁሉም ተጠቃሚዎች** (NM, RM, WM, LM, AU) | Steps 7–8, NM Quick Reference, Common Questions |
| **🔒 Tenant Administrator (TA) ብቻ** | Steps 1–6, 9, User Management, Approval Rule Changes |

> **TA-ብቻ ክፍሎች** በዚህ መመሪያ ውስጥ ሁሉ በ🔒 ምልክት ተደርገባቸዋል።

**የተገመተ የማዋቀር ጊዜ፦** ለመጀመሪያ ውቅር 45–90 ደቂቃዎች።

### ሚናዎች ድርጅትዎን እንዴት እንደሚያንጸባርቁ

**Position** (ደረጅ 3) ሲፈጥሩ፣ ከSMART-ቅድመ-ተወስነ role codes አንዱን ይመርጣሉ
([Getting Started → System Roles](GETTING_STARTED.md#system-roles-summary)ን ለሙሉ ዝርዝር ይመልከቱ)፦

- **L1 nodes** (ከፍተኛ level፣ ለምሳሌ Main Factory) → **NM** positions ይመርቁ
- **L2 nodes** (ለምሳሌ Regional Center) → **RM** positions ይመርቁ
- **L3 nodes** (ለምሳሌ Sub Region) → **RM** positions ይመርቁ
- **L4 nodes** (ለምሳሌ Warehouse Area፣ ክምችት-ያዢ) → **WM** positions ይመርቁ
- **LM** positions በ**የትኛውም node level** ላይ ሊፈጠሩ ይችላሉ — LM ከዛ ለያ
  node ብቻ ይወሰናል
- **ለመላው-ቴናንት** (ከ node ጋር ያልተያያዘ) → **AU** positions፣ እና
  position ያልተመረቁ **LM** መለያዎች

> **ማስታወሻ፦** የTA role የራስዎ የአድሚን መለያ ብቻ ነው — ለመደበኛ staff TA
> positions አይፈጥሩም። NM ኦፐሬሽናል staff-ዎ የሚጠቀመው ከፍተኛው role ነው።

---

## የፕላን ደረጆች (ጥቅሎች)

SMART workspaces ከሶስት ጥቅሎች በአንዱ ላይ ናቸው፦ **Starter**, **Growth**,
ወይም **Enterprise**። ሲመዘገቡ ጥቅል ይመርጣሉ፣ ወይም የSMART አስተዳዳሪዎ
ሲያስገባዎት አንዱን ይመርቃል። በኋላ ጥቅልን **ለመቀየር**፣ የSMART አስተዳዳሪዎን
ያግኙ — ከመተግበሪያው ውስጥ በራስዎ መቀየር አይችሉም።

እያንዳንዱ ጥቅል ገደቦችዎን እና የትኞቹ features እንደተካተቱ ይወስናል። የተለመዱ
ነባሪዎች፦

| | Starter | Growth | Enterprise |
|---|---|---|---|
| Warehouses / org nodes | 3 | 10 | ያልተገደበ |
| Staff accounts | 5 | 25 | ያልተገደበ |
| Products (SKUs) | 500 | 1,500 | ያልተገደበ |
| Core Inventory Management | ✓ | ✓ | ✓ |
| Pull & Push Transfers | ✓ | ✓ | ✓ |
| Lot & Batch Traceability | ✓ | ✓ | ✓ |
| Sister (Branch Exchange) Transfers | — | ✓ | ✓ |
| Logistics & Fleet Management | — | ✓ | ✓ |
| Audit Log Export | — | ✓ | ✓ |
| Custom Branding | — | ✓ | ✓ |
| AI Forecasting & Analytics | — | — | ✓ |
| API Access | — | — | ✓ |

> **ከላይ ያሉት ቁጥሮች ነባሪዎች ናቸው እናም ሊከለሱ ይችላሉ።** የ sign-up page
> ሁልጊዜ የወቅቱን ጥቅል ይዘት እና ዋጋ ያሳያል፣ እና **Settings → Tenant Admin →
> Plan** ለ*ራስዎ* workspace የተፈጻሚውን ትክክለኛ ገደብ እና ባህሪ ያሳያል። ጥቅሎች
> ከጊዜ ወደ ጊዜ ይከለሳሉ፤ ክለሳ ለአዲስ sign-ups እና plan ለውጦች ይተገበራል፣
> ራሱን ባለ ነባር workspace ገደቦችን አይቀይርም።

**የTA መለያ ነጻ ነው።** የራስዎ TA መለያ ወደ staff-account limit አይቆጠርም።
**Warehouses = ክምችት የሚይዙ ቦታዎች፤ approval-ብቻ ቦታዎች ነጻ ናቸው** — አንድ
org node ወደ warehouse limit የሚቆጠረው ክምችት ከያዘ ብቻ ነው
(`is_stock_holding = true`)።

**ዋጋዎች።** እያንዳንዱ ጥቅል የወርሃዊ እና የዓመታዊ ዋጋ አለው። ዋጋዎች ከVAT በፊት
ይታያሉ፣ **15% VAT** እና ድምር ለብቻ ይታያል። የዋጋ ለውጥ ለ**ቀጣይ renewal**
ይተገበራል፤ ቀድሞ የተቀበሉትን invoice በፍጹም አይቀይርም።

**ጥቅል መቀየር።** ጥቅል ለውጦች በSMART አስተዳዳሪዎ ይፈጸማሉ። አዲሱ ገደብ እና
feature **ወዲያውኑ** ይተገበራል፣ አዲሱ ዋጋ ከ**ቀጣይ invoice** ይከፈላል።

- **Monthly billing:** ለቀረው የወቅቱ ወር ምንም ተጨማሪ ክፍያ አይኖርም።
- **Annual billing — upgrade:** ያሻገሩበት ቀሪ ወር ነጻ ነው። በወቅቱ ዓመት
  **ለቀሩት ሙሉ ወራት**፣ በአዲሱ እና አሮጌው ዓመታዊ ዋጋ መካከል ያለውን **ልዩነት**፣
  በወር የተካፈለ፣ ከVAT ጋር የሚያስከፍል invoice ይቀበላሉ።
  *ለምሳሌ፦* Starter 1,000 → Growth 2,000 ከ7 ሙሉ ወራት ቀሪ፦
  (2,000 − 1,000) × 7 ÷ 12 = 583.33 + 87.50 VAT = **670.83 ETB**።
- **Downgrade:** ዝቅተኛው ገደብ ወዲያውኑ ይተገበራል። ለወቅቱ ጊዜ **ምንም refund
  ወይም credit የለም**፤ ዝቅተኛው ዋጋ ከቀጣይ invoice ይተገበራል።

ይህ የማሻገር invoice በ invoice ዝርዝርዎ ውስጥ **Proration** ተብሎ ይመልክታል።
ይህን መክፈል ኮንትራትዎን ወይም ክፍያ ቀናትዎን አይቀይርም።

**ተጨማሪ-አገልግሎቶች (Add-ons)።** በጥቅልዎ ውስጥ ያልተካተተ feature (ለምሳሌ
API Access) በSMART አስተዳዳሪዎ በራሱ ሊጨመር ይችላል። ወዲያውኑ ይሰራል እና ከቀጣይ
invoice ከጥቅልዎ ጋር ይከፈላል። በ**annual** billing ደግሞ በወቅቱ ዓመት ቀሪ
ላሉ ሙሉ ወራት በ add-on-ው ዓመታዊ ዋጋ (በወር የተካፈለ፣ ከVAT ጋር) **Proration**
invoice ይቀበላሉ፤ ለቀረው የወቅቱ ወር ነጻ ነው። Add-on መሰረዝ ወዲያውኑ ያቆመዋል፣
ምንም refund የለም።

> መደበኛ invoice ክፍያ እየጠበቀ እያለ፣ የጥቅል እና add-on ለውጦች እስኪከፈል ወይም
> እስኪሰረዝ ድረስ ይቆማሉ፣ ስለዚህ ያ invoice በፍጹም በተሳሳተ ዋጋ አይወጣም።

> **Branch Exchange (Sister) transfers — የ Starter tier ገደብ፦**
> በተመሳሳይ level ባሉ warehouses መካከል የጎን ዝውውሮች (lateral transfers)
> በStarter tier ላይ አይገኙም። Staff አንድ ለመፍጠር ቢሞክሩ የ plan-limit
> ስህተት ይቀበላሉ። ይህ feature የሚያስፈልግ ከሆነ፣ ወደ Growth ወይም Enterprise
> ስለ ማሻገር የSMART አስተዳዳሪዎን ያግኙ።

> **በማዋቀር ጊዜ ገደብ ላይ መድረስ፦** warehouse (Step 2)፣ staff account
> (Step 4) ወይም product (Step 7) ለመጨመር ሲሞክሩ ስህተት ከተቀበሉ፣ ምናልባት
> የፕላንዎን ገደብ ደርሰዋል። bug ነው ብለው ከማሰብ ይልቅ tier upgrade ለመጠየቅ
> የSMART አስተዳዳሪዎን ያግኙ።

---

## 🔒 ፕላንዎ፣ Subscription እና ደረሰኞች (TA ብቻ)

*Settings → Tenant Admin*

የTenant Admin ገፅ አምስት tabs አለው፦

| Tab | ምን ማድረግ ይችላሉ |
|-----|-----------------|
| **Profile** | የድርጅትዎን ዝርዝሮች ማየት እና ማዘመን |
| **Plan** | ጥቅልዎን፣ ገደቦችዎን፣ feature-ዎችን፣ subscription-ዎን እና invoices-ዎን ማየት |
| **Contract** | የኮንትራት መጀመሪያ እና ማብቂያ ቀናትዎን ማየት (ለማንበብ-ብቻ) |
| **Contact** | የድርጅትዎን የእውቂያ ሰዎች ማስተዳደር |
| **Features** | ጥቅልዎ የትኞቹ features እንደያዘ ማየት |

### Subscription ሁኔታ

**Plan** tab ያለዎትን subscription ያሳያል — ጥቅል፣ billing period፣ አሁኑ
period እና ድምር ከVAT ጋር — ከእነዚህ ሁኔታዎች በአንዱ፦

| ሁኔታ | ትርጉም |
|--------|---------|
| **Pending payment (ክፍያ በመጠባበቅ)** | workspace-ዎ ሙሉ በሙሉ ነቅ ነው። የመጀመሪያ invoice-ዎ እስካሁን አልተከፈለም። |
| **Active (ነቅ)** | የወቅቱ period-ዎ ተከፍሏል። |
| **Past due (ያለፈ ጊዜ)** | renewal ጊዜው አልፎታል። ለማስፈፍ SMART-ን ያግኙ። |
| **Cancelled (ተሰርዟል)** | subscription-ው አብቅቷል። |

> **የወቅቱ ቅጂ፦** ያልተከፈለ invoice ራሱ workspace-ዎን አይገድብም ወይም
> አያግደውም። የሚገድበው **የኮንትራት ማብቂያ ቀንዎ** ሳይታደስ ካለፈ ነው — ከዚህ በታች
> [የኮንትራት ቀናት](#የኮንትራት-ቀናት) እና
> [ኮንትራታችን ሲያበቃ ምን ይከሰታል?](#የተለመዱ-ጥያቄዎች)ን ይመልከቱ።

### ደረሰኞች እና እንዴት እንደሚከፈል

SMART ደረሰኞችዎን ያወጣል፤ በPlan tab ላይ **Invoices** list ውስጥ ከ period፣
subtotal፣ VAT፣ total እና ሁኔታ (Pending, Paid, Failed, Cancelled) ጋር
ይታያሉ።

ለ**Pending** invoice፣ ለክፍያ መመሪያ **How to pay**ን ይጫኑ።

`[PAYMENT INSTRUCTIONS PLACEHOLDER — የባንክ ስም፣ የመለያ ስም እና ቁጥር፣
ለማጣቀስ reference፣ እና ደረሰኝ የሚላክበት ቦታ። ከ go-live በፊት ይቀርባል።]`

SMART ክፍያዎን ሲያረጋግጥ፣ invoice **Paid** ያሳያል፣ subscription-ዎ
**Active** ይሆናል፣ እና **የኮንትራት ማብቂያ ቀንዎ ይገፈፋል** ወደ የተከፈለው
period ማብቂያ።

### የኮንትራት ቀናት

ኮንትራትዎ ከምዝገባዎ (ወይም onboarding) ቀን ለአንድ billing period ይሄዳል፣
እና ክፍያ በተረጋገጠ ቁጥር ይገፋፋል። የContract tab **ለማንበብ-ብቻ** ነው፤
የኮንትራት ቀናት በSMART ይተዳደራሉ። ለመቀየር SMART-ን ያግኙ።

workspace-ዎ የኮንትራት ማብቂያ ቀንዎ ሲደርስ እና ካለፈ በኋላ በአራት ደረጆች
ያልፋል፦

| ደረጅ | መቼ | ምን ማድረግ ይችላሉ |
|-------|------|------------------|
| **Active (ነቅ)** | ከኮንትራት ማብቂያ ቀንዎ በፊት ከ14 ቀን በላይ | ሁሉም ነገር፣ እንደ ልማድ |
| **Expiring (ወደ ማብቂያው የቀረበ)** | ከኮንትራት ማብቂያ ቀንዎ በፊት 14 ቀን ወይም ያነሰ | ሁሉም ነገር፣ እንደ ልማድ — ከማስጠንቀቂያ banner ጋር |
| **Grace (የምሕረት ጊዜ)** | ከኮንትራት ማብቂያ ቀንዎ በኋላ እስከ 14 ቀን | ሁሉም ነገር፣ እንደ ልማድ — ከ banner ጋር |
| **Read-only (ለማንበብ-ብቻ)** | ከኮንትራት ማብቂያ ቀንዎ በኋላ ከ14 ቀን በላይ | ዕይታ እና export ብቻ — ከዚህ በታች ይመልከቱ |

**Read-only** እያንዳንዱን አዲስ transaction፣ approval፣ edit ወይም upload
ያግዳል። አሁንም መቻል ይችላሉ፦ login ማድረግ፣ ውሂብዎን ማየት እና export ማድረግ፣
የራስዎን password መቀየር፣ የTerms ዝማኔዎችን መቀበል፣ contacts-ዎን ማስተዳደር፣
staff member password reset ማድረግ፣ እና staff account ማቦዝን። ከዚህ
ውጪ ያለው ሁሉ SMART renewal-ዎን እስኪመዘግብ ድረስ ይከለከላል — ከዚህ በታች
[Renewal እንዴት እጠይቃለሁ?](#የተለመዱ-ጥያቄዎች)ን ይመልከቱ። Read-only መሆንዎ
ከ**suspension** የተለየ ነው፣ suspension የሚከሰተው SMART workspace-ዎን
ሆን ተብሎ ካገደ ብቻ ነው (የSMART ተወካይዎን ያግኙ) — ያለፈ ኮንትራት ራሱ ብቻውን
አያግድዎትም።

---

## 🔒 ደረጅ 1 — የድርጅት Levels (TA ብቻ)

*Org Setup → "Organisation Levels" tab*

ድርጅትዎ ምን ያህል levels እንደያዘ እና እያንዳንዱ level ምን እንደሚባል ይግልጹ።

1. ወደ Org Setup → "Organisation Levels"ን ይጫኑ
2. የ levels ቁጥር ያስገቡ (በተለምዶ 3–5)
3. እያንዳንዱን level በቀላል ቋንቋ ይሰይሙ
4. ዝቅተኛውን level እንደ **Stock Holding** ምልክት ያድርጉ — ይህ አካላዊ ክምችት
   የሚከተልበት ነው
5. Save ይጫኑ

**ከ save በኋላ**፣ ከወቅቱ bottom level በታች level መጨመር ይችላሉ፣ ወይም
ገና org nodes ከሌለው bottom level-ን ማስወገድ ይችላሉ። በ stack መሃል ላይ
level ማስገባት ወይም ማስወገድ ራስ-አገልግሎት (self-service) አይደለም — ለዛ
የSMART support ያግኙ።

**በተቀመጠ level ላይ “Holds stock”ን ማቀያየር፦** ማብራት (on) ሁልጊዜ
ይፈቀዳል — በዛ level ያሉ ነባር ቦታዎች እንዳሉ ይቀራሉ፤ ክምችት መያዝ ያለበት ከሆነ
ከዚያ በኋላ እያንዳንዱን ለብቻ ያቀያይሩ። ማጥፋት (off) የሚፈቀደው በዛ level ላይ
ያለ ነቅ ቦታ ገና ክምችት የሚይዝ ካልሆነ ብቻ ነው — ካለ፣ መጀመሪያ approval-ብቻ
ማቀያየር ያለባቸውን ያሳይዎታል።

የ4-level structure ምሳሌ፦

| Level | ምሳሌ ስም | ማስታወሻ |
|-------|-------------|-------|
| L1 | Main Factory | የ hierarchy ከፍተኛ |
| L2 | Regional Center | ክልላዊ hubs |
| L3 | Sub Region | አማራጭ መካከለኛ level |
| L4 ★ | Warehouse Area | ★ እንደ Stock Holding ምልክት ያድርጉ |

`[SCREENSHOT: 4 levels የተዋቀሩበትን Organisation Levels tab]`

---

## 🔒 ደረጅ 2 — የድርጅት ዛፍ (Organisation Tree) (TA ብቻ)

*Org Setup → "Organisation Tree" tab*

ከደረጅ 1 levels ተጠቅመው እውነተኛ nodes (ፋብሪካዎች፣ ቢሮዎች፣ warehouses)
ይፍጥሩ።

1. "+ Add Node"ን ይጫኑ እና ከ top-level node-ዎ ይጀምሩ (ለምሳሌ "Factory A")
2. level-ውን (L1) ይምረጡ እና ስም ያስገቡ
3. child nodes ይጨምሩ — መጀመሪያ parent-ን ይምረጡ፣ ከዚያ child ይጨምሩ
4. ሙሉ org chart-ዎ ሲስተም ውስጥ እስኪገባ ድረስ ይድገሙ

**ምክሮች፦**
- ሁሉም ቅርንጫፎች ተመሳሳይ ጥልቀት መሆን አያስፈልጋቸውም (ድብልቅ-ጥልቀት structures
  ይደገፋሉ)
- ወጥነት ያላቸው፣ ኦፊሴላዊ ስሞችን ይጠቀሙ — በ reports እና audit logs ውስጥ
  ይታያሉ
- ድርጅትዎ እያደገ ሲሄድ ተጨማሪ nodes በኋላ መጨመር ይችላሉ
- Node ፍጥረት በፕላን tier-ዎ warehouse limit ይገደባል — node ሲጨምሩ
  ስህተት ከተቀበሉ፣ bug ነው ብለው ከማሰብ ይልቅ ተጨማሪ አቅም ለመጠየቅ የSMART
  አስተዳዳሪዎን ያግኙ ([Plan Tiers](#የፕላን-ደረጆች-ጥቅሎች)ን ይመልከቱ)
- ነባር ቦታ "Holds stock" setting-ን ከ edit form-ው ማቀያየር ይችላሉ።
  ማጥፋት የሚያግደው ያ ቦታ ክፍት transfers፣ pending adjustments፣ ወይም
  on-hand ክምችት ካለው ነው — መጀመሪያ እነዚያን ያጽዱ፣ ከዚያ ያቀያይሩ። Toggle-ው
  ራሱ level-ው approval-ብቻ ከሆነ ይከለክላል፤ መጀመሪያ ለ level-ው "Holds
  stock"ን ያብሩ (ደረጅ 1)።

`[SCREENSHOT: ባለ-ሁለት-ፋብሪካ structure ያለውን Organisation Tree]`

---

## 🔒 ደረጅ 3 — Positions (TA ብቻ)

*Org Setup → "Positions" tab*

Positions ሰዎችን ከ nodes ያገናኛሉ እና ምን ማድረግ እንደሚችሉ ይወስናሉ።

1. ለእያንዳንዱ node፣ ቢያንስ አንድ main position ይፍጠሩ
2. የተመከረ፦ ለ coverage የassistant position ይጨምሩ
3. ርዕስ (title) ያስቀምጡ (በ approval ማስታወቂያዎች እና audit logs ውስጥ
   ይታያል)
4. role level ይምረጡ፦ **NM** (ከፍተኛ)፣ **RM** (መካከለኛ)፣ **WM**
   (warehouse)

**ምሳሌዎች፦**

| Node | Main Position | Assistant |
|------|--------------|-----------|
| Factory A (L1) | "HQ Director (NM)" | "Deputy HQ (Asst NM)" |
| Region A (L2) | "Region A Manager (RM)" | "Region A Deputy (Asst RM)" |
| WHA1 (L4) | "WHA1 Warehouse Manager (WM)" | "WHA1 Warehouse Assistant (WM)" |

💡 **ምክር፦** Position titles በመላው ሲስተም ይታያሉ — ኦፊሴላዊ፣ የሚታወቁ titles
ይጠቀሙ።

`[SCREENSHOT: ለFactory A እና Warehouse nodes positions የሚያሳየውን Positions tab]`

---

## 🔒 ደረጅ 4 — Personnel (ተጠቃሚዎችን መጨመር) (TA ብቻ)

*Org Setup → "Personnel" tab*

1. "+ Add Person"ን ይጫኑ እና ስም እና ኢሜይል ያስገቡ
2. system role-ቸውን ይምረጡ (NM / RM / WM / LM / AU)
3. ወደ position ይመርቁ (ከ org node-ቸው ያገናኛቸዋል)
4. የመጀመሪያ password ያስቀምጡ (በመጀመሪያ login ላይ እንዲቀይሩ ይጠየቃሉ)
5. ለሁሉም staff ይድገሙ

**የኢሜይል ቅርጽ ምክር፦** `role_locationname@yourcompany.com`
- ለምሳሌ፦ `wm_warehouse1@company.com`
- ለምሳሌ፦ `rm_region_a@company.com`

👥 **ማስታወሻ፦** አንድ ሰው ወደ ብዙ positions ሊመረቅ ይችላል — permission-ቸው
የተመረቁት positions ሁሉ ድምር ነው።

> **የ staff account ገደብ፦** መለያዎችን መጨመር በፕላን tier-ዎ user limit
> ይገደባል። አዲስ ሰው ሲጨምሩ ስህተት ከተቀበሉ፣ የፕላን ገደብዎ ደርሰዋል — bug ነው
> ብለው ከማሰብ ይልቅ upgrade ለመጠየቅ የSMART አስተዳዳሪዎን ያግኙ
> ([Plan Tiers](#የፕላን-ደረጆች-ጥቅሎች)ን ይመልከቱ)።

`[SCREENSHOT: positions የተመረቁ ተጠቃሚ ዝርዝር የሚያሳየውን Personnel tab]`

---

## 🔒 ደረጅ 5 — Transfer Types (TA ብቻ)

*Org Setup → "Transfer Types" tab*

ለሶስቱ transfer types የማሳያ ስሞችን ያስተካክሉ።

| System Code | ነባሪ ስም | ትርጉሙ |
|------------|-------------|---------------|
| PULL | Request Stock | Warehouse ከከፍተኛ level ይጠይቃል |
| PUSH | Send Stock | ከፍተኛ level ክምችት ወደ ታች ይገፋል |
| SISTER | Branch Exchange | በ warehouses መካከል የጎን ዝውውር — **Growth tier ወይም ከዛ በላይ ያስፈልጋል**፤ በStarter ላይ አይገኝም |

ለእያንዳንዱ transfer type፦
1. የድርጅትዎ የተመረጠ የማሳያ ስም ያስገቡ
2. መግለጫ ይጨምሩ (አማራጭ)
3. የትኞቹ levels ሊጀምሩት እንደሚችሉ ያስቀምጡ
4. Active/Inactive ያቀያይሩ

`[SCREENSHOT: ባለ-custom display names Transfer Types tab]`

---

## 🔒 ደረጅ 6 — Approval Rules (TA ብቻ)

*Org Setup → "Approval Rules" tab*

### Transfer Approval Rules

ለእያንዳንዱ transfer type፣ የሚከተሉትን የሚገልጹ rules ይፍጠሩ፦
- **From Level → To Level** (ይህ rule የትኛውን አቅጣጫ እንደሚሸፍን)
- **Quantity range** (0 እስከ ያልተገደበ፣ ወይም የተወሰነ range)
- **Approval steps** (ማን ያጸድቃል፣ በየትኛው ቅደም ተከተል፣ በስንት ሰዓት ውስጥ)

> **ለምሳሌ፦** Request Stock | Warehouse Area → Sub Region | Qty:
> 5,001+ units | Step 1: Sub Region Manager (24ሰ) | Step 2:
> Regional Manager (48ሰ)

`[SCREENSHOT: multi-step rule configuration የሚያሳየውን Transfer Rules]`

### Adjustment Approval Rules

በ role level stock adjustments መቼ approval እንደሚያስፈልጋቸው በ quantity
ይግልጹ።

### Self-Approval Limits

በ role አንድ blanket self-approval quantity ያስቀምጡ — ከዚህ ገደብ በታች
ያሉ transfers በራስ-ሰር ይጸድቃሉ፦

| Role | ምሳሌ ገደብ |
|------|--------------|
| Warehouse Manager (WM) | እስከ 5,000 units — በራስ-ሰር ወዲያውኑ ይጸድቃል |
| Regional Manager (RM) | እስከ 20,000 units — በራስ-ሰር ወዲያውኑ ይጸድቃል |
| Factory Manager (NM) | ያልተገደበ — ሁሉም transfers በራስ-ሰር ይጸድቃሉ |

💡 **ምክር፦** rules ካስተካከሉ በኋላ፣ ለቀላል-ቋንቋ ማጠቃለያ **Approval
Policies** ገፅን ይመልከቱ።

---

## ደረጅ 7 — Products እና Categories

*Products ገፅ — TA እና NM products መፍጠር ይችላሉ፤ ሁሉም roles ማየት ይችላሉ*

### 🔒 Product Categories መፍጠር (TA ብቻ)

1. ወደ Products → Categories ይሂዱ
2. "+ Add Category"ን ይጫኑ እና ስም ያስገቡ (ለምሳሌ "Raw Materials",
   "Finished Goods")
3. products ከመጨመርዎ በፊት ሁሉንም categories ይፍጠሩ

### Products መጨመር (TA እና NM)

1. ወደ Products → "+ Add Product"ን ይጫኑ
2. የ product ስም፣ SKU (ወይም auto-generate)፣ እና category ይምረጡ
3. **Type Code** ያስገቡ — 2–10 alphanumeric ባህሪያት (ለምሳሌ RAW, FIN,
   PKG)
4. Unit of Measure ይምረጡ (KG, Piece, Box, Roll, ወዘተ)
5. product image ይጫኑ (አማራጭ፣ ከፍተኛው 2MB፣ JPG/PNG/WebP)
6. Save ይጫኑ

`[SCREENSHOT: ሁሉም fields የተሞሉት Add Product panel]`

### 🔒 Controlled Products — ልዩ Approval Rules (TA ብቻ)

ከ quantity ነጻ ሁልጊዜ approval ለሚፈልጉ ከፍተኛ-ዋጋ ወይም ስልታዊ items፦

1. መጀመሪያ product-ውን ይፍጠሩ፣ ከዚያ ለማስተካከል ይክፈቱት
2. ወደ "Minimum Approval Level" ክፍል ይውርዱ
3. ተፈጻሚ transfer types-ላችን override ያብሩ
4. ይምረጡ፦ **ሁልጊዜ** approval ይፈልግ፣ ወይም **ከ quantity threshold በላይ**
5. የትኛው position ማጽደቅ እንዳለበት ይምረጡ
6. Save — በ product ላይ 🔒 icon ይታያል

> **አስፈላጊ — Controlled products በ transfer ሁለት approver
> interactions ይፈልጋሉ፦**
> Warehouse manager ለ controlled product PULL ሲፈጥር፣ transfer-ው
> መደበኛውን review step **አያልፍም**። ሙሉ ፍሰቱ፦
> DRAFT → Pending Review → (reviewer ያስፋፋል) → Pending Approval →
> (override approver ያጸድቃል) → Approved
>
> ይህ ማለት ይህ ሂደት ከመደበኛ transfer ረዘም ይላል። ይህንን ለ warehouse
> managers-ዎ ያስተላልፉ ቀድመው እንዲያቅዱ — በተለይ ለጊዜ-ስልታዊ የክምችት ዝውውሮች።

---

## ደረጅ 8 — የመክፈቻ ክምችት (Opening Stock)

*Inventory ገፅ → Receive Stock — NM እና TA opening stock ማስገባት ይችላሉ*

ስራ ላይ ከመውጣትዎ በፊት፣ በእያንዳንዱ warehouse ያለውን ነባር ክምችት ይመዝግቡ።

1. ወደ Inventory ገፅ ይሂዱ
2. warehouse-ውን ይምረጡ
3. "Receive Stock"ን ይጫኑ
4. product-ውን ይምረጡ እና የመክፈቻ quantity ያስገቡ
5. ማስታወሻ ይጨምሩ (ለምሳሌ "Opening balance — ሰኔ 2026")
6. Submit — ክምችት ወዲያውኑ ወደ ledger ይጨመራል
7. በእያንዳንዱ warehouse ላለ እያንዳንዱ product ይድገሙ

**⚠️ አስፈላጊ፦** Opening stock entries ዘላቂ ናቸው እና መሰረዝ አይቻልም
(ledger-ው ለ audit ዓላማ ያልተለወጠ ነው)። ስህተቶችን ለማስተካከል reason code
`COUNT_CORRECTION` ያለው Adjustments ይጠቀሙ።

`[SCREENSHOT: product እና quantity fields ያለው Receive Stock panel]`

---

## 🔒 ደረጅ 9 — Branding (አማራጭ፣ TA ብቻ)

*Org Setup → "Branding" tab*

| ንጥል | ዝርዝር |
|------|-------|
| Organisation Logo | ከፍተኛው 1MB፣ JPG/PNG/WebP። በ navigation header ይታያል። |
| Organisation Banner | ከፍተኛው 3MB፣ JPG/PNG/WebP። በDashboard ይታያል። |

1. ወደ Org Setup → "Branding" tab ይሂዱ
2. logo እና banner ይጫኑ
3. Save — ወዲያውኑ በመላው ፕላትፎርም ይታያል

`[SCREENSHOT: logo እና banner upload ያለው Branding tab]`

---

## Organisation Manager (NM) — Quick Reference

*ይህ ክፍል ለOrganisation Managers እና ኦፐሬሽናል staff ነው።*

### ኃላፊነቶችዎ
- products መፍጠር እና ማስተዳደር
- transfers መገምገም እና ማጽደቅ
- Send Stock (PUSH) transfers መጀመር
- የክምችት level-ዎችን መከታተል
- approval policies ማየት

### Transfers ማጽደቅ

1. ወደ Transfers ገፅ ይሂዱ
2. "Pending Review" ወይም "Pending Approval" ሁኔታ ያላቸውን transfers
   ያግኙ
3. ዝርዝሮችን ይገምግሙ (product, quantity, source, destination)
4. **Review** ከዚያ **Approve** ይጫኑ — ወይም ተገቢ ካልሆነ **Reject**

### ክምችት ማስወጣት እና መላክ (Issuing & Dispatching)

1. በTransfers ገፅ ላይ Approved transfer ያግኙ
2. ክምችት ለመንቀሳቀስ ዝግጁ መሆኑን ለማረጋገጥ **Issue**ን ይጫኑ
3. ከ source መውጣቱን ለማረጋገጥ **Dispatch**ን ይጫኑ
4. destination WM ከዛ ይቀበለዋል

> **በራስ ፈንታ መስራት (Acting on Behalf)፦** source warehouse-ው ለሌላ
> facility የሆነ transfer Issue/Dispatch ካደረጉ፣ ሲስተሙ "Acting on
> behalf of: [Warehouse Name]" ያሳያል እና ይህን በ audit log ውስጥ
> ይመዘግባል።

### Approval Policies ማየት

በ navigation ውስጥ ወደ **Approval Policies** ይሂዱ ለማየት፦
- ለ transaction type በ self-approval ገደቦችዎ
- የትኞቹ products 🔒 ልዩ approval ፍላጎት እንዳላቸው
- ሙሉ policy matrix (TA/SA ሁሉንም levels ያዩ)

---

## ተከታይ አስተዳደር (Ongoing Administration)

### 🔒 አዲስ ተጠቃሚ መጨመር (TA ብቻ)
1. Org Setup → Personnel → "+ Add Person"
2. ስም፣ ኢሜይል፣ role ያስገቡ፣ ወደ position ይመርቁ፣ password ያስቀምጡ
3. credentials ደህንነት ባለው መንገድ ያጋሩ

### 🔒 ተጠቃሚን ማቦዝን (TA ብቻ)
1. Personnel list → ተጠቃሚ ያግኙ → Active-ን off ያድርጉ
2. መለያው ወዲያውኑ ይዘጋል

> **⚠️ ማስታወሻ፦** የቦዘነ ተጠቃሚ pending approvals ካሉት፣ የSMART
> አስተዳዳሪዎን ያግኙ። አውቶማቲክ ድጋሚ-ማስተላለፍ (re-routing) በቀጣይ ዝማኔ
> ይመጣል።

### 🔒 ተጠቃሚን ዳግም ማንቃት (TA ብቻ)
1. Personnel list → ያልነቀ ተጠቃሚ ያግኙ → Active-ን ድጋሚ ያብሩ
2. ቀድሞ የነበራቸው primary position በራስ-ሰር ይመለሳል — በእጅ ድጋሚ-ለመመርቅ
   አያስፈልግም
3. ተጨማሪ positions (acting ወይም delegate assignments) ነበራቸው ከሆነ፣
   primary position ብቻ በራስ-ሰር ይመለሳል፤ አሁንም ካስፈለገ acting ወይም
   delegate positions በእጅ ድጋሚ ይመርቁ

### 🔒 Approval Rules ማስተካከል (TA ብቻ)
1. Org Setup → Approval Rules → rule-ውን ያግኙ እና ያስተካክሉ
2. quantities, steps, ወይም approver positions ያዘምኑ
3. Save — ለውጦች ወዲያውኑ ይተገብራሉ

### የታወቁ ገደቦች — የወቅቱ ቅጂ

- **Adjustment approval position ማስፈፀም፦** Adjustment approval
  rules የተመረጠ approver position ይገልጻሉ፣ ነገር ግን ሲስተሙ approval
  permission ያላቸው ሌሎች ተጠቃሚዎች ከማጽደቅ በቴክኒክ አይከለክልም። Adjustment
  approval-ን በአስተዳደር ቡድንዎ ውስጥ እንደ ሂደት ልማድ ያስፈጻሙ።

- **የ Transfer notes ርዝመት፦** Transfer notes እስከ 2000 ባህሪያት
  ይገደባሉ።

- **PUSH /review አይተገብርም፦** PUSH እና Sister transfers review step
  የላቸውም። PULL transfers ብቻ ናቸው በ PENDING_REVIEW → PENDING_APPROVAL
  ፍሰት የሚያልፉ። ለ staff በ PUSH transfers review action ለመጠቀም
  አያስተምሩ።

- **በቅርቡ የሚመጣ፦** bulk CSV import (ለ products ወይም opening stock)፣
  dispatch strategy configuration (FEFO/FIFO/LIFO)፣ እና stock-count
  submission በ product ላይ ይታያሉ ነገር ግን **Coming soon** ተብለው ምልክት
  ተደርጎባቸዋል — ገፆቹ አሉ፣ ነገር ግን ገና ምንም backend የላቸውም። በwork
  space-ዎ ያለ button ግራጫ (greyed out) ከሆነ፣ ላዩ ላይ hover ያድርጉ፦
  Coming soon feature፣ plan limit፣ ወይም workspace-ዎ read-only
  መሆኑን ይነግርዎታል።

---

## የተለመዱ ጥያቄዎች

**ጥ፦ ጥቅልዬን እንዴት ላሻገር ወይም ልቀይር እችላለሁ?**
የSMART አስተዳዳሪዎን ያግኙ — ጥቅል ለውጦች የሚፈጸመው በSMART ነው፣ ከራስዎ Tenant
Admin ገፅ አይደለም። አዲስ ገደብ እና feature ለውጡ እንደተፈጸመ ይተገብራል። በ annual
billing አንድ upgrade በዓመትዎ ቀሪ ወራት ላይ pro-rated **Proration**
invoice ያስከፍላል (
[Plan Tiers](#የፕላን-ደረጆች-ጥቅሎች)ን ይመልከቱ)፤ downgrade ምንም refund
የለውም።

**ጥ፦ "Proration" invoice ምንድን ነው?**
በ annual billing ዓመት መካከል ለ upgrade ወይም add-on የሚወጣ ነጠላ-ጊዜ
invoice ነው። በዛ ዓመት ቀሪ ባሉት ሙሉ ወራት ላይ ብቻ ይተገብራል፤ ለውጡ የተፈጸመበት
ወር ነጻ ነው።

**ጥ፦ ተመዝግቤ ነገር ግን የማረጋገጫ ኢሜይል በፍጹም አልተቀበልኩም።**
በ sign-in ገፅ ወይም verification ገፅ ላይ **Resend link**ን ይጠቀሙ።
ሊንኮች ከ48 ሰዓት በኋላ ያልቃሉ። አሁንም ባይደርስ፣ spam ፎልደርዎን ያረጋግጡ ወይም
የSMART support-ን ያግኙ።

**ጥ፦ “account owner” ማን ነው?**
workspace-ውን የመዘገበው ሰው (ወይም በSMART የተፈጠረው የመጀመሪያ TA)። ለ
subscription-ው እና invoices-ው ዋና contact ነው/ናት።

**ጥ፦ ተጠቃሚዎችን ከጨመርኩ በኋላ org structure-ን ልቀይር እችላለሁ?**
አዎ — አዲስ nodes እና positions መጨመር ይችላሉ። ነባር ተጠቃሚዎች
assignments-ቸውን ይይዛሉ። Node ለማስወገድ፣ መጀመሪያ ተጠቃሚዎቹን ድጋሚ ይመርቁ።

**ጥ፦ org levels-ን በኋላ ልቀይር እችላለሁ?**
በየትኛውም ጊዜ ከወቅቱ bottom level በታች level መጨመር ይችላሉ፣ እና ገና org
nodes ከሌለው bottom level-ን ማስወገድ ይችላሉ — የመጀመሪያ levels-ዎን
ካስቀመጡ በኋላ Organisation Levels tab ሁለቱንም አማራጮች ያሳያል። በ stack
መሃል ላይ level ማስገባት ወይም ማስወገድ ራስ-አገልግሎት አይደለም፤ ያስፈልግዎት ከሆነ
የSMART support ያግኙ።

**ጥ፦ approver ካልተገኘ ምን ይደረጋል?**
እንደTA፣ በየትኛውም position ፈንታ ማጽደቅ ይችላሉ። pending ንጥል-ውን በTransfers
ወይም Adjustments ገፅ ላይ ያግኙ እና በቀጥታ ያጽድቁት ወይም ያስተባብሉት — audit
log በእነሱ ፈንታ እንደሰሩ ይመዘግባል።

**ጥ፦ Transfer Pending Approval ውስጥ ተይዟል እና ማንም ድርጊት አይወስድም —
ምን ማድረግ አለብኝ?**
ይህ የተመረቀው approver position ክፍት ሲሆን (ተጠቃሚ ከተቦዘነ ወይም ድጋሚ ከተመረቀ)
transfer-ው ከቀረበ በኋላ ሊከሰት ይችላል። ሲስተሙ እስካሁን በራስ-ሰር ማስጠንቀቂያ
አይሰጥም — "Pending Approval" ተብሎ የተጣራ Transfers በየጊዜው ያረጋግጡ።
እንደTA በራስዎ ያልፈጠሩትን ማንኛውንም transfer ማጽደቅ ወይም ማስተባበል ይችላሉ።
ለመፍታት፦
1. ወደ Transfers → ሁኔታ "Pending Approval" ተብሎ ያጣሩ
2. የተያዘውን transfer ያግኙ እና ይክፈቱት
3. በቀጥታ ያጽድቁት ወይም ያስተባብሉት (audit log የTA ድርጊት ይመዘግባል)
4. ከዛ node ላይ አዲስ transfers ከመፍጠርዎ በፊት፣ ለቀጣይ transfers በትክክል
   እንዲሄዱ ለ approver position ተጠቃሚ ይመርቁ

ይህን ለማስቀረት፦ approver position የያዘ ማንኛውንም ተጠቃሚ ከማቦዝንዎ በፊት፣
መጀመሪያ ምትክ ለዛ position ይመርቁ። ሲስተሙ ከዛ አዲስ transfers ወደ ምትኩ
በራስ-ሰር ያቀናል።

**ጥ፦ ተጠቃሚ ከአንድ በላይ position ሊይዝ ይችላል?**
አዎ። permission-ቸው የተመረቁት positions ሁሉ ድምር ነው — ብዙ አካባቢዎችን
የሚከታተል manager ላላቸው ጠቃሚ ነው።

**ጥ፦ በ product ላይ ያለው 🔒 icon ምን ያመለክታል?**
Product-ው Controlled ነው — መደበኛ transfer flow-ን የሚያልፉ ልዩ approval
rules አለው። ትንሽ quantities እንኳ የተወሰነ approval ይፈልጋል። ዝርዝሮችን
ለ Approval Policies ገፅ ይመልከቱ።

**ጥ፦ Adjustment እና Receive Stock ልዩነት ምንድን ነው?**
- **Receive Stock** — ክምችት warehouse ይደርሳል (ከ supplier ወይም
  opening balance)
- **Adjustment** — የክምችት ቆጠራ ያስተካክላል (ጉዳት፣ ስርቆት፣ የቆጠራ ስህተት)

**ጥ፦ የተጠናቀቀ transfer መመለስ ይቻላል?**
አይ — ledger-ው ለ audit ታማኝነት ያልተለወጠ ነው። የተገላቢጦሽ (reverse)
transfer ይፍጠሩ ወይም reason code `RETURN` ያለው Adjustment ይጠቀሙ።

**ጥ፦ ኮንትራታችን ሲያበቃ ምን ይከሰታል?**
ወዲያውኑ ምንም ነገር አይከሰትም። ከማብቂያ ቀን በፊት የ14-ቀን **Expiring**
ማስጠንቀቂያ ያገኛሉ፣ ከዚያ ከዛ በኋላ የ14-ቀን **Grace** ጊዜ — ሁለቱም ጊዜ ሙሉ
መዳረሻ አለ፣ banner ብቻ ጋር። ከዛ በኋላ ብቻ፣ አሁንም ካልታደሰ፣ workspace-ዎ
**Read-only** ይሆናል፦ አሁንም login ማድረግ፣ ሁሉንም ነገር ማየት እና export
ማድረግ ይችላሉ፣ ነገር ግን ምንም አዲስ transactions፣ approvals፣ edits ወይም
uploads የለም። ለሙሉ ደረጅ ሰንጠረዥ ከላይ ያለውን
[የኮንትራት ቀናት](#የኮንትራት-ቀናት)ን ይመልከቱ።

**ጥ፦ Renewal እንዴት እጠይቃለሁ?**
ከPlan tab-ዎ፣ በየትኛውም ጊዜ — workspace-ዎ ገና Read-only ሆኖ እያለ ጨምሮ
(ይህ እዛ አሁንም ከሚገኙት ጥቂት ድርጊቶች አንዱ ነው)። የSMART ቡድን ጥያቄዎን ያያል
እና ክፍያ ለማዋቀር ይከተላል፤ SMART ሲመዘግበው፣ ሙሉ መዳረሻ ወዲያውኑ ይመለሳል።

**ጥ፦ ለምን button ግራጫ (greyed out) ነው?**
ሶስት ሊሆኑ የሚችሉ ምክንያቶች፦ workspace-ዎ **Read-only** ነው (ኮንትራት
ጊዜው አልፎታል — ከላይ ይመልከቱ)፣ **plan limit** ደርሰዋል (ለምሳሌ SKU
cap-ዎ)፣ ወይም feature-ው **Coming soon** ተብሎ ምልክት ተደርጎበታል (ገና
አልተሰራም — [Known Limitations](#የታወቁ-ገደቦች--የወቅቱ-ቅጂ)ን ይመልከቱ)።
button-ው ላይ hover ያድርጉ — የትኛው እንደተፈጸመ ይነግርዎታል።

**ጥ፦ ፀድቆ ያለቀ Branch Exchange ልሰረዝ እችላለሁ?**
አይ — Branch Exchange Approved status ከደረሰ በኋላ መሰረዝ አይቻልም።
ሁለቱም warehouse managers አረጋግጠዋል እና ክምችት ለ transfer-ው ተይዟል።
Transfer-ው አካላዊ ለመፈጸም ካልቻለ፣ ለ destination receipt-ውን ያጠናቅቁ
እና ሚዛኑን ለማስተካከል stock Adjustment ይጠቀሙ (reason: RETURN ወይም
DAMAGE)። ለድጋፍ የአስተዳዳሪዎን ያግኙ።

**ጥ፦ password-ዬን ረስቼዋለሁ — በራሴ ድጋሚ ላስቀምጥ እችላለሁ?**
አዎ። በ sign-in ገፅ ላይ **Forgot password?**ን ይጫኑ እና የኢሜይል
አድራሻዎን ያስገቡ። አድራሻው ከመለያ ጋር ከተመሳሰለ፣ በኢሜይል reset link
ይቀበላሉ — ሊንኩ ለ60 ደቂቃ ተፈጻሚ ነው እና አንድ ጊዜ ብቻ ሊጠቀም ይችላል።
መክፈት አዲስ password እንዲያስቀምጡ ያስችልዎታል። ከተቀመጠ በኋላ፣ ሌሎች ነቅ
sessions-ዎ ሁሉ ይወጣሉ፣ እና በመለያዎ ላይ ያለ login lockout ወዲያውኑ
ይጸዳል። ኢሜይል ካልደረሰ፣ Tenant Administrator-ዎ ለእርስዎ ድጋሚ
ያስቀምጡልዎት ይጠይቁ (ቀጣዩን ጥያቄ ይመልከቱ)።

**ጥ፦ የተጠቃሚ password-ን እንዴት ድጋሚ ላስቀምጥ እችላለሁ?**
ወደ Settings → Personnel ይሂዱ። የተጠቃሚውን ረድፍ ይጫኑ ለ detail panel-ው
እንድ ይክፈት። "Reset Password"ን ይጫኑ እና ያረጋግጡ። የተጠቃሚው password
ወደ የሰጡት ጊዜያዊ credential ይቀየራል። በቀጣይ login-ቸው ላይ ለመቀየር ይገደዳሉ።
ይህ ደግሞ ተጠቃሚውን ከሁሉም ነባር sessions-ቸው ያወጣል። ለተረሱ passwords ወይም
የተያዘ መለያ ለመክፈት ይህን መጠቀም ይችላሉ።

**ጥ፦ ተጠቃሚ ተገድቦ ከቀረ ምን ይከሰታል?**
ከ5 ተከታይ ያልተሳካ login ሙከራዎች በኋላ፣ መለያው በራስ-ሰር ለ15 ደቂቃ ይገደባል።
ተጠቃሚው በ login screen ላይ መልዕክት ያያል። 15 ደቂቃ መጠበቅ እና ድጋሚ መሞከር
ይችላሉ፣ ወይም ትክክለኛ credentials እየተጠቀሙ መሆኑን ለማረጋገጥ እርስዎን (Tenant
Admin) ያግኙ። Lockout-ው በራስ-ሰር ይጸዳል — ምንም admin ድርጊት አያስፈልግም።
ተጠቃሚው password-ቸውን በተሳካ ሁኔታ ድጋሚ ካስቀመጡ፣ lockout counter-ውም
ወዲያውኑ ይጸዳል።

**ጥ፦ ለእያንዳንዱ warehouse ወይም region የተለየ adjustment rules መፍጠር
አለብኝ?**
አዎ። እያንዳንዱ adjustment rule ለተወሰነለት node ይተገብራል። ድርጅትዎ ብዙ
warehouses ወይም regions ካለው፣ ለእያንዳንዱ የተለየ rule መፍጠር አለብዎት።
ለ WHA1 የተቀመጠ rule ወደ WHA2 ወይም WHB1 በራስ-ሰር አይተገብርም። ሙሉ coverage
ለማረጋገጥ እያንዳንዱን node በስልት ይስሩ። ቀጣይ ዝማኔ በአንድ ደረጅ በተመሳሳይ org
level ላሉ nodes ሁሉ rules መተግበርን ያስችላል።

**ጥ፦ በመላው-ቴናንት LM እና node-የተመረቀ LM መካከል ያለው ልዩነት ምንድን ነው?**
Logistics Manager ሲፈጥሩ፣ ሁለት አማራጮች አለዎት። በመላው-ቴናንት LM
(ምንም position assignment ሳይኖር የተፈጠረ) በመላው ድርጅት ላይ የንባብ ታይነት
አለው — በሁሉም warehouses ላይ የሚከታተል ዋና logistics ተቀናጅ ላላቸው ጠቃሚ
ነው። Node-የተመረቀ LM ከአንድ node ላይ ላለ specific position የተያያዘ ነው
እና ያንን node እና ከዛ በታች ያሉትን nodes ሁሉ ያያል — አንድ warehouse እና
ተከታይ depots-ውን የሚከታተል logistics ተቀናጅ ላላቸው ጠቃሚ ነው። የ staff
member እውነተኛ ኦፐሬሽናል ወሰን ላይ ተመስርተው ይምረጡ።

---

**ጥ፦ ለ approver position ሁለተኛ ሰው ስመርቅ ምን ይከሰታል?**
ሲስተሙ ብዙ ተጠቃሚዎች በአንድ ጊዜ ተመሳሳይ position እንዲይዙ ይፈቅዳል። ነገር ግን፣
transfer ወይም adjustment ለ approval ወደ ያ position ሲላክ፣ ሲስተሙ
አንድ ያዢ ይመርቃል — በተለምዶ በቅርብ የተመረቀውን። ይህ ማለት ለ approver position
ሁለተኛ ሰው መጨመር approval tasks ወደ አዲሱ ያዢ ፈንታ ወደ ኋላ ሊሄድ ይችላል።
Approval routing ወደ ትክክል ያልሆነ ሰው የሚሄድ ከመሰለ፣ ያ position ምን
ያህል ነቅ ተጠቃሚዎች እንደያዘ ያረጋግጡ (Settings → Positions → view
holders)። ሁለቱም እውነት ተባብሮ-approvers ካልሆኑ፣ የታሰበው approver ብቻ
እንዲይዘው assignments ያስወግዱ ወይም ያስተካክሉ።

---

**ጥ፦ pending transfers ላይ approver የሆነን ተጠቃሚ ካቦዘንኩ ምን ይከሰታል?**
ተጠቃሚ ሲቦዝን፣ position assignment-ቸው በራስ-ሰር ይወገዳል። ሲስተሙ እስካሁን
በራስ-ሰር ማስጠንቀቂያ አይሰጥም — ወደ ያ ተጠቃሚ የተላኩ pending transfers
አሁንም ያ ተጠቃሚ approver መሆኑን ያሳያሉ፣ ስለዚህ "Pending Approval" ተብሎ
የተጣራ Transfers ራስዎ ማረጋገጥ አለብዎት። እንደTA በራስዎ ያልፈጠሩትን ማንኛውንም
transfer ማጽደቅ ወይም ማስተባበል ይችላሉ። Adjustments፦ መደበኛ adjustments
እንደ ልማድ በእርስዎ ሊጸድቁ ይችላሉ። Product approval minimum የተተገበረበት
adjustment ለተላከለት ልዩ ሰው ተዘግቷል፤ ያ ሰው ከተቦዘነ በማንም ሊጸድቅ አይችልም —
ያስተባብሉት፣ እና ፈጣሪው ድጋሚ እንዲያስገባ ይጠይቁት ነቅ approver ጋር እንዲሄድ።
position-ውን ድጋሚ መመርቅ ቀድሞ-የተላከ adjustment አይቀያይርም። Approver
ከማቦዝንዎ በፊት፣ routing ያልተቋረጠ እንዲቀጥል ሌላ ተጠቃሚ ለ position-ቸው
ይመርቁ።

---

**ጥ፦ Adjustment approval rules ማን ማጽደቅ እንዳለበት ሊገልጹ ይችላሉ?**
Adjustment approval rules quantity thresholds እና routing behaviour
ይገልጻሉ፣ ነገር ግን ሲስተሙ በመጨረሻ step ላይ የትኛው የተወሰነ named position
ማጽደቅ እንዳለበት አያስፈጻም — adjustment approval permission ያለው
ማንኛውም ተጠቃሚ pending adjustment ማስፈፈም ይችላል። ስለ ማን adjustments
እንደሚያጸድቅ ጥብቅ ቁጥጥር ካስፈለገዎት፣ ይህን በቴክኒክ ማስፈፊያ ላይ ከመመርኮዝ
ይልቅ ለ managers-ዎ እንደ ሂደት ፍላጎት ያስተላልፉ።

---

**ጥ፦ Logistics Manager (LM) በሲስተሙ ውስጥ በእውነት ምን ማድረግ ይችላል?**
LM logistics እና dispatch-ላይ-ያተኮረ role ነው — inventory operations
role አይደለም። LM ይችላል፦
- በተመረቀለት node እና ከዛ በታች ያሉ nodes ሁሉ ላይ ክምችት ማየት
- transfers ማየት እና መዘርዘር
- shipments መቀበል እና መላክ
- adjustments እና product information ማየት

LM አይችልም፦
- transfers መፍጠር ወይም ማስገባት
- adjustments መፍጠር ወይም ማስገባት
- transfers ወይም adjustments ማጽደቅ

ሰፋ ያለ ኦፐሬሽናል መዳረሻ (approvals, transfers መፍጠር) ያስፈልግዎት ከሆነ፣
Warehouse Manager (WM) ወይም Regional Manager (RM) role ይመርቁ።
ማስታወሻ፦ node assignment ሳይኖር ከተፈጠረ (በመላው-ቴናንት LM)፣ LM በመላው
ድርጅት ላይ ክምችት ማየት ይችላል ነገር ግን አሁንም ከላይ ያሉትን ድርጊት ገደቦች ይይዛል።

---

**ጥ፦ ሁሉም ተጠቃሚዎች PUSH (Send Stock) transfers ሊጀምሩ ይችላሉ?**
አይ። PUSH transfers የሚጀመረው በ org hierarchy-ዎ Level 1
(Factory/Main) እና Level 2 (Regional) ተጠቃሚዎች ብቻ ነው — በተለምዶ NM
እና RM roles። ይህ በ distribution ውስጥ ክምችት እንዴት እንደሚፈስ ያንጸባርቃል፦
ፋብሪካዎች እና regional hubs ክምችትን ወደ warehouses ይገፋሉ፣ በተቃራኒ
አይደለም።

Warehouse Managers (WM)፣ Logistics Managers (LM)፣ እና satellite
staff PULL (Request Stock) ወይም Sister (lateral exchange)
transfers ብቻ ሊጀምሩ ይችላሉ። WM ለ warehouse-ቸው ክምችት እንዲላክ ካስፈለገ፣
PULL request ማስገባት አለባቸው — NM ወይም RM-ቸው ያያል እና ያጸድቃል።

---

**ጥ፦ አዲስ satellite depot ጨመርኩ — approval rules በራስ-ሰር ይተገብራል?**
አይ። አዲስ node (warehouse ወይም satellite) ሲጨምሩ፣ እነሱን እስኪፈጥሩ ድረስ
ምንም transfer ወይም adjustment approval rules የለውም። rules እስኪጨመሩ
ድረስ፣ ከዛ node transfers ከታሰበው ፖሊሲ ጋር ላይስማማ የሚችል የሲስተሙን ነባሪ
bands ይከተላል። አዲስ node ከፈጠሩ በኋላ፣ ወደ Settings → Approval Rules
ይሂዱ እና ለዛ node staff መጠቀም ከመጀመራቸው በፊት ተገቢውን transfer እና
adjustment rules ይጨምሩ።

---

**ጥ፦ Staff member ተሹሞ ወደ ሌላ role ተዛውሯል። ምን ማድረግ አለብኝ?**
ተጠቃሚ ወደ አዲስ position ድጋሚ ሲመረቅ፦
1. በአዲሱ position ላይ PRIMARY ይመርቁ (ወሰናቸው በቀጣይ login ላይ ወዲያውኑ
   ይዘምናል)
2. ከዛ በኋላ መያዝ የለባቸውም ከሆነ የቀድሞ position assignment-ቸውን
   ያስወግዱ — force-remove ይጠቀሙ (ለ sole PRIMARY ማስወገድ SA token
   ያስፈልጋል)
3. የቀድሞ position pending approvals ተመርቆት ከነበረ፣ እነሱ በራስ-ሰር
   አይገፉም — "Pending Approval" ተብሎ የተጣራ Transfers/Adjustments
   ራስዎ ያረጋግጡ። Pending transfers እንደTA በቀጥታ ማጽደቅ ወይም ማስተባበል
   ይችላሉ። Pending adjustments ደግሞ እንደ ልማድ ሊጸድቁ ይችላሉ፣ ከ product
   approval minimum ያ adjustment-ን ለዛ ልዩ ሰው ካልዘጋው በስተቀር — በዛ
   ጊዜ በማንም ሊጸድቅ አይችልም እና መስተባበል አለበት፣ ፈጣሪው ድጋሚ እንዲያስገባ
   ይጠይቁት ነቅ approver ጋር እንዲሄድ። ምትኩን መጀመሪያ መምረቅ ከዛ በኋላ
   ለሚላክ ነገር ሁሉ ይህን ያስቀርታል።

ተጠቃሚው ወደ ከፍተኛ level ከተዛወረ (ለምሳሌ WM → RM)፣ የቀድሞ WM ወሰናቸው
በቀጣይ login ላይ በአዲሱ RM ወሰን ይተካል። ወደ ዝቅተኛ level ከተዛወሩ (ለምሳሌ
RM → WM)፣ መዳረሻቸው በዛው መጠን ይጠባል። ከ position ለውጥ በኋላ ሁልጊዜ
ተጠቃሚው logout እና ድጋሚ login በማድረግ ያረጋግጡ።

---

## የማዋቀር Checklist

### 🔒 Tenant Administrator Checklist

**መለያ እና ፕላን፦**
- [ ] የኢሜይል አድራሻ ተረጋግጧል (self sign-up)
- [ ] Settings → Tenant Admin → Plan ተገምግሟል — ጥቅል፣ ገደቦች እና
  features እንደ ተጠበቀው ነው
- [ ] የድርጅት profile እና contact ሰዎች ተጠናቅቀዋል (Profile እና Contact
  tabs)
- [ ] የመጀመሪያ invoice ተገምግሟል እና ክፍያ ተዋቅሯል (ከወጣ)

**የድርጅት Structure፦**
- [ ] Organisation levels ተገልጸዋል
- [ ] Organisation tree ተጠናቅቋል — ሁሉም nodes ተፈጥረዋል
- [ ] ለእያንዳንዱ node positions ተፈጥረዋል (main + assistant የተመከረ)
- [ ] Transfer types በcustom display names ተሰይመዋል
- [ ] ለሁሉም ነቅ types Transfer approval rules ተዋቅረዋል
- [ ] Adjustment approval rules ተዋቅረዋል
- [ ] በ role level Self-approval limits ተቀምጠዋል

**ሰዎች እና Products፦**
- [ ] ሁሉም staff ተጨምረዋል እና ወደ positions ተመርቀዋል
- [ ] የመጀመሪያ passwords ደህንነት ባለው መንገድ ተጋርተዋል
- [ ] Product categories ተፈጥረዋል
- [ ] ሁሉም products በ type codes እና units ተጨምረዋል
- [ ] Controlled products በ🔒 approval rules ተዋቅረዋል
- [ ] Product images ተጭነዋል (አማራጭ)
- [ ] ለሁሉም warehouse nodes Opening stock ተመዝግቧል

**ማረጋገጫ፦**
- [ ] Approval Policies ገፅ ተገምግሟል — rules በትክክል ይታያሉ
- [ ] Test transfer ተፈጥሮ በሙሉ lifecycle ተጸድቋል
- [ ] ቢያንስ አንድ WM, RM, እና NM ተጠቃሚ መዳረሻ ተረጋግጧል
- [ ] Branding ተጭኗል (አማራጭ)
- [ ] Audit Log ተረጋግጧል — የማዋቀር ድርጊቶች ተመዝግበዋል

---

> **📋 ከመጀመር በፊት ማስታወሻ፦** ከደንበኞች ጋር ከማጋራትዎ በፊት፣ ሁሉንም
> screenshot placeholders በእውነተኛ screenshots ይተኩ። ለኢትዮጲያ
> ደንበኞች ካስፈለገ ወደ አማርኛ ወይም ኦሮምኛ ይተርጉሙ። ሁሉንም TA-ብቻ ክፍሎች ከ
> መጨረሻው permission matrix ጋር ይገምግሙ።

---

*የሰነድ ቅጂ፦ 1.6 | መጨረሻ የተዘመነ፦ ጥቅምት 2026 | የተያዘው በ፦ Development team*
*1.5 (2026-10-10) — የኮንትራት ደረጆች ተጨምረዋል (Active/Expiring/Grace/
Read-only)፣ read-only access gate፣ renewal እንዴት እንደሚጠየቅ፣ እና ለ
bulk CSV import, dispatch strategy እና stock-count submission
Coming soon status።*
*1.5 — ወደ ሁለት ክፍሎች ተከፍሏል፦ Getting Started (ከ sign-up በፊት) አሁን
የራሱ ሰነድ ነው፤ ይህ መመሪያ ክፍል 2 ነው፣ ከPlan Tiers ጀምሮ workspace
setup-ን ይሸፍናል።*
*1.3 — annual billing ላይ pro-rated upgrades እና add-ons፤ ጥቅል
ለውጦች የሚፈጸመው በSMART ብቻ ነው።*
*1.2 — self sign-up, email verification, ከዋጋ እና VAT ያላቸው ጥቅሎች,
subscription እና invoices, read-only contract.*
