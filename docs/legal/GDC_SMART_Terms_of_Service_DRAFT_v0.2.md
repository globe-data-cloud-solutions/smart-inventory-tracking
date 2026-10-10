# **GDC/LEGAL REVIEW PENDING**

> Markdown mirror of the .docx of the same name (source of truth = .docx). Draft v0.2, 10 Oct 2026. Not legal advice; counsel review required.

**TERMS OF SERVICE**

*SMART Inventory Management Platform — multi-tenant inventory, product tracking and analytics service*

**DRAFT v0.2 FOR GDC BUSINESS AND LEGAL REVIEW \| Updated 10 October 2026 (supersedes draft of 10 October 2026, v0.1)**

| **EDITORIAL NOTE — NOT FOR PUBLICATION.** This draft has been updated to match how the SMART platform actually works (self sign-up, plan packages, billing, downgrade and expiry rules, immutable ledger, offline PWA, AI forecasting) and to reference Ethiopian law. Yellow **COUNSEL NOTE** boxes mark points that need a decision or confirmation by GDC management and Ethiopian counsel; delete every note and replace every \[BRACKETED PLACEHOLDER\] before customers accept this document. Statutory references were checked against secondary sources and third-party transcriptions of the Negarit Gazeta — counsel must verify them against the official texts. This draft is not legal advice. |
|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

**Effective date:** \[DATE\] **Version:** \[TERMS_VERSION — must match the value stored by the platform\]

**Service provider:** \[GLOBE DATA CLOUD SOLUTIONS — CONFIRM FULL REGISTERED NAME AND LEGAL FORM, e.g. PLC\], a company registered in the Federal Democratic Republic of Ethiopia under commercial registration no. \[NO.\] and TIN \[TIN\], trading as “SMART Inventory” (“**GDC**”, “we”, “us” or “our”).

**Contact:** \[support@DOMAIN\] \| \[legal@DOMAIN\] \| \[REGISTERED ADDRESS, Addis Ababa, Ethiopia\] \| \[TELEPHONE / WHATSAPP BUSINESS NUMBER\]

# 1. Agreement and acceptance

1.1 These Terms of Service (“**Terms**”) govern access to and use of the SMART Inventory Management Platform, including its progressive web application (PWA) on desktop, tablet and mobile browsers, its APIs, reports and exports, AI-assisted forecasting and recommendation features, notifications, and related onboarding and support (together, the “**Service**”). The agreement is between GDC and the business or other legal entity that registers a tenant account or is onboarded by GDC (“**Customer**”).

1.2 **Self sign-up.** When Customer registers online, the individual completing registration becomes Customer’s first Tenant Administrator (“**account owner**”) and must accept these Terms and the Privacy Statement by an affirmative action (for example, ticking a box and selecting “Create account”). That individual represents that they are authorised to bind Customer. Email verification is required before the account is activated.

1.3 **GDC-assisted onboarding.** Where GDC creates the tenant on Customer’s behalf, the account owner must accept these Terms at first login before using the Service. Any signed order form or service agreement also applies.

1.4 **Electronic acceptance and records.** The parties agree that acceptance by electronic means, and electronic records of that acceptance, have the same legal effect as a signed paper document, as recognised by the Electronic Transaction Proclamation No. 1205/2020. GDC records the Terms version accepted, the date and time, and the accepting user, and Customer may request a copy of that record.

1.5 **Order of precedence.** If a signed order form, service agreement, memorandum of understanding, service-level agreement or data processing agreement conflicts with these Terms, the signed document controls only for the subject it expressly addresses. Mandatory provisions of Ethiopian law prevail over these Terms.

| **COUNSEL NOTE 1 — acceptance mechanics.** The platform stores acceptance (timestamp + version) and forces re-acceptance by the account owner only when TERMS_VERSION changes; other users are not gated. Confirm that (a) owner-only acceptance is sufficient to bind the company, (b) a separate, light-weight “acceptable use” acknowledgement for ordinary users is not required, and (c) whether an Amharic version must be offered at acceptance (see clause 23.3). |
|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 2. Definitions

