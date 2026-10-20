<!-- Machine translation from session 2026-10-19, pending native-speaker review. Source: frontend/public/help/ta-onboarding-guide.md @ 2570460 -->
# SMART Inventory — Qajeelfama Onboarding TA

**Sadarkaa:** 1.7 | **Haaromfame:** October 2026 | **Dhaggeeffattoota:** Tenant Administrators fi Organisation Managers

**Jijjiirama v1.7:** Sadarkaa 1 (Sadarkaalee Dhaabbataa) fi Sadarkaa 2 (Muka Dhaabbataa) amma sadarkaa
duraan-olkaa'ame ykn bakka jiru irratti "Kuusaa qabata" jijjiiruu fi wanti jijjiirama kana danqu
ni dabalatu.

**Jijjiirama v1.6:** Sadarkaa 1 (Sadarkaalee Dhaabbataa) fi gaaffii "Sadarkaalee dhaabbataa booda jijjiiruu
nan danda'aa?" FAQ amma erga qusannoo jalqabaa booda sadarkaa gadii jala dabaluu ykn duwwaa yoo ta'e
balleessuu danda'uu ni calaqqisiisu.

**Kutaa 2 kan 2 — Bakka hojii kee qindeessuu.** Haaraa dhaa? [Jalqaba](GETTING_STARTED.md) (Kutaa 1)
dursa dubbisi — osoo hin jalqabin, herrega kee argachuu, imeelii kee mirkaneessuu, seensa, gaheewwan
sirna, tartiiba qindaa'inaa, fi sadarkaalee karooraa hundi achi jiru.

> **Yaadannoo Dura:** Maddoota `[SCREENSHOT PLACEHOLDER]` hunda suuraalee dhugaa dhaan osoo maamiltootaaf hin qoodin dura bakka buusi.

---

## Qajeelfama Kana Akkamitti Fayyadamuu

Qajeelfamni kun dhaggeeffattoota lama ni ilaala:

| Dhaggeeffattoota | Kutaalee |
|----------|----------|
| **Fayyadamtoota Hundaa** (NM, RM, WM, LM, AU) | Sadarkaa 7–8, Yaadannoo Saffisaa NM, Gaaffii Baratamoo |
| **🔒 Tenant Administrator (TA) Qofa** | Sadarkaa 1–6, 9, Bulchiinsa Fayyadamaa, Jijjiirama Seera Mirkaneessaa |

> **Kutaalee TA-qofa** mallattoo 🔒 qajeelfama kana guutuu keessatti qabu.

**Yeroo qindaa'inaaf tilmaamame:** daqiiqaa 45–90 qindaa'ina jalqabaaf.

### Gaheewwan Dhaabbata Keetiin Akkamitti Walitti Dhufan

