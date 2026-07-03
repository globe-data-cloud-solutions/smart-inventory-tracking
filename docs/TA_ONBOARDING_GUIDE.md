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
| Logistics Manager | LM | Node-scoped (or tenant-wide if created without a position) | Read-only operational view — monitors transfers and stock movements. Scoped to their assigned node when given a position; see note below. |
| Auditor | AU | Tenant-wide | Read-only compliance role — views all audit logs, transactions, and reports. Cannot create or modify anything. |

> **Logistics Manager (LM) scope:** Logistics Managers are scoped to their assigned
> node and all nodes beneath it. An LM given a position at the factory level sees
> that factory's data and all regions, warehouses, and satellite depots below it.
> An LM given a position at a warehouse sees that warehouse and any satellite depots
> under it. An LM can also be created **without** a position (a tenant-wide account)
> — that account has unrestricted, tenant-wide read access since it has no node to
> scope to.

### Role Hierarchy
TA (highest tenant authority)

└── NM (National/Factory level)

└── RM (Regional level)

└── WM (Warehouse level)

LM (node-scoped when assigned a position; tenant-wide read-only otherwise)

AU (cross-cutting, read-only)

### How Roles Map to Your Organisation

When you create a **Position** (Step 3), you assign it one of these role codes:

- **L1 nodes** (top level, e.g. Main Factory) → assign **NM** positions
- **L2 nodes** (e.g. Regional Center) → assign **RM** positions
- **L3 nodes** (e.g. Sub Region) → assign **RM** positions
- **L4 nodes** (e.g. Warehouse Area, stock-holding) → assign **WM** positions
- **LM** positions can be created at **any node level** — the LM is then scoped to
  that exact node (see note above)
- **Tenant-wide** (not tied to a node) → **AU** positions, and **LM** accounts
  created without a position

> **Note:** The TA role is your administrator account only — you do not create TA positions for regular staff. NM is the highest role your operational staff will use.

---

## Setup Order

Complete these steps in order — each step depends on the previous one.

| Step | What | Where |
|------|------|-------|
| 1 🔒 | Organisation Levels | Org Setup → Organisation Levels |
| 2 🔒 | Organisation Tree | Org Setup → Organisation Tree |
| 3 🔒 | Positions | Org Setup → Positions |
| 4 🔒 | Personnel (Users) | Org Setup → Personnel |
| 5 🔒 | Transfer Types | Org Setup → Transfer Types |
| 6 🔒 | Approval Rules | Org Setup → Approval Rules |
| 7 | Products & Categories | Products page |
| 8 | Opening Stock | Inventory → Receive Stock |
| 9 🔒 | Branding (optional) | Org Setup → Branding |

---

## Plan Tiers

SMART tenants are on one of three plan tiers: **Starter**, **Growth**, or **Enterprise**. Your tier is assigned by your SMART administrator (the platform operator) and can only be changed by them — you cannot change your own tier from within the application.

| Tier | What it affects |
|------|----------------|
| Starter | Limited number of warehouses and staff accounts; Branch Exchange (Sister) transfers not available |
| Growth | Higher limits on warehouses and staff accounts; Branch Exchange transfers enabled |
| Enterprise | Highest limits; all features enabled |

**Specific limits** (maximum warehouses, maximum staff accounts) depend on your contract — ask your SMART administrator for the exact figures that apply to your organisation.

> **Branch Exchange (Sister) transfers — Starter tier restriction:** Lateral transfers
> between warehouses at the same level are not available on the Starter tier. If staff
> attempt to create one they will receive a plan-limit error. If this feature is
> required, contact your SMART administrator about upgrading to Growth or Enterprise.

> **Hitting a limit during setup:** If you receive an error when trying to add a
> warehouse (Step 2) or a staff account (Step 4), you have likely reached your plan
> limit. Contact your SMART administrator to request a tier upgrade rather than
> assuming it is a bug.

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
- Node creation is subject to your plan tier's warehouse limit — if you receive an error when adding a node, contact your SMART administrator to request more capacity rather than assuming it is a bug (see [Plan Tiers](#plan-tiers))

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

