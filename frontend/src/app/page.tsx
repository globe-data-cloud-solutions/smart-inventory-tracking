import Link from "next/link";

const BG   = "#0f2d1f";
const GOLD = "#FCDD09";

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

function Stripe({ h = 5 }: { h?: number }) {
  /* inline: height is a runtime number — Tailwind JIT cannot build arbitrary px from JS vars */
  return <div aria-hidden="true" className="eth-stripe w-full" style={{ height: h }} />;
}

function Wave({ from, to, flip }: { from: string; to: string; flip?: boolean }) {
  const path = flip
    ? "M0,40 C240,0 480,80 720,40 C960,0 1200,80 1440,40 L1440,0 L0,0 Z"
    : "M0,40 C240,80 480,0 720,40 C960,80 1200,0 1440,40 L1440,80 L0,80 Z";
  return (
    <div className="overflow-hidden leading-none -my-px">
      <svg viewBox="0 0 1440 80" preserveAspectRatio="none" className="block w-full h-16">
        <rect width="1440" height="80" fill={from} />
        <path d={path} fill={to} />
      </svg>
    </div>
  );
}

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

/* HeroLines: data-driven animation duration/delay/opacity must stay as style= */
function HeroLines() {
  return (
    <div aria-hidden="true" className="hero-lines-mask absolute inset-0 overflow-hidden">
      {LINES.map((l, i) => (
        /* inline: l.top, l.op, l.dur, l.del are runtime data-array values —
           Tailwind JIT cannot build classes from runtime JS variables */
        <div
          key={i}
          style={{ position: "absolute", top: l.top, left: 0, right: 0, height: 1, overflow: "hidden" }}
        >
          {/* inline: multi-stop gradient + keyframe animation driven by runtime data */}
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

export default function HomePage() {
  return (
    <div className="min-h-screen bg-white overflow-x-hidden">

      {/* ════ STICKY NAVBAR ═════════════════════════════════════════════════ */}
      <nav className="fixed top-0 inset-x-0 z-50 bg-white border-b border-gray-200 shadow-sm">
        <div className="max-w-[1200px] mx-auto px-6 h-14 flex items-center gap-6">
          <Link href="/" className="flex items-center gap-2 no-underline">
            <Logo size={32} />
            <span className="font-bold text-[15px] text-[#0f2d1f] whitespace-nowrap">
              SMART <span className="text-[#2D6A4F] font-medium">Inventory</span>
            </span>
          </Link>
          <div className="flex items-center gap-8 mx-auto">
            {(["#features", "#tenants", "#credentials"] as const).map((href, i) => (
              <a key={i} href={href} className="nav-link">
                {["Features", "Tenants", "Credentials"][i]}
              </a>
            ))}
          </div>
          <Link href="/login" className="btn-signin">
            Sign in
          </Link>
        </div>
      </nav>

      {/* ════ HERO ══════════════════════════════════════════════════════════ */}
      {/* Multi-stop angled gradient — style= required (Tailwind bg-gradient-to-* only supports 4 directions) */}
      <section
        className="pt-14 relative text-center"
        style={{ background: `linear-gradient(170deg, ${BG} 0%, #1B4332 55%, #2D6A4F 100%)` }}
      >
        <HeroLines />
        <div className="relative z-[1] max-w-[800px] mx-auto px-6 pt-24 pb-20">
          <div className="flex justify-center mb-7">
            <Logo size={80} />
          </div>
          {/* clamp() viewport font — style= required (Tailwind arbitrary values don't support clamp in JIT) */}
          <h1
            className="font-extrabold text-white m-0 leading-[1.08] tracking-[-0.02em]"
            style={{ fontSize: "clamp(2.5rem, 6vw, 4.5rem)" }}
          >
            SMART Inventory
            <span className="block text-[#FCDD09]">Tracker</span>
          </h1>
          <p
            className="mt-5 text-[rgba(240,253,244,0.85)] leading-relaxed max-w-[540px] mx-auto"
            style={{ fontSize: "clamp(1rem, 2vw, 1.2rem)" }}
          >
            Real-time stock ledger · FEFO dispatch · Offline barcode scanning ·
            3-layer security — built for Ethiopian producers and distributors.
          </p>
          <div className="mt-6 flex justify-center">
            <span className="inline-flex items-center gap-2 px-4 py-1.5 bg-white/[0.08] border border-white/[0.18] rounded-full text-xs font-medium text-[rgba(200,240,220,0.9)]">
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
              🇪🇹 &nbsp;English · አማርኛ · Afaan Oromoo · Offline-ready · Multi-tenant
            </span>
          </div>
          <div className="mt-8 flex gap-3 justify-center flex-wrap">
            <Link href="/login" className="btn-cta-primary">Open Dashboard →</Link>
            <a href="#features" className="btn-hero-outline">Explore Features</a>
          </div>
          <p className="mt-8 text-xs font-mono text-emerald-300 bg-black/25 border border-white/10 rounded px-5 py-2.5 inline-block">
            📧 smartadmin@smart-inventory.com &nbsp;·&nbsp; 🔑 SmartAdmin@2026
          </p>
        </div>
        <Stripe h={6} />
      </section>

      {/* ════ STATS ═════════════════════════════════════════════════════════ */}
      <section className="bg-[#1B4332] px-6 py-10">
        <div className="max-w-[1000px] mx-auto grid grid-cols-4 gap-8 text-center">
          {STATS.map((s) => (
            <div key={s.label}>
              <p className="text-[2.25rem] font-extrabold text-[#FCDD09] m-0">{s.value}</p>
              <p className="text-[13px] font-semibold text-white mt-1">{s.label}</p>
              <p className="text-[11px] text-green-300 mt-0.5">{s.sub}</p>
            </div>
          ))}
        </div>
      </section>

      <Wave from="#1B4332" to="#fff" />

      {/* ════ PLATFORM CAPABILITIES ═════════════════════════════════════════ */}
      <section id="features" className="bg-white px-6 py-20">
        <div className="max-w-[1200px] mx-auto">
          <div className="text-center mb-14">
            <span className="inline-block text-[11px] font-bold uppercase tracking-[0.1em] text-[#2D6A4F] bg-emerald-100 px-3 py-1 rounded-full mb-3">
              Platform Capabilities
            </span>
            <h2 className="text-[2rem] font-extrabold text-[#0f2d1f] m-0">
              Everything your warehouse team needs
            </h2>
            <p className="text-[15px] text-gray-500 mt-2 max-w-[520px] mx-auto">
              From barcode scanning on the warehouse floor to AI-powered demand forecasting.
            </p>
          </div>
          <div className="grid grid-cols-3 border border-gray-300">
            {FEATURES.map((f, i) => (
              /* --facc: per-feature accent color — runtime data; injected once per card */
              <div
                key={f.title}
                className={`cap-card ${i % 3 !== 2 ? "[border-right:1px_solid_#D1D5DB]" : ""} ${i < 3 ? "[border-bottom:1px_solid_#D1D5DB]" : ""}`}
                style={{ "--facc": f.accent } as React.CSSProperties}
              >
                <div className="h-[3px] rounded-sm mb-6 bg-[var(--facc)]" />
                <div className="text-[1.75rem] mb-3">{f.icon}</div>
                <h3 className="text-[15px] font-bold text-[#0f2d1f] m-0 mb-2">{f.title}</h3>
                <p className="text-[13px] text-gray-500 leading-relaxed m-0">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <Wave from="#fff" to="#F3F4F6" flip />
      <Stripe h={4} />

      {/* ════ TENANT SHOWCASE ═══════════════════════════════════════════════ */}
      <section id="tenants" className="bg-gray-100 px-6 py-20">
        <div className="max-w-[1200px] mx-auto">
          <div className="text-center mb-12">
            <span className="inline-block text-[11px] font-bold uppercase tracking-[0.1em] text-[#2D6A4F] bg-emerald-100 px-3 py-1 rounded-full mb-3">
              Live Demo Tenants
            </span>
            <h2 className="text-[2rem] font-extrabold text-[#0f2d1f] m-0">
              Two live companies, ready to explore
            </h2>
            <p className="text-sm text-gray-500 mt-2">
              Sign in as SA to switch between tenants. Sign in as WM to see only your warehouse.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-8">
            {TENANTS.map((ten) => (
              /* --tc: per-tenant brand color — one CSS var injection covers all 3 uses below */
              <Link
                key={ten.slug}
                href={`/dashboard/tenants/${ten.slug}`}
                className="tenant-card"
                style={{ "--tc": ten.color } as React.CSSProperties}
              >
                <div>
                  <div className="px-6 py-5 flex items-center gap-3 bg-[var(--tc)]">
                    <span className="text-[2.5rem]">{ten.icon}</span>
                    <div>
                      <p className="font-bold text-lg text-white m-0">{ten.name}</p>
                      <p className="text-[13px] text-white/75 m-0">{ten.industry}</p>
                    </div>
                    <span className="ml-auto text-[11px] font-bold bg-black/20 text-white px-2 py-0.5 rounded">
                      {ten.orgType}
                    </span>
                  </div>
                  <div className="px-6 py-5 grid grid-cols-2 gap-6">
                    <div>
                      <p className="text-[11px] font-bold uppercase tracking-[0.07em] text-gray-400 mb-2">Locations</p>
                      {ten.warehouses.map((w) => (
                        <p key={w} className="text-[13px] text-gray-700 my-0.5 flex items-center gap-1.5">
                          <span className="w-1.5 h-1.5 rounded-full flex-shrink-0 bg-[var(--tc)]" />
                          {w}
                        </p>
                      ))}
                    </div>
                    <div>
                      <p className="text-[11px] font-bold uppercase tracking-[0.07em] text-gray-400 mb-2">Products</p>
                      {ten.categories.map((c) => (
                        <p key={c} className="text-[13px] text-gray-700 my-0.5 flex items-center gap-1.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-gray-300 flex-shrink-0" />
                          {c}
                        </p>
                      ))}
                    </div>
                  </div>
                  <div className="px-6 py-2.5 border-t border-gray-100 bg-gray-50 flex justify-between items-center">
                    <span className="text-xs text-gray-400">{ten.skuCount} SKUs · {ten.userCount} user accounts</span>
                    <span className="text-xs font-bold text-[var(--tc)]">Open dashboard →</span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <Stripe h={4} />
      <Wave from="#F3F4F6" to={BG} flip />

      {/* ════ CREDENTIALS CTA ═══════════════════════════════════════════════ */}
      <section id="credentials" className="bg-[#0f2d1f] px-6 py-20 text-center">
        <div className="max-w-[860px] mx-auto">
          <h2 className="text-[2rem] font-extrabold text-white m-0">
            Start exploring the demo
          </h2>
          <p className="text-sm text-emerald-300 mt-2 mb-12">
            Each role is scoped to its own data — WMs see only their warehouse, NMs their center.
          </p>
          <div className="grid grid-cols-3 gap-4 mb-10 text-left">
            {CREDS.map((c) => (
              /* --rc: per-role badge color — one CSS var injection covers the badge below */
              <div key={c.email} className="p-4 rounded bg-white/[0.05] border border-white/10" style={{ "--rc": c.roleColor } as React.CSSProperties}>
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-[11px] font-bold text-white px-1.5 py-0.5 rounded bg-[var(--rc)]">
                    {c.role}
                  </span>
                  <span className="text-xs text-emerald-300 overflow-hidden text-ellipsis whitespace-nowrap">{c.company}</span>
                </div>
                <p className="text-xs font-mono text-[#a7f3d0] break-all m-0 mb-1">{c.email}</p>
                <p className="text-xs font-mono text-emerald-300 m-0">{c.pw}</p>
              </div>
            ))}
          </div>
          <Link href="/login" className="btn-cta-primary">
            Sign in to dashboard →
          </Link>
        </div>
      </section>

      {/* ════ FOOTER ════════════════════════════════════════════════════════ */}
      <Stripe h={5} />
      <footer className="bg-[#061410] px-6 py-8">
        <div className="max-w-[1200px] mx-auto flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <Logo size={24} />
            <div>
              <p className="font-bold text-sm text-white m-0">SMART Inventory Tracker</p>
              <p className="text-[11px] text-green-900 m-0">PRD v4.0 · Phase 0</p>
            </div>
          </div>
          <p className="text-xs text-green-900">FastAPI · Next.js 14 · PostgreSQL 16 · AWS ECS Fargate</p>
          <p className="text-xs text-green-900">🇪🇹 EN · አማርኛ · Afaan Oromoo</p>
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
