"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { DEMO_TENANTS, type DemoProduct } from "@/lib/demo-data";
import { usePermission } from "@/hooks/usePermission";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useTenantName } from "@/hooks/useTenantName";

type Strategy = "FEFO" | "FIFO" | "LIFO";

interface DispatchConfig {
  id: string; product_id: string; product_name: string;
  product_sku: string; scope: string; strategy: Strategy; effective_from: string;
}

const STRATEGY_CLASS: Record<Strategy, string> = {
  FEFO: "bg-amber-100 text-amber-800 border-amber-200",
  FIFO: "bg-blue-100  text-blue-800  border-blue-200",
  LIFO: "bg-violet-100 text-violet-800 border-violet-200",
};

function FefoOverrideModal({ productName, onClose }: { productName: string; onClose: () => void }) {
  const [reason, setReason]       = useState("");
  const [submitted, setSubmitted] = useState(false);

  return (
    <>
      <div onClick={onClose} className="fixed inset-0 bg-black/40 z-[200]" />
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-white rounded-lg p-8 z-[201] w-[400px] shadow-2xl">
        {submitted ? (
          <div className="text-center">
            <div className="w-14 h-14 rounded-full bg-amber-100 flex items-center justify-center mx-auto mb-4 text-2xl">⚠️</div>
            <p className="font-bold text-base text-gray-900 mb-2">{t("dispatch.override_applied")}</p>
            <p className="text-sm text-gray-500 mb-6">{t("dispatch.override_logged")} {productName}.</p>
            <button onClick={onClose} className="px-6 py-2 bg-amber-800 text-white border-0 rounded-md text-sm font-bold cursor-pointer">
              {t("common.confirm")}
            </button>
          </div>
        ) : (
          <>
            <p className="font-bold text-base text-gray-900 mb-1">{t("dispatch.override_btn")}</p>
            <p className="text-sm text-gray-500 mb-5">
              {t("dispatch.override_warning")} <strong>{productName}</strong>. {t("dispatch.override_audit_note")}
            </p>
            <label className="block text-xs font-bold uppercase tracking-wide text-gray-700 mb-1.5">
              {t("dispatch.override_reason")} *
            </label>
            <textarea
              value={reason} onChange={(e) => setReason(e.target.value)} rows={3}
              placeholder={t("dispatch.override_placeholder")}
              className="w-full px-2.5 py-2 text-sm border border-gray-300 rounded-md outline-none resize-vertical mb-4"
            />
            <div className="flex gap-2.5">
              <button onClick={onClose} className="flex-1 py-2 bg-gray-100 border-0 rounded-md text-sm font-semibold cursor-pointer">{t("common.cancel")}</button>
              <button
                disabled={!reason.trim()}
                onClick={() => setSubmitted(true)}
                className={`flex-[2] py-2 border-0 rounded-md text-sm font-bold ${reason.trim() ? "bg-amber-800 text-white cursor-pointer" : "bg-gray-200 text-gray-400 cursor-not-allowed"}`}
              >
                {t("dispatch.override_submit")}
              </button>
            </div>
          </>
        )}
      </div>
    </>
  );
}

