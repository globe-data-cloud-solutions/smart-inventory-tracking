# **GDC/LEGAL REVIEW PENDING**

> Markdown mirror of the .docx of the same name (source of truth = .docx). Draft v0.2, 10 Oct 2026. Not legal advice; counsel review required.

**PRIVACY STATEMENT**

*SMART Inventory Management Platform — inventory, product tracking, warehouse operations and analytics*

**DRAFT v0.2 FOR GDC BUSINESS AND LEGAL REVIEW \| Updated 10 October 2026 (supersedes draft of 10 October 2026, v0.1)**

| **EDITORIAL NOTE — NOT FOR PUBLICATION.** This draft now describes the SMART platform’s actual data flows as designed (self sign-up, tenant administration, immutable inventory ledger, offline PWA, camera barcode scanning, AWS hosting, email notifications, AI forecasting) and maps them to Ethiopia’s Personal Data Protection Proclamation No. 1321/2024 (“**PDP Proclamation**”). Yellow **COUNSEL NOTE** boxes mark items GDC must confirm against the production system or decide with Ethiopian counsel. Article references were checked against secondary sources and third-party transcriptions; verify against the official Negarit Gazeta text. Delete all notes and placeholders before publication. This draft is not legal advice. |
|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

**Effective date:** \[DATE\] \| **Last updated:** \[DATE\] \| **Version:** \[PRIVACY_VERSION\]

**Who we are:** \[GLOBE DATA CLOUD SOLUTIONS — CONFIRM FULL REGISTERED NAME AND LEGAL FORM\], \[REGISTERED ADDRESS\], Addis Ababa, Ethiopia, operator of the SMART Inventory Management Platform (“**GDC**”, “we”, “us”). ECA data-protection registration no.: \[NUMBER\]. Privacy contact: \[privacy@DOMAIN\]. Data Protection Officer: \[NAME / “not appointed” — see Counsel Note 6\].

# 1. Purpose and scope

This Privacy Statement explains how GDC collects, uses, shares, stores and protects personal data when people visit our website, sign up for or are onboarded to the SMART platform, use the platform’s web and mobile (PWA) application, APIs and exports, contact support, or otherwise deal with us.

It should be read with our Terms of Service and, where signed, a Data Processing Agreement (“**DPA**”). The SMART platform is used by businesses (“**Customers**”) to manage their own inventory operations. When a Customer records information about its employees, suppliers, recipients or other individuals in the platform, **the Customer is the controller** of that information and GDC processes it on the Customer’s behalf as a **processor** (see section 5). If you are an employee or business contact of a Customer, please also read that Customer’s own privacy notice.

# 2. Personal data we process

**Tenant sign-up and company data** — company name, organisation type (producer, retailer or hybrid), business address and contact details, selected plan and billing period, and the name, business email, telephone number and job title of the person who signs up (who becomes the first Tenant Administrator), together with the record of their acceptance of the Terms and this statement (version, date and time).

**User account data** — name, business email, telephone number (if provided), username, role and position, the organisation level, warehouse or facility the user is assigned to, preferred language (English or Amharic), account status, email-verification status, and a securely hashed password (we never store passwords in readable form).

**Personnel and organisation records entered by Customers** — personnel names, positions, reporting lines, facility assignments and approval authority.

**Inventory and business records** — products, SKUs, barcodes, batches/lots, expiry dates, stock receipts, transfers, issues, adjustments, stock counts, approvals, suppliers and customer/recipient records, attachments and product images. These are mainly business data, but they become personal data where they identify an individual — for example, a sole-trader supplier’s name and phone number, or the user who performed or approved a transaction (every ledger entry records who did it and when).

**Security, audit and log data** — log-in times, failed log-in attempts and account lock-outs, password resets, IP address, browser and device type, actions performed, permission and role changes, and system and error logs.

**Offline and device data** — when the app is used offline, transactions are temporarily stored in the browser’s local storage (IndexedDB) on the device until they synchronise, together with sync status and timestamps. The app also stores a session token and language preference on the device.

**Camera data** — if a user scans a barcode or QR code, the camera image is processed in the browser on the device to read the code; only the decoded value is sent to the platform. We do not store camera images.

**Billing and payment data** — invoices, plan and price history, payment status, bank-transfer references and proof of payment supplied by the Customer, billing contacts and tax details (such as TIN). We do not collect or store payment-card numbers.

**AI feature data** — forecasts, recommendations and anomaly flags generated for the tenant, and records of whether users approved, rejected or modified a recommendation.

