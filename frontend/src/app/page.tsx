import Link from "next/link";

/* ─────────────────────────────────────────────────────────────────────────────
   SMART Inventory Tracker — Homepage
   All colours are inline styles. No custom Tailwind tokens used.
   Safe to render on first load without any Tailwind config rebuild.
───────────────────────────────────────────────────────────────────────────── */

const BG   = "#0f2d1f";   // deep forest hero bg
const MID  = "#1B4332";   // mid green
const GOLD = "#FCDD09";   // Ethiopian gold — primary CTA
const TEXT = "#f0fdf4";   // near-white text on dark

/* ── Small reusable logo mark ─────────────────────────────────────────────── */
function Logo({ size = 36 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none" aria-hidden="true">
      <rect width="40" height="40" rx="8" fill={GOLD} />
      <polygon points="20,4 36,12 36,24 20,32 4,24 4,12" fill={BG} />
      <polygon points="20,10 30,16 30,23 20,29 10,23 10,16" fill={GOLD} />
      <polygon points="20,16 25,19 25,23 20,26 15,23 15,19" fill={BG} />
    </svg>
  );
}

/* ── Ethiopian 3-colour stripe ────────────────────────────────────────────── */
function Stripe({ h = 5 }: { h?: number }) {
  return (
    <div
      aria-hidden="true"
      className="eth-stripe w-full"
      style={{ height: h }}
    />
  );
}

/* ── Wave SVG divider ─────────────────────────────────────────────────────── */
function Wave({ from, to, flip }: { from: string; to: string; flip?: boolean }) {
  const path = flip
    ? "M0,40 C240,0 480,80 720,40 C960,0 1200,80 1440,40 L1440,0 L0,0 Z"
    : "M0,40 C240,80 480,0 720,40 C960,80 1200,0 1440,40 L1440,80 L0,80 Z";
  return (
    <div style={{ overflow: "hidden", lineHeight: 0, margin: "-1px 0" }}>
      <svg viewBox="0 0 1440 80" preserveAspectRatio="none"
        style={{ display: "block", width: "100%", height: 64 }}>
        <rect width="1440" height="80" fill={from} />
        <path d={path} fill={to} />
      </svg>
    </div>
  );
}

/* ── Animated background lines (disappear at centre, reappear opposite side) ─ */
const LINES = [
  { top:  "8%",  dur: 9,  del: 0,   dir: "right", op: 0.10 },
  { top: "18%",  dur: 13, del: -4,  dir: "left",  op: 0.07 },
  { top: "28%",  dur: 11, del: -2,  dir: "right", op: 0.09 },
  { top: "38%",  dur: 16, del: -7,  dir: "left",  op: 0.06 },
  { top: "50%",  dur: 10, del: -1,  dir: "right", op: 0.08 },
  { top: "62%",  dur: 14, del: -5,  dir: "left",  op: 0.07 },
  { top: "72%",  dur: 12, del: -3,  dir: "right", op: 0.09 },
  { top: "84%",  dur: 8,  del: -6,  dir: "left",  op: 0.06 },
  { top: "93%",  dur: 15, del: -9,  dir: "right", op: 0.05 },
] as const;

function HeroLines() {
  return (
    /* The radial gradient mask fades lines to transparent at the centre
       where the title sits, then brings them back at the edges.
       As each streak passes through the transparent zone it vanishes,
       and when it exits on the far side it reappears — the "disappear
       and come from the other end" effect. */
    <div
      aria-hidden="true"
      className="hero-lines-mask"
      style={{ position: "absolute", inset: 0, overflow: "hidden" }}
    >
      {LINES.map((l, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            top: l.top,
            left: 0,
            right: 0,
            height: 1,
            overflow: "hidden",
          }}
        >
          {/* The moving streak — a soft gradient blob that sweeps the line */}
          <div
            style={{
              position: "absolute",
              top: 0,
              width: "35%",
              height: "100%",
              background: `linear-gradient(to right,
                transparent 0%,
                rgba(255,255,255,${l.op}) 40%,
                rgba(252,221,9,${l.op * 0.6}) 50%,
                rgba(255,255,255,${l.op}) 60%,
                transparent 100%)`,
              animation: `${l.dir === "right" ? "sweep-right" : "sweep-left"} ${l.dur}s ${l.del}s linear infinite`,
            }}
          />
        </div>
      ))}
    </div>
  );
}

