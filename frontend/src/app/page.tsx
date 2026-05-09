import Link from "next/link";

// ─── Brand constants ──────────────────────────────────────────────────────────
const C = {
  dark:    "#12291E",   // deep forest — header, footer
  forest:  "#1B4332",   // primary green
  mid:     "#2D6A4F",   // mid green
  bright:  "#40916C",   // bright green — hover
  leaf:    "#078930",   // Ethiopian flag green
  gold:    "#FCDD09",   // Ethiopian flag gold — primary CTA
  amber:   "#C9A800",   // darker gold — hover
  red:     "#DA121A",   // Ethiopian flag red
  mist:    "#F0F4F1",   // section backgrounds
  mint:    "#D8F3DC",   // card tint
  white:   "#FFFFFF",
  text:    "#1A202C",   // body text
  subtle:  "#4A5568",   // secondary text
};

// ─── Logo mark ────────────────────────────────────────────────────────────────
function LogoMark({ size = 44 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <rect width="48" height="48" rx="10" fill={C.gold} />
      <path d="M24 6L42 15V27L24 36L6 27V15Z" fill={C.dark} />
      <path d="M24 13L36 19.5V27L24 33L12 27V19.5Z" fill={C.gold} />
      <path d="M24 20L30 23.5V27L24 30L18 27V23.5Z" fill={C.dark} />
    </svg>
  );
}

// ─── Ethiopian 3-stripe divider ───────────────────────────────────────────────
function EthStripe({ h = 5 }: { h?: number }) {
  return (
    <div aria-hidden="true" style={{
      height: h,
      background: `linear-gradient(to right,${C.leaf} 0% 33.3%,${C.gold} 33.3% 66.6%,${C.red} 66.6% 100%)`,
    }} />
  );
}

// ─── Wave divider ─────────────────────────────────────────────────────────────
function Wave({ from, to, flip = false }: { from: string; to: string; flip?: boolean }) {
  const d = flip
    ? "M0 36C180 0 360 72 540 36C720 0 900 72 1080 36C1260 0 1440 72 1440 36V0H0Z"
    : "M0 36C180 72 360 0 540 36C720 72 900 0 1080 36C1260 72 1440 0 1440 36V72H0Z";
  return (
    <div className="w-full overflow-hidden -my-px" aria-hidden="true">
      <svg viewBox="0 0 1440 72" preserveAspectRatio="none" className="w-full h-12 md:h-16 block">
        <rect width="1440" height="72" fill={from} />
        <path d={d} fill={to} />
      </svg>
    </div>
  );
}