**Support and communications** — emails, messages and support tickets, and diagnostic information you choose to provide.

**Website enquiries** — name, company, email, telephone and message if you request a demonstration or contact us.

**Sensitive data.** The platform is not designed for sensitive personal data as defined in the PDP Proclamation (for example health, biometric, genetic, or racial or ethnic-origin data), government identification numbers, or individuals’ bank or card numbers. Customers must not enter such data unless GDC has agreed in writing.

# 3. How we receive personal data

- Directly from you — when you sign up, verify your email, contact us, request a demo, open a support request or pay an invoice.

- From the Customer that employs or engages you — when its Tenant Administrator creates your account or records you as personnel, supplier or recipient.

- Automatically — from your browser or device when you use the platform (log-in events, IP address, actions taken, sync events).

- From service providers — for example, email-delivery status, or payment confirmations from a payment provider if one is enabled.

# 4. Why we use personal data and our legal grounds

Under Article 7 of the PDP Proclamation, processing is lawful only on a recognised ground. We rely on the following:

| **Purpose**                                                                                                               | **Legal ground (PDP Proclamation Art. 7)**                                                           |
|---------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------|
| Creating and verifying tenant and user accounts; authenticating users; enforcing roles, facility scopes and plan features | Performance of a contract with the Customer; GDC’s legitimate interest in providing a secure service |
| Providing the platform: recording inventory transactions, approvals, alerts, reports, exports, offline sync               | Performance of a contract (processing on the Customer’s instructions for Customer Data)              |
| Sending service emails (verification, password reset, approval and stock alerts) and service notices                      | Performance of a contract; legitimate interest                                                       |
| Billing, invoicing, recording payments, tax and accounting records                                                        | Performance of a contract; compliance with legal obligations (tax and commercial law)                |
| Security, fraud and misuse prevention, account lock-out, audit logging, incident investigation                            | Legitimate interest; compliance with legal obligations                                               |
| Customer support and onboarding                                                                                           | Performance of a contract; legitimate interest                                                       |
| Generating AI forecasts and recommendations and improving models from feedback                                            | Performance of a contract; legitimate interest (see section 13)                                      |
| Service reliability and improvement using aggregated or de-identified metrics                                             | Legitimate interest                                                                                  |
| Marketing emails about GDC products                                                                                       | Consent, which you can withdraw at any time                                                          |
| Responding to lawful requests from courts, ECA, tax or other authorities                                                  | Compliance with legal obligations                                                                    |

Where we rely on legitimate interest we have balanced it against your rights and expectations. Where we rely on consent, we ask for it separately, you can withdraw it at any time, and withdrawal does not affect earlier lawful processing. Using the platform is never conditional on consenting to marketing.

# 5. Customer data: controller and processor roles

For personal data that a Customer enters into its tenant, the Customer decides why and how it is processed and is the controller; GDC is the processor and processes it only under a written contract and on the Customer’s documented instructions, as required by Article 16 of the PDP Proclamation. Our Terms of Service contain those processor commitments, and we sign a separate DPA where needed.

GDC is an independent controller for: sign-up and account-administration data, billing records, security logs we use to protect the platform, support communications, website enquiries and marketing contacts.

**Who inside a Customer can see your data.** Users of the same Customer can see records according to the role and facility scope their administrator assigns. For example, managers can see who recorded or approved transactions within their scope, and Tenant Administrators can see all users and records in their tenant.

**GDC personnel access.** Authorised GDC platform administrators have technical access to all tenants to operate the service. We use that access only to onboard Customers, provide support the Customer requests, maintain and secure the platform, investigate incidents or misuse, administer billing, and comply with law. Our personnel are bound by confidentiality, and administrator activity is logged.

We do not sell personal data, and we do not use Customer Data for advertising.

# 6. Sharing and recipients

We share personal data only as needed for the purposes above, with:

- **Cloud infrastructure provider** — Amazon Web Services (AWS), which hosts the application, database, file storage (e.g. product images, logos, attachments), content delivery, email delivery (Amazon SES), monitoring and logging, and backups.

- **Payment provider** — \[none at launch; NAME if an online payment method is enabled\].

- **Communications tools** — \[email provider for support@ / WhatsApp Business, if used for support\].

- **Professional advisers** — auditors, accountants, lawyers and insurers, under confidentiality.

- **Authorities** — the Ethiopian Communications Authority, Ministry of Revenues, courts, law-enforcement or other public bodies where the law requires or permits disclosure. We review each request and disclose only what is legally required.