## 🔒 Step 4 — Personnel (Adding Users) (TA Only)

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

> **Staff account limit:** Adding accounts is subject to your plan tier's user limit. If you receive an error when adding a new person, you have reached your plan cap — contact your SMART administrator to request an upgrade rather than assuming it is a bug (see [Plan Tiers](#plan-tiers)).

`[SCREENSHOT: Personnel tab showing user list with positions assigned]`

---

## 🔒 Step 5 — Transfer Types (TA Only)

*Org Setup → Transfer Types tab*

Customise the display names for the three transfer types.

| System Code | Default Name | What It Means |
|------------|-------------|---------------|
| PULL | Request Stock | Warehouse requests from a higher level |
| PUSH | Send Stock | Higher level pushes stock down |
| SISTER | Branch Exchange | Lateral transfer between warehouses — **requires Growth tier or higher**; not available on Starter |

For each transfer type:
1. Enter your organisation's preferred display name
2. Add a description (optional)
3. Set which levels can initiate it
4. Toggle Active/Inactive

`[SCREENSHOT: Transfer Types tab with custom display names]`

---

## 🔒 Step 6 — Approval Rules (TA Only)

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

> **Important — Controlled products require two approver interactions per transfer:**
> When a warehouse manager creates a PULL for a controlled product, the transfer does
> NOT skip the normal review step. The full flow is:
> DRAFT → Pending Review → (reviewer advances) → Pending Approval → (override approver approves) → Approved
>
> This means the process takes longer than a standard transfer. Communicate this to your
> warehouse managers so they plan ahead — especially for time-sensitive stock movements.

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

### 🔒 Reactivating a User (TA Only)
1. Personnel list → find the inactive user → toggle Active back on
2. Their previous primary position is automatically restored — no need to manually reassign them
3. If they held additional positions (acting or delegate assignments), only the primary position is restored automatically; reassign any acting or delegate positions manually if still needed

### 🔒 Adjusting Approval Rules (TA Only)
1. Org Setup → Approval Rules → find and edit the rule
2. Update quantities, steps, or approver positions
3. Save — changes take effect immediately

### Known Limitations — Current Version

- **Adjustment approval position enforcement:** Adjustment approval rules specify a
  preferred approver position, but the system does not technically block other users
  with approval permission from approving. Enforce adjustment approval as a process
  discipline among your management team.

- **Transfer notes length:** Transfer notes are limited to 2000 characters.

- **PUSH /review not applicable:** PUSH and Sister transfers do not have a review
  step. Only PULL transfers go through the PENDING_REVIEW → PENDING_APPROVAL flow.
  Do not instruct staff to use the review action on PUSH transfers.

---

## Common Questions

**Q: Can I change the org structure after adding users?**
Yes — you can add new nodes and positions. Existing users keep their assignments. To remove a node, reassign its users first.

**Q: What if an approver is unavailable?**
As TA, you can approve on behalf of any position. Find the pending item in the
Transfers or Adjustments page and approve or reject it directly — the audit log
records that you acted on their behalf.

**Q: A transfer is stuck in Pending Approval and no one is actioning it — what do I do?**
This can happen when the assigned approver position becomes vacant (user deactivated
or reassigned) after the transfer was submitted. The system automatically escalates
stuck transfers to the Tenant Admin. To resolve:
1. Go to Transfers → filter by status "Pending Approval"
2. Find the stuck transfer and open it
3. Approve or reject it directly (the audit log records TA action)
4. Before creating new transfers from that node, assign a user to the approver
   position so future transfers route correctly

To prevent this: before deactivating any user who holds an approver position,
assign a replacement to that position first. The system will then route new
transfers to the replacement automatically.

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

**Q: What is the difference between a tenant-wide LM and a node-assigned LM?**
When creating a Logistics Manager, you have two options. A tenant-wide LM (created without a position assignment) has read visibility across the entire organization — useful for a head logistics coordinator overseeing all warehouses. A node-assigned LM is linked to a specific position at a node and sees that node and all nodes beneath it — useful for a logistics coordinator overseeing one warehouse and its satellite depots. Choose based on the staff member's actual operational scope.

