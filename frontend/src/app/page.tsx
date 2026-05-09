import Link from "next/link";
import Image from "next/image";

export default function HomePage() {
  return (
    <div className="min-h-screen bg-white flex flex-col">
      {/* ── Nav ── */}
      <nav className="fixed top-0 inset-x-0 z-50 bg-white/90 backdrop-blur border-b border-gray-100">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-brand-600 flex items-center justify-center">
              <svg viewBox="0 0 24 24" fill="none" className="w-5 h-5 text-white" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M20 7l-8-4-8 4m16 0v10l-8 4m0-14L4 17m8 4V11" />
              </svg>
            </div>
            <span className="font-bold text-gray-900 text-lg tracking-tight">SMART Inventory</span>
          </div>
          <div className="flex items-center gap-4">
            <Link href="/login"
              className="text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors">
              Sign in
            </Link>
            <Link href="/login"
              className="rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 transition-colors shadow-sm">
              Get started
            </Link>
          </div>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section className="relative pt-32 pb-20 px-6 overflow-hidden bg-gradient-to-br from-slate-900 via-brand-900 to-slate-900">
        {/* Background grid */}
        <div className="absolute inset-0 opacity-10"
          style={{
            backgroundImage: "linear-gradient(rgba(255,255,255,.1) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.1) 1px,transparent 1px)",
            backgroundSize: "60px 60px"
          }} />

        <div className="relative max-w-7xl mx-auto">
          <div className="lg:grid lg:grid-cols-2 lg:gap-16 items-center">
            {/* Left — text */}
            <div className="text-center lg:text-left mb-12 lg:mb-0">
              <div className="inline-flex items-center gap-2 rounded-full bg-brand-500/20 border border-brand-400/30 px-4 py-1.5 mb-6">
                <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
                <span className="text-sm font-medium text-brand-200">Multi-tenant · Real-time · Offline-ready</span>
              </div>
              <h1 className="text-5xl lg:text-6xl font-extrabold text-white leading-tight tracking-tight">
                SMART Inventory
                <span className="block text-brand-400">Tracker</span>
              </h1>
              <p className="mt-6 text-lg text-slate-300 max-w-lg mx-auto lg:mx-0">
                End-to-end inventory management for Producers, Importers, and Retailers.
                FEFO dispatch, real-time ledger, offline scanning — in English, Amharic, and Oromifa.
              </p>
              <div className="mt-8 flex flex-col sm:flex-row gap-4 justify-center lg:justify-start">
                <Link href="/login"
                  className="rounded-lg bg-brand-500 px-6 py-3.5 text-base font-semibold text-white hover:bg-brand-400 transition-colors shadow-lg shadow-brand-500/30">
                  Sign in to dashboard →
                </Link>
                <Link href="/login"
                  className="rounded-lg border border-white/20 px-6 py-3.5 text-base font-semibold text-white hover:bg-white/10 transition-colors">
                  View demo credentials
                </Link>
              </div>
            </div>

            {/* Right — SVG illustration */}
            <div className="flex justify-center lg:justify-end">
              <WarehouseIllustration />
            </div>
          </div>
        </div>
      </section>

      {/* ── Stats bar ── */}
      <section className="bg-brand-600 py-8 px-6">
        <div className="max-w-7xl mx-auto grid grid-cols-2 lg:grid-cols-4 gap-6 text-center">
          {[
            { value: "115", label: "Permission actions" },
            { value: "10", label: "Microservices" },
            { value: "3", label: "Languages (EN / AM / OR)" },
            { value: "99.9%", label: "Target uptime SLA" },
          ].map((s) => (
            <div key={s.label}>
              <p className="text-3xl font-bold text-white">{s.value}</p>
              <p className="text-sm text-brand-100 mt-1">{s.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Features ── */}
      <section className="py-20 px-6 bg-gray-50">
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl font-bold text-gray-900">Built for Ethiopian businesses</h2>
            <p className="mt-3 text-gray-500 max-w-xl mx-auto">
              From water bottling plants in Addis Ababa to cement factories in Harar — one platform handles it all.
            </p>
          </div>
          <div className="grid md:grid-cols-3 gap-8">
            {FEATURES.map((f) => (
              <div key={f.title} className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
                <div className="w-12 h-12 rounded-lg bg-brand-50 flex items-center justify-center mb-4 text-2xl">
                  {f.icon}
                </div>
                <h3 className="font-semibold text-gray-900 mb-2">{f.title}</h3>
                <p className="text-sm text-gray-500 leading-relaxed">{f.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Tenants preview ── */}
      <section className="py-20 px-6">
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-3xl font-bold text-gray-900">Live demo tenants</h2>
            <p className="mt-3 text-gray-500">Sign in with the SA account to manage both companies.</p>
          </div>
          <div className="grid md:grid-cols-2 gap-8">
            <TenantPreviewCard
              logo="💧"
              name="Addis Water"
              industry="Bottled Water · Producer"
              color="bg-cyan-500"
              textColor="text-cyan-700"
              bgColor="bg-cyan-50"
              warehouses={["Main Production Center", "North WH + North-Subcenter WH", "South WH", "East WH", "West WH"]}
              products={["Pure Water 500ml Pack of 6 / 12 / 24", "Pure Water 1L Pack of 6 / 12 / 24", "Pure Water 1.5L Pack of 6 / 12", "Sparkling Water 500ml & 1L"]}
            />
            <TenantPreviewCard
              logo="🏗️"
              name="Muger Cement"
              industry="Cement Manufacturing · Producer"
              color="bg-amber-500"
              textColor="text-amber-700"
              bgColor="bg-amber-50"
              warehouses={["Harar Production Center", "Ambo Production Center", "Kombolcha WH", "Mekele WH", "Dire Dawa WH", "Hawassa WH"]}
              products={["OPC Grade 42.5N — 25kg & 50kg", "OPC Grade 32.5R — 25kg & 50kg", "Portland Pozzolana Cement (PPC)", "Sulphate Resistant Cement (SRC)", "White Portland Cement (WPC)"]}
            />
          </div>
        </div>
      </section>

      {/* ── CTA ── */}
      <section className="py-16 px-6 bg-gradient-to-r from-brand-600 to-brand-800">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-3xl font-bold text-white mb-4">Ready to explore the demo?</h2>
          <p className="text-brand-100 mb-8">Use the System Admin account to access all tenants, warehouses, and inventory.</p>
          <div className="bg-white/10 border border-white/20 rounded-xl p-6 text-left max-w-sm mx-auto mb-6">
            <p className="text-xs text-brand-200 uppercase tracking-wider font-semibold mb-3">SA Demo Credentials</p>
            <p className="text-sm text-white font-mono">📧 smartadmin@smart-inventory.com</p>
            <p className="text-sm text-white font-mono mt-1">🔑 SmartAdmin@2026</p>
          </div>
          <Link href="/login"
            className="inline-flex items-center gap-2 rounded-lg bg-white px-6 py-3.5 text-base font-semibold text-brand-700 hover:bg-brand-50 transition-colors shadow-lg">
            Open dashboard →
          </Link>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="bg-gray-900 py-8 px-6">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2 text-gray-400 text-sm">
            <span className="font-semibold text-white">SMART Inventory Tracker</span>
            <span>· PRD v4.0</span>
          </div>
          <p className="text-gray-500 text-sm">
            FastAPI · Next.js 14 · PostgreSQL · AWS ECS · Tailwind CSS
          </p>
          <p className="text-gray-500 text-sm">
            🇪🇹 Built for Ethiopia · English · አማርኛ · Afaan Oromoo
          </p>
        </div>
      </footer>
    </div>
  );
}

// ── Subcomponents ─────────────────────────────────────────────────────────────

function WarehouseIllustration() {
  return (
    <svg viewBox="0 0 480 380" className="w-full max-w-lg" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* Background glow */}
      <ellipse cx="240" cy="300" rx="180" ry="40" fill="#3B82F6" opacity="0.1" />

      {/* Main warehouse */}
      <rect x="120" y="140" width="240" height="150" rx="4" fill="#1E3A5F" />
      <polygon points="100,140 240,60 380,140" fill="#1D4ED8" />
      <rect x="185" y="200" width="60" height="90" rx="2" fill="#0F172A" />
      <rect x="200" y="215" width="12" height="20" rx="1" fill="#3B82F6" opacity="0.6" />

      {/* Windows */}
      <rect x="135" y="165" width="35" height="25" rx="2" fill="#2563EB" opacity="0.7" />
      <rect x="185" y="165" width="35" height="25" rx="2" fill="#2563EB" opacity="0.7" />
      <rect x="295" y="165" width="35" height="25" rx="2" fill="#2563EB" opacity="0.7" />
      <rect x="310" y="165" width="35" height="25" rx="2" fill="#2563EB" opacity="0.5" />

      {/* Left small warehouse */}
      <rect x="30" y="195" width="80" height="95" rx="3" fill="#1E3A5F" />
      <polygon points="20,195 70,155 120,195" fill="#2563EB" opacity="0.8" />
      <rect x="50" y="240" width="22" height="50" rx="1" fill="#0F172A" />

      {/* Right small warehouse */}
      <rect x="370" y="195" width="80" height="95" rx="3" fill="#1E3A5F" />
      <polygon points="360,195 410,155 460,195" fill="#2563EB" opacity="0.8" />
      <rect x="405" y="240" width="22" height="50" rx="1" fill="#0F172A" />

      {/* Connection lines */}
      <line x1="110" y1="240" x2="120" y2="240" stroke="#3B82F6" strokeWidth="2" strokeDasharray="4,3" />
      <line x1="360" y1="240" x2="370" y2="240" stroke="#3B82F6" strokeWidth="2" strokeDasharray="4,3" />

      {/* Floating boxes */}
      <rect x="155" y="100" width="24" height="24" rx="3" fill="#3B82F6" opacity="0.9" transform="rotate(-8 167 112)" />
      <rect x="295" y="95" width="24" height="24" rx="3" fill="#60A5FA" opacity="0.8" transform="rotate(6 307 107)" />
      <rect x="225" y="75" width="20" height="20" rx="3" fill="#93C5FD" opacity="0.7" transform="rotate(-4 235 85)" />

      {/* Truck */}
      <rect x="155" y="290" width="65" height="35" rx="3" fill="#1E40AF" />
      <rect x="130" y="298" width="30" height="27" rx="3" fill="#1D4ED8" />
      <circle cx="150" cy="325" r="7" fill="#374151" />
      <circle cx="150" cy="325" r="3" fill="#6B7280" />
      <circle cx="205" cy="325" r="7" fill="#374151" />
      <circle cx="205" cy="325" r="3" fill="#6B7280" />

      {/* Data nodes */}
      <circle cx="240" cy="30" r="14" fill="#1E40AF" />
      <text x="240" y="35" textAnchor="middle" fill="white" fontSize="11" fontWeight="bold">SA</text>
      <line x1="240" y1="44" x2="240" y2="60" stroke="#3B82F6" strokeWidth="1.5" />
      <circle cx="70" cy="145" r="10" fill="#0EA5E9" opacity="0.9" />
      <text x="70" y="149" textAnchor="middle" fill="white" fontSize="8">WH</text>
      <circle cx="410" cy="145" r="10" fill="#0EA5E9" opacity="0.9" />
      <text x="410" y="149" textAnchor="middle" fill="white" fontSize="8">WH</text>
    </svg>
  );
}

function TenantPreviewCard({
  logo, name, industry, color, textColor, bgColor, warehouses, products,
}: {
  logo: string; name: string; industry: string;
  color: string; textColor: string; bgColor: string;
  warehouses: string[]; products: string[];
}) {
  return (
    <div className="rounded-2xl border border-gray-200 overflow-hidden shadow-sm hover:shadow-md transition-shadow">
      <div className={`${color} p-6 text-white`}>
        <div className="flex items-center gap-3">
          <span className="text-4xl">{logo}</span>
          <div>
            <h3 className="text-xl font-bold">{name}</h3>
            <p className="text-sm opacity-90">{industry}</p>
          </div>
        </div>
      </div>
      <div className="p-6 bg-white">
        <div className="grid grid-cols-2 gap-6">
          <div>
            <p className={`text-xs font-semibold uppercase tracking-wider ${textColor} mb-2`}>Locations</p>
            <ul className="space-y-1">
              {warehouses.map((w) => (
                <li key={w} className="text-sm text-gray-600 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-gray-300 flex-shrink-0" />
                  {w}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className={`text-xs font-semibold uppercase tracking-wider ${textColor} mb-2`}>Products</p>
            <ul className="space-y-1">
              {products.map((p) => (
                <li key={p} className="text-sm text-gray-600 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-gray-300 flex-shrink-0" />
                  {p}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

const FEATURES = [
  {
    icon: "🔐",
    title: "3-Layer Security (RBAC + ABAC)",
    description:
      "115 permission actions enforced at API Gateway, service layer, and PostgreSQL RLS. Users can only see data within their tenant, region, and warehouse scope.",
  },
  {
    icon: "📦",
    title: "Immutable Inventory Ledger",
    description:
      "Every stock movement is an INSERT into an append-only ledger — no direct balance edits. FEFO auto-enforced for products with expiry tracking.",
  },
  {
    icon: "📱",
    title: "Offline-First PWA",
    description:
      "Warehouse staff can scan barcodes and record transactions offline. Queued in IndexedDB and synced automatically when connectivity returns.",
  },
  {
    icon: "⚡",
    title: "Transactional Outbox (No Kafka)",
    description:
      "Async side-effects (notifications, analytics ETL) are delivered via PostgreSQL NOTIFY + Celery — atomic with every transaction, no message broker required.",
  },
  {
    icon: "🌍",
    title: "English · Amharic · Oromifa",
    description:
      "Full i18n support with language packs served from S3. Users select their language; Oromifa pack reviewed by native Afaan Oromoo speakers before go-live.",
  },
  {
    icon: "📊",
    title: "AI-Ready Analytics Pipeline",
    description:
      "Separate PRODUCER and RETAILER AI cohorts. Forecasts require PENDING_APPROVAL before execution. All analytics run on read replicas — never the primary DB.",
  },
];