- **Corporate transactions** — a buyer or successor in a merger, reorganisation or sale of the business, subject to equivalent protections.

Our current list of sub-processors is available at \[SUB-PROCESSOR LIST URL\] or on request. We give Customers at least \[30\] days’ notice of new sub-processors.

| **COUNSEL NOTE 1 — sub-processor list.** Confirm the production list (AWS services in use; any monitoring, error-tracking or analytics tools; support mailbox and WhatsApp; future payment gateway). AWS Cognito is provisioned but not used for log-in at launch (own email + password log-in) — keep it off the list unless enabled. |
|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 7. Where data is stored and international transfers

The platform is hosted on AWS in \[AWS REGION, COUNTRY\]. GDC personnel and support staff access the platform from Ethiopia \[and LIST ANY OTHER COUNTRIES\]. Copies of data may also exist on users’ own devices while offline.

Personal data collected in Ethiopia is subject to the PDP Proclamation’s rules on storage and cross-border transfer (Articles 18–22). GDC transfers or stores personal data outside Ethiopia only where permitted by those rules — for example, under an adequacy decision or authorisation of the Ethiopian Communications Authority, where necessary for performance of a contract, or with appropriate safeguards — and we do not transfer sensitive personal data abroad without the Authority’s prior approval. \[Describe the legal basis confirmed by counsel.\]

| **COUNSEL NOTE 2 — DATA LOCALISATION (HIGH PRIORITY).** Article 22(1) of the PDP Proclamation requires controllers and processors to store locally collected personal data on a server or data centre located in Ethiopia; Art. 22(2) allows ECA to designate “critical personal data” that may only be processed in Ethiopia; Art. 22(3) requires prior ECA approval for cross-border transfer of sensitive data; Arts. 18–21 set transfer conditions. The SMART platform is designed for AWS (dev uses us-east-1; production region undecided — the design document lists Europe or South Africa); AWS has no Ethiopian region. Before launch GDC needs counsel’s view and, if necessary, ECA engagement on: whether an in-country primary or copy is required for tenant data; whether ECA authorisation is available for the chosen region; and how this section should then read. Do not publish section 7 until resolved. Note that the Proclamation attaches criminal penalties (imprisonment and fines) to unlawful transfers of personal data outside Ethiopia. |
|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 8. How long we keep data

We keep personal data only as long as necessary for the purpose collected, and then delete or anonymise it securely. Our schedule is:

| **Data**                                                                     | **Retention**                                                                                                                                                                                                    |
|------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Tenant Customer Data (inventory ledger, master data, personnel, attachments) | For the subscription. After termination, available for export for 30 days, then deleted or anonymised within \[60\] days.                                                                                        |
| Inventory ledger entries                                                     | The ledger is append-only for audit integrity: individual posted transactions are not edited or deleted during the subscription; corrections are made by adjustment entries. See section 11 on erasure requests. |
| User accounts                                                                | Until the Customer deactivates the account; deactivated accounts are kept with the tenant so that historical transactions remain attributable, then deleted with the tenant.                                     |
| Security, access and audit logs                                              | \[12\] months, or longer where needed for an ongoing investigation or legal claim.                                                                                                                               |
| Backups                                                                      | Rolling cycle of approximately \[35\] days; deleted data disappears from backups as they rotate.                                                                                                                 |
| Invoices, payment and tax records                                            | At least 10 years, as required by Ethiopian commercial and tax law.                                                                                                                                              |
| Terms and privacy acceptance records                                         | For the life of the account plus \[5\] years.                                                                                                                                                                    |
| Abandoned sign-ups (email never verified)                                    | \[30\] days.                                                                                                                                                                                                     |
| Website and demo enquiries                                                   | \[24\] months after last contact, unless you become a Customer.                                                                                                                                                  |
| Support tickets and correspondence                                           | \[3\] years after closure.                                                                                                                                                                                       |
| Marketing contacts                                                           | Until you unsubscribe or withdraw consent.                                                                                                                                                                       |
| Offline data on devices                                                      | Until synchronised, or until the user clears the browser data or logs out.                                                                                                                                       |

| **COUNSEL NOTE 3 — retention.** Bracketed periods are proposals. GDC tech must confirm the production backup cycle (the design document specifies RDS backup retention of at least 30 days), log retention settings, and that tenant deletion after the export window is implemented. Counsel to confirm the 10-year period (Commercial Code books-of-account rule; Tax Administration law requires the longer of that and 5 years from filing). |
|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 9. Security

