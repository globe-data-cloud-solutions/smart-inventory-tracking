# SMART Inventory — User Setup & Onboarding Guide

**Version:** 1.0 | **Updated:** June 2026 | **Audience:** Tenant Administrators & Organisation Managers

> **Pre-Launch Reminder:** Replace all `[SCREENSHOT PLACEHOLDER]` notes with real screenshots before sharing with customers.

---

## How to Use This Guide

This guide covers two audiences:

| Audience | Sections |
|----------|----------|
| **All Users** (NM, RM, WM, LM, AU) | Steps 7–8, NM Quick Reference, Common Questions |
| **🔒 Tenant Administrator (TA) Only** | Steps 1–6, 9, User Management, Approval Rule Changes |

> **TA-only sections** are marked with 🔒 throughout this guide.

**Estimated setup time:** 45–90 minutes for initial configuration.

---

## Before You Begin

Have the following ready:
- Your organisation chart (levels, names, locations)
- List of all staff with their roles and locations
- Transfer and approval policies (who approves what, at what quantities)
- Product list (names, SKUs, units of measure, categories)
- Organisation logo and banner image (optional, for branding)

### Login
- **URL:** Your SMART Inventory URL (provided by your administrator)
- **TA Email:** `admin@your-slug.com`
- **Initial Password:** Provided during onboarding

---

## System Roles — Predefined by SMART

SMART uses a fixed set of roles. These are defined by the platform and cannot be changed — you assign staff to these roles when creating positions and user accounts.

| Role | Code | Scope | What They Do |
|------|------|-------|-------------|
| Super Admin | SA | Platform-wide | Platform operator only — manages all tenants. Not used within your organisation. |
| Tenant Administrator | TA | Full tenant | Configures the entire tenant — org structure, approval rules, users, branding. You are this role. |
| National Manager | NM | Full tenant | Senior operational role — approves high-value transfers, oversees all facilities, creates products. |
| Regional Manager | RM | Regional scope | Mid-level role — approves transfers within their region, manages regional stock. |
| Warehouse Manager | WM | Warehouse scope | Operational role — creates transfers, receives stock, submits adjustments at their warehouse. |
| Logistics Manager | LM | Tenant-wide | Read-only operational view — monitors transfers and stock movements across the organisation. |
| Auditor | AU | Tenant-wide | Read-only compliance role — views all audit logs, transactions, and reports. Cannot create or modify anything. |

### Role Hierarchy
TA (highest tenant authority)

└── NM (National/Factory level)

└── RM (Regional level)

└── WM (Warehouse level)

LM (cross-cutting, read-mostly)

AU (cross-cutting, read-only)

### How Roles Map to Your Organisation

When you create a **Position** (Step 3), you assign it one of these role codes:

- **L1 nodes** (top level, e.g. Main Factory) → assign **NM** positions
- **L2 nodes** (e.g. Regional Center) → assign **RM** positions
- **L3 nodes** (e.g. Sub Region) → assign **RM** positions
- **L4 nodes** (e.g. Warehouse Area, stock-holding) → assign **WM** positions
- **Tenant-wide** (not tied to a node) → **AU** and **LM** positions

> **Note:** The TA role is your administrator account only — you do not create TA positions for regular staff. NM is the highest role your operational staff will use.

---

## Setup Order

Complete these steps in order — each step depends on the previous one.

| Step | What | Where |
|------|------|-------|
| 1 🔒 | Organisation Levels | Org Setup → Organisation Levels |
| 2 🔒 | Organisation Tree | Org Setup → Organisation Tree |
| 3 🔒 | Positions | Org Setup → Positions |
| 4 🔒 | Transfer Types | Org Setup → Transfer Types |
| 5 🔒 | Approval Rules | Org Setup → Approval Rules |
| 6 🔒 | Personnel (Users) | Org Setup → Personnel |
| 7 | Products & Categories | Products page |
| 8 | Opening Stock | Inventory → Receive Stock |
| 9 🔒 | Branding (optional) | Org Setup → Branding |

---

## 🔒 Step 1 — Organisation Levels (TA Only)

*Org Setup → Organisation Levels tab*

Define how many levels your organisation has and what each level is called.