**Authorized User** — an employee, contractor or other individual whom Customer, through its Tenant Administrator, gives a user account under Customer’s tenant.

**Customer Data** — all data submitted to, imported into, captured offline for, or generated within the Service for Customer, including organisation structure, facilities, products, SKUs, batches/lots, expiry dates, stock movements, transfers, approvals, stock counts, suppliers, recipients, personnel records, attachments, images and reports, but excluding Service Data.

**Inventory Ledger** — the append-only record of inventory transactions maintained by the Service, from which stock balances are calculated.

**Plan** — the subscription package selected by or for Customer (currently Starter, Professional or Enterprise, as described on the pricing page or order form), which determines available features, usage limits and fees; together with any paid **Add-ons**.

**Service Data** — technical and operational data GDC generates about the operation of the Service, such as logs, performance metrics, security events and aggregated usage statistics.

**Platform Administrator** — authorised GDC personnel with platform-wide administrative access used to operate, support and secure the Service.

**Tenant / Tenant Administrator** — Customer’s logically separated environment within the Service, and the Authorized User(s) holding the Tenant Administrator role who manage that environment.

**Personal Data**, **controller**, **processor**, **data subject** and **personal data breach** have the meanings given in the Personal Data Protection Proclamation No. 1321/2024 (“**PDP Proclamation**”) or other applicable data-protection law.

# 3. Access rights and permitted use

3.1 Subject to these Terms and payment of applicable fees, GDC grants Customer a limited, non-exclusive, non-transferable, non-sublicensable right during the subscription term to access and use the Service for Customer’s internal business operations, within its Plan limits and the Documentation.

3.2 Available functions depend on Customer’s Plan, organisation type, configuration and the permissions assigned to each role. Features that are not included in Customer’s Plan are unavailable until the Plan is changed. The Service may support multi-level organisation hierarchies, multiple warehouses and facilities, approval workflows, FEFO/FIFO/LIFO dispatch strategies, barcode/QR scanning, offline capture, alerts, dashboards, exports and AI-assisted analytics.

3.3 **Acceptable use.** Customer and its Authorized Users must not: (a) use the Service in breach of any law, including the Computer Crime Proclamation No. 958/2016 and the PDP Proclamation; (b) access, or attempt to access, another tenant’s data or any part of the Service without authorisation; (c) probe, scan, load-test, disrupt or bypass security or usage controls, except with GDC’s written consent; (d) reverse engineer, decompile or attempt to extract source code except where law expressly permits; (e) resell, sublicense, time-share or operate the Service as a service bureau without GDC’s written permission; (f) upload malware or unlawful, infringing or deceptive content; (g) use the Service to send unsolicited advertising; (h) share user credentials or create accounts for fictitious persons; or (i) use the Service to build or benchmark a competing product.

# 4. Accounts, users and security

4.1 Customer must provide accurate registration, company and billing details and keep them current. Customer must maintain at least one active Tenant Administrator. Only Tenant Administrators can create Authorized User accounts; each Authorized User must have an individual account.

4.2 Customer is responsible for all activity under its tenant, for assigning roles, facility scopes and approval thresholds appropriately, for segregation of duties, and for promptly disabling accounts of people who leave or no longer need access.

4.3 The Service applies security controls such as mandatory email verification, temporary account lock-out after repeated failed log-in attempts, limited session lifetimes and forced password change after an administrator reset. Customer must not attempt to circumvent these controls and must share temporary passwords only through secure channels.

4.4 Customer will notify GDC without undue delay at \[security@DOMAIN\] of any suspected compromise of credentials, unauthorised access or misuse.

# 5. Customer responsibilities for inventory records

5.1 Customer is responsible for the accuracy, legality and completeness of Customer Data and for having all rights and notices required to submit it, including notices to its own employees, suppliers and recipients whose personal data it enters.

5.2 The Service is a record-keeping and decision-support tool. It does not verify physical stock. Customer remains responsible for physical counts, product identifiers, units of measure, batch/lot and expiry information, stock valuation, tax treatment, statutory books of account, and verifying reports before relying on them.