// ─── Homepage ─────────────────────────────────────────────────────────────────
export default function HomePage() {
  return (
    <div className="min-h-screen bg-white overflow-x-hidden" style={{ color: C.text }}>

      {/* ══ STICKY NAVBAR ══════════════════════════════════════════════════ */}
      <nav className="fixed top-0 inset-x-0 z-50 bg-white border-b border-gray-200 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-14 flex items-center gap-6">

          {/* Logo — left */}
          <Link href="/" className="flex items-center gap-2 shrink-0">
            <LogoMark size={32} />
            <span className="font-bold text-sm hidden sm:block" style={{ color: C.dark }}>
              SMART <span className="font-normal" style={{ color: C.mid }}>Inventory</span>
            </span>
          </Link>

          {/* Nav links — center */}
          <div className="hidden md:flex items-center gap-6 text-sm font-medium text-gray-600 mx-auto">
            <a href="#features"    className="hover:text-green-800 transition-colors">Features</a>
            <a href="#tenants"     className="hover:text-green-800 transition-colors">Tenants</a>
            <a href="#credentials" className="hover:text-green-800 transition-colors">Credentials</a>
          </div>

          {/* Far-right: square Sign in button */}
          <Link
            href="/login"
            className="ml-auto shrink-0 font-semibold text-sm border-2 px-5 py-2 transition-all duration-150 hover:text-white"
            style={{
              borderRadius: 4,
              borderColor: C.forest,
              color: C.forest,
            }}
            onMouseEnter={() => {}}
          >
            Sign in
          </Link>
        </div>
      </nav>

      {/* ══ HERO — centered, big logo + headline ══════════════════════════ */}
      <section
        className="pt-14 pb-0 text-center"
        style={{ background: `linear-gradient(170deg,${C.dark} 0%,${C.forest} 55%,${C.mid} 100%)` }}
      >
        <div className="max-w-4xl mx-auto px-4 sm:px-6 pt-16 pb-12">
          {/* Big centered logo */}
          <div className="flex justify-center mb-6">
            <LogoMark size={72} />
          </div>

          {/* Big centered title */}
          <h1 className="text-5xl sm:text-6xl lg:text-7xl font-extrabold text-white leading-tight tracking-tight">
            SMART Inventory
            <span className="block mt-1" style={{ color: C.gold }}>Tracker</span>
          </h1>

          <p className="mt-5 text-lg sm:text-xl text-green-100/90 max-w-2xl mx-auto leading-relaxed">
            Real-time ledger · FEFO dispatch · Offline barcode scanning · 3-layer RBAC+ABAC security.
            Purpose-built for Ethiopian producers and distributors.
          </p>

          {/* Language badge */}
          <div className="mt-5 flex justify-center">
            <div className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-4 py-1.5">
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
              <span className="text-sm font-medium text-green-200">
                🇪🇹 English · አማርኛ · Afaan Oromoo · Offline-ready · Multi-tenant
              </span>
            </div>
          </div>

          {/* CTAs */}
          <div className="mt-8 flex flex-wrap gap-4 justify-center">
            <Link
              href="/login"
              className="px-8 py-3.5 font-bold text-sm transition-all duration-150 shadow-lg hover:opacity-90"
              style={{ background: C.gold, color: C.dark, borderRadius: 4 }}
            >
              Open Dashboard →
            </Link>
            <a
              href="#features"
              className="px-8 py-3.5 font-semibold text-sm border-2 border-white/40 text-white hover:bg-white/10 transition-all duration-150"
              style={{ borderRadius: 4 }}
            >
              Explore Features
            </a>
          </div>

          {/* Credential hint */}
          <p className="mt-7 text-xs font-mono text-green-400 bg-black/20 border border-white/10 rounded px-5 py-2.5 inline-block">
            📧 smartadmin@smart-inventory.com &nbsp;·&nbsp; 🔑 SmartAdmin@2026
          </p>
        </div>

        <EthStripe h={6} />
      </section>

      {/* ══ STATS BAR ═══════════════════════════════════════════════════════ */}
      <section style={{ background: C.forest }} className="py-10 px-4">
        <div className="max-w-5xl mx-auto grid grid-cols-2 sm:grid-cols-4 gap-8 text-center">
          {STATS.map((s) => (
            <div key={s.label}>
              <p className="text-4xl font-extrabold" style={{ color: C.gold }}>{s.value}</p>
              <p className="text-sm font-semibold text-white mt-1">{s.label}</p>
              <p className="text-xs text-green-300 mt-0.5">{s.sub}</p>
            </div>
          ))}
        </div>
      </section>

      <Wave from={C.forest} to={C.white} />

      {/* ══ PLATFORM CAPABILITIES — 3-column rectangles, stacked ════════════ */}
      <section id="features" className="py-20 px-4 bg-white">
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-14">
            <p className="text-xs font-bold uppercase tracking-widest mb-2" style={{ color: C.mid }}>
              Platform Capabilities
            </p>
            <h2 className="text-3xl sm:text-4xl font-extrabold" style={{ color: C.dark }}>
              Everything your warehouse team needs
            </h2>
            <p className="text-gray-500 mt-3 max-w-xl mx-auto">
              From barcode scanning on the warehouse floor to AI-powered demand forecasting.
            </p>
          </div>

          {/* 3-column rectangular grid, two rows */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-0 border-l border-t"
            style={{ borderColor: "#D1D5DB" }}>
            {FEATURES.map((f) => (
              <div
                key={f.title}
                className="group p-8 border-r border-b transition-all duration-200 hover:shadow-inner cursor-default"
                style={{ borderColor: "#D1D5DB", borderRadius: 0, background: C.white }}
              >
                {/* Icon strip */}
                <div
                  className="w-full h-1 mb-6 rounded-sm"
                  style={{ background: f.accent }}
                />
                <div className="text-3xl mb-4">{f.icon}</div>
                <h3 className="text-base font-bold mb-2" style={{ color: C.dark }}>{f.title}</h3>
                <p className="text-sm text-gray-500 leading-relaxed">{f.desc}</p>
                {/* Bottom accent on hover */}
                <div
                  className="mt-5 w-8 h-0.5 transition-all duration-300 group-hover:w-full"
                  style={{ background: f.accent }}
                />
              </div>
            ))}
          </div>
        </div>
      </section>

      <Wave from={C.white} to={C.mist} flip />
      <EthStripe h={5} />

      {/* ══ TENANT SHOWCASE ═════════════════════════════════════════════════ */}
      <section id="tenants" className="py-20 px-4" style={{ background: C.mist }}>
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-12">
            <p className="text-xs font-bold uppercase tracking-widest mb-2" style={{ color: C.mid }}>
              Live Demo Tenants
            </p>
            <h2 className="text-3xl sm:text-4xl font-extrabold" style={{ color: C.dark }}>
              Two live companies, ready to explore
            </h2>
            <p className="text-gray-500 mt-2 text-sm">
              Sign in as SA to switch between tenants. Sign in as WM to see your warehouse scope.
            </p>
          </div>

          <div className="grid md:grid-cols-2 gap-8">
            {TENANTS.map((t) => (
              <Link
                key={t.slug}
                href={`/dashboard/tenants/${t.slug}`}
                className="block group border-2 hover:border-current transition-all duration-200 hover:-translate-y-1 hover:shadow-xl"
                style={{ borderColor: "#D1D5DB", borderRadius: 4, background: C.white, overflow: "hidden" }}
              >
                {/* Colored header strip */}
                <div className="px-6 py-5 flex items-center gap-4" style={{ background: t.color }}>
                  <span className="text-5xl">{t.icon}</span>
                  <div>
                    <h3 className="text-xl font-bold text-white">{t.name}</h3>
                    <p className="text-white/80 text-sm">{t.industry}</p>
                  </div>
                  <span className="ml-auto text-white/70 text-xs font-semibold bg-black/20 px-2.5 py-1" style={{ borderRadius: 2 }}>
                    {t.orgType}
                  </span>
                </div>

                <div className="p-6 grid grid-cols-2 gap-6">
                  <div>
                    <p className="text-xs font-bold uppercase tracking-wider text-gray-400 mb-2">Locations</p>
                    {t.warehouses.map((w) => (
                      <p key={w} className="text-sm text-gray-600 flex items-center gap-1.5 py-0.5">
                        <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: t.color }} />
                        {w}
                      </p>
                    ))}
                  </div>
                  <div>
                    <p className="text-xs font-bold uppercase tracking-wider text-gray-400 mb-2">Products</p>
                    {t.categories.map((c) => (
                      <p key={c} className="text-sm text-gray-600 flex items-center gap-1.5 py-0.5">
                        <span className="w-1.5 h-1.5 rounded-full bg-gray-300 shrink-0" />
                        {c}
                      </p>
                    ))}
                    <p className="mt-2 text-xs text-gray-400">{t.skuCount} SKUs · {t.userCount} users</p>
                  </div>
                </div>

                <div className="px-6 py-3 border-t border-gray-100 flex items-center justify-between"
                  style={{ background: "#FAFAFA" }}>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-400">{t.userCount} accounts</span>
                  </div>
                  <span className="text-xs font-bold group-hover:underline" style={{ color: t.color }}>
                    Open dashboard →
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <EthStripe h={5} />
      <Wave from={C.mist} to={C.dark} flip />

      {/* ══ CREDENTIALS CTA ═════════════════════════════════════════════════ */}
      <section id="credentials" style={{ background: C.dark }} className="py-20 px-4">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-3xl sm:text-4xl font-extrabold text-white mb-3">
            Start exploring the demo
          </h2>
          <p className="text-green-400 mb-10 text-sm">
            Each role is scoped to its own data — WMs see only their warehouse, NMs see their center.
          </p>

          <div className="grid sm:grid-cols-3 gap-4 mb-10 text-left">
            {CREDS.map((c) => (
              <div
                key={c.email}
                className="p-4 border border-white/10"
                style={{ background: "rgba(255,255,255,0.04)", borderRadius: 4 }}
              >
                <div className="flex items-center gap-2 mb-2">
                  <span
                    className="text-xs font-bold px-2 py-0.5 text-white"
                    style={{ background: c.roleColor, borderRadius: 2 }}
                  >
                    {c.role}
                  </span>
                  <span className="text-xs text-green-400 truncate">{c.company}</span>
                </div>
                <p className="text-xs font-mono text-green-200 break-all">{c.email}</p>
                <p className="text-xs font-mono text-green-500 mt-0.5">{c.pw}</p>
              </div>
            ))}
          </div>

          <Link
            href="/login"
            className="inline-flex items-center gap-2 px-10 py-4 font-bold text-base shadow-xl hover:opacity-90 transition"
            style={{ background: C.gold, color: C.dark, borderRadius: 4 }}
          >
            Sign in to dashboard →
          </Link>
        </div>
      </section>

      {/* ══ FOOTER ══════════════════════════════════════════════════════════ */}
      <EthStripe h={5} />
      <footer style={{ background: "#0A1C12" }} className="py-8 px-4">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <LogoMark size={24} />
            <div>
              <p className="text-white text-sm font-bold">SMART Inventory Tracker</p>
              <p className="text-green-800 text-xs">PRD v4.0 · Phase 0</p>
            </div>
          </div>
          <p className="text-green-900 text-xs">FastAPI · Next.js 14 · PostgreSQL 16 · AWS ECS Fargate</p>
          <p className="text-green-900 text-xs">🇪🇹 EN · አማርኛ · Afaan Oromoo</p>
        </div>
      </footer>
    </div>
  );
}

// ─── Static data ──────────────────────────────────────────────────────────────

const STATS = [
  { value: "115",   label: "Permission Actions",  sub: "RBAC + ABAC enforcement" },
  { value: "10",    label: "Microservices",        sub: "FastAPI + Next.js 14" },
  { value: "3",     label: "Languages",            sub: "EN · አማርኛ · Oromoo" },
  { value: "99.9%", label: "Uptime SLA",           sub: "AWS ECS Fargate" },
];

const FEATURES = [
  {
    icon: "📦", accent: "#40916C",
    title: "Immutable Inventory Ledger",
    desc: "Every stock movement is an append-only INSERT. Balances are derived — nothing is ever overwritten or deleted.",
  },
  {
    icon: "🔐", accent: "#FCDD09",
    title: "RBAC + ABAC Security",
    desc: "115 permission actions at 3 layers: API Gateway, service level, and PostgreSQL Row-Level Security.",
  },
  {
    icon: "🏭", accent: "#DA121A",
    title: "Multi-Location Hierarchy",
    desc: "Production centers, warehouses, and sub-centers in a parent–child tree. Users auto-scoped to their location.",
  },
  {
    icon: "📱", accent: "#0891B2",
    title: "Offline PWA + Barcode Scan",
    desc: "Warehouse staff record movements offline via camera scan. IndexedDB queue syncs on reconnect.",
  },
  {
    icon: "⚡", accent: "#7C3AED",
    title: "FEFO Dispatch Engine",
    desc: "Auto-enforced when expiry tracking is active. Override requires permission + reason code + audit trail.",
  },
  {
    icon: "🌍", accent: "#078930",
    title: "EN · Amharic · Oromifa",
    desc: "Language packs served from S3 CDN. Switch per-user. Native speaker review for Oromifa before go-live.",
  },
];

const TENANTS = [
  {
    name: "Addis Water", slug: "addis-water", icon: "💧",
    industry: "Bottled Water · Producer", orgType: "PRODUCER",
    color: "#0891B2", skuCount: 10, userCount: 7,
    warehouses: ["Main Production Center", "North WH", "↳ North-Subcenter WH", "South WH", "East WH", "West WH"],
    categories: ["Still Water (500ml, 1L, 1.5L)", "Sparkling Water (500ml, 1L)", "Pack sizes: 6 · 12 · 24"],
  },
  {
    name: "Muger Cement", slug: "muger-cement", icon: "🏗️",
    industry: "Cement Manufacturing · Producer", orgType: "PRODUCER",
    color: "#D97706", skuCount: 10, userCount: 7,
    warehouses: ["Harar Production Center", "Ambo Production Center", "Kombolcha WH", "Mekele WH", "Dire Dawa WH", "Hawassa WH"],
    categories: ["OPC 42.5N & 32.5R", "Portland Pozzolana (PPC)", "Sulphate Resistant (SRC)", "White Portland (WPC)", "Sizes: 25kg · 50kg bags"],
  },
];

const CREDS = [
  { role: "SA",  roleColor: "#DC2626", company: "All tenants",  email: "smartadmin@smart-inventory.com", pw: "SmartAdmin@2026" },
  { role: "TA",  roleColor: "#7C3AED", company: "Addis Water",  email: "admin@addis-water.com",          pw: "AddisWater@2026"  },
  { role: "TA",  roleColor: "#D97706", company: "Muger Cement", email: "admin@muger-cement.com",         pw: "MugerCement@2026" },
];