1. Go to Org Setup → click "Organisation Levels"
2. Enter the number of levels (typically 3–5)
3. Name each level in plain language
4. Mark the lowest level as **Stock Holding** — this is where physical stock is tracked
5. Save — you **cannot** change level count after adding org nodes

**⚠️ Set this carefully — it cannot be changed once you start building the org tree.**

Example 4-level structure:

| Level | Example Name | Notes |
|-------|-------------|-------|
| L1 | Main Factory | Top of hierarchy |
| L2 | Regional Center | Regional hubs |
| L3 | Sub Region | Optional intermediate level |
| L4 ★ | Warehouse Area | ★ Mark as Stock Holding |

`[SCREENSHOT: Organisation Levels tab showing 4 levels configured]`

---

## 🔒 Step 2 — Organisation Tree (TA Only)

*Org Setup → Organisation Tree tab*

Create the actual nodes (factories, offices, warehouses) using the levels from Step 1.

1. Click "+ Add Node" and start with your top-level node (e.g. "Factory A")
2. Select the level (L1) and enter the name
3. Add child nodes — select the parent first, then add child
4. Repeat until your full org chart is in the system

**Tips:**
- Not all branches need the same depth (mixed-depth structures are supported)
- Use consistent, official names — they appear in reports and audit logs
- You can add more nodes later as your organisation grows

`[SCREENSHOT: Organisation Tree showing two-factory structure]`

---

## 🔒 Step 3 — Positions (TA Only)

*Org Setup → Positions tab*

Positions link people to nodes and determine what they can do.

1. For each node, create at least one main position
2. Recommended: add an assistant position for coverage
3. Set the title (appears in approval notifications and audit logs)
4. Select the role level: **NM** (top), **RM** (mid), **WM** (warehouse)

**Examples:**

| Node | Main Position | Assistant |
|------|--------------|-----------|
| Factory A (L1) | "HQ Director (NM)" | "Deputy HQ (Asst NM)" |
| Region A (L2) | "Region A Manager (RM)" | "Region A Deputy (Asst RM)" |
| WHA1 (L4) | "WHA1 Warehouse Manager (WM)" | "WHA1 Warehouse Assistant (WM)" |

💡 **Tip:** Position titles appear throughout the system — use official, recognisable titles.

`[SCREENSHOT: Positions tab showing positions for Factory A and Warehouse nodes]`

---

## 🔒 Step 4 — Transfer Types (TA Only)

*Org Setup → Transfer Types tab*

Customise the display names for the three transfer types.

| System Code | Default Name | What It Means |
|------------|-------------|---------------|
| PULL | Request Stock | Warehouse requests from a higher level |
| PUSH | Send Stock | Higher level pushes stock down |
| SISTER | Branch Exchange | Lateral transfer between warehouses |

For each transfer type:
1. Enter your organisation's preferred display name
2. Add a description (optional)
3. Set which levels can initiate it
4. Toggle Active/Inactive

`[SCREENSHOT: Transfer Types tab with custom display names]`

---

## 🔒 Step 5 — Approval Rules (TA Only)

*Org Setup → Approval Rules tab*

### Transfer Approval Rules

For each transfer type, create rules specifying:
- **From Level → To Level** (which direction this rule covers)
- **Quantity range** (0 to unlimited, or a specific range)
- **Approval steps** (who approves, in what order, within how many hours)

> **Example:** Request Stock | Warehouse Area → Sub Region | Qty: 5,001+ units | Step 1: Sub Region Manager (24h) | Step 2: Regional Manager (48h)

`[SCREENSHOT: Transfer Rules showing multi-step rule configuration]`

### Adjustment Approval Rules

Define when stock adjustments need approval by quantity per role level.

### Self-Approval Limits

Set a blanket self-approval quantity per role — transfers below this limit are automatically approved:

| Role | Example Limit |
|------|--------------|
| Warehouse Manager (WM) | Up to 5,000 units — self-approved instantly |
| Regional Manager (RM) | Up to 20,000 units — self-approved instantly |
| Factory Manager (NM) | Unlimited — all transfers self-approved |

💡 **Tip:** After setting up rules, check the **Approval Policies** page for a plain-language summary.

---

## 🔒 Step 6 — Personnel (Adding Users) (TA Only)

*Org Setup → Personnel tab*

