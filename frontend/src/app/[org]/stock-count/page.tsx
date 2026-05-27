"use client";

import { useCallback, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, getTotalStock, type DemoProduct } from "@/lib/demo-data";
import { useScanner } from "@/hooks/useScanner";
import { t } from "@/lib/i18n";

function ScannerToggle({ products, warehouseId, open, hint, onToggle, onHint, onCount }: {
  products: DemoProduct[];
  warehouseId: string;
  open: boolean; hint: string;
  onToggle: () => void;
  onHint: (h: string) => void;
  onCount: (productId: string, warehouseId: string, qty: number) => void;
}) {
  const handleScan = useCallback((code: string) => {
    const p = products.find((pr) => pr.sku === code || pr.sku.toLowerCase() === code.toLowerCase());
    if (p) {
      const expected = warehouseId ? (p.stock[warehouseId] ?? 0) : 0;
      onCount(p.id, warehouseId, expected);
      onHint(`✓ ${p.name} — expected ${expected} pre-filled`);
    } else {
      onHint(`No product matched SKU: ${code}`);
    }
  }, [products, warehouseId, onCount, onHint]);

  const { videoRef, isActive, error: scanErr, start, stop } = useScanner(handleScan);

  function toggle() {
    if (open) { stop(); onToggle(); }
    else { onToggle(); void start(); }
  }

  return (
    <div className="relative">
      <button
        onClick={toggle}
        className={`px-3.5 py-2 rounded cursor-pointer text-xs font-bold flex items-center gap-1.5 border-2 transition-all ${
          open
            ? "border-emerald-600 bg-green-50 text-emerald-600"
            : "border-gray-300 bg-gray-50 text-gray-700"
        }`}
      >
        <span>{open ? "■" : "⬛"}</span>
        {open ? t("scanner.stop") : t("count.scan_to_count")}
      </button>
      {open && (
        <div className="absolute top-full right-0 z-50 mt-1.5 w-[280px] rounded-lg overflow-hidden shadow-xl border-2 border-emerald-600">
          {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
          <video ref={videoRef} className="w-full h-[160px] object-cover block bg-black" playsInline muted />
          {!isActive && (
            <div className="absolute top-0 left-0 right-0 h-[160px] flex items-center justify-center bg-black/50 text-white text-sm">
              {t("scanner.idle")}…
            </div>
          )}
          {(hint || scanErr) && (
            <div className={`px-2.5 py-2 bg-white text-xs font-semibold ${hint.startsWith("✓") ? "text-emerald-600" : "text-red-600"}`}>
              {hint || scanErr}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface CountEntry { productId: string; warehouseId: string; counted: string; }

function varianceCls(v: number): string {
  if (v > 0) return "text-emerald-600";
  if (v < 0) return "text-red-600";
  return "text-gray-500";
}

export default function StockCountPage() {
  const { org } = useParams() as { org: string };
  const [sessionActive, setSessionActive] = useState(false);
  const [submitted, setSubmitted]         = useState(false);
  const [counts, setCounts]               = useState<Record<string, string>>({});
  const [selectedWH, setSelectedWH]       = useState("");
  const [scannerOpen, setScannerOpen]     = useState(false);
  const [scanHint, setScanHint]           = useState("");

  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("sa.select_tenant")}</p>;
  const tenant = DEMO_TENANTS.find((ten) => ten.slug === org);
  if (!tenant) return (
    <div className="p-8">
      <h2 className="text-2xl font-bold text-[#0f2d1f] mb-2">{t("count.title")}</h2>
      <p className="text-sm text-gray-400">{t("common.no_data")}</p>
    </div>
  );

  const warehouse = tenant.warehouses.find((w) => w.id === selectedWH);
  const products: DemoProduct[] = selectedWH
    ? tenant.products.filter((p) => (p.stock[selectedWH] ?? 0) > 0)
    : tenant.products;

  function getExpected(p: DemoProduct): number { return selectedWH ? (p.stock[selectedWH] ?? 0) : getTotalStock(p); }
  function countKey(pid: string) { return `${pid}::${selectedWH}`; }

  const totalVariance = products.reduce((acc, p) => {
    const raw = counts[countKey(p.id)] ?? "";
    return raw ? acc + (parseFloat(raw) - getExpected(p)) : acc;
  }, 0);
  const filledCount = products.filter((p) => counts[countKey(p.id)] !== undefined && counts[countKey(p.id)] !== "").length;

  if (submitted) {
    return (
      <div className="p-8 max-w-[560px] mx-auto mt-16 text-center">
        <div className="w-16 h-16 rounded-full bg-green-100 flex items-center justify-center mx-auto mb-6 text-3xl">✓</div>
        <h2 className="text-2xl font-extrabold text-[#0f2d1f] mb-2">{t("count.success")}</h2>
        <p className="text-gray-500 text-sm mb-6">
          {filledCount} {t("count.products_counted")}.
        </p>
        <button
          onClick={() => { setSubmitted(false); setSessionActive(false); setCounts({}); setSelectedWH(""); }}
          className="px-6 py-2.5 bg-eth-forest text-eth-gold font-bold text-sm rounded-md border-0 cursor-pointer"
        >
          {t("count.start_session")}
        </button>
      </div>
    );
  }

  if (!sessionActive) {
    return (
      <div className="p-8">
        <h2 className="text-2xl font-bold text-[#0f2d1f] mb-2">{t("count.title")}</h2>
        <p className="text-sm text-gray-500 mb-8">{tenant.name} · {t("count.subtitle")}</p>
        <div className="bg-white border border-gray-200 rounded-lg p-8 max-w-[480px]">
          <p className="font-bold text-[15px] text-gray-800 mb-4">{t("count.start_session")}</p>
          <label className="block text-xs font-bold text-gray-700 uppercase tracking-wide mb-1.5">{t("table.location")}</label>
          <select
            value={selectedWH} onChange={(e) => setSelectedWH(e.target.value)}
            className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md outline-none mb-5 cursor-pointer"
          >
            <option value="">{t("count.all_locations")}</option>
            {tenant.warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
          <div className="px-3.5 py-3 bg-green-50 rounded-md border border-emerald-200 mb-5 text-sm text-green-800">
            {selectedWH ? `${products.length} ${t("count.products_to_count")} ${warehouse?.name}` : `${tenant.products.length} ${t("count.products_across")} ${tenant.warehouses.length} ${t("warehouses.locations")}`}
          </div>
          <button
            onClick={() => setSessionActive(true)}
            className="w-full py-3 bg-eth-forest text-eth-gold font-bold text-sm rounded-md border-0 cursor-pointer"
          >
            {t("count.start_session")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8">
      <div className="mb-6 flex items-start justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("count.session_active")}</h2>
          <p className="text-sm text-gray-500 mt-1">
            {tenant.name} · {warehouse?.name ?? t("inventory.all_locations")} · {filledCount}/{products.length} {t("count.products_counted")}
          </p>
        </div>
        <div className="flex gap-2.5">
          <ScannerToggle products={products} warehouseId={selectedWH} open={scannerOpen} hint={scanHint}
            onToggle={() => setScannerOpen((o) => !o)} onHint={setScanHint}
            onCount={(pid, wid, qty) => { const k = `${pid}::${wid}`; setCounts((c) => ({ ...c, [k]: String(qty) })); }}
          />
          <button onClick={() => { setSessionActive(false); setCounts({}); setScannerOpen(false); setScanHint(""); }}
            className="px-4 py-2 bg-gray-100 border border-gray-200 rounded text-sm font-semibold cursor-pointer text-gray-700">
            {t("common.cancel")}
          </button>
          <button onClick={() => setSubmitted(true)} disabled={filledCount === 0}
            className={`px-4 py-2 font-bold text-sm rounded border-0 ${filledCount > 0 ? "bg-emerald-600 text-white cursor-pointer" : "bg-gray-200 text-gray-400 cursor-not-allowed"}`}>
            {t("count.submit_session")} ({filledCount})
          </button>
        </div>
      </div>

      {filledCount > 0 && (
        <div className="flex gap-3 mb-6">
          {[
            { label: t("count.counted"), value: filledCount, cls: "text-eth-forest", bg: "bg-green-50" },
            { label: t("count.variance"), value: totalVariance > 0 ? `+${totalVariance.toFixed(0)}` : totalVariance.toFixed(0), cls: varianceCls(totalVariance), bg: totalVariance !== 0 ? "bg-red-50" : "bg-gray-50" },
          ].map((s) => (
            <div key={s.label} className={`px-5 py-2.5 ${s.bg} rounded-md border border-gray-200 text-center`}>
              <p className={`text-xl font-extrabold m-0 ${s.cls}`}>{s.value}</p>
              <p className="text-xs text-gray-500 mt-0.5">{s.label}</p>
            </div>
          ))}
        </div>
      )}

      <div className="bg-white border border-gray-200 rounded overflow-hidden">
        <div className="h-[3px]" style={{ background: tenant.color }} />
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-50 border-b-2 border-gray-200">
              {[
                { key: "table.sku",       align: "text-left"  },
                { key: "table.product",   align: "text-left"  },
                { key: "count.expected",  align: "text-right" },
                { key: "count.counted",   align: "text-right" },
                { key: "count.variance",  align: "text-right" },
              ].map((h) => (
                <th key={h.key} className={`px-4 py-2.5 ${h.align} text-[11px] font-bold text-gray-500 uppercase tracking-wide`}>
                  {t(h.key)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {products.map((p, idx) => {
              const key      = countKey(p.id);
              const expected = getExpected(p);
              const raw      = counts[key] ?? "";
              const counted  = raw !== "" ? parseFloat(raw) : null;
              const variance = counted !== null ? counted - expected : null;
              return (
                <tr key={p.id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                  <td className="px-4 py-2.5 font-mono text-[11px] text-gray-400">{p.sku}</td>
                  <td className="px-4 py-2.5 font-semibold text-gray-800">{p.name}</td>
                  <td className="px-4 py-2.5 text-right text-gray-500">{expected.toLocaleString()}</td>
                  <td className="px-3 py-2 text-right">
                    <input
                      type="number" min={0} step={1} value={raw}
                      onChange={(e) => setCounts((c) => ({ ...c, [key]: e.target.value }))}
                      placeholder="—"
                      className={`w-[90px] px-2 py-1.5 text-right rounded border text-sm outline-none ${raw ? "border-emerald-600 bg-green-50" : "border-gray-300 bg-white"}`}
                    />
                  </td>
                  <td className={`px-4 py-2.5 text-right font-bold ${variance !== null ? varianceCls(variance) : "text-gray-200"}`}>
                    {variance !== null ? (variance > 0 ? `+${variance.toFixed(0)}` : variance.toFixed(0)) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