5.3 **Immutable ledger.** To preserve audit integrity, posted inventory transactions cannot be edited or deleted. Errors are corrected by recording adjustment or reversing transactions, which remain visible in the audit history. Customer accepts this design and agrees that requests to delete individual posted transactions cannot be fulfilled except as required by law (see the Privacy Statement).

5.4 **Offline use.** Transactions captured while offline are stored on the user’s device until they synchronise. GDC is not responsible for transactions lost because a device was lost, reset or cleared before synchronisation, or for conflicts resolved according to the documented sync rules. Customer must secure devices used with the Service.

5.5 Customer must maintain suitable devices, browsers, internet connectivity and power supply. Service performance may be affected by network outages or restrictions outside GDC’s control.

# 6. Plans, fees, taxes and payment

6.1 **Plans and prices.** Customer selects a Plan and a billing period (monthly or annual) at sign-up or in its order form. Prices are stated in \[Ethiopian Birr (ETB)\] and are \[exclusive / inclusive\] of value-added tax. The billing period selected at sign-up applies for the subscription and cannot currently be switched mid-subscription. GDC may change list prices on at least \[30\] days’ notice; a price change applies from Customer’s next renewal and does not affect a period already invoiced.

6.2 **Invoices and payment.** Fees are invoiced in advance for each billing period. Unless GDC enables an online payment method, Customer pays by bank transfer to the account stated on the invoice, quoting the invoice reference, and sends proof of payment to \[billing@DOMAIN\]. A payment is treated as received when GDC records it against the invoice. Payment is due within \[15\] days of the invoice date.

6.3 **Early access before payment.** GDC may allow a new Customer to use the Service before its first invoice is paid. That access is provided at GDC’s discretion and may be limited, made read-only or ended under clause 13 if the first invoice is not paid when due.

6.4 **Upgrades and Add-ons.** Plan changes are made by GDC at Customer’s request. On annual billing, an upgrade or a paid Add-on taken mid-period is charged pro rata: the annual price difference (or annual Add-on price) × the number of whole months remaining ÷ 12; the partial month in which the change takes effect is free. On monthly billing, the new price applies from the next invoice.

6.5 **Downgrades.** For a paid subscription, a downgrade is scheduled and takes effect at the start of the next renewal period; Customer keeps its current Plan until then, and the renewal invoice is issued at the lower Plan, with the change applied when that renewal invoice is recorded as paid. If no invoice has ever been paid, a downgrade applies immediately. At Customer’s request GDC may apply a downgrade immediately, in which case no refund or credit is given. An upgrade requested while a downgrade is scheduled cancels the scheduled downgrade. Where Customer’s existing data exceeds the limits of the lower Plan (for example, more warehouses or users), existing data is kept but new items above the limit cannot be created.

6.6 **No refunds or credits.** Except where required by law or expressly agreed in writing, fees paid are non-refundable, and GDC does not issue refunds or account credits for downgrades, unused periods or unused features.

6.7 **Taxes.** Customer pays all applicable taxes and duties, including VAT at the rate required by the Value Added Tax Proclamation No. 1341/2024 (currently 15%) and any bank or transfer charges. GDC will issue tax invoices that comply with Ethiopian tax law. Where Customer is required to withhold tax from a payment, Customer will provide GDC with the official withholding receipt promptly.

6.8 **Late payment.** If an undisputed amount is overdue, GDC may, after at least \[15\] days’ written notice, restrict the Service under clause 13. Customer must raise any billing dispute in good faith within \[15\] days of the invoice and pay undisputed amounts.

| **COUNSEL NOTE 2 — commercial and tax.** (a) Confirm currency and whether published prices include VAT (consumer-facing price display rules require tax-inclusive display; this is a B2B service but confirm). (b) Account credits are deliberately excluded until GDC’s accountant confirms Ethiopian VAT credit-note handling. (c) Confirm withholding-tax treatment for SaaS fees. (d) If an online payment provider (e.g. a local gateway or a foreign processor) is added later, update 6.2 and the Privacy Statement, and check National Bank of Ethiopia foreign-exchange rules if any fees are payable in foreign currency. |
|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 7. Subscription term, expiry and renewal