1. Click "+ Add Person" and enter name and email
2. Select their system role (NM / RM / WM / LM / AU)
3. Assign them to a position (links them to their org node)
4. Set an initial password (they'll be prompted to change on first login)
5. Repeat for all staff

**Email format suggestion:** `role_locationname@yourcompany.com`
- Example: `wm_warehouse1@company.com`
- Example: `rm_region_a@company.com`

👥 **Note:** A person can be assigned to multiple positions — their permissions are the combination of all assigned positions.

`[SCREENSHOT: Personnel tab showing user list with positions assigned]`

---

## Step 7 — Products & Categories

*Products page — TA and NM can create products; all roles can view*

### 🔒 Creating Product Categories (TA Only)

1. Go to Products → Categories
2. Click "+ Add Category" and enter a name (e.g. "Raw Materials", "Finished Goods")
3. Create all categories before adding products

### Adding Products (TA and NM)

1. Go to Products → click "+ Add Product"
2. Enter the product name, SKU (or auto-generate), and select a category
3. Enter a **Type Code** — 2–10 alphanumeric characters (e.g. RAW, FIN, PKG)
4. Select Unit of Measure (KG, Piece, Box, Roll, etc.)
5. Upload a product image (optional, max 2MB, JPG/PNG/WebP)
6. Click Save

`[SCREENSHOT: Add Product panel with all fields filled]`

### 🔒 Controlled Products — Special Approval Rules (TA Only)

For high-value or sensitive items that always require approval regardless of quantity:

1. Create the product first, then open it for editing
2. Scroll to "Minimum Approval Level" section
3. Enable the override for relevant transfer types
4. Choose: **Always** require approval, OR **above a quantity threshold**
5. Select which position must approve
6. Save — a 🔒 icon will appear on the product

---

## Step 8 — Opening Stock

*Inventory page → Receive Stock — NM and TA can enter opening stock*

Before going live, record existing stock at each warehouse.

1. Go to the Inventory page
2. Select the warehouse
3. Click "Receive Stock"
4. Select the product and enter the opening quantity
5. Add a note (e.g. "Opening balance — June 2026")
6. Submit — stock is added to the ledger immediately
7. Repeat for each product at each warehouse

**⚠️ Important:** Opening stock entries are permanent and cannot be deleted (the ledger is immutable for audit purposes). Use Adjustments with reason code `COUNT_CORRECTION` to fix errors.

`[SCREENSHOT: Receive Stock panel with product and quantity fields]`

---

## 🔒 Step 9 — Branding (Optional, TA Only)

*Org Setup → Branding tab*

| Item | Specs |
|------|-------|
| Organisation Logo | Max 1MB, JPG/PNG/WebP. Shows in navigation header. |
| Organisation Banner | Max 3MB, JPG/PNG/WebP. Shows on Dashboard. |

1. Go to Org Setup → Branding tab
2. Upload logo and banner
3. Save — appears immediately across the platform

`[SCREENSHOT: Branding tab with logo and banner upload]`

---

## Organisation Manager (NM) — Quick Reference

*This section is for Organisation Managers and operational staff.*

### Your Responsibilities
- Create and manage products
- Review and approve transfers
- Initiate Send Stock (PUSH) transfers
- Monitor stock levels
- View approval policies

### Approving Transfers

1. Go to Transfers page
2. Find transfers with status "Pending Review" or "Pending Approval"
3. Review details (product, quantity, source, destination)
4. Click **Review** then **Approve** — or **Reject** if not appropriate

### Issuing & Dispatching Stock

1. Find an Approved transfer in the Transfers page
2. Click **Issue** to confirm stock is ready to move
3. Click **Dispatch** to confirm it has left the source
4. The destination WM will then receive it

> **Acting on Behalf:** If you Issue/Dispatch a transfer where the source warehouse belongs to another facility, the system shows "Acting on behalf of: [Warehouse Name]" and records this in the audit log.

### Viewing Approval Policies

Go to **Approval Policies** in the navigation to see:
- Your self-approval limits per transaction type
- Which products have 🔒 special approval requirements
- Full policy matrix (TA/SA see all levels)

---

## Ongoing Administration

### 🔒 Adding a New User (TA Only)
1. Org Setup → Personnel → "+ Add Person"
2. Enter name, email, role, assign to position, set password
3. Share credentials securely

### 🔒 Deactivating a User (TA Only)
1. Personnel list → find user → toggle Active to off
2. Account is immediately locked

> **⚠️ Note:** If a deactivated user has pending approvals, contact your SMART administrator. Automatic re-routing is coming in a future update.

### 🔒 Adjusting Approval Rules (TA Only)
1. Org Setup → Approval Rules → find and edit the rule
2. Update quantities, steps, or approver positions
3. Save — changes take effect immediately

---

## Common Questions

**Q: Can I change the org structure after adding users?**
Yes — you can add new nodes and positions. Existing users keep their assignments. To remove a node, reassign its users first.

**Q: What if an approver is unavailable?**
As TA, you can approve on behalf of any position. Find the pending item and approve it — the audit log records that you acted on their behalf.

**Q: Can a user have more than one position?**
Yes. Their permissions are the union of all assigned positions — useful for managers covering multiple areas.

**Q: What does the 🔒 icon mean on a product?**
The product is Controlled — it has special approval rules that override normal transfer flow. Even small quantities require specific approval. See the Approval Policies page for details.

**Q: What is the difference between Adjustment and Receive Stock?**
- **Receive Stock** — stock arrives at a warehouse (from supplier or opening balance)
- **Adjustment** — corrects the stock count (damage, theft, count error)

**Q: Can I undo a completed transfer?**
No — the ledger is immutable for audit integrity. Create a reverse transfer or use an Adjustment with reason code `RETURN`.

**Q: Can I cancel a Branch Exchange after it has been approved?**
No — once a Branch Exchange reaches Approved status it cannot be cancelled. Both warehouse managers have confirmed and stock is committed to the transfer. If the transfer cannot physically proceed, complete the receipt at the destination and use a stock Adjustment (reason: RETURN or DAMAGE) to correct the balance. Contact your administrator for assistance.

**Q: How do I reset a user's password?**
Go to Settings → Personnel. Click the user's row to open their detail panel. Click "Reset Password" and confirm. The user's password will be reset to a temporary credential you provide. They will be forced to change it on their next login. You can use this for forgotten passwords or to unlock a compromised account.

**Q: What happens if a user gets locked out?**
After 5 consecutive failed login attempts, the account is automatically locked for 15 minutes. The user will see a message on the login screen. They can wait 15 minutes and retry, or contact you (the Tenant Admin) to verify they are using the correct credentials. The lockout clears automatically — no admin action is required. If the user successfully resets their password, the lockout counter is also cleared immediately.

**Q: Do I need to create separate adjustment rules for each warehouse or region?**
Yes. Each adjustment rule applies to the specific node it is configured for. If your organization has multiple warehouses or regions, you must create a separate rule for each one. A rule set for WHA1 will not automatically apply to WHA2 or WHB1. Work through each node systematically to ensure full coverage. A future update will allow you to apply rules across all nodes at the same org level in one step.

---

## Setup Checklist

### 🔒 Tenant Administrator Checklist

**Organisation Structure:**
- [ ] Organisation levels defined
- [ ] Organisation tree complete — all nodes created
- [ ] Positions created for every node (main + assistant recommended)
- [ ] Transfer types named with custom display names
- [ ] Transfer approval rules configured for all active types
- [ ] Adjustment approval rules configured
- [ ] Self-approval limits set per role level

**People & Products:**
- [ ] All staff added and assigned to positions
- [ ] Initial passwords shared securely
- [ ] Product categories created
- [ ] All products added with type codes and units
- [ ] Controlled products configured with 🔒 approval rules
- [ ] Product images uploaded (optional)
- [ ] Opening stock entered at all warehouse nodes

**Verification:**
- [ ] Approval Policies page reviewed — rules display correctly
- [ ] Test transfer created and approved through full lifecycle
- [ ] At least one WM, RM, and NM user confirmed access
- [ ] Branding uploaded (optional)
- [ ] Audit Log checked — setup actions recorded

---

> **📋 Pre-Launch Reminder:** Before sharing with customers, replace all screenshot placeholders with real screenshots. Translate to Amharic or Oromifa if required for Ethiopian customers. Review all TA-only sections against the final permission matrix.

---

*Document Version: 1.0 | Last Updated: June 2026 | Maintained by: Development team*