export default function DispatchPage() {
  const { org }      = useParams() as { org: string };
  const tenantName   = useTenantName(org);
  const user         = getSession();
  const qc           = useQueryClient();
  const canConfigure = usePermission("dispatch:configure");
  const canOverride  = usePermission("dispatch:fefo_override");
  const [overrideProduct, setOverrideProduct] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [toast, setToast]   = useState("");

  const { data: configs = [] } = useQuery<DispatchConfig[]>({
    queryKey: ["dispatch-config", org],
    queryFn:  () => api.get<DispatchConfig[]>("/api/v1/dispatch-config"),
    enabled: org !== SA_ORG_SLUG,
    staleTime: 0,
  });

  const { data: apiProducts = [] } = useQuery<Array<{ id: string; sku: string; name: string }>>({
    queryKey: ["products", org],
    queryFn:  () => api.get<Array<{ id: string; sku: string; name: string }>>("/api/v1/products"),
    enabled: org !== SA_ORG_SLUG,
    staleTime: 30_000,
  });

  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("sa.select_tenant")}</p>;
  const tenant = DEMO_TENANTS.find((ten) => ten.slug === org);
  if (!user) return <p className="p-8 text-gray-500">{t("common.no_data")}</p>;

  const displayProducts: DemoProduct[] = tenant?.products ?? apiProducts.map((p) => ({
    id: p.id, sku: p.sku, name: p.name,
    category: "—", unit: "—", batchTracking: false, reorderPoint: 0, stock: {},
  }));

  function getStrategy(productId: string): Strategy {
    return configs.find((c) => c.product_id === productId)?.strategy ?? "FIFO";
  }

  async function setStrategy(productId: string, productName: string, productSku: string, strategy: Strategy) {
    setSaving(productId);
    try {
      await api.post("/api/v1/dispatch-config", { product_id: productId, product_name: productName, product_sku: productSku, scope: "PRODUCT", strategy });
      await qc.invalidateQueries({ queryKey: ["dispatch-config", org] });
      setToast(`${productName}: ${t("dispatch.success")}`);
      setTimeout(() => setToast(""), 3000);
    } catch { setToast(t("dispatch.save_error") ); setTimeout(() => setToast(""), 3000); }
    finally { setSaving(null); }
  }

  return (
    <div className="p-8">
      {toast && (
        <div className="fixed bottom-6 right-6 z-[200] bg-[#0f2d1f] text-eth-gold font-bold text-sm px-5 py-2.5 rounded-md shadow-xl">
          {toast}
        </div>
      )}
      {overrideProduct && <FefoOverrideModal productName={overrideProduct} onClose={() => setOverrideProduct(null)} />}

      <div className="mb-6">
        <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("dispatch.title")}</h2>
        <p className="text-sm text-gray-500 mt-1">{tenantName ?? org} · {t("dispatch.subtitle")}</p>
      </div>

      {/* Strategy legend */}
      <div className="grid grid-cols-3 gap-3 mb-6">
        {(["FEFO", "FIFO", "LIFO"] as Strategy[]).map((s) => (
          <div key={s} className={`px-4 py-3.5 rounded-lg border ${STRATEGY_CLASS[s]}`}>
            <p className="font-extrabold text-sm mb-1">{s}</p>
            <p className="text-xs text-gray-500 m-0">{t(`dispatch.strategy_desc.${s}`)}</p>
          </div>
        ))}
      </div>

      {/* Auto-FEFO notice */}
      <div className="bg-yellow-50 border border-yellow-200 rounded-md px-3.5 py-2.5 mb-6 text-sm text-amber-800">
        <strong>{t("dispatch.auto_fefo")}:</strong>{" "}
        {t("dispatch.auto_fefo_note")}
        {canOverride && " " + t("dispatch.override_note")}
      </div>

      {/* Product table */}
      <div className="bg-white border border-gray-200 rounded overflow-hidden">
        <div className="h-[3px]" style={{ background: tenant?.color ?? "#1B4332" }} />
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-50 border-b-2 border-gray-200">
              {["table.sku", "table.product", "dispatch.batch_tracking", "dispatch.current_strategy",
                ...(canConfigure ? ["dispatch.set_strategy"] : []),
                ...(canOverride  ? ["dispatch.override_col"] : [])].map((key) => (
                <th key={key} className="px-3.5 py-2.5 text-left text-[11px] font-bold text-gray-500 uppercase tracking-wide">{t(key)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayProducts.map((p, idx) => {
              const strategy  = p.batchTracking ? "FEFO" : getStrategy(p.id);
              const cls       = STRATEGY_CLASS[strategy]!;
              const isAutoFefo = p.batchTracking;
              const isSaving  = saving === p.id;
              return (
                <tr key={p.id} className={`border-b border-gray-100 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                  <td className="px-3.5 py-2.5 font-mono text-[11px] text-gray-400">{p.sku}</td>
                  <td className="px-3.5 py-2.5 font-semibold text-gray-800">{p.name}</td>
                  <td className="px-3.5 py-2.5">
                    <span className={`text-xs font-bold px-2 py-0.5 rounded ${p.batchTracking ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-400"}`}>
                      {p.batchTracking ? t("dispatch.yes") : t("dispatch.no")}
                    </span>
                  </td>
                  <td className="px-3.5 py-2.5">
                    <span className={`text-xs font-bold px-2 py-0.5 rounded border ${cls}`}>
                      {strategy}{isAutoFefo ? ` (${t("dispatch.auto")})` : ""}
                    </span>
                  </td>
                  {canConfigure && (
                    <td className="px-3.5 py-2">
                      {isAutoFefo ? (
                        <span className="text-xs text-gray-300">{t("dispatch.auto_cannot_override")}</span>
                      ) : (
                        <div className="flex gap-1.5">
                          {(["FEFO", "FIFO", "LIFO"] as Strategy[]).map((strat) => {
                            const active = strategy === strat;
                            const sc = STRATEGY_CLASS[strat]!;
                            return (
                              <button key={strat} disabled={isSaving || active}
                                onClick={() => void setStrategy(p.id, p.name, p.sku, strat)}
                                className={`text-xs font-bold px-2.5 py-1 rounded border transition-all ${active ? sc : "border-gray-200 bg-white text-gray-400"} ${(isSaving || active) ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
                              >
                                {strat}
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </td>
                  )}
                  {canOverride && (
                    <td className="px-3.5 py-2">
                      {(strategy === "FEFO" || isAutoFefo) ? (
                        <button
                          onClick={() => setOverrideProduct(p.name)}
                          className="text-xs font-bold px-2.5 py-1 rounded border border-yellow-200 bg-yellow-50 text-amber-800 cursor-pointer"
                        >
                          {t("dispatch.override_btn")}
                        </button>
                      ) : (
                        <span className="text-xs text-gray-200">—</span>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