7.1 The subscription runs for the billing period stated in the order form or sign-up record and renews for successive periods of the same length unless either party gives notice of non-renewal at least \[30\] days before the end date, or as otherwise agreed. Customer may ask to renew at any time.

7.2 GDC will contact Customer before the end date of its subscription. If the subscription end date passes without renewal, Customer has a **14-day grace period** with normal access. After the grace period the tenant automatically becomes **read-only**: users can still log in, view and export Customer Data, but cannot record new transactions. Full access is restored once the renewal is paid.

7.3 Suspension (as opposed to read-only status) is a separate, manual decision by GDC under clause 13.

# 8. Service levels and support

8.1 GDC will use commercially reasonable efforts to make the production Service available **99.5% of the time in each calendar month**, excluding scheduled maintenance announced at least \[48\] hours in advance, emergency security maintenance, and events described in clause 21 (force majeure) or caused by Customer, its devices or its internet or power supply. \[Service credits: none / as set out in a separate SLA.\]

8.2 Support is provided by email at \[support@DOMAIN\] \[and WhatsApp Business at NUMBER\] during \[business hours, Monday–Friday, East Africa Time, excluding Ethiopian public holidays\], in English and Amharic. GDC aims to respond to support requests within **two (2) business days**; urgent incidents affecting the whole Service are prioritised.

8.3 GDC may improve, change or discontinue features. GDC will give reasonable advance notice of a change that materially reduces core functionality of Customer’s Plan, except where urgent security or legal reasons prevent it.

| **COUNSEL NOTE 3 — SLA.** The 99.5% uptime target and two-business-day email response come from GDC’s pre-launch requirements. Decide whether these are binding commitments with service credits or targets only. A binding SLA should not be offered until production monitoring on AWS has been running and measured. |
|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 9. Customer Data and data protection

9.1 **Ownership.** As between the parties, Customer owns Customer Data. Customer grants GDC a limited right to host, copy, transmit, display, back up and otherwise process Customer Data only as needed to provide, secure, support and improve the Service, to comply with law, and as described in the Privacy Statement.

9.2 **Roles.** For personal data within Customer Data, Customer is the controller and GDC acts as processor on Customer’s documented instructions, which consist of these Terms, Customer’s configuration and use of the Service, and any data processing agreement (“**DPA**”). For account, billing, security and business-contact data, GDC acts as an independent controller as described in the Privacy Statement. These Terms are intended to constitute the written processing contract required by Article 16(3) of the PDP Proclamation; the parties will sign a separate DPA where either party reasonably requests one.

9.3 **GDC’s processor commitments.** GDC will: (a) process personal data only on Customer’s instructions unless required by law; (b) ensure personnel with access are bound by confidentiality; (c) apply the security measures in clause 11; (d) notify Customer without undue delay, and in any event within \[24/48\] hours, after becoming aware of a personal data breach affecting Customer Data, so that Customer can meet its own 72-hour notification duty under Articles 43–44 of the PDP Proclamation; (e) assist Customer, taking into account the nature of the processing, with data-subject requests, impact assessments and regulator enquiries; (f) only engage sub-processors listed in the Privacy Statement, giving at least \[30\] days’ notice of new sub-processors; and (g) at the end of the subscription, return (via export) and then delete Customer Data in accordance with clause 15.

9.4 **Registration.** GDC will maintain its registration with the Ethiopian Communications Authority (“**ECA**”) as required by Article 33 of the PDP Proclamation. Customer is responsible for any registration it requires as a controller.

9.5 **Location of data.** Customer Data is hosted in \[HOSTING LOCATION / CLOUD REGION\] as described in the Privacy Statement. GDC will not move the primary hosting location of Customer Data to a different country without \[60\] days’ prior notice.

9.6 **Prohibited data.** Customer must not store in the Service sensitive personal data (as defined in the PDP Proclamation, for example health, biometric or ethnic-origin data), government identification numbers, payment-card or bank-account numbers of individuals, or data about minors, except where GDC has agreed in writing that the Service is configured for that data.

