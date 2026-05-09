import Link from "next/link";
import { DEMO_TENANTS, getTotalStock } from "@/lib/demo-data";

// ── Logo mark — small, compact ─────────────────────────────────────────────
function LogoMark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <rect width="32" height="32" rx="7" fill="#FCDD09" />
      <path d="M16 4L28 10V18L16 24L4 18V10Z" fill="#0B3D2E" />
      <path d="M16 9L23 13V18L16 22L9 18V13Z" fill="#FCDD09" />
      <path d="M16 13L19.5 15V18L16 20L12.5 18V15Z" fill="#0B3D2E" />
    </svg>
  );
}

// ── Ethiopian 3-stripe divider ────────────────────────────────────────────
function EthStripe({ height = 5 }: { height?: number }) {
  return (
    <div
      aria-hidden="true"
      style={{
        height,
        background: "linear-gradient(to right, #078930 0% 33.3%, #FCDD09 33.3% 66.6%, #DA121A 66.6% 100%)",
      }}
    />
  );
}

// ── Wavy section divider ──────────────────────────────────────────────────
function WaveDown({ fromColor, toColor }: { fromColor: string; toColor: string }) {
  return (
    <div className="w-full overflow-hidden -mb-px" aria-hidden="true">
      <svg viewBox="0 0 1440 72" preserveAspectRatio="none" className="w-full h-12 md:h-16 block">
        <rect width="1440" height="72" fill={fromColor} />
        <path d="M0 36C180 72 360 0 540 36C720 72 900 0 1080 36C1260 72 1440 0 1440 36V72H0Z" fill={toColor} />
      </svg>
    </div>
  );
}

function WaveUp({ fromColor, toColor }: { fromColor: string; toColor: string }) {
  return (
    <div className="w-full overflow-hidden -mt-px" aria-hidden="true">
      <svg viewBox="0 0 1440 72" preserveAspectRatio="none" className="w-full h-12 md:h-16 block">
        <rect width="1440" height="72" fill={fromColor} />
        <path d="M0 36C180 0 360 72 540 36C720 0 900 72 1080 36C1260 0 1440 72 1440 36V0H0Z" fill={toColor} />
      </svg>
    </div>
  );
}

