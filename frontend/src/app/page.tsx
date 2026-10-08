"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { t, getCurrentLocale, loadLocale } from "@/lib/i18n";
import { AuthLangSwitcher } from "@/components/features/auth/AuthLangSwitcher";

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
  // This page has no other post-mount state change to piggyback a re-render on
  // (unlike signup's useQuery), so re-read the locale here too, same pattern as
  // Providers.tsx / AuthLangSwitcher, so a non-"en" locale actually shows.
  const [, setLocaleTick] = useState(0);
  useEffect(() => {
    const loc = getCurrentLocale();
    if (loc !== "en") {
      loadLocale(loc).then(() => setLocaleTick((n) => n + 1)).catch(() => {});
    }
  }, []);

  const NAV_ANCHORS = [
    { href: "#features",    key: "landing.nav.features" },
    { href: "#get-started", key: "landing.nav.get_started_anchor" },
    { href: "#credentials", key: "landing.nav.credentials" },
  ];

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
          <div className="hidden md:flex items-center gap-8 mx-auto">
            {NAV_ANCHORS.map((a) => (
              <a key={a.href} href={a.href} className="nav-link">
                {t(a.key)}
              </a>
            ))}
          </div>
          <div className="flex items-center gap-3 ml-auto md:ml-0">
            <div className="hidden sm:flex">
              <AuthLangSwitcher />
            </div>
            <Link href="/login" className="btn-signin hidden sm:inline-block">
              {t("landing.nav.sign_in")}
            </Link>
            <Link href="/signup" className="btn-nav-primary">
              {t("landing.nav.get_started_cta")}
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
            {t("landing.hero.subtitle")}
          </p>
          <div className="mt-6 flex justify-center">
            <span className="inline-flex items-center gap-2 px-4 py-1.5 bg-white/[0.08] border border-white/[0.18] rounded-full text-xs font-medium text-[rgba(200,240,220,0.9)]">
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
              🇪🇹 &nbsp;English · አማርኛ · Afaan Oromoo · {t("landing.hero.badge_suffix")}
            </span>
          </div>
          <div className="mt-8 flex gap-3 justify-center flex-wrap">
            <Link href="/signup" className="btn-cta-primary">{t("landing.hero.cta_primary")}</Link>
            <Link href="/login" className="btn-hero-outline">{t("landing.nav.sign_in")}</Link>
            <a href="#features" className="btn-hero-outline">{t("landing.hero.cta_explore")}</a>
          </div>
        </div>
        <Stripe h={6} />
      </section>

      {/* ════ STATS ═════════════════════════════════════════════════════════ */}
      <section className="bg-[#1B4332] px-6 py-10">
        <div className="max-w-[1000px] mx-auto grid grid-cols-2 md:grid-cols-4 gap-8 text-center">
          {STATS.map((s) => (
            <div key={s.labelKey}>
              <p className="text-[2.25rem] font-extrabold text-[#FCDD09] m-0">{s.value}</p>
              <p className="text-[13px] font-semibold text-white mt-1">{t(s.labelKey)}</p>
              <p className="text-[11px] text-green-300 mt-0.5">{t(s.subKey)}</p>
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
              {t("landing.features.section_badge")}
            </span>
            <h2 className="text-[2rem] font-extrabold text-[#0f2d1f] m-0">
              {t("landing.features.heading")}
            </h2>
            <p className="text-[15px] text-gray-500 mt-2 max-w-[520px] mx-auto">
              {t("landing.features.subheading")}
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 border border-gray-300">
            {FEATURES.map((f, i) => (
              <div
                key={f.titleKey}
                className="cap-card"
                style={{
                  borderRight:  i % 3 === 2 ? "none" : "1px solid #D1D5DB",
                  borderBottom: i >= 3      ? "none" : "1px solid #D1D5DB",
                }}
              >
                {/* Per-feature accent color — runtime data value */}
                <div className="h-[3px] rounded-sm mb-6" style={{ background: f.accent }} />
                <div className="text-[1.75rem] mb-3">{f.icon}</div>
                <h3 className="text-[15px] font-bold text-[#0f2d1f] m-0 mb-2">{t(f.titleKey)}</h3>
                <p className="text-[13px] text-gray-500 leading-relaxed m-0">{t(f.descKey)}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <Wave from="#fff" to="#F3F4F6" flip />
      <Stripe h={4} />

      {/* ════ GET STARTED ═══════════════════════════════════════════════════ */}
      <section id="get-started" className="bg-gray-100 px-6 py-20">
        <div className="max-w-[760px] mx-auto text-center">
          <span className="inline-block text-[11px] font-bold uppercase tracking-[0.1em] text-[#2D6A4F] bg-emerald-100 px-3 py-1 rounded-full mb-3">
            {t("landing.get_started.section_badge")}
          </span>
          <h2 className="text-[2rem] font-extrabold text-[#0f2d1f] m-0">
            {t("landing.get_started.heading")}
          </h2>
          <p className="text-sm text-gray-500 mt-2 mb-8">
            {t("landing.get_started.subheading")}
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-left mb-8">
            {SETUP_STEPS.map((s) => (
              <div key={s.titleKey} className="p-4 rounded-xl bg-white border border-gray-200">
                <p className="text-[1.5rem] mb-2">{s.icon}</p>
                <p className="text-sm font-bold text-[#0f2d1f] m-0">{t(s.titleKey)}</p>
                <p className="text-[12px] text-gray-500 mt-1 m-0">{t(s.descKey)}</p>
              </div>
            ))}
          </div>
          <Link href="/signup" className="btn-cta-primary">
            {t("landing.hero.cta_primary")}
          </Link>
          <p className="text-xs text-gray-500 mt-4">
            {t("landing.get_started.already_customer")}{" "}
            <Link href="/login" className="underline text-[#2D6A4F] hover:text-[#1B4332]">
              {t("landing.nav.sign_in")}
            </Link>
          </p>
        </div>
      </section>

      <Stripe h={4} />
      <Wave from="#F3F4F6" to={BG} flip />

      {/* ════ CREDENTIALS CTA ═══════════════════════════════════════════════ */}
      {/* TEMP: remove before go-live + reset SA password (Alex) */}
      <section id="credentials" className="bg-[#0f2d1f] px-6 py-20 text-center">
        <div className="max-w-[560px] mx-auto">
          <h2 className="text-[2rem] font-extrabold text-white m-0">
            {t("landing.credentials.heading")}
          </h2>
          <p className="text-sm text-emerald-300 mt-2 mb-8">
            {t("landing.credentials.subheading")}
          </p>
          {/* TEMP: remove before go-live + reset SA password (Alex) */}
          <div className="p-5 rounded-xl bg-white/[0.05] border border-white/10 text-left mb-8">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-[11px] font-bold text-white px-1.5 py-0.5 rounded bg-red-600">{t("landing.credentials.badge")}</span>
              <span className="text-xs text-emerald-300">{t("landing.credentials.role_label")}</span>
            </div>
            <p className="text-xs font-mono text-[#a7f3d0] m-0 mb-1">smartadmin@smart-inventory.com</p>
            <p className="text-xs font-mono text-emerald-300 m-0">Admin@2026</p>
          </div>
          <Link href="/login" className="btn-cta-primary">
            {t("landing.credentials.cta")}
          </Link>
        </div>
      </section>

      {/* ════ FOOTER ════════════════════════════════════════════════════════ */}
      <Stripe h={5} />
      <footer className="bg-[#061410] px-6 py-8">
        <div className="max-w-[1200px] mx-auto flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <Logo size={24} />
            <p className="font-bold text-sm text-white m-0">SMART Inventory Tracker</p>
          </div>
          <p className="text-xs text-green-900">{t("landing.footer.stack")}</p>
          <p className="text-xs text-green-900">🇪🇹 EN · አማርኛ · Afaan Oromoo</p>
        </div>
      </footer>
    </div>
  );
}

/* ─── Static data ────────────────────────────────────────────────────────── */

const STATS = [
  { value: "115",   labelKey: "landing.stats.actions_label",   subKey: "landing.stats.actions_sub" },
  { value: "10",    labelKey: "landing.stats.services_label",  subKey: "landing.stats.services_sub" },
  { value: "3",     labelKey: "landing.stats.languages_label", subKey: "landing.stats.languages_sub" },
  { value: "99.9%", labelKey: "landing.stats.uptime_label",    subKey: "landing.stats.uptime_sub" },
];

const FEATURES = [
  { icon: "📦", accent: "#40916C", titleKey: "landing.features.ledger.title",    descKey: "landing.features.ledger.desc" },
  { icon: "🔐", accent: "#FCDD09", titleKey: "landing.features.rbac.title",      descKey: "landing.features.rbac.desc" },
  { icon: "🏭", accent: "#DA121A", titleKey: "landing.features.hierarchy.title", descKey: "landing.features.hierarchy.desc" },
  { icon: "📱", accent: "#0891B2", titleKey: "landing.features.offline.title",   descKey: "landing.features.offline.desc" },
  { icon: "⚡", accent: "#7C3AED", titleKey: "landing.features.dispatch.title",  descKey: "landing.features.dispatch.desc" },
  { icon: "🌍", accent: "#078930", titleKey: "landing.features.i18n.title",      descKey: "landing.features.i18n.desc" },
];

const SETUP_STEPS = [
  { icon: "🏢", titleKey: "landing.get_started.step1_title", descKey: "landing.get_started.step1_desc" },
  { icon: "👤", titleKey: "landing.get_started.step2_title", descKey: "landing.get_started.step2_desc" },
  { icon: "✅", titleKey: "landing.get_started.step3_title", descKey: "landing.get_started.step3_desc" },
];