We use technical and organisational measures appropriate to the risk, including:

- Tenant isolation enforced in the application and database (row-level security), with server-side permission checks on every request.

- Role-based and scope-based access control with least-privilege defaults; only Tenant Administrators create users.

- Hashed passwords, mandatory email verification, temporary account lock-out after repeated failed log-in attempts, short-lived sessions, and forced password change after an administrator reset.

- Encryption in transit (HTTPS/TLS) and \[encryption at rest for databases, backups and file storage\]; secrets held in a managed secrets store, never in code.

- Append-only inventory ledger and audit logs of significant actions and administrator access.

- Automated backups, monitoring and alerting; restricted, logged production access; secure development and dependency management.

- Confidentiality obligations and security awareness for GDC personnel.

No system is perfectly secure. Customers are responsible for their users’ passwords, timely removal of leavers, and the security of devices used with the platform, especially devices that hold offline data.

# 10. Personal data breaches

If we become aware of a personal data breach, we will act promptly to contain and investigate it. Where GDC is the controller, we will notify the Ethiopian Communications Authority within **72 hours** of becoming aware of it (Article 43 of the PDP Proclamation) and inform affected individuals as required by Article 44, unless an exception applies (for example, the data was encrypted or the risk has been mitigated). Where GDC is the processor, we will notify the affected Customer without undue delay, and in any event within \[24/48\] hours, and support the Customer in meeting its own notification duties.

# 11. Your rights

Under the PDP Proclamation you may have the right to: be informed about processing; access your personal data; have inaccurate data corrected; have data erased; object to processing (including profiling) and to direct marketing; restrict processing in certain cases; receive your data in a portable format where applicable; not be subject to decisions based solely on automated processing that significantly affect you; withdraw consent; and complain to the Ethiopian Communications Authority.

**How to make a request.** If your request concerns data that a Customer controls (for example, your employee or supplier record in a Customer’s tenant), please contact that Customer; we will help the Customer respond. For data GDC controls, write to \[privacy@DOMAIN\]. We may need to verify your identity. We respond without excessive delay and in any event within \[30\] days, and tell you if we need more time and why.

**Erasure and the inventory ledger.** Because posted inventory transactions form an append-only audit record that Customers rely on for accounting and legal purposes, a request to erase personal data may be met by deactivating the account and removing or anonymising profile details where possible, while retaining the minimum data needed to keep historical transactions attributable, for as long as the law or the Customer’s legitimate record-keeping needs require.

| **COUNSEL NOTE 4 — ledger vs erasure.** Confirm that retaining user attribution in immutable ledger entries is defensible under the PDP Proclamation (legal obligation / legitimate interest of the Customer as controller) and decide whether the platform needs a pseudonymisation function for deactivated users. |
|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 12. Cookies, local storage and similar technologies

The platform uses only technologies that are strictly necessary to provide it: storage of the session/authentication token, language preference, the service-worker cache that lets the app load offline, and the IndexedDB queue for offline transactions. \[We do not use advertising cookies, tracking pixels or third-party analytics on the platform.\] You can clear these through your browser settings, but the platform may not work correctly and unsynchronised offline transactions will be lost.

| **COUNSEL NOTE 5 — cookies/analytics.** GDC tech must verify the production web app and marketing website (including any embedded third-party scripts, fonts or analytics) before publishing the bracketed statement. |
|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 13. AI forecasting and automated processing

The platform provides demand forecasts, replenishment or production-demand recommendations, slow/fast-moving classifications, expiry-risk predictions and anomaly alerts based on a tenant’s historical inventory transactions. These outputs concern products and stock, not individuals; they are labelled as AI-generated and require review by a person before action. We record users’ approve/reject/modify decisions to improve the models. \[Models are trained only on each Customer’s own data / Models may also be trained on de-identified data pooled across Customers of the same organisation type.\] We do not currently send data to third-party AI providers.

Anomaly alerts may highlight unusual transactions recorded by a particular user. Such alerts are for review by the Customer and do not by themselves lead to decisions about any individual.

# 14. Minors

The platform is a business service and is not directed to minors. Under the PDP Proclamation a minor is a person under 16. Customers must not create user accounts for, or enter personal data about, minors.

# 15. Marketing

We send marketing messages only with consent (or as otherwise permitted by law), and every marketing email includes a way to unsubscribe. Service emails such as verification, password reset, approval and stock alerts, billing and security notices are part of the service and are not marketing. Service emails are currently sent in English.