**Bakka Hojii** (Sadarkaa 3) yeroo uumtu, kodii gahee SMART dursaan ibsame keessaa tokko ni ramaddi
(tarree guutuuf [Jalqaba → Gaheewwan Sirna](GETTING_STARTED.md#system-roles-summary) ilaali):

- **L1 nodes** (sadarkaa olaanaa, fakkeenyaaf Main Factory) → bakkeewwan hojii **NM** ramaddi
- **L2 nodes** (fakkeenyaaf Regional Center) → bakkeewwan hojii **RM** ramaddi
- **L3 nodes** (fakkeenyaaf Sub Region) → bakkeewwan hojii **RM** ramaddi
- **L4 nodes** (fakkeenyaaf Warehouse Area, kuusaa qabatu) → bakkeewwan hojii **WM** ramaddi
- Bakkeewwan hojii **LM** **sadarkaa node kamiyyuu** irratti uumamuu danda'u — LM sana booda
  node sana qofaaf daangeffama
- **Dhaabbata guutuu** (node tokkotti hin hidhamne) → bakkeewwan hojii **AU**, fi herregoota
  **LM** bakka hojii malee uumaman

> **Yaadannoo:** Gaheen TA herrega bulchaa kee qofa. Hojjettoota baratamaaf bakka hojii TA hin uumtu. NM gaheen olaanaa hojjettoonni kee hojii ooliif fayyadaman.

---

## Sadarkaalee Karooraa (Packages)

Bakki hojii SMART karoora sadii keessaa tokko irratti jira: **Starter**, **Growth**, ykn **Enterprise**.
Karoora yeroo galmooftu filatta, ykn bulchaan SMART kee yeroo si galmeessu filata. Karoora booda
**jijjiiruuf**, bulchaa SMART kee qunnami — mana keessaa ofii kee jijjiiruu hin dandeessu.

Karoorri tokkoon tokkoon daangaa kee fi amaloota dabalataman murteessa. Durii baratamaa:

| | Starter | Growth | Enterprise |
|---|---|---|---|
| Kuusaalee / nodes dhaabbataa | 3 | 10 | Daangaa hin qabu |
| Herregoota hojjettootaa | 5 | 25 | Daangaa hin qabu |
| Meeshaalee (SKUs) | 500 | 1,500 | Daangaa hin qabu |
| Bulchiinsa Kuusaa Bu'uuraa | ✓ | ✓ | ✓ |
| Dabarsaalee Pull fi Push | ✓ | ✓ | ✓ |
| Hordoffii Koora fi Gurmuu | ✓ | ✓ | ✓ |
| Dabarsaalee Sister (Branch Exchange) | — | ✓ | ✓ |
| Lojistiksii fi Bulchiinsa Konkolaataa | — | ✓ | ✓ |
| Baafata Galmee Dhageettii | — | ✓ | ✓ |
| Mallattoo Dhuunfaa | — | ✓ | ✓ |
| Tilmaama AI fi Xiinxala | — | — | ✓ |
| Seensa API | — | — | ✓ |

> **Lakkoofsonni armaan olii durii dha, ni haaromfamuu danda'u.** Fuulli galmee yeroo hunda
> qabiyyee fi gatii karooraa ammaa ni argisiisa, **Qindaa'ina → Bulchaa Dhaabbataa → Plan** immoo
> daangaa fi amaloota *bakka hojii keetiif* murtaa'an sirriitti ni argisiisa. Karoorri yeroo
> yerootti ni haaromfama; haaromsa tokko galmee haaraa fi jijjiirama karooraa irratti hojiirra
> oola, bakka hojii jiru daangaa isaa ofumaan hin jijjiirru.

**Herregni TA bilisa.** Herregni TA kee mataa kee daangaa herrega-hojjettootaa keessa hin lakkaa'amu.
**Kuusaaleen = bakkeewwan kuusaa qabatan; bakkeewwan mirkaneessaa-qofa bilisa dha** — node
dhaabbataa tokko kuusaa yoo qabate qofa (`is_stock_holding = true`) daangaa kuusaa keessa lakkaa'ama.

**Gatiwwan.** Karoorri tokkoon tokkoon gatii ji'aa fi waggaa qaba. Gatiwwan Taaksii dura mul'atu,
**Taaksii %15** fi waliigalli adda ba'anii argamu. Jijjiiramni gatii **haaromsa itti aanu** irratti
hojiirra oola; invoisii duraan argattee hin jijjiiru.

**Karoora jijjiiruu.** Jijjiiramni karooraa bulchaa SMART kee tiin hojjetama. Daangaa fi amaloonni
haaraan **yeroma sanatti** hojiirra oolu, gatiin haaraan immoo **invoisii itti aanu** irraa kaffalama.

- **Kaffaltii ji'aa:** ji'a ammaa hafee irratti kaffaltii dabalataa hin jiru.
- **Kaffaltii waggaa — guddina:** ji'a hafte guddifte keessatti kaffaltiin hin jiru. Ji'oota guutuu
  waggaa ammaa keessa hafan irratti, **garaagarummaa** gatii waggaa haaraa fi durii gidduu jiru,
  ji'aan madaalame, Taaksii waliin invoisii argatta.
  *Fakkeenya:* Starter 1,000 → Growth 2,000 ji'a guutuu 7 hafee waliin:
  (2,000 − 1,000) × 7 ÷ 12 = 583.33 + 87.50 Taaksii = **670.83 ETB**.
- **Xiqqeessuu:** daangaan gadii yeroma sanatti hojiirra oola. Yeroo ammaa kanaaf **deebii ykn
  kireeditii hin jiru**; gatiin gadii invoisii itti aanu irraa hojiirra oola.

Invoisii guddina kun tarree invoisii kee keessatti **Proration** jedhamee ibsama. Kaffaluun kun
waliigaltee ykn guyyaa kaffaltii kee hin jijjiiru.

**Add-ons.** Amala karoora kee keessa hin jirre (fakkeenyaaf Seensa API) bulchaa SMART kee tiin
ofiisaa dabalamuu danda'a. Yeroma sanatti hojjeta, invoisii itti aanu irraa kaasee karoora kee
waliin kaffalama. Kaffaltii **waggaa** irratti ji'oota guutuu hafan irratti gatii waggaa add-on
sanaan (ji'aan madaalame, Taaksii waliin) invoisii **Proration** argatta; ji'a ammaa hafee bilisa.
Add-on haquun yeroma sanatti dhaaba, deebiin hin jiru.

> Invoisiin idilee kaffaltii eegaa yeroo jiru, jijjiiramni karoora fi add-on hamma kaffalamutti
> ykn haqamuttii dhaabbata, kanaafuu invoisiin gatii dogoggoraan baafamee hin beeku.

> **Dabarsaalee Branch Exchange (Sister) — daangaa sadarkaa Starter:** Dabarsaaleen karaa gama
> gidduu kuusaalee sadarkaa tokko qaban sadarkaa Starter irratti hin argamne. Hojjettoonni tokko
> uumuu yoo yaalan dogoggora daangaa-karooraa argatu. Amalli kun yoo barbaachise, Growth ykn
> Enterprise ti guddina ilaalchisee bulchaa SMART kee qunnami.

> **Qindaa'ina keessatti daangaa gahuu:** Kuusaa (Sadarkaa 2), herrega hojjettootaa (Sadarkaa 4)
> ykn meeshaa (Sadarkaa 7) dabaluuf yaaluu keessatti dogoggora yoo argatte, daangaa karoora kee
> gaheera jechuu dha. Balaa akka ta'e yaaduu mannaa, guddina sadarkaa gaafachuuf bulchaa SMART
> kee qunnami.

---

## 🔒 Karoora, Galmee fi Invoisii Kee (TA Qofa)

*Qindaa'ina → Bulchaa Dhaabbataa*

Fuulli Bulchaa Dhaabbataa taabii shan qaba:

| Taabii | Maal gochuu dandeessa |
|-----|-----------------|
| **Profile** | Ibsa dhaabbata kee ilaali fi haaromsi |
| **Plan** | Karoora kee, daangaa, amaloota, galmee fi invoisii ilaali |
| **Contract** | Guyyaa jalqabaa fi dhumaa waliigaltee kee ilaali (ilaaluu-qofa) |
| **Contact** | Namoota qunnamtii dhaabbata kee bulchi |
| **Features** | Amaloota karoorri kee dabalatu ilaali |

### Haala Galmee

Taabiin **Plan** galmee kee ni argisiisa — karoora, yeroo kaffaltii, yeroo ammaa fi hamma Taaksii
dabalatee — haala kanneen keessaa tokko waliin:

| Haala | Hiikaa |
|--------|---------|
| **Kaffaltii eeggataa** | Bakki hojii kee guutummaatti ni hojjeta. Invoisiin kee jalqabaa amma kaffalame hin jiru. |
| **Hojjechaa** | Yeroon kee ammaa kaffalameera. |
| **Yeroon dabre** | Haaromsi tokko tureera. Furuuf SMART qunnami. |
| **Haqame** | Galmeen xumurameera. |

> **Sadarkaa ammaa:** invoisiin hin kaffalamne ofumaan bakka hojii kee hin daangessu ykn hin dhaabu.
> Kan daangessu **guyyaa dhumaa waliigaltee** kee osoo hin haaromfamin darbuu dha — gaditti
> [Guyyoota waliigaltee](#contract-dates) fi [Yeroo waliigalteen keenya dhumu maaltu ta'a?](#common-questions)
> ilaali.

### Invoisii fi Akkamitti Kaffaluu

SMART invoisii kee siif erga; taabii Plan irratti tarree **Invoices** keessatti yeroo, waliigala
Taaksii dura, Taaksii, waliigala fi haala (Pending, Paid, Failed, Cancelled) waliin mul'ata.

Invoisii **Pending** ta'eef, odeeffannoo kaffaltii argachuuf **How to pay** cuqaasi.

`[PAYMENT INSTRUCTIONS PLACEHOLDER — bank name, account name and number, reference to quote, and where to send the receipt. To be supplied before go-live.]`

SMART kaffaltii kee yeroo mirkaneessu, invoisiin **Paid** ta'a, galmeen kee **Active** ta'a,
**guyyaan dhumaa waliigaltee** kee immoo gara dhuma yeroo kaffalamee sanatti fuula dura deema.

### Guyyoota Waliigaltee

Waliigalteen kee guyyaa galmee (ykn onboarding) kee irraa eegalee yeroo kaffaltii tokkoof hojjeta,
kaffaltiin yeroo mirkanaa'u hundaan ni dheeraata. Taabiin Contract **ilaaluu-qofa** dha; guyyoonni
waliigaltee SMART tiin bulfamu. Jijjiiruuf SMART qunnami.

Bakki hojii kee guyyaan dhumaa waliigaltee kee dhihaachaa fi darbaa jiru keessa sadarkaa afran
keessa dabra:

| Sadarkaa | Yoom | Maal gochuu dandeessa |
|-------|------|------------------|
| **Active** | Guyyaa dhumaa waliigaltee kee irraa guyyaa 14 ol dura | Waan hundaa, akkuma baratame |
| **Expiring** | Guyyaa dhumaa waliigaltee kee irraa guyyaa 14 ykn gadi dura | Waan hundaa, akkuma baratame — mallattoo akeekkachiisaa waliin |
| **Grace** | Guyyaa dhumaa waliigaltee kee booda hamma guyyaa 14 | Waan hundaa, akkuma baratame — mallattoo waliin |
| **Read-only** | Guyyaa dhumaa waliigaltee kee booda guyyaa 14 ol | Ilaaluu fi baasuu qofa — gaditti ilaali |

**Read-only** gabbarraa haaraa, mirkaneessaa, gulaalaa ykn fe'aa hunda dhaaba. Ammas: seenuu,
daataa kee ilaaluu fi baasuu, jecha darbii kee mataa kee jijjiiruu, haaromsa waliigaltee fudhachuu,
qunnamtoota kee bulchuu, jecha darbii hojjetaa tokkoo deebisuu, fi herrega hojjetaa dhaabuu ni
dandeessa. Wanti kaan hundi hamma SMART haaromsa kee galmeessutti ni daangeffama — gaditti
[Akkamitti haaromsa gaafachuu danda'a?](#common-questions) ilaali. Read-only ta'uun kee **dhaabuu**
irraa adda; kun kan ta'u SMART ganamaan bakka hojii kee yoo dhaabe qofa (nama SMART kee qunnami) —
waliigalteen yeroon isaa darbe qofti si hin dhaabu.

---

## 🔒 Sadarkaa 1 — Sadarkaalee Dhaabbataa (TA Qofa)

*Org Setup → taabii Organisation Levels*

Dhaabbata kee sadarkaa meeqa akka qabu fi sadarkaa tokkoon tokkoon maal akka jedhamu ibsi.

1. Gara Org Setup deemii → "Organisation Levels" cuqaasi
2. Lakkoofsa sadarkaalee galchi (yeroo baay'ee 3–5)
3. Sadarkaa tokkoon tokkoon afaan salphaan mogaasi
4. Sadarkaa gadii **Stock Holding** jedhu — kun iddoo kuusaan dhugaan itti hordofamuu dha
5. Qusadhu

**Erga qusattee booda**, sadarkaa amma gadii hafte jalatti dabaluu, ykn sadarkaa gadii nodes
dhaabbataa hin qabaannee yoo ta'e balleessuu dandeessa. Giddu gala stack irratti sadarkaa dabaluu
ykn balleessuun ofii-tajaajila miti — kanaaf gargaarsa SMART qunnami.

**Sadarkaa qusatame irratti "Kuusaa qabata" jijjiiruu:** banuun yeroo hunda ni eyyamama — bakkeewwan
amma sadarkaa sana keessa jiran akkuma turan ni turu; kuusaa qabachuu kan qaban yoo ta'e tokkoon
tokkoon booda jijjiiri. Cufuun kan eyyamamu sadarkaa sana keessa bakki hojjetaa tokko iyyuu kuusaa
yoo hin qabanne dha — yoo qaban, bakka hojii-mirkaneessaa-qofaatti jijjiiruuf kan jalqabaa
sitti argama.

Fakkeenya caaseffama sadarkaa 4:

| Sadarkaa | Maqaa Fakkeenyaa | Yaadannoo |
|-------|-------------|-------|
| L1 | Main Factory | Olaantummaa caaseffamaa |
| L2 | Regional Center | Giddugaleewwan naannoo |
| L3 | Sub Region | Sadarkaa giddu-galeessaa filannoo |
| L4 ★ | Warehouse Area | ★ Stock Holding jedhu |

`[SCREENSHOT: Organisation Levels tab showing 4 levels configured]`

---

## 🔒 Sadarkaa 2 — Muka Dhaabbataa (TA Qofa)

*Org Setup → taabii Organisation Tree*

Sadarkaalee Sadarkaa 1 fayyadamuun nodes dhugaa (warshaalee, waajjiraalee, kuusaalee) uumi.

1. "+ Add Node" cuqaasii node sadarkaa-olaanaa irraa jalqabi (fakkeenyaaf "Factory A")
2. Sadarkaa (L1) filadhuu maqaa galchi
3. Nodes ijoollee dabali — dura abbaa filadhu, ergasii ijoollee dabali
4. Caaseffama dhaabbata kee guutuun sirna keessa hamma galutti irra deebi'i

**Gorsa:**
- Damee hundi fageenya tokko qabaachuu hin barbaachisu (caaseffamoonni fageenya adda addaa ni
  jiraatu)
- Maqaalee wal fakkaatan, ofiisawaa fayyadami — gabaasaalee fi galmeewwan dhageettii keessatti
  mul'atu
- Dhaabbanni kee guddachaa jiru booda nodes dabalataa dabaluu dandeessa
- Node uumuun daangaa kuusaa sadarkaa karoora kee ti qajeelfama — node dabaluuf yaaluu keessatti
  dogoggora yoo argatte, balaa akka ta'e yaaduu mannaa dandeettii dabalataaf bulchaa SMART kee
  qunnami (ilaali [Sadarkaalee Karooraa](#plan-tiers))
- Qindaa'ina "Kuusaa qabata" bakka jiru tokko fooramii gulaalaa isaa irraa jijjiiruu dandeessa.
  Cufuun kun bakki sun dabarsaalee banaa, sirreeffamoota eeggataa, ykn kuusaa harkaa yoo qabaate
  ni dhorkama — duraan dursa kana qulqulleessii, ergasii jijjiiri. Switch kun ofumaan ni cufama
  sadarkaan isaa mirkaneessaa-qofa yoo ta'e; dursa sadarkaa sanaaf "Kuusaa qabata" bani
  (Sadarkaa 1).

`[SCREENSHOT: Organisation Tree showing two-factory structure]`

---

## 🔒 Sadarkaa 3 — Bakkeewwan Hojii (TA Qofa)

*Org Setup → taabii Positions*

Bakkeewwan hojii namoota nodes waliin walqunnamsiisanii waan gochuu danda'an murteessu.

1. Node tokkoon tokkoof yoo xiqqaate bakka hojii tokko guddaa uumi
2. Kan gorfamu: hojii dabalataaf bakka hojii gargaaraa dabali
3. Mataduree qindaa'i (beeksisaalee mirkaneessaa fi galmee dhageettii keessatti mul'ata)
4. Sadarkaa gahee filadhu: **NM** (olaanaa), **RM** (giddu-galeessaa), **WM** (kuusaa)

**Fakkeenyoota:**

| Node | Bakka Hojii Guddaa | Gargaaraa |
|------|--------------|-----------|
| Factory A (L1) | "HQ Director (NM)" | "Deputy HQ (Asst NM)" |
| Region A (L2) | "Region A Manager (RM)" | "Region A Deputy (Asst RM)" |
| WHA1 (L4) | "WHA1 Warehouse Manager (WM)" | "WHA1 Warehouse Assistant (WM)" |

💡 **Gorsa:** Maqaaleen bakka hojii sirna guutuu keessatti mul'atu — maqaa ofiisawaa, beekamaa
fayyadami.

`[SCREENSHOT: Positions tab showing positions for Factory A and Warehouse nodes]`

---

## 🔒 Sadarkaa 4 — Hojjettoota (Fayyadamtoota Dabaluu) (TA Qofa)

*Org Setup → taabii Personnel*

1. "+ Add Person" cuqaasii maqaa fi imeelii galchi
2. Gahee sirna isaanii filadhu (NM / RM / WM / LM / AU)
3. Gara bakka hojii ramadi (gara node dhaabbataa isaanii walqunnamsiisa)
4. Jecha darbii jalqabaa qindaa'i (seensa jalqabaa irratti jijjiiruuf gaafatamu)
5. Hojjettoota hundaaf irra deebi'i

**Yaada qabiyyee imeelii:** `role_locationname@yourcompany.com`
- Fakkeenya: `wm_warehouse1@company.com`
- Fakkeenya: `rm_region_a@company.com`

👥 **Yaadannoo:** Namni tokko bakka hojii hedduutti ramadamuu danda'a — hayyamni isaanii bakka
hojii ramadame hundaa walitti qabama.

> **Daangaa herrega hojjettootaa:** Herregoota dabaluun daangaa fayyadamaa sadarkaa karoora kee
> ti qajeelfama. Nama haaraa dabaluuf yaaluu keessatti dogoggora yoo argatte, daangaa karoora
> kee gaheerta — balaa akka ta'e yaaduu mannaa guddina gaafachuuf bulchaa SMART kee qunnami
> (ilaali [Sadarkaalee Karooraa](#plan-tiers)).

`[SCREENSHOT: Personnel tab showing user list with positions assigned]`

---

## 🔒 Sadarkaa 5 — Gosoota Dabarsaa (TA Qofa)

*Org Setup → taabii Transfer Types*

Maqaalee argisiisa gosoota dabarsaa sadanii ofiisawaa godhi.

| Kodii Sirna | Maqaa Durii | Hiikaa |
|------------|-------------|---------------|
| PULL | Request Stock | Kuusaan sadarkaa olaanaa irraa gaafata |
| PUSH | Send Stock | Sadarkaan olaanaa kuusaa gadi dhiibu |
| SISTER | Branch Exchange | Dabarsaa karaa gama gidduu kuusaalee — **sadarkaa Growth ykn ol
  barbaachisa**; Starter irratti hin argamu |

Gosa dabarsaa tokkoon tokkoof:
1. Maqaa argisiisu filatamaa dhaabbata kee galchi
2. Ibsa dabali (filannoo)
3. Sadarkaalee kami akka jalqabuu danda'an qindaa'i
4. Active/Inactive jijjiiri

`[SCREENSHOT: Transfer Types tab with custom display names]`

---

## 🔒 Sadarkaa 6 — Seerota Mirkaneessaa (TA Qofa)

*Org Setup → taabii Approval Rules*

### Seerota Mirkaneessaa Dabarsaa

Gosa dabarsaa tokkoon tokkoof, seerota kanneen ibsan uumi:
- **Sadarkaa irraa → Sadarkaatti** (karaan seerri kun ilaalu)
- **Hamma baay'inaa** (0 irraa hamma daangaa hin qabneetti, ykn hamma murtaa'e)
- **Tartiiba mirkaneessaa** (eenyu mirkaneessa, akkamiin, sa'aatii meeqa keessatti)

> **Fakkeenya:** Request Stock | Warehouse Area → Sub Region | Baay'ina: 5,001+ yuunitii |
> Sadarkaa 1: Sub Region Manager (sa'aatii 24) | Sadarkaa 2: Regional Manager (sa'aatii 48)

`[SCREENSHOT: Transfer Rules showing multi-step rule configuration]`

### Seerota Mirkaneessaa Sirreeffamaa

Sirreeffamoonni kuusaa sadarkaa gahee tokkoon tokkoof hamma baay'inaan mirkaneessuu akka
barbaadan ibsi.

### Daangaa Ofiin-Mirkaneessuu

Gahee tokkoon tokkoof hamma ofiin-mirkaneessuu waliigalaa qindaa'i — dabarsaaleen daangaa kana
gadi ofumaan ni mirkanaa'u:

| Gahee | Fakkeenya Daangaa |
|------|--------------|
| Warehouse Manager (WM) | Hamma yuunitii 5,000 — yeroma sanatti ofumaan mirkanaa'a |
| Regional Manager (RM) | Hamma yuunitii 20,000 — yeroma sanatti ofumaan mirkanaa'a |
| Factory Manager (NM) | Daangaa hin qabu — dabarsaaleen hundi ofumaan mirkanaa'u |

💡 **Gorsa:** Seerota qusattee booda, cuunfaa afaan-salphaa argachuuf fuula **Approval Policies**
ilaali.

---

## Sadarkaa 7 — Meeshaalee fi Gosoota

*Fuula Meeshaalee — TA fi NM meeshaalee uumuu danda'u; gaheen hundi ilaaluu danda'a*

### 🔒 Gosoota Meeshaa Uumuu (TA Qofa)

1. Gara Products → Categories deemi
2. "+ Add Category" cuqaasii maqaa galchi (fakkeenyaaf "Raw Materials", "Finished Goods")
3. Meeshaalee dabaluu dura gosoota hundaa uumi

### Meeshaalee Dabaluu (TA fi NM)

1. Gara Products deemi → "+ Add Product" cuqaasi
2. Maqaa meeshaa, SKU (ykn ofumaan uumi), fi gosa filadhu
3. **Type Code** galchi — qubee 2–10 (fakkeenyaaf RAW, FIN, PKG)
4. Safartuu filadhu (KG, Piece, Box, Roll, kkf)
5. Suuraa meeshaa fe'i (filannoo, hamma 2MB, JPG/PNG/WebP)
6. Save cuqaasi

`[SCREENSHOT: Add Product panel with all fields filled]`

### 🔒 Meeshaalee To'annaa Jala Jiran — Seerota Mirkaneessaa Addaa (TA Qofa)

Meeshaalee gatii olaanaa ykn tasgabbii barbaadaniif yeroo hunda baay'ina osoo hin ilaalin
mirkaneessuu barbaadaniif:

1. Dursa meeshaa uumi, ergasii gulaaluuf bani
2. Gara kutaa "Minimum Approval Level" scroll godhi
3. Gosoota dabarsaa walfakkaataniif override banii
4. Filadhu: **Yeroo hundaa** mirkaneessuu barbaachisa, YKn **hamma murtaa'e ol**
5. Bakki hojii kami mirkaneessuu akka qabu filadhu
6. Save godhi — mallattoon 🔒 meeshaa irratti ni mul'ata

> **Barbaachisaa — meeshaaleen to'annaa jala jiran walqunnamtii mirkaneessaa lama dabarsaa
> tokkoof barbaadu:**
> Bulchaan kuusaa meeshaa to'annaa jala jiruuf PULL yeroo uumu, dabarsaan sun sadarkaa
> ilaalchisaa idilee hin darbu. Fiilmichi guutuun:
> DRAFT → Pending Review → (ilaalaan fuula dura) → Pending Approval → (mirkaneessaan override
> mirkaneessa) → Approved
>
> Kun hiika hojiin kun dabarsaa idilee irraa yeroo dheeraa fudhata jechuu dha. Kana bulchitoota
> kuusaa keetiif himi akka dursa karoorfatan — keessattuu sochii kuusaa yeroo-tiin walqabatu.

---

## Sadarkaa 8 — Kuusaa Jalqabaa

*Fuula Kuusaa → Receive Stock — NM fi TA kuusaa jalqabaa galchuu danda'u*

Hojiirra osoo hin galin dura, kuusaa kuusaa tokkoon tokkoo keessa jiru galmeessi.

1. Gara fuula Inventory deemi
2. Kuusaa filadhu
3. "Receive Stock" cuqaasi
4. Meeshaa filadhuu baay'ina jalqabaa galchi
5. Yaadannoo dabali (fakkeenyaaf "Opening balance — June 2026")
6. Submit godhi — kuusaan yeroma sanatti galmeetti dabalama
7. Meeshaa tokkoon tokkoof kuusaa tokkoon tokkoo keessatti irra deebi'i

**⚠️ Barbaachisaa:** Galmeewwan kuusaa jalqabaa yeroo hundaaf dha, hin haqamuu danda'an (galmeen
kakuu sababa hordoffiif hin jijjiiramne). Dogoggora sirreessuuf koodii sababa `COUNT_CORRECTION`
qabu Adjustments fayyadami.

`[SCREENSHOT: Receive Stock panel with product and quantity fields]`

---

## 🔒 Sadarkaa 9 — Mallattoo (Filannoo, TA Qofa)

*Org Setup → taabii Branding*

| Meeshaa | Ulaagaa |
|------|-------|
| Mallattoo Dhaabbataa | Hamma 1MB, JPG/PNG/WebP. Mataduree navigation keessatti mul'ata. |
| Bannerii Dhaabbataa | Hamma 3MB, JPG/PNG/WebP. Dashboard irratti mul'ata. |

1. Gara Org Setup → taabii Branding deemi
2. Mallattoo fi bannerii fe'i
3. Save godhi — yeroma sanatti bal'inaan platform keessatti mul'ata

`[SCREENSHOT: Branding tab with logo and banner upload]`

---

## Organisation Manager (NM) — Yaadannoo Saffisaa

*Kutaan kun Organisation Managers fi hojjettoota hojii oolif ti.*

### Itti Gaafatamummaa Kee
- Meeshaalee uumuu fi bulchuu
- Dabarsaalee ilaaluu fi mirkaneessuu
- Dabarsaalee Send Stock (PUSH) jalqabuu
- Sadarkaalee kuusaa hordofuu
- Imaammata mirkaneessaa ilaaluu

### Dabarsaalee Mirkaneessuu

1. Gara fuula Transfers deemi
2. Dabarsaalee haala "Pending Review" ykn "Pending Approval" qaban argadhu
3. Bal'ina ilaalaa (meeshaa, baay'ina, madda, galtee)
4. **Review** ergasii **Approve** cuqaasi — ykn sirrii yoo hin ta'in **Reject**

### Kuusaa Baasuu fi Ergamuu

1. Fuula Transfers irratti dabarsaa Approved ta'e argadhu
2. Kuusaan sochoo'uuf qophaa'e mirkaneessuuf **Issue** cuqaasi
3. Maddaa irraa ba'uu mirkaneessuuf **Dispatch** cuqaasi
4. WM galtee ergasii ni fudhata

> **Bakka Namaa Hojjechuu:** Dabarsaa kuusaan maddaa dhaabbata biraa ta'e Issue/Dispatch yoo
> goote, sirni "Acting on behalf of: [Warehouse Name]" argisiisa, galmee dhageettii keessattis
> kana ni galmeessa.

### Imaammata Mirkaneessaa Ilaaluu

Ilaaluuf navigation keessa **Approval Policies** deemi:
- Daangaalee ofiin-mirkaneessuu kee gosa raawwii tokkoon tokkoof
- Meeshaalee 🔒 barbaachisummaa mirkaneessaa addaa qaban
- Maatriksii imaammataa guutuu (TA/SA sadarkaalee hundaa ilaalu)

---

## Bulchiinsa Itti Fufaa

### 🔒 Fayyadamaa Haaraa Dabaluu (TA Qofa)
1. Org Setup → Personnel → "+ Add Person"
2. Maqaa, imeelii, gahee galchi, gara bakka hojii ramadi, jecha darbii qindaa'i
3. Ragaalee amansiisaa haala eegumsaan qoodi

### 🔒 Fayyadamaa Dhaabuu (TA Qofa)
1. Tarree Personnel → fayyadamaa argadhu → Active cufi
2. Herregni yeroma sanatti ni cufama

> **⚠️ Yaadannoo:** Fayyadamaan dhaabame mirkaneessaa eeggataa yoo qabaate, bulchaa SMART kee
> qunnami. Ofumaan karaa haaraa argamsiisuun fuulduratti dhufa.

### 🔒 Fayyadamaa Ammas Kaasuu (TA Qofa)
1. Tarree Personnel → fayyadamaa hin hojjenne argadhu → Active ammas bani
2. Bakki hojii isaanii guddaa duraanii ofumaan ni deebi'a — harkaan deebisanii ramaduu hin
   barbaachisu
3. Bakkeewwan hojii dabalataa (ramaddii acting ykn delegate) yoo qabaatan, bakka hojii guddaa
   qofti ofumaan deebi'a; yoo ammas barbaachise bakkeewwan acting ykn delegate harkaan deebisanii
   ramadi

### 🔒 Seerota Mirkaneessaa Sirreessuu (TA Qofa)
1. Org Setup → Approval Rules → seera argadhuu sirreessi
2. Baay'ina, tartiiba, ykn bakkeewwan mirkaneessaa haaromsi
3. Save godhi — jijjiiramni yeroma sanatti hojiirra oola

### Daangaa Beekamoo — Sadarkaa Ammaa

- **Raawwii bakka hojii mirkaneessaa sirreeffamaa:** Seerotni mirkaneessaa sirreeffamaa bakka
  hojii mirkaneessaa filatamaa ibsu, garuu sirni fayyadamtoota biroo hayyama mirkaneessaa qaban
  mirkaneessuu irraa teeknikaan hin dhorku. Mirkaneessaa sirreeffamaa akka qajeelfama hojii
  gidduu garee bulchiinsa keetitti raawwadhu.

- **Dheerina yaadannoo dabarsaa:** Yaadannoo dabarsaa qubee 2000tti daangeffamaadha.

- **PUSH /review hin ilaallatu:** Dabarsaalee PUSH fi Sister sadarkaa ilaalchisaa hin qaban.
  Dabarsaalee PULL qofti fiilmii PENDING_REVIEW → PENDING_APPROVAL darbu. Hojjettoota gocha
  review dabarsaalee PUSH irratti fayyadamuu hin qajeelchiin.

- **Dhufaa jiru:** bulk CSV import (meeshaalee ykn kuusaa jalqabaaf), qindaa'ina tooftaa ergaa
  (FEFO/FIFO/LIFO), fi galmee stock-count meeshaa keessatti mul'atu garuu **Dhufaa jiru** jedhamee
  ibsameera — fuulota ni jiru, garuu amma ofitti hin hojjetan. Qabannoon bakka hojii kee keessaa
  gurraacha ta'e yoo argite, isa irratti ejjedhu: Dhufaa jiru, daangaa karoora, ykn bakka hojii
  kee read-only ta'uu akka siif himu.

---

## Gaaffii Baratamaa

**G: Karoora koo akkamitti guddisuu ykn jijjiiruu?**
Bulchaa SMART kee qunnami — jijjiiramni karooraa SMART tiin hojjetama, fuula Tenant Admin kee
irraa miti. Daangaan fi amaloonni haaraan jijjiiramni yeroo godhame hojiirra oolu. Kaffaltii
waggaa irratti guddinni invoisii **Proration** ji'oota waggaa kee keessaa hafaniif ni
uuma (ilaali [Sadarkaalee Karooraa](#plan-tiers)); xiqqeessuun deebii hin qabu.

**G: Invoisiin "Proration" maali?**
Invoisii yeroo tokko guddina ykn add-on waggaa kaffaltii keessatti giddu galeessa godhame.
Ji'oota guutuu waggaa sana keessaa hafan qofa ilaala; ji'a jijjiiramni itti ta'e bilisa.

**G: Galmoofnee garuu imeelii mirkaneessaa hin arganne.**
Fuula seensaa ykn fuula mirkaneessaa irratti **Resend link** fayyadami. Hidhaawwan sa'aatii
48 booda yeroo isaanii darba. Ammas hin dhufne, akkaawuntii spam kee ilaali ykn SMART
support qunnami.

**G: "Abbaan herregaa" eenyu dha?**
Namni bakka hojii galmeesse (ykn TA jalqabaa SMART tiin uumame). Isaan ijoo qunnamtii
galmee fi invoisii dha.

**G: Erga fayyadamtoota dabaleetii caaseffama dhaabbataa jijjiiruu danda'aa?**
Eeyyee — nodes fi bakkeewwan hojii haaraa dabaluu dandeessa. Fayyadamtoonni jiran ramaddii
isaanii ni qabatu. Node balleessuuf, dursa fayyadamtoota isaa deebisanii ramadi.

**G: Sadarkaalee dhaabbataa booda jijjiiruu nan danda'aa?**
Yeroo kamiyyuu sadarkaa amma gadii hafte jalatti dabaluu dandeessa, sadarkaa gadii nodes
dhaabbataa hin qabaanne yoo ta'e immoo balleessuu dandeessa — taabiin Organisation Levels
erga sadarkaalee jalqabaa kee qusattee booda filannoo lamaanuu ni argisiisa. Giddu gala
stack irratti sadarkaa dabaluu ykn balleessuun ofii-tajaajila miti; yoo barbaachise SMART
support qunnami.

**G: Mirkaneessaan hin argamne maal godhamuu qaba?**
TA ta'ee, bakka hojii kamiyyuu bakka taa'uun mirkaneessuu dandeessa. Wanta eeggataa Transfers
ykn Adjustments keessatti argadhuu kallattiin mirkaneessi ykn dhoorki — galmeen dhageettii
bakka isaanii taatee akka hojjette ni galmeessa.

**G: Dabarsaan Pending Approval keessa hafee namni tokko irratti hin hojjetu — maal godhamuu qaba?**
Kun yeroo bakki mirkaneessaa ramadame erga dabarsaan galmaa'e booda duwwaa ta'u (fayyadamaan
dhaabamee ykn deebi'ee ramadamee) ta'uu danda'a. Sirni ammatti ofumaan si hin akeekkachiisu —
Transfers haala "Pending Approval" tiin cirame yeroo hundaa ilaali. TA ta'ee ofii kee hin
uumne dabarsaa kamiyyuu mirkaneessuu ykn dhoorkuu dandeessa. Furmaata:
1. Gara Transfers → haala "Pending Approval" tiin ciri
2. Dabarsaa hafee argadhuu bani
3. Kallattiin mirkaneessi ykn dhoorki (galmeen dhageettii gocha TA galmeessa)
4. Node sanaa irraa dabarsaa haaraa uumuu dura, dabarsaaleen fuulduraa sirriitti akka
   qajeelfaman bakka hojii mirkaneessaatti fayyadamaa ramadi

Kana ittisuuf: fayyadamaa bakka hojii mirkaneessaa qabu dhaabuu dura, dursa bakka sanaaf
bakka bu'aa ramadi. Sirni ergasii dabarsaalee haaraa ofumaan bakka bu'aatti qajeelcha.

**G: Fayyadamaan bakka hojii tokko ol qabaachuu danda'aa?**
Eeyyee. Hayyamni isaanii bakka hojii ramadame hundaa walitti qabama — bulchitoota bakka
baay'ee ilaalaniif gaarii dha.

**G: Mallattoon 🔒 meeshaa irratti maal jechuu dha?**
Meeshaan sun To'annaa jala jira — fiilmii dabarsaa idilee kan cabsu seerota mirkaneessaa addaa
qaba. Baay'inni xiqqaan iyyuu mirkaneessaa addaa barbaada. Bal'inaaf fuula Approval Policies
ilaali.

**G: Adjustment fi Receive Stock gidduu garaagarummaan maali?**
- **Receive Stock** — kuusaan kuusaa tokkotti dhaqqaba (dhiyeessaa irraa ykn kuusaa jalqabaa irraa)
- **Adjustment** — lakkoofsa kuusaa sirreessa (miidhaa, hattummaa, dogoggora lakkoofsaa)

**G: Dabarsaa xumurame deebisuu nan danda'aa?**
Lakkii — galmeen kakuu sababa hordoffii sirrii dha. Dabarsaa deebii uumi ykn koodii sababa
`RETURN` qabu Adjustment fayyadami.

**G: Yeroo waliigalteen keenya dhumu maaltu ta'a?**
Yeroma sanatti wanti tokko hin ta'u. Guyyaa dhumaa dura akeekkachiisa **Expiring** guyyaa 14
argatta, ergasii guyyaa 14 **Grace** booda isaa — yeroo lamaan mal'inaan seensa guutuu,
mallattoo qofaan. Ergasii qofa, ammas yoo hin haaromfamin, bakki hojii kee **Read-only**
ta'a: amma seenuu, waan hundaa ilaaluu fi baasuu dandeessa, garuu gabbarraa haaraa, mirkaneessaa,
gulaalaa ykn fe'aa hin jiru. Taabila sadarkaa guutuu argachuuf armaan olii [Guyyoota
waliigaltee](#contract-dates) ilaali.

**G: Akkamitti haaromsa gaafadha?**
Yeroo kamiyyuu taabii Plan kee irraa — bakki hojii kee amma Read-only ta'ee jiru keessattuu
(kun wantoota amma sanatti hojjetaman keessaa tokko). Garee SMART gaaffii kee ilaalee kaffaltii
qindeessuuf si hordofa; SMART erga galmeessee boodas, seensi guutuun yeroma sanatti deebi'a.

**G: Qabduun maaliif gurraacha ta'e?**
Sababoota sadii danda'u: bakki hojii kee **Read-only** dha (waliigaltee yeroo darbe — armaan
olii ilaali), **daangaa karooraa** gahuu kee (fakkeenyaaf daangaa SKU kee), ykn amalli
**Dhufaa jiru** jedhamee ibsameera (amma hin ijaaramne — ilaali [Daangaa Beekamoo](#known-limitations-current-version)).
Qabduu irratti ejjedhu — kan ilaallatu si hima.

**G: Branch Exchange erga mirkanaa'ee dhiisuu nan danda'aa?**
Lakkii — Branch Exchange erga Approved gahee dhiisuu hin danda'amu. Bulchitoonni kuusaa
lachanuu mirkaneessaniiru, kuusaanis dabarsaaf murteeffameera. Dabarsaan dhugaan itti fufuu
yoo hin dandeenye, galtee irratti fudhannoo xumuraa Adjustment kuusaa fayyadamuun lakkoofsa
sirreessi (sababa: RETURN ykn DAMAGE). Gargaarsaaf bulchaa kee qunnami.

**G: Jecha darbii koo irraanfadhee — ofii koo deebisuu nan danda'aa?**
Eeyyee. Fuula seensaa irratti **Forgot password?** cuqaasii teessoo imeelii kee galchi.
Teessoon herrega waliin wal simatu yoo ta'e, hidhaa deebisaa imeeliin argatta — hidhaan sun
daqiiqaa 60f sirrii dha, yeroo tokko qofa fayyadamuu danda'ama. Banuun jecha darbii haaraa
qindeessuuf si dandeessisa. Erga qindaa'ee booda, kutaalee kee biroo kan ammas hojjetaa jiran
hundi baafamu, qabannoon seensa herrega kee irratti jiru kamiyyuu yeroma sanatti qulqullaa'a.
Imeeliin yoo hin dhufin, Tenant Administrator kee akka siif deebisu gaafadhu (gaaffii itti
aanu ilaali).

**G: Jecha darbii fayyadamaa akkamitti deebisuu?**
Gara Settings → Personnel deemi. Saree fayyadamaa paanaalii bal'ina isaanii banuuf cuqaasi.
"Reset Password" cuqaasii mirkaneessi. Jechi darbii fayyadamaa amantaa yeroof ati kennitu
tti deebi'a. Seensa isaanii itti aanu irratti jijjiiruuf dirqamu. Kun fayyadamaa kutaalee
jiran hundaa irraa baasa. Kana jecha darbii irraanfatameef ykn herrega miidhame banuuf
fayyadami.

**G: Fayyadamaan yoo qabamee cufame maaltu ta'a?**
Yaalii seensaa walitti fufiinsaan hin milkoofne 5 booda, herregni ofumaan daqiiqaa 15f
cufama. Fayyadamaan mallattoo qabannaa seensaa irratti argata. Daqiiqaa 15 eeggachuu fi
ammas yaaluu, ykn amantaa sirrii fayyadamaa jiraachuu mirkaneessuuf si (Tenant Admin)
qunnamuu danda'u. Qabannoon ofumaan qulqullaa'a — gocha bulchaa hin barbaachisu.
Fayyadamaan jecha darbii isaanii milkaa'inaan deebise, lakkoofsi qabannoo yeroma sanatti
ni qulqullaa'a.

**G: Kuusaa tokkoon tokkoo ykn naannoo tokkoon tokkoof seera sirreeffamaa addaa uumuu qabaa?**
Eeyyee. Seerri sirreeffamaa tokkoon tokkoon node murtaa'eef hojjetameef hojjeta. Dhaabbanni
kee kuusaalee ykn naannoolee hedduu yoo qabaate, tokkoon tokkoof seera adda uumuu qabda.
Seerri WHA1 qindaa'e ofumaan WHA2 ykn WHB1 hin hojjetu. Hordoffii guutuu mirkaneessuuf node
tokkoon tokkoo haala sirna qabuun hojjedhu. Haaromsi fuulduraa seerota sadarkaa dhaabbataa
wal fakkaatu keessaa nodes hunda irratti tarkaanfii tokkoon hojiirra oolchuuf si dandeessisa.

**G: LM dhaabbata guutuu fi LM node ramadame gidduu garaagarummaan maali?**
Logistics Manager yeroo uumtu, filannoo lama qabda. LM dhaabbata guutuu (bakka hojii malee
uumame) kuusaa dhaabbata guutuu irratti mul'achiisuu ilaaluu qaba — kuusaalee hunda too'atu
qindeessaa lojistiksii ol'aanaadhaaf gaarii dha. LM node-tti ramadame bakka hojii node
murtaa'ee waliin walqunnamee node sanaa fi nodes jalaa hundaa ni ilaala — kuusaa tokkoo fi
bakka hojii ishee jalaa too'atu qindeessaa lojistiksiidhaaf gaarii dha. Daangaa dhugaa
hojii hojjetaa sanarratti hundaa'i filadhu.

---

**G: Bakka hojii mirkaneessaaf nama lammaffaa yoo ramadee maaltu ta'a?**
Sirni fayyadamtoota hedduu bakka hojii tokko yeroma tokkotti qabaachuu ni eyyama. Haa ta'u
malee, dabarsaan ykn sirreeffamni mirkaneessuuf bakka sanaa qajeelfamu, sirni ni filata
ya'a — baratamaan isa dhumaa ramadame. Kun hiika bakka hojii mirkaneessaaf nama lammaffaa
dabaluun hojiin mirkaneessaa qabataa haaraa gara jalqabaa irraa gara haaraatti qajeelfamuu
danda'a jechuu dha. Qajeelfamni mirkaneessaa gara nama hin barbaadamne yoo deemaa fakkaate,
fayyadamtoota ammatti bakka sana qaban meeqa akka ta'an ilaali (Settings → Positions →
qabattoota ilaali). Lamaanuu dhugumatti waliin-mirkaneessitoota yoo hin ta'in, bakka
sana yeroo kamiyyuu mirkaneessaa barbaadame qofti akka qabatu ramaddii balleessi ykn
sirreessi.

---

**G: Fayyadamaa mirkaneessaa dabarsaalee eeggataa irratti ta'e yoo dhaabe maaltu ta'a?**
Fayyadamaan yeroo dhaabamu, ramaddiin bakka hojii isaanii ofumaan ni baafama. Sirni
ammatti ofumaan si hin akeekkachiisu — dabarsaaleen eeggataa gara fayyadamaa sanatti
qajeelfaman ammas fayyadamaa sana mirkaneessaa akka ta'e argisiisu, kanaafuu Transfers
haala "Pending Approval" tiin cirame ofii kee ilaaluu qabda. TA ta'ee ofii kee hin uumne
dabarsaa kamiyyuu mirkaneessuu ykn dhoorkuu dandeessa. Adjustments: sirreeffamoonni idilee
akkuma baratame siin mirkanaa'uu danda'u. Sirreeffamni hamma gadaanaa mirkaneessaa meeshaa
itti hojjetame nama murtaa'e tokkoof cufameera; namni sun yoo dhaabame namni kamiyyuu
mirkaneessuu hin danda'u — dhoorki, uumaan ammas akka dhiyeessu gaafadhu akka gara
mirkaneessaa hojjetaa ta'eetti qajeelfamuuf. Bakka hojii deebisanii ramaduun sirreeffama
duraan dhiyaate hin sochoosu. Mirkaneessaa dhaabuu dura, qajeelfamni osoo hin addaan citin
akka itti fufuuf fayyadamaa biraa bakka hojii isaaniif ramadi.

---

**G: Seerotni mirkaneessaa sirreeffamaa eenyu mirkaneessuu akka qabu ibsuu danda'uu?**
Seerotni mirkaneessaa sirreeffamaa daangaa baay'inaa fi amala qajeelfamaa ibsu, garuu sirni
bakka hojii murtaa'e sadarkaa dhumaa irratti mirkaneessuu akka qabu hin raawwachiisu —
fayyadamaan hayyama mirkaneessaa sirreeffamaa qabu kamiyyuu sirreeffama eeggataa
mirkaneessuu danda'a. Eenyu sirreeffamoota mirkaneessuu irratti to'annoo cimaa yoo
barbaadde, kana raawwii teeknikaa irratti hirkachuu mannaa qajeelfama hojii bulchitoota
keetiif himi.

---

**G: Logistics Manager (LM) sirna keessatti dhugaan maal gochuu danda'a?**
LM gahee lojistiksii fi ergaa-irratti-xiyyeeffate — gahee hojii kuusaa miti.
LM kan gochuu danda'u:
- Kuusaa node isaaniif ramadame fi nodes jalaa hundaa ilaaluu
- Dabarsaalee ilaaluu fi tarreessuu
- Erga fudhachuu fi ergamuu
- Sirreeffamoota fi odeeffannoo meeshaa ilaaluu

LM kan hin gochuu danda'amne:
- Dabarsaalee uumuu ykn galchuu
- Sirreeffamoota uumuu ykn galchuu
- Dabarsaalee ykn sirreeffamoota mirkaneessuu

Nama seensa hojii bal'aa qabu (mirkaneessaa, dabarsaalee uumuu) yoo barbaadde, Warehouse
Manager (WM) ykn Regional Manager (RM) gahee bakka isaa ramadi.
Yaadannoo: node malee yoo uumame (LM dhaabbata guutuu), LM kuusaa dhaabbata guutuu irratti
ilaaluu danda'a garuu ammas daangaa gochaa armaan olii waliin qaba.

---

**G: Fayyadamtoonni hundi dabarsaalee PUSH (Send Stock) jalqabuu danda'uu?**
Lakkii. Dabarsaaleen PUSH Level 1 (Factory/Main) fi Level 2 (Regional) caaseffama dhaabbata
keetii irratti fayyadamtoota qofaan jalqabamuu danda'u — baratamaan gaheewwan NM fi RM.
Kun akkamitti kuusaan qoodamaa keessa akka dhangala'u ni calaqqisiisa: warshaaleen fi
giddugaleeyyiin naannoo kuusaa gara kuusaaleetti gad dhiibu, kan biraan miti.

Warehouse Managers (WM), Logistics Managers (LM), fi hojjettoonni sateelaayitii dabarsaalee
PULL (Request Stock) ykn Sister (walqixxee karaa gama) qofa jalqabuu danda'u. WM kuusaan
gara kuusaa isaaniitti ergamuu yoo barbaade, gaaffii PULL galchuu qaba — NM ykn RM isaanii
argee ni mirkaneessa.

---

**G: Ani deepoo sateelaayitii haaraa dabale — seerotni mirkaneessaa ofumaan isaaf hojjetu?**
Lakkii. Node haaraa (kuusaa ykn sateelaayitii) yeroo dabaltu, hamma uumtutti seera
mirkaneessaa dabarsaa ykn sirreeffamaa hin qabu. Hamma seerota dabaltutti, dabarsaaleen
node sanaa ganda durii sirnaa darbu, kunis imaammata kee karoorfatee waliin wal hin simatu
ta'a. Node haaraa erga uumtee booda, gara Settings → Approval Rules deemii node sanaaf
seerota dabarsaa fi sirreeffamaa barbaachisaa dabali hojjettoonni fayyadamuu jalqabuu
dura.

---

**G: Hojjetaan tokko ol-guddifame ykn gara gahee biraatti deeme. Maal gochuun qaba?**
Fayyadamaa gara bakka hojii haaraatti yeroo deebistee ramaddu:
1. Bakka hojii haaraa irratti PRIMARY ramadi (daangaan isaanii seensa isaanii itti aanu
   irratti yeroma sanatti haaromfama)
2. Bakka hojii duraanii ammas qabaachuu hin qaban yoo ta'e balleessi
   — force-remove PRIMARY qofaa balleessuuf fayyadami (SA token barbaachisa)
3. Bakki hojii duraanii mirkaneessaa eeggataa qabaatee yoo ta'e, kunneen ofumaan hin
   olguddifaman — Transfers/Adjustments haala "Pending Approval" tiin cirame ofii kee
   ilaali. Dabarsaalee eeggataa akka TA kallattiin mirkaneessuu ykn dhoorkuu dandeessa.
   Sirreeffamoonni eeggataa akkuma baratame mirkanaa'uu danda'u, hamma gadaanaa
   mirkaneessaa meeshaa sirreeffama sana nama murtaa'eef yoo hin cuftin — yoo kana ta'e
   namni kamiyyuu mirkaneessuu hin danda'u, dhoorkamuu qaba, uumaan ammas dhiyeessee gara
   mirkaneessaa hojjetaa tokkootti qajeelfamuu qaba. Bakka bu'aa dursa ramaduun wanta
   ergasii dhiyaatu hunda kana irraa oolcha.

Fayyadamaan gara sadarkaa olaanaatti yoo deeme (fakkeenyaaf WM → RM), daangaan WM duraanii
seensa isaanii itti aanu irratti daangaa RM haaraatiin bakka buufama. Gara sadarkaa
gadaanaatti yoo deeme (fakkeenyaaf RM → WM), seensi isaanii akkasuma ni dhiphata. Erga
jijjiirama bakka hojii kamiyyuu booda fayyadamaan ba'ee ammas galuun yeroo hunda mirkaneessi.

---

## Tarree Qindaa'inaa

### 🔒 Tarree Tenant Administrator

**Herrega fi Karoora:**
- [ ] Teessoon imeelii mirkanaa'eera (self sign-up)
- [ ] Settings → Tenant Admin → Plan ilaalameera — karoora, daangaa fi amaloonni akka
  karoorfametti
- [ ] Piroofaayilii dhaabbataa fi namoonni qunnamtii xumurameera (taabiin Profile fi Contact)
- [ ] Invoisiin jalqabaa ilaalamee kaffaltiin qindaa'eera (yoo baafame)

**Caaseffama Dhaabbataa:**
- [ ] Sadarkaaleen dhaabbataa ibsameera
- [ ] Mukni dhaabbataa xumurameera — nodes hundi uumamaniiru
- [ ] Bakkeewwan hojii node tokkoon tokkoof uumamaniiru (guddaa + gargaaraa gorfameera)
- [ ] Gosoonni dabarsaa maqaa argisiisu ofiisawaadhaan moggaafamaniiru
- [ ] Seerotni mirkaneessaa dabarsaa gosoota hojjetaa hundaaf qindaa'aniiru
- [ ] Seerotni mirkaneessaa sirreeffamaa qindaa'aniiru
- [ ] Daangaaleen ofiin-mirkaneessuu gahee sadarkaa tokkoon tokkoof qusatamaniiru

**Namoota fi Meeshaalee:**
- [ ] Hojjettoonni hundi dabalamanii bakkeewwan hojiitti ramadamaniiru
- [ ] Jechi darbii jalqabaa haala eegumsaan qoodameera
- [ ] Gosoonni meeshaa uumamaniiru
- [ ] Meeshaaleen hundi kodii gosaa fi safartuu waliin dabalamaniiru
- [ ] Meeshaaleen to'annaa jala jiran seerota mirkaneessaa 🔒 waliin qindaa'aniiru
- [ ] Suuraaleen meeshaa fe'amaniiru (filannoo)
- [ ] Kuusaan jalqabaa nodes kuusaa hundatti galameera

**Mirkaneessa:**
- [ ] Fuulli Approval Policies ilaalameera — seerotni sirriitti mul'atu
- [ ] Dabarsaan qorannoo uumamee fiilmii guutuu keessa mirkanaa'eera
- [ ] Yoo xiqqaate WM tokko, RM tokko, fi NM tokko seensi isaanii mirkanaa'eera
- [ ] Mallattoon fe'ameera (filannoo)
- [ ] Galmeen dhageettii ilaalameera — gochaaleen qindaa'inaa galmaa'aniiru

---

> **📋 Yaadannoo Dura:** Maamiltootaaf osoo hin qoodin dura bakka buusaa screenshot hunda
> screenshot dhugaa dhaan bakka buusi. Yoo maamiltoota Itiyoophiyaaf barbaachise gara
> Amaarffaa ykn Afaan Oromoo hiiki. Kutaalee TA-qofa hunda maatriksii hayyamaa dhumaa waliin
> ilaali.

---

*Sadarkaa Galmee: 1.6 | Haaromfame: October 2026 | Kan Eegamu: Development team*
*1.5 (2026-10-10) — sadarkaalee waliigaltee (Active/Expiring/Grace/Read-only), daangaa
seensaa read-only, akkamitti haaromsa gaafachuu, fi haala Coming soon bulk CSV import,
tooftaa ergaa fi galmee stock-count dabalamaniiru.*
*1.5 — gara kutaa lamaatti qoodame: Getting Started (galmee dura) amma sanduuqa mataa
isaa dha; qajeelfamni kun Kutaa 2, qindaa'ina bakka hojii Plan Tiers irraa eegalee dabalata.*
*1.3 — guddina fi add-ons kaffaltii waggaa irratti ji'aan madaalame; jijjiiramni karooraa
SMART qofaan hojjetama.*