9.7 **Aggregated data.** GDC may create and use aggregated or de-identified statistics derived from Service Data and Customer Data to operate, secure and improve the Service, provided they do not identify Customer, any individual, or Customer’s confidential commercial information. GDC does not sell Customer Data and does not use it for third-party advertising.

| **COUNSEL NOTE 4 — DATA LOCALISATION (HIGH PRIORITY).** Article 22(1) of the PDP Proclamation requires controllers and processors to store personal data collected in Ethiopia on a server or data centre located in Ethiopia; Article 22(2) lets ECA designate “critical personal data” that may only be processed in Ethiopia; Article 22(3) requires prior ECA approval for cross-border transfer of sensitive personal data; Articles 18–21 set the conditions for any cross-border transfer. The SMART platform is built for AWS (development currently uses us-east-1; the production region is not yet decided — the design document lists Europe or South Africa) and AWS has no region in Ethiopia. Before launch, counsel must advise whether offshore hosting is permissible (e.g. with an ECA adequacy decision or authorisation, contractual necessity, or a local primary copy), whether an in-country copy/primary is needed, and how ECA interprets Art. 22 in practice. Options to evaluate include a local data centre or cloud provider for the primary database. Do not publish clause 9.5 until this is resolved. |
|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 10. GDC personnel access

10.1 Platform Administrators have technical ability to access all tenants in order to operate the Service. GDC limits that access to authorised personnel who need it to onboard Customers, provide support requested by Customer, maintain and secure the Service, investigate incidents or misuse, administer billing, or comply with law. GDC personnel are bound by confidentiality obligations.

10.2 GDC will not access the content of Customer Data for any other purpose and will log Platform Administrator activity in accordance with its internal security procedures.

# 11. Security

11.1 GDC maintains administrative, technical and organisational safeguards appropriate to the nature of the Service, including tenant isolation enforced at the application and database layers, role- and scope-based permission checks on every request, hashed passwords, account lock-out and session expiry, encryption in transit (HTTPS/TLS), managed secrets storage, audit logging of significant actions, regular backups, and restricted production access. No system is completely secure, and GDC does not warrant that the Service will be free of vulnerabilities.

11.2 Customer remains responsible for security within its control, including strong passwords, user provisioning, device security, and reviewing approvals and audit records.

11.3 Audit logs and the Inventory Ledger support accountability and investigation. They do not replace Customer’s own statutory books of account and record-keeping obligations.

# 12. AI-assisted features

12.1 Demand forecasts, replenishment or production-demand recommendations, slow/fast-moving classifications, expiry-risk predictions and anomaly alerts (“**AI Outputs**”) are generated by statistical and machine-learning models from historical transaction data. AI Outputs are clearly labelled, are estimates only, may be inaccurate or unavailable (for example, where there is insufficient history), and must be reviewed by a responsible person before Customer acts on them. Customer remains responsible for all ordering, dispatch, pricing and stock decisions.

12.2 The Service records whether users approve, reject or modify AI recommendations, and uses that feedback to improve the models. The Service does not use AI Outputs to make decisions about individuals that produce legal or similarly significant effects.

12.3 GDC does not currently send Customer Data to third-party AI model providers. GDC will update the Privacy Statement and give prior notice before doing so.

| **COUNSEL NOTE 5 — model training across tenants.** The product requirements describe “model cohorts” (Producer vs Retailer) used for forecast-model training. Decide whether models are trained (a) only on each tenant’s own data, or (b) across tenants using de-identified data. If (b), keep clause 9.7, add an explicit statement here, and consider an opt-out for Customers. Confirm 12.3 remains true at launch. |
|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 13. Restriction and suspension

13.1 GDC may restrict (for example, make read-only) or suspend all or part of the Service if reasonably necessary: (a) to address a security threat or prevent harm to the Service or other customers; (b) to stop unlawful use or a material breach of clause 3.3; (c) for undisputed fees overdue after notice under clause 6.8; or (d) to comply with law or an order of a competent authority.

13.2 Where practicable GDC will give prior notice, limit the restriction to what is reasonably necessary, and restore access once the cause is resolved. During restriction for non-payment Customer may still export its data.

# 14. Confidentiality