/* ── Homepage ─────────────────────────────────────────────────────────────── */
export default function HomePage() {
  return (
    <div style={{ minHeight: "100vh", background: "#fff", overflowX: "hidden" }}>

      {/* ════════════════ STICKY NAVBAR ════════════════════════════════════ */}
      <nav style={{
        position: "fixed", top: 0, left: 0, right: 0, zIndex: 50,
        background: "#fff", borderBottom: "1px solid #e5e7eb",
        boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
      }}>
        <div style={{
          maxWidth: 1200, margin: "0 auto",
          padding: "0 1.5rem", height: 56,
          display: "flex", alignItems: "center", gap: "1.5rem",
        }}>
          {/* Logo + brand name */}
          <Link href="/" style={{ display: "flex", alignItems: "center", gap: 8, textDecoration: "none" }}>
            <Logo size={32} />
            <span style={{ fontWeight: 700, fontSize: 15, color: BG, whiteSpace: "nowrap" }}>
              SMART <span style={{ color: "#2D6A4F", fontWeight: 500 }}>Inventory</span>
            </span>
          </Link>

          {/* Centre nav links */}
          <div style={{ display: "flex", alignItems: "center", gap: "2rem", margin: "0 auto" }}>
            {["#features", "#tenants", "#credentials"].map((href, i) => (
              <a key={i} href={href} style={{
                fontSize: 14, fontWeight: 500, color: "#374151",
                textDecoration: "none", transition: "color 0.15s",
              }}
                onMouseEnter={e => (e.currentTarget.style.color = MID)}
                onMouseLeave={e => (e.currentTarget.style.color = "#374151")}
              >
                {["Features", "Tenants", "Credentials"][i]}
              </a>
            ))}
          </div>

          {/* Far-right: Sign in — light gray square button */}
          <Link href="/login" style={{
            marginLeft: "auto",
            padding: "8px 20px",
            background: "#F3F4F6",
            color: "#374151",
            fontSize: 13,
            fontWeight: 600,
            borderRadius: 4,
            textDecoration: "none",
            border: "1px solid #D1D5DB",
            transition: "background 0.15s",
            whiteSpace: "nowrap",
          }}
            onMouseEnter={e => (e.currentTarget.style.background = "#E5E7EB")}
            onMouseLeave={e => (e.currentTarget.style.background = "#F3F4F6")}
          >
            Sign in
          </Link>
        </div>
      </nav>

      {/* ════════════════ HERO — centred, animated background ══════════════ */}
      <section style={{
        paddingTop: 56,
        position: "relative",
        background: `linear-gradient(170deg, ${BG} 0%, #1B4332 55%, #2D6A4F 100%)`,
        textAlign: "center",
      }}>
        {/* Animated lines behind the title */}
        <HeroLines />

        {/* Content sits above lines */}
        <div style={{ position: "relative", zIndex: 1, maxWidth: 800, margin: "0 auto", padding: "6rem 1.5rem 5rem" }}>

          {/* Big centred logo */}
          <div style={{ display: "flex", justifyContent: "center", marginBottom: "1.75rem" }}>
            <Logo size={80} />
          </div>

          {/* Big centred heading */}
          <h1 style={{
            fontSize: "clamp(2.5rem, 6vw, 4.5rem)",
            fontWeight: 800,
            color: "#ffffff",
            lineHeight: 1.08,
            letterSpacing: "-0.02em",
            margin: 0,
          }}>
            SMART Inventory
            <span style={{ display: "block", color: GOLD }}>Tracker</span>
          </h1>

          <p style={{
            marginTop: "1.25rem",
            fontSize: "clamp(1rem, 2vw, 1.2rem)",
            color: "rgba(240,253,244,0.85)",
            lineHeight: 1.6,
            maxWidth: 540,
            marginLeft: "auto",
            marginRight: "auto",
          }}>
            Real-time stock ledger · FEFO dispatch · Offline barcode scanning ·
            3-layer security — built for Ethiopian producers and distributors.
          </p>

          {/* Language badge */}
          <div style={{ marginTop: "1.5rem", display: "flex", justifyContent: "center" }}>
            <span style={{
              display: "inline-flex", alignItems: "center", gap: 8,
              padding: "6px 16px",
              background: "rgba(255,255,255,0.08)",
              border: "1px solid rgba(255,255,255,0.18)",
              borderRadius: 100,
              fontSize: 12, fontWeight: 500, color: "rgba(200,240,220,0.9)",
            }}>
              <span style={{
                width: 8, height: 8, borderRadius: "50%",
                background: "#4ade80",
                animation: "pulse 2s ease-in-out infinite",
              }} />
              🇪🇹 &nbsp;English · አማርኛ · Afaan Oromoo · Offline-ready · Multi-tenant
            </span>
          </div>

          {/* CTAs */}
          <div style={{ marginTop: "2rem", display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
            <Link href="/login" style={{
              padding: "12px 32px",
              background: GOLD,
              color: BG,
              fontWeight: 700,
              fontSize: 14,
              borderRadius: 4,
              textDecoration: "none",
              boxShadow: "0 4px 20px rgba(252,221,9,0.35)",
            }}>
              Open Dashboard →
            </Link>
            <a href="#features" style={{
              padding: "12px 32px",
              border: "2px solid rgba(255,255,255,0.35)",
              color: "#fff",
              fontWeight: 600,
              fontSize: 14,
              borderRadius: 4,
              textDecoration: "none",
            }}>
              Explore Features
            </a>
          </div>

          {/* Credential hint */}
          <p style={{
            marginTop: "2rem",
            fontSize: 12,
            fontFamily: "monospace",
            color: "#6ee7b7",
            background: "rgba(0,0,0,0.25)",
            border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: 4,
            padding: "10px 20px",
            display: "inline-block",
          }}>
            📧 smartadmin@smart-inventory.com &nbsp;·&nbsp; 🔑 SmartAdmin@2026
          </p>
        </div>

        <Stripe h={6} />
      </section>

      {/* ════════════════ STATS ════════════════════════════════════════════ */}
      <section style={{ background: MID, padding: "2.5rem 1.5rem" }}>
        <div style={{
          maxWidth: 1000, margin: "0 auto",
          display: "grid", gridTemplateColumns: "repeat(4,1fr)",
          gap: "2rem", textAlign: "center",
        }}>
          {STATS.map((s) => (
            <div key={s.label}>
              <p style={{ fontSize: "2.25rem", fontWeight: 800, color: GOLD, margin: 0 }}>{s.value}</p>
              <p style={{ fontSize: 13, fontWeight: 600, color: "#fff", marginTop: 4 }}>{s.label}</p>
              <p style={{ fontSize: 11, color: "#86efac", marginTop: 2 }}>{s.sub}</p>
            </div>
          ))}
        </div>
      </section>

      <Wave from={MID} to="#fff" />

      {/* ════════════════ PLATFORM CAPABILITIES — 3-col rectangles ════════ */}
      <section id="features" style={{ background: "#fff", padding: "5rem 1.5rem" }}>
        <div style={{ maxWidth: 1200, margin: "0 auto" }}>
          {/* Section heading */}
          <div style={{ textAlign: "center", marginBottom: "3.5rem" }}>
            <span style={{
              display: "inline-block", fontSize: 11, fontWeight: 700,
              textTransform: "uppercase", letterSpacing: "0.1em",
              color: "#2D6A4F", background: "#D1FAE5",
              padding: "4px 12px", borderRadius: 100, marginBottom: 12,
            }}>
              Platform Capabilities
            </span>
            <h2 style={{ fontSize: "2rem", fontWeight: 800, color: BG, margin: 0 }}>
              Everything your warehouse team needs
            </h2>
            <p style={{ fontSize: 15, color: "#6B7280", marginTop: 8, maxWidth: 520, marginLeft: "auto", marginRight: "auto" }}>
              From barcode scanning on the warehouse floor to AI-powered demand forecasting.
            </p>
          </div>

          {/* 3-column bordered rectangle grid — 2 rows stacked */}
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            border: "1px solid #D1D5DB",
          }}>
            {FEATURES.map((f, i) => (
              <div key={f.title} className="cap-card" style={{
                /* Remove double borders on right/bottom edges */
                borderRight: (i % 3 === 2) ? "none" : "1px solid #D1D5DB",
                borderBottom: (i >= 3)     ? "none" : "1px solid #D1D5DB",
              }}>
                {/* Coloured top accent strip */}
                <div style={{ height: 3, background: f.accent, borderRadius: 2, marginBottom: "1.5rem" }} />
                <div style={{ fontSize: "1.75rem", marginBottom: "0.75rem" }}>{f.icon}</div>
                <h3 style={{ fontSize: 15, fontWeight: 700, color: BG, margin: "0 0 8px" }}>{f.title}</h3>
                <p style={{ fontSize: 13, color: "#6B7280", lineHeight: 1.6, margin: 0 }}>{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <Wave from="#fff" to="#F3F4F6" flip />
      <Stripe h={4} />

      {/* ════════════════ TENANT SHOWCASE ══════════════════════════════════ */}
      <section id="tenants" style={{ background: "#F3F4F6", padding: "5rem 1.5rem" }}>
        <div style={{ maxWidth: 1200, margin: "0 auto" }}>
          <div style={{ textAlign: "center", marginBottom: "3rem" }}>
            <span style={{
              display: "inline-block", fontSize: 11, fontWeight: 700,
              textTransform: "uppercase", letterSpacing: "0.1em",
              color: "#2D6A4F", background: "#D1FAE5",
              padding: "4px 12px", borderRadius: 100, marginBottom: 12,
            }}>
              Live Demo Tenants
            </span>
            <h2 style={{ fontSize: "2rem", fontWeight: 800, color: BG, margin: 0 }}>
              Two live companies, ready to explore
            </h2>
            <p style={{ fontSize: 14, color: "#6B7280", marginTop: 8 }}>
              Sign in as SA to switch between tenants. Sign in as WM to see only your warehouse.
            </p>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(2,1fr)", gap: "2rem" }}>
            {TENANTS.map((t) => (
              <Link key={t.slug} href={`/dashboard/tenants/${t.slug}`} style={{ textDecoration: "none" }}>
                <div style={{
                  background: "#fff",
                  border: "1px solid #D1D5DB",
                  borderRadius: 4,
                  overflow: "hidden",
                  transition: "box-shadow 0.2s, transform 0.2s",
                }}
                  onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.boxShadow = "0 8px 24px rgba(0,0,0,0.1)"; (e.currentTarget as HTMLDivElement).style.transform = "translateY(-3px)"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.boxShadow = "none"; (e.currentTarget as HTMLDivElement).style.transform = "none"; }}
                >
                  {/* Coloured header */}
                  <div style={{ background: t.color, padding: "1.25rem 1.5rem", display: "flex", alignItems: "center", gap: 12 }}>
                    <span style={{ fontSize: "2.5rem" }}>{t.icon}</span>
                    <div>
                      <p style={{ fontWeight: 700, fontSize: 18, color: "#fff", margin: 0 }}>{t.name}</p>
                      <p style={{ fontSize: 13, color: "rgba(255,255,255,0.75)", margin: 0 }}>{t.industry}</p>
                    </div>
                    <span style={{
                      marginLeft: "auto", fontSize: 11, fontWeight: 700,
                      background: "rgba(0,0,0,0.2)", color: "#fff",
                      padding: "3px 8px", borderRadius: 3,
                    }}>{t.orgType}</span>
                  </div>

                  {/* Body */}
                  <div style={{ padding: "1.25rem 1.5rem", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem" }}>
                    <div>
                      <p style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.07em", color: "#9CA3AF", marginBottom: 8 }}>Locations</p>
                      {t.warehouses.map((w) => (
                        <p key={w} style={{ fontSize: 13, color: "#374151", margin: "3px 0", display: "flex", alignItems: "center", gap: 6 }}>
                          <span style={{ width: 6, height: 6, borderRadius: "50%", background: t.color, flexShrink: 0 }} />
                          {w}
                        </p>
                      ))}
                    </div>
                    <div>
                      <p style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.07em", color: "#9CA3AF", marginBottom: 8 }}>Products</p>
                      {t.categories.map((c) => (
                        <p key={c} style={{ fontSize: 13, color: "#374151", margin: "3px 0", display: "flex", alignItems: "center", gap: 6 }}>
                          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#D1D5DB", flexShrink: 0 }} />
                          {c}
                        </p>
                      ))}
                    </div>
                  </div>

                  <div style={{
                    padding: "10px 1.5rem",
                    borderTop: "1px solid #F3F4F6",
                    background: "#FAFAFA",
                    display: "flex", justifyContent: "space-between", alignItems: "center",
                  }}>
                    <span style={{ fontSize: 12, color: "#9CA3AF" }}>{t.skuCount} SKUs · {t.userCount} user accounts</span>
                    <span style={{ fontSize: 12, fontWeight: 700, color: t.color }}>Open dashboard →</span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <Stripe h={4} />
      <Wave from="#F3F4F6" to={BG} flip />

      {/* ════════════════ CREDENTIALS CTA ══════════════════════════════════ */}
      <section id="credentials" style={{ background: BG, padding: "5rem 1.5rem", textAlign: "center" }}>
        <div style={{ maxWidth: 860, margin: "0 auto" }}>
          <h2 style={{ fontSize: "2rem", fontWeight: 800, color: "#fff", margin: 0 }}>
            Start exploring the demo
          </h2>
          <p style={{ fontSize: 14, color: "#6ee7b7", marginTop: 8, marginBottom: "3rem" }}>
            Each role is scoped to its own data — WMs see only their warehouse, NMs their center.
          </p>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "1rem", marginBottom: "2.5rem", textAlign: "left" }}>
            {CREDS.map((c) => (
              <div key={c.email} style={{
                padding: "1rem", borderRadius: 4,
                background: "rgba(255,255,255,0.05)",
                border: "1px solid rgba(255,255,255,0.1)",
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                  <span style={{
                    fontSize: 11, fontWeight: 700, color: "#fff",
                    background: c.roleColor, padding: "2px 7px", borderRadius: 3,
                  }}>{c.role}</span>
                  <span style={{ fontSize: 12, color: "#6ee7b7", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.company}</span>
                </div>
                <p style={{ fontSize: 12, fontFamily: "monospace", color: "#a7f3d0", wordBreak: "break-all", margin: "0 0 4px" }}>{c.email}</p>
                <p style={{ fontSize: 12, fontFamily: "monospace", color: "#6ee7b7", margin: 0 }}>{c.pw}</p>
              </div>
            ))}
          </div>

          <Link href="/login" style={{
            display: "inline-block",
            padding: "14px 40px",
            background: GOLD,
            color: BG,
            fontWeight: 700,
            fontSize: 15,
            borderRadius: 4,
            textDecoration: "none",
            boxShadow: "0 4px 20px rgba(252,221,9,0.3)",
          }}>
            Sign in to dashboard →
          </Link>
        </div>
      </section>

      {/* ════════════════ FOOTER ═══════════════════════════════════════════ */}
      <Stripe h={5} />
      <footer style={{ background: "#061410", padding: "2rem 1.5rem" }}>
        <div style={{
          maxWidth: 1200, margin: "0 auto",
          display: "flex", flexWrap: "wrap",
          alignItems: "center", justifyContent: "space-between", gap: "1rem",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Logo size={24} />
            <div>
              <p style={{ fontWeight: 700, fontSize: 14, color: "#fff", margin: 0 }}>SMART Inventory Tracker</p>
              <p style={{ fontSize: 11, color: "#166534", margin: 0 }}>PRD v4.0 · Phase 0</p>
            </div>
          </div>
          <p style={{ fontSize: 12, color: "#166534" }}>FastAPI · Next.js 14 · PostgreSQL 16 · AWS ECS Fargate</p>
          <p style={{ fontSize: 12, color: "#166534" }}>🇪🇹 EN · አማርኛ · Afaan Oromoo</p>
        </div>
      </footer>
    </div>
  );
}

/* ─── Static data ────────────────────────────────────────────────────────── */

const STATS = [
  { value: "115",   label: "Permission Actions", sub: "RBAC + ABAC enforcement" },
  { value: "10",    label: "Microservices",       sub: "FastAPI + Next.js 14"   },
  { value: "3",     label: "Languages",           sub: "EN · አማርኛ · Oromoo"    },
  { value: "99.9%", label: "Uptime SLA",          sub: "AWS ECS Fargate"        },
];

const FEATURES = [
  { icon: "📦", accent: "#40916C", title: "Immutable Inventory Ledger",   desc: "Every stock movement is an append-only INSERT. Balances are derived — nothing is ever overwritten or deleted." },
  { icon: "🔐", accent: "#FCDD09", title: "RBAC + ABAC Security",         desc: "115 permission actions enforced at 3 layers: API Gateway, service level, and PostgreSQL Row-Level Security." },
  { icon: "🏭", accent: "#DA121A", title: "Multi-Location Hierarchy",     desc: "Production centers, warehouses, and sub-centers in a parent–child tree. Users are auto-scoped to their location." },
  { icon: "📱", accent: "#0891B2", title: "Offline PWA + Barcode Scan",   desc: "Record movements offline via camera scan. IndexedDB queue syncs automatically when connectivity returns." },
  { icon: "⚡", accent: "#7C3AED", title: "FEFO Dispatch Engine",         desc: "Auto-enforced when expiry tracking is active. Override requires explicit permission + reason code + audit trail." },
  { icon: "🌍", accent: "#078930", title: "EN · Amharic · Oromifa",       desc: "Language packs served from S3 CDN, cached by service worker. Switch per-user. Native speaker review for Oromifa." },
];

const TENANTS = [
  {
    name: "Addis Water", slug: "addis-water", icon: "💧",
    industry: "Bottled Water · Producer", orgType: "PRODUCER",
    color: "#0891B2", skuCount: 10, userCount: 7,
    warehouses: ["Main Production Center", "North WH", "  ↳ North-Subcenter WH", "South WH", "East WH", "West WH"],
    categories: ["Still Water — 500ml, 1L, 1.5L packs", "Sparkling Water — 500ml, 1L", "Pack sizes: 6 · 12 · 24 units"],
  },
  {
    name: "Muger Cement", slug: "muger-cement", icon: "🏗️",
    industry: "Cement Manufacturing · Producer", orgType: "PRODUCER",
    color: "#D97706", skuCount: 10, userCount: 7,
    warehouses: ["Harar Production Center", "Ambo Production Center", "Kombolcha WH", "Mekele WH", "Dire Dawa WH", "Hawassa WH"],
    categories: ["OPC 42.5N & 32.5R", "Portland Pozzolana (PPC)", "Sulphate Resistant (SRC)", "White Portland (WPC)", "Bags: 25kg · 50kg"],
  },
];

const CREDS = [
  { role: "SA", roleColor: "#DC2626", company: "All tenants",  email: "smartadmin@smart-inventory.com", pw: "SmartAdmin@2026" },
  { role: "TA", roleColor: "#7C3AED", company: "Addis Water",  email: "admin@addis-water.com",          pw: "AddisWater@2026"  },
  { role: "TA", roleColor: "#D97706", company: "Muger Cement", email: "admin@muger-cement.com",         pw: "MugerCement@2026" },
];