# 16. Changes to this statement

We may update this statement to reflect changes in the platform, our practices or the law. We will update the “last updated” date, and for material changes we will notify Tenant Administrators by email or in-product notice before the change takes effect. Earlier versions are available on request.

# 17. Contact and complaints

Privacy questions and requests: \[GLOBE DATA CLOUD SOLUTIONS — CONFIRM FULL REGISTERED NAME AND LEGAL FORM\], \[Data Protection Officer / privacy contact\], \[REGISTERED ADDRESS\], Addis Ababa, Ethiopia \| \[privacy@DOMAIN\] \| \[PHONE\]. We aim to resolve concerns directly. You also have the right to complain to the **Ethiopian Communications Authority**, the data-protection authority under the PDP Proclamation: \[ECA address, website and complaint channel — verify before publication\].

| **COUNSEL NOTE 6 — DPO, registration and DPIA.** (a) A DPO is mandatory where core activities involve large-scale systematic monitoring or large-scale processing of sensitive data; GDC likely falls outside both, but appointing a named privacy lead is recommended. (b) GDC must register with ECA before processing (Art. 33; certificate valid two years). (c) Assess whether a data protection impact assessment is needed, in particular for offshore hosting and any cross-tenant model training. (d) Provide this statement in Amharic as well as English. |
|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# Annex A — Open items for GDC / legal review (delete before publication)

| **\#** | **Item**                                                                         | **Owner**          | **Section** |
|--------|----------------------------------------------------------------------------------|--------------------|-------------|
| 1      | Hosting region, Art. 22 localisation and transfer basis; ECA engagement          | Counsel + GDC tech | 7           |
| 2      | ECA registration number; DPO or privacy lead                                     | GDC                | Header, 17  |
| 3      | Production sub-processor list (AWS services, support tools, payment provider)    | GDC tech           | 6           |
| 4      | Retention periods; backup cycle; tenant deletion job after export window         | GDC tech + counsel | 8           |
| 5      | Encryption-at-rest confirmation; cookies/analytics on app and website            | GDC tech           | 9, 12       |
| 6      | AI model-training approach (per tenant vs pooled de-identified)                  | GDC product        | 13          |
| 7      | Ledger attribution vs erasure; pseudonymisation of deactivated users             | Counsel + product  | 11          |
| 8      | Rights response time (\[30\] days) and processor breach window (\[24/48\] hours) | GDC                | 10, 11      |
| 9      | Amharic translation                                                              | GDC                | All         |

# Annex B — Research references

Reviewed as drafting references, not copied. Verify current versions and official texts before publication.

**Ethiopian law and guidance**

- Personal Data Protection Proclamation No. 1321/2024 — Ministry of Justice: https://justice.gov.et/en/law/personal-data-protection-proclamation/ ; ECA: https://pdp.eca.et/pdp-proclamation ; text transcription: https://www.metaappz.com/References/ethiopian_laws/federal/pr_1321_2024/en/txt

- DLA Piper, Data Protection Laws of the World — Ethiopia: https://www.dlapiperdataprotection.com/index.html?t=law&c=ET

- Mondaq, Ethiopian Personal Data Protection Law: Business Compliance Guide (2026): https://www.mondaq.com/privacy-protection/1766200/

- Haymanot & Advocates, Ethiopia Personal Data Protection Q&A: https://www.haymanotbelay.com/ethiopia-personal-data-protection-qa-guide/

- Mehrteab & Leul, Legal Update on Personal Data Protection: https://mehrteableul.com/insight/legal-update-on-personal-data-protection-under-the-ethiopian-regime/

- Techhive Advisory, Review of Ethiopia’s Data Protection Act: https://www.techhiveadvisory.africa/insights/review-of-ethiopias-data-protection-act

- Computer Crime Proclamation No. 958/2016 and Electronic Transaction Proclamation No. 1205/2020 (summaries): https://www.dlapiperdataprotection.com/index.html?t=law&c=ET

- Record retention — PwC Tax Summaries, Ethiopia: https://taxsummaries.pwc.com/ethiopia/corporate/tax-administration

**Comparable SaaS inventory providers**

- Fishbowl — Privacy Statement: https://www.fishbowlinventory.com/legal/privacy

- Odoo — Privacy Policy: https://www.odoo.com/privacy

- Zoho — Terms of Service: https://www.zoho.com/terms.html

- Bloom Inventory (Ethiopia) — Privacy Policy: https://www.inventory.et/privacy