Each party may receive non-public business, technical, financial, pricing, security or operational information from the other (“**Confidential Information**”). Customer Data is Customer’s Confidential Information. The recipient will use Confidential Information only to perform or exercise rights under this agreement, protect it with at least reasonable care, and disclose it only to personnel, advisers and service providers who need to know it and are bound by confidentiality duties. These duties do not apply to information that is or becomes public without breach, was lawfully known before disclosure, is independently developed, or is lawfully received from a third party without restriction. A recipient may disclose information where required by law or a competent authority, giving advance notice where legally permitted. These obligations continue for \[three (3)\] years after termination, and for trade secrets for as long as they remain trade secrets.

# 15. Termination, export and deletion

15.1 Either party may terminate for material breach not cured within \[30\] days after written notice. Either party may terminate immediately where the other becomes insolvent or ceases business, subject to applicable law. Customer may terminate for convenience by giving notice of non-renewal under clause 7.1; fees already paid are not refunded.

15.2 On termination or expiry, Customer’s right to use the Service ends, except that Customer may log in and **export Customer Data for 30 days** (in the formats then supported, such as Excel, CSV and PDF). After that period GDC will delete or irreversibly anonymise Customer Data within \[60\] days, except for (a) copies in backups, which are overwritten on GDC’s rolling backup cycle of approximately \[35\] days, and (b) records GDC must keep by law, such as invoices and payment records. Retained data remains protected by these Terms.

15.3 Clauses that by their nature should survive termination (including 6 for amounts due, 9, 14, 15, 17, 18, 19 and 22) survive.

# 16. Intellectual property and feedback

GDC and its licensors own all rights in the Service, software, models, Documentation, designs and trademarks, excluding Customer Data and third-party materials. No rights are granted except those expressly stated. Customer’s logo and branding uploaded to the Service remain Customer’s property and are licensed to GDC only to display them within Customer’s tenant. GDC may use suggestions and feedback without restriction or payment, provided this does not disclose Customer’s Confidential Information.

# 17. Warranties and disclaimers

17.1 GDC warrants that it will provide the Service with reasonable skill and care and in material conformity with the Documentation. Customer’s remedy for breach of this warranty is for GDC to use reasonable efforts to correct the non-conformity, or, if GDC cannot do so within a reasonable time, for Customer to terminate the affected subscription.

17.2 Except as expressly stated and to the extent permitted by law, the Service is provided “as available”, and GDC disclaims implied warranties, including of fitness for a particular purpose. GDC does not warrant that the Service will be uninterrupted or error-free, or that AI Outputs, forecasts or reports will be accurate or meet Customer’s requirements.

# 18. Limitation of liability

18.1 To the extent permitted by law, neither party is liable for indirect or consequential loss, loss of profit, revenue, goodwill or anticipated savings, or loss arising from stock-outs, overstock, expiry or business interruption, however caused.

18.2 To the extent permitted by law, each party’s total aggregate liability arising out of or relating to this agreement is limited to the **fees paid or payable by Customer for the Service in the 12 months** before the event giving rise to the claim.

18.3 Nothing in these Terms excludes or limits liability for fraud, intentional wrongdoing or gross negligence, for Customer’s obligation to pay fees, or any liability that cannot be excluded or limited under Ethiopian law, including the Civil Code.

| **COUNSEL NOTE 6 — liability.** Confirm how the Ethiopian Civil Code treats contractual exclusion and limitation clauses (in particular for gross negligence and intentional fault) and whether a higher cap should apply to breaches of confidentiality or data protection, given PDP Proclamation fines of up to 4% of worldwide turnover (Art. 60). |
|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 19. Indemnities

19.1 Customer will defend and indemnify GDC against third-party claims, regulatory fines and reasonable costs arising from Customer Data (including Customer’s failure to give required notices or obtain required consents) or Customer’s unlawful use of the Service, except to the extent caused by GDC’s breach.

19.2 GDC will defend Customer against third-party claims that the Service, as provided by GDC, infringes that third party’s intellectual property rights, and pay damages finally awarded or agreed in settlement, provided Customer promptly notifies GDC, gives GDC control of the defence and settlement, and cooperates reasonably. GDC may modify or replace the affected feature or, if neither is reasonably possible, terminate the affected subscription and refund prepaid fees for the unused period. This clause does not apply to claims arising from Customer Data or combinations not supplied by GDC.