---

**Q: What happens when I assign a second person to an approver position?**
The system allows multiple users to hold the same position simultaneously. However, when
a transfer or adjustment is routed to that position for approval, the system picks one
holder — typically the most recently assigned. This means adding a second person to an
approver position can cause approval tasks to route to the new holder instead of the
original. If approval routing seems to go to the wrong person, check how many active
users hold that position (Settings → Positions → view holders). Remove or adjust
assignments so only the intended approver holds it at any time, unless both are
genuinely co-approvers.

---

**Q: What happens if I deactivate a user who is an approver on pending transfers?**
When a user is deactivated, their position assignment is removed automatically. If they
were the designated approver on pending transfers or adjustments, those items will
escalate to the Tenant Admin for approval. You will see them appear in your approvals
queue. Before deactivating an approver, assign another user to their position so routing
continues uninterrupted.

---

**Q: Can adjustment approval rules specify who must approve?**
Adjustment approval rules define quantity thresholds and routing behaviour, but the
system does not enforce which specific named position must approve at the final step —
any user with adjustment approval permission can post a pending adjustment. If you need
strict control over who approves adjustments, communicate this as a process requirement
to your managers rather than relying on technical enforcement.

---

**Q: What can a Logistics Manager (LM) actually do in the system?**
LM is a logistics and dispatch-focused role — not an inventory operations role.
An LM can:
- View stock at their assigned node and all nodes beneath it
- View and list transfers
- Receive and dispatch shipments
- View adjustments and product information

An LM cannot:
- Create or submit transfers
- Create or submit adjustments
- Approve transfers or adjustments

If you need someone with broader operational access (approvals, creating transfers),
assign them a Warehouse Manager (WM) or Regional Manager (RM) role instead.
Note: if created without a node assignment (tenant-wide LM), the LM can view stock
across the entire organisation but still has the same action restrictions above.

---

**Q: Can all users initiate PUSH (Send Stock) transfers?**
No. PUSH transfers can only be initiated by users at Level 1 (Factory/Main) and
Level 2 (Regional) of your org hierarchy — typically NM and RM roles. This reflects
how stock flows in distribution: factories and regional hubs push stock downward to
warehouses, not the other way around.

Warehouse Managers (WM), Logistics Managers (LM), and satellite staff can only
initiate PULL (Request Stock) or Sister (lateral exchange) transfers. If a WM needs
stock sent to their warehouse, they should submit a PULL request — their NM or RM
will see and approve it.

---

**Q: I added a new satellite depot — do approval rules apply to it automatically?**
No. When you add a new node (warehouse or satellite), it has no transfer or adjustment
approval rules until you create them. Until rules are added, transfers from that node
will route through the system's default bands, which may not match your intended policy.
After creating any new node, go to Settings → Approval Rules and add the appropriate
transfer and adjustment rules for that node before staff begin using it.

---

**Q: A staff member was promoted or moved to a different role. What do I need to do?**
When reassigning a user to a new position:
1. Assign them PRIMARY at the new position (their scope updates immediately on next login)
2. Remove their old position assignment if they should no longer hold it
   — use force-remove (SA token required for sole PRIMARY removal)
3. If the old position had pending approvals routed to it, those will escalate to TA
   once the holder is removed — approve them or wait for the replacement to be assigned

If the user moves to a higher level (e.g. WM → RM), their old WM scope is replaced
by the new RM scope on next login. If they move to a lower level (e.g. RM → WM), their
access narrows accordingly. Always verify by having the user log out and back in after
any position change.

---

## Setup Checklist

### 🔒 Tenant Administrator Checklist

**Plan & Limits:**
- [ ] Confirmed your plan tier and limits with your SMART administrator before beginning setup

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

*Document Version: 1.1 | Last Updated: July 2026 | Maintained by: Development team*