// ── Mini dashboard preview ────────────────────────────────────────────────
function MiniDashboard() {
  const tenant = DEMO_TENANTS[0]!;
  const preview = tenant.products.slice(0, 5);
  return (
    <div className="rounded-2xl overflow-hidden border border-white/10 shadow-2xl w-full max-w-md">
      {/* Window title bar */}
      <div className="flex items-center gap-2 px-4 py-2.5" style={{ background: "#061410" }}>
        <span className="w-3 h-3 rounded-full bg-eth-red" />
        <span className="w-3 h-3 rounded-full bg-eth-gold" />
        <span className="w-3 h-3 rounded-full bg-eth-leaf" />
        <span className="ml-3 text-xs text-green-400 font-medium">Addis Water — Live Inventory</span>
        <span className="ml-auto flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
          <span className="text-xs text-green-400">Live</span>
        </span>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-3" style={{ background: "#0a1c12" }}>
        {[
          { v: "10",   l: "SKUs" },
          { v: "6",    l: "Locations" },
          { v: "46K+", l: "Units" },
        ].map((s) => (
          <div key={s.l} className="px-3 py-2.5 text-center border-r last:border-r-0 border-white/5">
            <p className="text-base font-bold text-eth-gold">{s.v}</p>
            <p className="text-xs text-green-400">{s.l}</p>
          </div>
        ))}
      </div>

      {/* Table */}
      <div style={{ background: "#0f2318" }}>
        <table className="w-full text-xs">
          <thead style={{ background: "#0a1c12" }}>
            <tr>
              <th className="text-left px-3 py-2 text-green-500 font-semibold">Product</th>
              <th className="text-right px-2 py-2 text-green-500 font-semibold">Main</th>
              <th className="text-right px-2 py-2 text-green-500 font-semibold">N.WH</th>
              <th className="text-right px-3 py-2 text-green-500 font-semibold">Total</th>
            </tr>
          </thead>
          <tbody>
            {preview.map((p, i) => (
              <tr key={p.id} style={{ background: i % 2 === 0 ? "#0f2318" : "#112619" }}>
                <td className="px-3 py-1.5 text-white truncate max-w-[120px]">
                  {p.name.replace("Pure Water ", "").replace("Sparkling Water ", "Spark ").replace(" — Pack of ", "×")}
                </td>
                <td className="px-2 py-1.5 text-right text-green-200 tabular-nums">
                  {(p.stock["aw-main"] ?? 0).toLocaleString()}
                </td>
                <td className="px-2 py-1.5 text-right text-green-200 tabular-nums">
                  {(p.stock["aw-north"] ?? 0).toLocaleString()}
                </td>
                <td className="px-3 py-1.5 text-right font-bold text-white tabular-nums">
                  {getTotalStock(p).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Footer */}
      <div className="px-4 py-2 flex justify-between text-xs text-green-600 border-t border-white/5" style={{ background: "#061410" }}>
        <span>FEFO dispatch ✓</span>
        <span>Synced just now</span>
      </div>
    </div>
  );
}

// ── Live inventory tables ─────────────────────────────────────────────────
function InventoryTables() {
  return (
    <section id="inventory" className="py-20 px-4 bg-eth-mist">
      <div className="max-w-7xl mx-auto">
        <div className="text-center mb-12">
          <span className="inline-block bg-eth-mint text-eth-forest text-xs font-semibold uppercase tracking-wider px-3 py-1 rounded-full mb-3">
            Live Demo Data
          </span>
          <h2 className="text-3xl font-bold text-eth-dark">Real inventory, real numbers</h2>
          <p className="text-gray-500 mt-3 max-w-xl mx-auto text-sm">
            Two live tenants with full warehouse hierarchies, product catalogues, and stock levels across all locations.
          </p>
        </div>

        <div className="space-y-10">
          {DEMO_TENANTS.map((tenant) => {
            const whs = tenant.warehouses.slice(0, 5);
            const grandTotal = tenant.products.reduce((a, p) => a + getTotalStock(p), 0);
            return (
              <div key={tenant.id} className="bg-white rounded-2xl shadow-sm border border-gray-200 overflow-hidden">
                {/* Header */}
                <div className="px-6 py-4 flex flex-wrap items-center justify-between gap-3" style={{ background: tenant.color }}>
                  <div className="flex items-center gap-3">
                    <span className="text-4xl">{tenant.logo}</span>
                    <div>
                      <h3 className="font-bold text-white text-xl">{tenant.name}</h3>
                      <p className="text-white/75 text-sm">{tenant.industry} · {tenant.warehouses.length} locations · {tenant.products.length} SKUs</p>
                    </div>
                  </div>
                  <Link
                    href={`/dashboard/tenants/${tenant.slug}`}
                    className="shrink-0 text-sm font-semibold bg-white/20 hover:bg-white/30 text-white px-4 py-2 rounded-lg transition-colors"
                  >
                    Full dashboard →
                  </Link>
                </div>

                {/* Location tabs */}
                <div className="px-6 py-3 bg-gray-50 border-b border-gray-100 flex flex-wrap gap-2">
                  {tenant.warehouses.map((w) => (
                    <span key={w.id} className={`inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full font-medium ${
                      w.type === "PRODUCTION" ? "bg-orange-100 text-orange-700" :
                      w.type === "SUBCENTER"  ? "bg-purple-100 text-purple-700" :
                                                "bg-blue-100 text-blue-700"
                    }`}>
                      {w.type === "PRODUCTION" ? "🏭" : w.type === "SUBCENTER" ? "🔖" : "🏗️"}
                      {w.parentId ? " ↳ " : " "}{w.name.replace(" Production Center", "").replace(" WH", "")}
                      {w.location ? <span className="text-[10px] opacity-60">· {w.location}</span> : null}
                    </span>
                  ))}
                </div>

                {/* Table */}
                <div className="overflow-x-auto">
                  <table className="w-full text-sm inv-table">
                    <thead className="bg-gray-50 border-b-2 border-gray-200">
                      <tr>
                        <th className="sticky left-0 bg-gray-50 text-left px-5 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">SKU</th>
                        <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Product</th>
                        <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Category</th>
                        {whs.map((w) => (
                          <th key={w.id} className="text-right px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">
                            {w.name.replace(" Production Center", "").replace(" WH", "").replace(" Subcenter", "-Sub")}
                          </th>
                        ))}
                        <th className="text-right px-5 py-3 text-xs font-semibold text-eth-forest uppercase tracking-wider">Total</th>
                        <th className="px-5 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {tenant.products.map((p, idx) => {
                        const total = getTotalStock(p);
                        const isLow = total < p.reorderPoint * tenant.warehouses.length;
                        return (
                          <tr key={p.id} className={idx % 2 === 0 ? "bg-white" : "bg-gray-50/50"}>
                            <td className="sticky left-0 px-5 py-3 font-mono text-xs text-gray-400 bg-inherit">{p.sku}</td>
                            <td className="px-4 py-3 text-gray-800 font-medium text-xs whitespace-nowrap">{p.name}</td>
                            <td className="px-4 py-3 text-xs text-gray-500">{p.category}</td>
                            {whs.map((w) => (
                              <td key={w.id} className="px-4 py-3 text-right text-gray-700 text-xs tabular-nums">
                                {(p.stock[w.id] ?? 0).toLocaleString()}
                              </td>
                            ))}
                            <td className="px-5 py-3 text-right font-bold text-gray-900 tabular-nums">{total.toLocaleString()}</td>
                            <td className="px-5 py-3">
                              <span className={`inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-0.5 rounded-full ${
                                isLow
                                  ? "bg-red-50 text-red-600 border border-red-200"
                                  : "bg-green-50 text-green-700 border border-green-200"
                              }`}>
                                <span className={`w-1.5 h-1.5 rounded-full ${isLow ? "bg-red-500" : "bg-green-500"}`} />
                                {isLow ? "Low" : "OK"}
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                    <tfoot>
                      <tr className="bg-eth-mist border-t-2 border-gray-200 font-semibold">
                        <td className="sticky left-0 bg-eth-mist px-5 py-3 text-xs text-gray-600">
                          {tenant.products.length} SKUs
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-500">{tenant.warehouses.length} locations</td>
                        <td />
                        {whs.map((w) => {
                          const colTotal = tenant.products.reduce((a, p) => a + (p.stock[w.id] ?? 0), 0);
                          return (
                            <td key={w.id} className="px-4 py-3 text-right text-xs text-eth-forest tabular-nums font-bold">
                              {colTotal.toLocaleString()}
                            </td>
                          );
                        })}
                        <td className="px-5 py-3 text-right text-sm text-eth-forest font-extrabold tabular-nums">
                          {grandTotal.toLocaleString()}
                        </td>
                        <td />
                      </tr>
                    </tfoot>
                  </table>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ── Main export ───────────────────────────────────────────────────────────
export default function HomePage() {
  return (
    <div className="min-h-screen bg-white overflow-x-hidden">

      {/* ── Navbar — compact, logo top-left ── */}
      <nav className="fixed top-0 inset-x-0 z-50 bg-white border-b border-gray-100 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-14 flex items-center gap-4">
          <Link href="/" className="flex items-center gap-2 shrink-0">
            <LogoMark size={30} />
            <span className="font-bold text-eth-dark text-sm leading-tight">
              SMART <span className="text-eth-mid font-medium hidden sm:inline">Inventory Tracker</span>
            </span>
          </Link>

          <div className="hidden md:flex items-center gap-5 ml-6 text-sm font-medium text-gray-600">
            <a href="#features"    className="hover:text-eth-forest transition-colors">Features</a>
            <a href="#inventory"   className="hover:text-eth-forest transition-colors">Live Data</a>
            <a href="#tenants"     className="hover:text-eth-forest transition-colors">Tenants</a>
            <a href="#credentials" className="hover:text-eth-forest transition-colors">Credentials</a>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <Link href="/login" className="hidden sm:inline text-sm font-medium text-eth-forest hover:text-eth-dark px-3 py-1.5 transition-colors">
              Sign in
            </Link>
            <Link href="/login"
              className="text-sm font-bold px-4 py-2 rounded-lg text-eth-dark shadow hover:opacity-90 transition"
              style={{ background: "#FCDD09" }}>
              Get started →
            </Link>
          </div>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section className="pt-14" style={{ background: "linear-gradient(155deg,#0B3D2E 0%,#1B4332 50%,#2D6A4F 100%)" }}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 pt-14 pb-6">
          <div className="grid lg:grid-cols-2 gap-10 lg:gap-16 items-center">

            {/* Copy */}
            <div className="text-center lg:text-left">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1.5 mb-5">
                <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
                <span className="text-xs font-medium text-green-200">Multi-tenant · Offline-ready · 3 languages</span>
              </div>

              <h1 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold text-white leading-[1.1] tracking-tight">
                Inventory you can
                <span className="block mt-1" style={{ color: "#FCDD09" }}>track & trust</span>
              </h1>

              <p className="mt-4 text-base sm:text-lg text-green-100/90 max-w-lg mx-auto lg:mx-0 leading-relaxed">
                Real-time ledger, FEFO dispatch, offline barcode scanning, and 3-layer security —
                purpose-built for Ethiopian producers and distributors.
              </p>

              <div className="mt-7 flex flex-wrap gap-3 justify-center lg:justify-start">
                <Link href="/login"
                  className="px-7 py-3 rounded-xl font-bold text-eth-dark text-sm shadow-lg hover:opacity-90 transition"
                  style={{ background: "#FCDD09" }}>
                  Open dashboard →
                </Link>
                <a href="#inventory"
                  className="px-7 py-3 rounded-xl font-semibold text-white text-sm border border-white/30 hover:bg-white/10 transition">
                  View live data
                </a>
              </div>

              <p className="mt-6 text-xs font-mono text-green-400 bg-white/5 border border-white/10 rounded-lg px-4 py-2.5 inline-block text-left">
                📧 smartadmin@smart-inventory.com &nbsp;·&nbsp; 🔑 SmartAdmin@2026
              </p>
            </div>

            {/* Dashboard preview */}
            <div className="flex justify-center lg:justify-end">
              <MiniDashboard />
            </div>
          </div>
        </div>
        <EthStripe height={6} />
      </section>

      {/* ── Stats ── */}
      <section style={{ background: "#1B4332" }} className="py-10 px-4">
        <div className="max-w-5xl mx-auto grid grid-cols-2 sm:grid-cols-4 gap-6 text-center">
          {[
            { v: "115",   l: "Permission actions", s: "RBAC + ABAC" },
            { v: "10",    l: "Microservices",       s: "FastAPI + Next.js" },
            { v: "3",     l: "Languages",           s: "EN · አማርኛ · Oromoo" },
            { v: "99.9%", l: "Uptime SLA",          s: "AWS ECS Fargate" },
          ].map((s) => (
            <div key={s.l}>
              <p className="text-3xl font-extrabold" style={{ color: "#FCDD09" }}>{s.v}</p>
              <p className="text-sm font-semibold text-white mt-1">{s.l}</p>
              <p className="text-xs text-green-400 mt-0.5">{s.s}</p>
            </div>
          ))}
        </div>
      </section>

      <WaveDown fromColor="#1B4332" toColor="#ffffff" />

      {/* ── Features ── */}
      <section id="features" className="py-16 px-4 bg-white">
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-12">
            <span className="inline-block bg-eth-mint text-eth-forest text-xs font-semibold uppercase tracking-wider px-3 py-1 rounded-full mb-3">
              Platform Capabilities
            </span>
            <h2 className="text-3xl font-bold text-eth-dark">Everything your warehouse team needs</h2>
            <p className="text-gray-500 mt-2 max-w-xl mx-auto text-sm">
              From barcode scanning on the warehouse floor to AI-powered demand forecasting — one platform, all roles.
            </p>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {FEATURES.map((f) => (
              <div key={f.title}
                className="p-6 rounded-2xl border border-gray-100 bg-white hover:border-eth-bright hover:shadow-md transition-all duration-200 group">
                <div className="w-12 h-12 rounded-xl flex items-center justify-center text-2xl mb-4" style={{ background: f.bg }}>
                  {f.icon}
                </div>
                <h3 className="font-semibold text-gray-900 mb-1.5 group-hover:text-eth-forest transition-colors">{f.title}</h3>
                <p className="text-sm text-gray-500 leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <WaveUp fromColor="#ffffff" toColor="#F0FDF4" />
      <EthStripe height={5} />

      {/* ── Inventory tables ── */}
      <InventoryTables />

      <EthStripe height={5} />
      <WaveDown fromColor="#F0FDF4" toColor="#ffffff" />

      {/* ── Tenant showcase ── */}
      <section id="tenants" className="py-16 px-4 bg-white">
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-10">
            <h2 className="text-3xl font-bold text-eth-dark">Two live demo companies</h2>
            <p className="text-gray-500 mt-2 text-sm">Login as SA to switch between tenants. Login as WM to see scoped warehouse view.</p>
          </div>
          <div className="grid md:grid-cols-2 gap-8">
            {DEMO_TENANTS.map((tenant) => (
              <Link key={tenant.id} href={`/dashboard/tenants/${tenant.slug}`}
                className="group block rounded-2xl overflow-hidden border border-gray-200 hover:shadow-xl hover:-translate-y-1 transition-all duration-200">
                <div className="p-6 flex items-center gap-4" style={{ background: tenant.color }}>
                  <span className="text-5xl">{tenant.logo}</span>
                  <div>
                    <h3 className="text-xl font-bold text-white">{tenant.name}</h3>
                    <p className="text-white/80 text-sm">{tenant.industry}</p>
                  </div>
                  <span className="ml-auto text-white/70 text-xs font-medium bg-white/15 px-2.5 py-1 rounded-lg">
                    {tenant.orgType}
                  </span>
                </div>
                <div className="bg-white p-5 grid grid-cols-2 gap-5">
                  <div>
                    <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Locations</p>
                    {tenant.warehouses.map((w) => (
                      <p key={w.id} className="text-xs text-gray-600 flex items-center gap-1.5 py-0.5">
                        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                          w.type === "PRODUCTION" ? "bg-orange-400" : w.type === "SUBCENTER" ? "bg-purple-400" : "bg-blue-400"
                        }`} />
                        {w.parentId ? <span className="text-gray-300">↳</span> : null}
                        {w.name}
                      </p>
                    ))}
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Categories</p>
                    {[...new Set(tenant.products.map(p => p.category))].map(cat => (
                      <p key={cat} className="text-xs text-gray-600 flex items-center gap-1.5 py-0.5">
                        <span className="w-1.5 h-1.5 rounded-full bg-gray-300 shrink-0" />
                        {cat}
                      </p>
                    ))}
                    <p className="mt-1.5 text-xs text-gray-400">{tenant.products.length} SKUs · {tenant.users.length} users</p>
                  </div>
                </div>
                <div className="px-5 py-3 bg-gray-50 border-t border-gray-100 flex items-center justify-between">
                  <div className="flex -space-x-1.5">
                    {tenant.users.slice(0, 5).map((u, i) => (
                      <div key={u.id}
                        className="w-7 h-7 rounded-full border-2 border-white flex items-center justify-center text-xs font-bold text-white"
                        style={{ background: tenant.color, zIndex: 5 - i }}>
                        {u.name[0]}
                      </div>
                    ))}
                  </div>
                  <span className="text-xs font-semibold text-eth-forest group-hover:underline">Open dashboard →</span>
                </div>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <WaveUp fromColor="#ffffff" toColor="#0B3D2E" />
      <EthStripe height={5} />

      {/* ── CTA + credentials ── */}
      <section id="credentials" style={{ background: "#0B3D2E" }} className="py-16 px-4">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-3xl font-bold text-white mb-2">Start exploring the demo</h2>
          <p className="text-green-300 mb-10 text-sm">Each role sees only what it has permission for — click any card to auto-fill the login form.</p>
          <div className="grid sm:grid-cols-3 gap-4 mb-10 text-left">
            {CREDS.map((c) => (
              <div key={c.email} className="rounded-xl p-4 border border-white/10 bg-white/5">
                <div className="flex items-center gap-2 mb-2">
                  <span className={`text-xs font-bold px-2 py-0.5 rounded ${c.cls}`}>{c.role}</span>
                  <span className="text-xs text-green-400 truncate">{c.company}</span>
                </div>
                <p className="text-xs font-mono text-green-200 break-all">{c.email}</p>
                <p className="text-xs font-mono text-green-500 mt-0.5">{c.pw}</p>
              </div>
            ))}
          </div>
          <Link href="/login"
            className="inline-flex items-center gap-2 px-8 py-3.5 rounded-xl font-bold text-eth-dark text-base shadow-xl hover:opacity-90 transition"
            style={{ background: "#FCDD09" }}>
            Sign in to dashboard →
          </Link>
        </div>
      </section>

      {/* ── Footer ── */}
      <EthStripe height={5} />
      <footer style={{ background: "#061410" }} className="py-8 px-4">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <LogoMark size={22} />
            <div>
              <p className="text-white text-sm font-semibold">SMART Inventory Tracker</p>
              <p className="text-green-700 text-xs">PRD v4.0 · Phase 0</p>
            </div>
          </div>
          <p className="text-green-800 text-xs text-center">
            FastAPI · Next.js 14 · PostgreSQL 16 · AWS ECS Fargate · Terraform
          </p>
          <p className="text-green-800 text-xs text-center">🇪🇹 EN · አማርኛ · Afaan Oromoo</p>
        </div>
      </footer>
    </div>
  );
}

// ── Static data ───────────────────────────────────────────────────────────

const FEATURES = [
  { icon: "📦", bg: "#D8F3DC", title: "Immutable Ledger", desc: "Every stock move is an append-only INSERT. Balances derived from the ledger — nothing ever overwritten." },
  { icon: "🔐", bg: "#FEF3C7", title: "RBAC + ABAC Security", desc: "115 permission actions across 3 enforcement layers: Gateway, service, and PostgreSQL Row-Level Security." },
  { icon: "🏭", bg: "#FEE2E2", title: "Location Hierarchy", desc: "Production centers, main warehouses, and sub-centers. Users are automatically scoped to their location." },
  { icon: "📱", bg: "#E0F2FE", title: "Offline + Barcode Scan", desc: "Record movements offline via camera barcode scan. IndexedDB queue syncs automatically on reconnect." },
  { icon: "⚡", bg: "#F3E8FF", title: "FEFO Dispatch Engine", desc: "Auto-enforced when expiry tracking is active. Override requires permission + reason code + audit trail." },
  { icon: "🌍", bg: "#ECFDF5", title: "EN · Amharic · Oromifa", desc: "Language packs from S3 CDN. Switch per-user. Native speaker review for Oromifa before Phase 1 go-live." },
];

const CREDS = [
  { role: "SA",  cls: "bg-red-600 text-white",    company: "All tenants",  email: "smartadmin@smart-inventory.com",  pw: "SmartAdmin@2026" },
  { role: "TA",  cls: "bg-purple-600 text-white",  company: "Addis Water",  email: "admin@addis-water.com",           pw: "AddisWater@2026" },
  { role: "TA",  cls: "bg-amber-600 text-white",   company: "Muger Cement", email: "admin@muger-cement.com",          pw: "MugerCement@2026" },
];