# 20. Third-party services

The Service relies on third-party infrastructure and services, including cloud hosting, email delivery and (when enabled) payment processing, listed in the Privacy Statement. GDC is responsible for sub-processors it engages to process Customer Data as if they were its own acts, but is not responsible for independent services that Customer chooses to connect or use, such as Customer’s own bank, email or device providers.

# 21. Force majeure

Neither party is liable for delay or failure caused by events beyond its reasonable control, including natural disasters, epidemics, war, civil unrest, government action, nationwide or regional internet or telecommunications shutdowns or restrictions, prolonged power outages, or failures of upstream cloud or network providers not caused by the affected party. Payment obligations for Service already provided are not excused. If a force majeure event continues for more than \[60\] days, either party may terminate the affected subscription on written notice.

# 22. Governing law and dispute resolution

22.1 These Terms are governed by the laws of the Federal Democratic Republic of Ethiopia.

22.2 The parties will first try to resolve any dispute through good-faith negotiation between senior representatives for \[30\] days after written notice of the dispute.

22.3 Any dispute not resolved by negotiation will be finally settled by arbitration under the Arbitration and Conciliation Working Procedure Proclamation No. 1237/2021, administered by \[the Arbitration Institute of the Addis Ababa Chamber of Commerce and Sectoral Associations\], before \[one / three\] arbitrator(s), seated in Addis Ababa, in the \[English\] language. To the extent permitted by law, the parties waive any appeal, including cassation, against the award. Either party may seek urgent interim relief, or recovery of undisputed fees, from a competent Ethiopian court.

| **COUNSEL NOTE 7 — disputes.** (a) Confirm the institution and the waiver of cassation review (Proclamation 1237/2021 Art. 49(2) allows cassation for a fundamental error of law unless waived). (b) Proclamation 1237/2021 Art. 7 excludes “administrative contracts” from arbitration — if a Customer is a public body or public enterprise, a court-based clause may be required. (c) Ethiopia acceded to the New York Convention in 2020, which supports enforcement if a foreign-seated option is ever needed. (d) Check whether a court in Addis Ababa should be named for the carve-outs. |
|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 23. Changes, notices and general

23.1 **Changes to these Terms.** GDC may update these Terms to reflect changes in the Service, its business or the law. GDC will give at least \[30\] days’ notice of material changes by email to the account owner and/or in-product notice. The account owner will be asked to accept the new version before continuing to use the Service. Changes do not apply retroactively to disputes that arose before the effective date. If Customer does not accept, it may stop using the Service and give notice of non-renewal; fees already paid are not refunded.

23.2 **Notices.** Notices to Customer may be sent to the account owner’s email address or shown in the Service. Notices to GDC must be sent to \[legal@DOMAIN\] and the registered address above. Operational emails from the Service are currently sent in English only.

23.3 **Language.** These Terms may be provided in English and Amharic. \[If there is any inconsistency, the English / Amharic version prevails.\]

23.4 **General.** Neither party may assign this agreement without the other’s written consent, except to a successor in a merger, reorganisation or sale of substantially all relevant assets, subject to applicable law. If any provision is held unenforceable, the rest remain in effect. Failure to enforce a provision is not a waiver. These Terms, the Privacy Statement, any order form and any DPA form the entire agreement regarding the Service and supersede prior proposals and discussions. The parties are independent contractors.

# 24. Contact

Questions about these Terms: \[GLOBE DATA CLOUD SOLUTIONS — CONFIRM FULL REGISTERED NAME AND LEGAL FORM, e.g. PLC\], \[REGISTERED ADDRESS\], Addis Ababa, Ethiopia \| \[legal@DOMAIN\] \| \[support@DOMAIN\] \| \[PHONE\].

# Annex A — Open items for GDC / legal review (delete before publication)

