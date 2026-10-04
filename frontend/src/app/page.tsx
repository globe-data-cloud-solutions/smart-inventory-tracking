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
  return (
    <div aria-hidden="true" className="eth-stripe w-full" style={{ height: h }} />
  );
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
        <div
          key={i}
          style={{ position: "absolute", top: l.top, left: 0, right: 0, height: 1, overflow: "hidden" }}
        >
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
          <div className="flex items-center gap-3">
            <Link href="/login" className="btn-signin">
              Sign in
            </Link>
            <Link href="/signup" className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium transition-colors">
              Create Account
            </Link>
          </div>
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
            <Link href="/signup" className="btn-cta-primary">Get Started Free →</Link>
            <Link href="/login" className="btn-hero-outline">Sign In</Link>
          </div>
          <p className="mt-8 text-xs font-mono text-emerald-300 bg-black/25 border border-white/10 rounded px-5 py-2.5 inline-block">
            System Administrator: smartadmin@smart-inventory.com / Admin@2026
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
              <div
                key={f.title}
                className="cap-card"
                style={{
                  borderRight:  i % 3 === 2 ? "none" : "1px solid #D1D5DB",
                  borderBottom: i >= 3      ? "none" : "1px solid #D1D5DB",
                }}
              >
                {/* Per-feature accent color — runtime data value */}
                <div className="h-[3px] rounded-sm mb-6" style={{ background: f.accent }} />
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

      {/* ════ TWO PATHS ════════════════════════════════════════════════════ */}
      <section className="bg-gradient-to-b from-gray-100 to-white px-6 py-20">
        <div className="max-w-[1200px] mx-auto">
          <div className="text-center mb-12">
            <span className="inline-block text-[11px] font-bold uppercase tracking-[0.1em] text-[#2D6A4F] bg-emerald-100 px-3 py-1 rounded-full mb-3">
              Two Ways to Get Started
            </span>
            <h2 className="text-[2rem] font-extrabold text-[#0f2d1f] m-0">
              Choose your path
            </h2>
          </div>
          <div className="grid grid-cols-2 gap-8">
            {/* Self-Service Path */}
            <div className="p-8 rounded-2xl bg-gradient-to-br from-emerald-50 to-emerald-100 border-2 border-emerald-300">
              <div className="text-4xl mb-4">🚀</div>
              <h3 className="text-xl font-bold text-[#0f2d1f] m-0 mb-2">Self-Service Signup</h3>
              <p className="text-sm text-gray-600 mb-6">
                Create your company account, configure your warehouse hierarchy, and start managing inventory right away.
              </p>
              <ul className="text-sm text-gray-700 space-y-2 mb-6">
                <li className="flex items-center gap-2">
                  <span>✓</span> Instant account creation
                </li>
                <li className="flex items-center gap-2">
                  <span>✓</span> Choose your plan tier
                </li>
                <li className="flex items-center gap-2">
                  <span>✓</span> Built-in onboarding wizard
                </li>
                <li className="flex items-center gap-2">
                  <span>✓</span> Support included
                </li>
              </ul>
              <Link href="/signup" className="block w-full text-center bg-emerald-600 hover:bg-emerald-700 text-white font-medium py-3 rounded-lg transition-colors">
                Create Free Account →
              </Link>
            </div>

            {/* System Admin Path */}
            <div className="p-8 rounded-2xl bg-gradient-to-br from-blue-50 to-blue-100 border-2 border-blue-300">
              <div className="text-4xl mb-4">👨‍💼</div>
              <h3 className="text-xl font-bold text-[#0f2d1f] m-0 mb-2">System Administrator</h3>
              <p className="text-sm text-gray-600 mb-6">
                Sign in as SA to create and manage multiple tenant accounts, configure organization structures, and oversee your implementation.
              </p>
              <ul className="text-sm text-gray-700 space-y-2 mb-6">
                <li className="flex items-center gap-2">
                  <span>✓</span> Multi-tenant management
                </li>
                <li className="flex items-center gap-2">
                  <span>✓</span> Advanced configuration
                </li>
                <li className="flex items-center gap-2">
                  <span>✓</span> Plan & contract management
                </li>
                <li className="flex items-center gap-2">
                  <span>✓</span> Full platform access
                </li>
              </ul>
              <Link href="/login" className="block w-full text-center bg-blue-600 hover:bg-blue-700 text-white font-medium py-3 rounded-lg transition-colors">
                System Admin Login →
              </Link>
            </div>
          </div>
        </div>
      </section>

      <Stripe h={4} />
      <Wave from="#fff" to="#F3F4F6" flip />

      {/* ════ GET STARTED ═══════════════════════════════════════════════════ */}
      <section id="tenants" className="bg-gray-100 px-6 py-20">
        <div className="max-w-[760px] mx-auto text-center">
          <span className="inline-block text-[11px] font-bold uppercase tracking-[0.1em] text-[#2D6A4F] bg-emerald-100 px-3 py-1 rounded-full mb-3">
            Get Started
          </span>
          <h2 className="text-[2rem] font-extrabold text-[#0f2d1f] m-0">
            Ready to streamline your inventory?
          </h2>
          <p className="text-sm text-gray-500 mt-2 mb-8">
            Create your account today and set up your first warehouse in minutes.
          </p>
          <div className="grid grid-cols-3 gap-4 text-left mb-8">
            {SETUP_STEPS.map((s, i) => (
              <div key={i} className="p-4 rounded-xl bg-white border border-gray-200">
                <p className="text-[1.5rem] mb-2">{s.icon}</p>
                <p className="text-sm font-bold text-[#0f2d1f] m-0">{s.title}</p>
                <p className="text-[12px] text-gray-500 mt-1 m-0">{s.desc}</p>
              </div>
            ))}
          </div>
          <div className="flex gap-3 justify-center flex-wrap">
            <Link href="/signup" className="btn-cta-primary">
              Create Your Account →
            </Link>
            <Link href="/login" className="btn-hero-outline">
              Sign In
            </Link>
          </div>
        </div>
      </section>

      <Stripe h={4} />
      <Wave from="#F3F4F6" to={BG} flip />

      {/* ════ CREDENTIALS CTA ═══════════════════════════════════════════════ */}
      <section id="credentials" className="bg-[#0f2d1f] px-6 py-20">
        <div className="max-w-[1200px] mx-auto">
          <h2 className="text-[2rem] font-extrabold text-white m-0 text-center mb-12">
            Demo Credentials & Quick Start
          </h2>
          <div className="grid grid-cols-2 gap-8">
            {/* System Admin Demo */}
            <div className="p-8 rounded-xl bg-white/[0.05] border border-white/10">
              <div className="flex items-center gap-2 mb-4">
                <span className="text-[11px] font-bold text-white px-2 py-1 rounded bg-red-600">SA</span>
                <span className="text-sm text-emerald-300 font-semibold">System Administrator (Demo)</span>
              </div>
              <p className="text-sm text-emerald-200 mb-4">
                Test the full platform as a system admin. Create tenants, manage organizations, and configure permissions.
              </p>
              <div className="p-4 rounded-lg bg-black/30 mb-4">
                <p className="text-xs text-gray-400 mb-1">Email</p>
                <p className="text-xs font-mono text-[#a7f3d0]">smartadmin@smart-inventory.com</p>
                <p className="text-xs text-gray-400 mt-3 mb-1">Password</p>
                <p className="text-xs font-mono text-emerald-300">Admin@2026</p>
              </div>
              <Link href="/login" className="block w-full text-center bg-red-600 hover:bg-red-700 text-white font-medium py-2 rounded-lg transition-colors text-sm">
                Demo Login →
              </Link>
            </div>

            {/* Self-Service Signup */}
            <div className="p-8 rounded-xl bg-gradient-to-br from-emerald-900/40 to-emerald-800/40 border border-emerald-600/50">
              <div className="flex items-center gap-2 mb-4">
                <span className="text-[11px] font-bold text-white px-2 py-1 rounded bg-emerald-600">NEW</span>
                <span className="text-sm text-emerald-200 font-semibold">Self-Service Signup</span>
              </div>
              <p className="text-sm text-emerald-200 mb-4">
                Create your own company account instantly. No demo required — get started with your real organization.
              </p>
              <div className="p-4 rounded-lg bg-white/5 mb-4">
                <p className="text-xs text-gray-300 mb-2">✨ Features:</p>
                <ul className="text-xs text-gray-300 space-y-1">
                  <li>• Instant account creation</li>
                  <li>• Choose your plan tier</li>
                  <li>• Email verification</li>
                  <li>• Onboarding wizard included</li>
                </ul>
              </div>
              <Link href="/signup" className="block w-full text-center bg-emerald-600 hover:bg-emerald-700 text-white font-medium py-2 rounded-lg transition-colors text-sm">
                Create Free Account →
              </Link>
            </div>
          </div>
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

const SETUP_STEPS = [
  { icon: "🏢", title: "Create Tenant",      desc: "Register your company and set the organisation type (Producer / Retailer)." },
  { icon: "🌳", title: "Configure Hierarchy", desc: "Define levels, nodes, positions, and supply routes in the org setup wizard." },
  { icon: "👥", title: "Add Users",           desc: "Create users, assign positions, and configure approval rules for transfers." },
];