| **\#** | **Item**                                                                                                                   | **Owner**             | **Clause**      |
|--------|----------------------------------------------------------------------------------------------------------------------------|-----------------------|-----------------|
| 1      | Hosting location vs PDP Art. 22 data localisation and Arts. 18–22 cross-border transfer; ECA position                      | Counsel + GDC tech    | 9.5, Note 4     |
| 2      | GDC registration with ECA as controller/processor (Art. 33); certificate number to insert                                  | GDC                   | 9.4             |
| 3      | Full registered name, legal form, commercial registration no., TIN, address, domain and emails                             | GDC                   | Header, 24      |
| 4      | Currency; VAT-inclusive or exclusive pricing; withholding tax; payment terms (days)                                        | GDC + accountant      | 6.1–6.8         |
| 5      | SLA binding or target; service credits; support hours and WhatsApp channel                                                 | GDC                   | 8               |
| 6      | AI model training across tenants (cohorts) and opt-out                                                                     | GDC product + counsel | 9.7, 12, Note 5 |
| 7      | Liability cap, carve-outs and super-cap for data protection                                                                | Counsel               | 18              |
| 8      | Arbitration institution, arbitrators, language, cassation waiver; public-body customers                                    | Counsel               | 22              |
| 9      | Governing-language clause and Amharic translation                                                                          | GDC + counsel         | 23.3            |
| 10     | Breach notification window to Customer (\[24/48\] hours) and backup cycle (\[35\] days) — confirm operationally achievable | GDC tech              | 9.3, 15.2       |
| 11     | Sync TERMS_VERSION in the platform with the version on this document                                                       | GDC tech              | Header          |

# Annex B — Research references

Reviewed as drafting references, not copied as contractual language. Verify current versions and official texts before publication.

**Ethiopian law and guidance**

- Personal Data Protection Proclamation No. 1321/2024 — Ministry of Justice: https://justice.gov.et/en/law/personal-data-protection-proclamation/ ; ECA: https://pdp.eca.et/pdp-proclamation ; text transcription: https://www.metaappz.com/References/ethiopian_laws/federal/pr_1321_2024/en/txt

- DLA Piper, Data Protection Laws of the World — Ethiopia: https://www.dlapiperdataprotection.com/index.html?t=law&c=ET

- Mondaq, Ethiopian Personal Data Protection Law: Business Compliance Guide (2026): https://www.mondaq.com/privacy-protection/1766200/

- Haymanot & Advocates, Ethiopia Personal Data Protection Q&A: https://www.haymanotbelay.com/ethiopia-personal-data-protection-qa-guide/

- Techhive Advisory, Review of Ethiopia’s Data Protection Act: https://www.techhiveadvisory.africa/insights/review-of-ethiopias-data-protection-act

- Electronic Transaction Proclamation No. 1205/2020: https://www.metaappz.com/References/ethiopian_laws/federal/pr_1205_2020/en/pdf

- Computer Crime Proclamation No. 958/2016 (summary): https://www.dlapiperdataprotection.com/index.html?t=law&c=ET

- Value Added Tax Proclamation No. 1341/2024 — EY: https://taxnews.ey.com/news/2024-1698 ; Fonoa: https://fonoa.com/blog/ethiopia-introduces-marketplace-rules-and-vat-on-remote-services-provided-by-nonresidents

- Record retention (Commercial Code / Tax Administration) — PwC Tax Summaries: https://taxsummaries.pwc.com/ethiopia/corporate/tax-administration

- Arbitration and Conciliation Working Procedure Proclamation No. 1237/2021 — White & Case: https://www.whitecase.com/insight-alert/ethiopia-modernizes-arbitration-framework

- Trade Competition and Consumers Protection Proclamation No. 813/2013 — overview: https://ethiopianbusinessreview.net/consumer-protection-overview-of-the-legal-framework/

**Comparable SaaS inventory providers**

- Fishbowl Inventory — Software Subscription Terms: https://www.fishbowlinventory.com/legal/eula/

- Zoho — Terms of Service: https://www.zoho.com/terms.html

- Odoo — Privacy Policy: https://www.odoo.com/privacy

- Bloom Inventory (Ethiopia) — https://www.inventory.et/ ; Privacy Policy: https://www.inventory.et/privacy
