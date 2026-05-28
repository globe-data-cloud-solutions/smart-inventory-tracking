"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { t } from "@/lib/i18n";

function toOrgAbbr(slug: string): string {
  return slug.split("-").map((w) => (w[0] ?? "").toUpperCase()).join("").slice(0, 4);
}

function FieldLabel({ text, hint }: { text: string; hint?: string }) {
  return (
    <label className="block text-xs font-bold uppercase tracking-wide text-gray-700 mb-1">
      {text}
      {hint && <span className="text-[11px] font-normal normal-case tracking-normal text-gray-400 ml-1.5">{hint}</span>}
    </label>
  );
}

function FieldErr({ msg }: { msg?: string }) {
  if (!msg) return null;
  const key = `product.add.error.${msg}`; const resolved = t(key);
  return <p role="alert" className="text-xs text-red-600 mt-1">{resolved !== key ? resolved : msg}</p>;
}

function Toast({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  useEffect(() => { const id = setTimeout(onDismiss, 4000); return () => clearTimeout(id); }, [onDismiss]);
  return (
    <div role="status" aria-live="polite" className="fixed bottom-6 right-6 z-[9999] bg-emerald-600 text-white px-5 py-3 rounded-md text-sm font-semibold shadow-xl">
      {message}
    </div>
  );
}

interface AddProductPanelProps { apiBase: string; onClose?: () => void; categories?: string[]; }

const fieldCls = "w-full px-3 py-2 rounded text-sm outline-none border";
const fieldOk  = `${fieldCls} border-gray-300`;
const fieldErr = `${fieldCls} border-red-600`;

export function AddProductPanel({ apiBase, onClose }: AddProductPanelProps) {
  const { org = "admin" } = useParams<{ org: string }>();
  const orgAbbr = toOrgAbbr(org);
  const token   = getToken();
  const qc      = useQueryClient();

  const [open, setOpen]                         = useState(false);
  const [name, setName]                         = useState("");
  const [category, setCategory]                 = useState("");
  const [isCustomCategory, setIsCustomCategory] = useState(false);
  const [typeCode, setTypeCode]                 = useState("");
  const [unit, setUnit]                         = useState<string>("");
  const [packSize, setPackSize]                 = useState<string>("1");
  const [reorderPoint, setReorderPoint]         = useState("");
  const [nameErr, setNameErr]                   = useState("");
  const [categoryErr, setCategoryErr]           = useState("");
  const [typeCodeErr, setTypeCodeErr]           = useState("");
  const [submitting, setSubmitting]             = useState(false);
  const [panelError, setPanelError]             = useState("");
  const [toast, setToast]                       = useState<string | null>(null);
  const [copied, setCopied]                     = useState(false);

  const { data: counterData, isFetching: skuLoading } = useQuery({
    queryKey: ["next-sku-counter", apiBase],
    queryFn:  () => api.get<{ counter: number }>(`${apiBase}/next-sku`, token ?? undefined),
    enabled:  open, staleTime: 0, refetchOnWindowFocus: false,
  });

  const { data: apiCategoriesData } = useQuery<{ id: string; name: string }[]>({
    queryKey: ["product-categories"],
    queryFn:  async () => {
      const res = await api.get<{ data: { id: string; name: string }[] }>(`${apiBase}/categories/`, token ?? undefined);
      return (res as unknown as { data: { id: string; name: string }[] }).data ?? (res as unknown as { id: string; name: string }[]);
    },
    enabled:  open && !!token,
    staleTime: 30_000,
  });

  const apiCategories: string[] = (apiCategoriesData ?? []).map((c) => c.name);

  const counter = counterData?.counter;

  const typeDisplay = typeCode.trim().toUpperCase() || "???";
  const previewSku  = counter != null ? `${orgAbbr}-${typeDisplay}-${unit}${packSize}-${String(counter).padStart(4, "0")}` : "";
  const nameOk     = name.trim().length > 0;
  const categoryOk = category.trim().length > 0;
  const typeCodeOk = /^[A-Za-z]{2,5}$/.test(typeCode.trim());
  const saveDisabled = !nameOk || !categoryOk || !typeCodeOk || submitting || skuLoading;

  const resetForm = () => {
    setName(""); setCategory(""); setIsCustomCategory(false); setTypeCode(""); setUnit(""); setPackSize("1");
    setReorderPoint(""); setNameErr(""); setCategoryErr(""); setTypeCodeErr(""); setPanelError("");
  };
  const openPanel  = () => { resetForm(); setOpen(true); };
  const closePanel = () => {
    if ((name.trim() || typeCode.trim()) && !window.confirm(t("product.add.confirm.discard"))) return;
    resetForm(); setOpen(false); onClose?.();
  };

  const handleSave = async () => {
    let valid = true;
    if (!name.trim())     { setNameErr("name_required");             valid = false; }
    if (!category.trim()) { setCategoryErr("Category is required."); valid = false; }
    if (!typeCodeOk)      { setTypeCodeErr("type_code_min");         valid = false; }
    if (!valid) return;
    setSubmitting(true); setPanelError("");
    try {
      const reorderQty = parseFloat(reorderPoint);
      const parsedPack = parseInt(packSize, 10);
      const data = await api.post<{ id: string; sku: string }>(apiBase, {
        name:          name.trim(),
        category:      category.trim(),
        unit:          unit.trim() || "units",
        pack_size:     !isNaN(parsedPack) && parsedPack > 0 ? parsedPack : 1,
        reorder_point: !isNaN(reorderQty) && reorderQty > 0 ? reorderQty : undefined,
      }, token ?? undefined);
      setToast(t("product.add.success").replace("{{sku}}", data.sku));
      void qc.invalidateQueries({ queryKey: ["products"] });
      void qc.invalidateQueries({ queryKey: ["product-categories"] });
      resetForm(); setOpen(false); onClose?.();
    } catch (err) {
      const e = err as Error & { status?: number };
      if (e.status === 409)      setNameErr("duplicate_name");
      else if (e.status === 429) setPanelError(t("product.add.error.sku_cap_reached"));
      else                       setPanelError(t("product.add.error.generic"));
    } finally { setSubmitting(false); }
  };

  const handleCopy = async () => {
    if (!previewSku || previewSku.includes("???")) return;
    await navigator.clipboard.writeText(previewSku);
    setCopied(true); setTimeout(() => setCopied(false), 2000);
  };

  const selectCls = "w-full px-3 py-2 rounded text-sm border border-gray-300 bg-white outline-none cursor-pointer";
  const showCategoryDropdown = apiCategories.length > 0 && !isCustomCategory;

  return (
    <>
      <button onClick={openPanel} className="px-4 py-2 bg-eth-gold text-[#0f2d1f] font-bold text-sm rounded border-0 cursor-pointer">
        {t("product.add.button")}
      </button>

      {open && <div aria-hidden="true" onClick={closePanel} className="fixed inset-0 z-[100] bg-black/40" />}

      <aside role="dialog" aria-modal="true" aria-label={t("product.add.title")}
        className={`fixed top-0 right-0 bottom-0 z-[101] w-[440px] bg-white shadow-2xl flex flex-col transition-transform duration-[250ms] ease-out ${open ? "translate-x-0" : "translate-x-full"}`}>

        {/* Header */}
        <div className="px-5 py-4 bg-[#0f2d1f] border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-base font-bold text-white m-0">{t("product.add.title")}</h2>
          <button onClick={closePanel} aria-label={t("product.add.cancel")} className="bg-transparent border-0 text-white/70 text-xl cursor-pointer p-1 leading-none">×</button>
        </div>

        {/* SKU preview banner */}
        <div className="px-5 py-2.5 bg-green-50 border-b border-emerald-200 flex items-center gap-2.5">
          <span className="text-[11px] font-bold text-gray-500 uppercase tracking-wide shrink-0">{t("product.add.field.sku")}</span>
          <span className={`font-mono text-[15px] font-extrabold flex-1 tracking-widest ${previewSku && !previewSku.includes("???") ? "text-emerald-600" : "text-gray-400"}`}>
            {skuLoading ? t("product.add.loading_sku") : (previewSku || t("product.add.field.sku_placeholder"))}
          </span>
          <button type="button" onClick={handleCopy} disabled={!previewSku || previewSku.includes("???")}
            className={`px-2.5 py-1 border border-emerald-200 rounded bg-white text-xs text-emerald-600 font-semibold shrink-0 ${(previewSku && !previewSku.includes("???")) ? "cursor-pointer" : "cursor-not-allowed"}`}>
            {copied ? t("product.add.field.sku_copied") : t("product.add.field.sku_copy")}
          </button>
        </div>

        {/* Form body */}
        <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-4">
          {panelError && (
            <div role="alert" className="bg-red-50 border border-red-200 rounded px-3.5 py-2.5 text-sm text-red-600">
              {panelError}
            </div>
          )}

          {/* Product Name */}
          <div>
            <FieldLabel text={t("product.add.field.name")} />
            <input value={name} onChange={(e) => { setName(e.target.value); setNameErr(""); }}
              placeholder={t("product.add.field.name_placeholder")} maxLength={255} aria-required="true"
              className={nameErr ? fieldErr : fieldOk} />
            <FieldErr msg={nameErr} />
          </div>

          {/* Category */}
          <div>
            <FieldLabel text={t("inventory.category")} />
            {showCategoryDropdown ? (
              <select value={category} onChange={(e) => {
                  if (e.target.value === "__new__") { setIsCustomCategory(true); setCategory(""); }
                  else { setCategory(e.target.value); setCategoryErr(""); }
                }}
                aria-required="true" className={categoryErr ? `${selectCls.replace("border-gray-300","border-red-600")}` : selectCls}>
                <option value="">— {t("receive_panel.select_type")} —</option>
                {apiCategories.map((c) => <option key={c} value={c}>{c}</option>)}
                <option value="__new__">+ {t("add_product.new_category")}</option>
              </select>
            ) : (
              <div className="flex gap-1.5">
                <input value={category} onChange={(e) => { setCategory(e.target.value); setCategoryErr(""); }}
                  placeholder="e.g. Bottled Water, Cement, Packaging" maxLength={100} aria-required="true"
                  className={`flex-1 ${categoryErr ? fieldErr : fieldOk}`} />
                {isCustomCategory && (
                  <button type="button" onClick={() => { setIsCustomCategory(false); setCategory(""); }}
                    className="px-2.5 text-xs bg-gray-100 border border-gray-300 rounded cursor-pointer text-gray-500 whitespace-nowrap">
                    ← {t("add_product.back")}
                  </button>
                )}
              </div>
            )}
            {categoryErr && <p role="alert" className="text-xs text-red-600 mt-1">{categoryErr}</p>}
          </div>

          {/* Product Type Code */}
          <div>
            <FieldLabel text={t("product.add.field.type_code")} hint={t("product.add.field.type_code_hint")} />
            <input value={typeCode} onChange={(e) => { const v = e.target.value.replace(/[^A-Za-z]/g, "").slice(0, 5); setTypeCode(v); setTypeCodeErr(""); }}
              placeholder={t("product.add.field.type_code_placeholder")} maxLength={5} aria-required="true"
              className={`uppercase ${typeCodeErr ? fieldErr : fieldOk}`} />
            <FieldErr msg={typeCodeErr} />
          </div>

          {/* Unit + Pack Size */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <FieldLabel text={t("product.add.field.unit")} hint={`(${t("receive_panel.optional")})`} />
              <input
                value={unit}
                onChange={(e) => setUnit(e.target.value)}
                placeholder="e.g. KG, Box, Bag"
                maxLength={20}
                className={fieldOk}
              />
            </div>
            <div>
              <FieldLabel text={t("product.add.field.pack_size")} />
              <input
                type="number"
                min="1"
                step="1"
                value={packSize}
                onChange={(e) => setPackSize(e.target.value)}
                placeholder="1"
                className={fieldOk}
              />
            </div>
          </div>

          {/* Reorder Point */}
          <div>
            <FieldLabel
              text={unit.trim() ? `${t("table.reorder_point")} (${unit.trim()})` : t("table.reorder_point")}
              hint={`(${t("receive_panel.optional")})`}
            />
            <input type="number" min="0" step="1" value={reorderPoint} onChange={(e) => setReorderPoint(e.target.value)} placeholder="0" className={fieldOk} />
          </div>

          {typeCode.trim().length >= 2 && previewSku && (
            <div className="bg-green-50 border border-emerald-200 rounded px-3 py-2 text-xs text-gray-700">
              <span className="font-semibold">{t("product.add.sku_preview_label")}: </span>
              <span className="font-mono text-emerald-600 font-bold">{previewSku}</span>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3.5 border-t border-gray-200 flex justify-end gap-2.5">
          <button type="button" onClick={closePanel} className="px-4 py-2 rounded border border-gray-300 bg-white text-sm font-semibold text-gray-700 cursor-pointer">
            {t("product.add.cancel")}
          </button>
          <button type="button" onClick={handleSave} disabled={saveDisabled}
            className={`px-4 py-2 rounded border-0 text-sm font-bold flex items-center gap-2 ${saveDisabled ? "bg-gray-300 text-gray-400 cursor-not-allowed" : "bg-[#0f2d1f] text-eth-gold cursor-pointer"}`}>
            {submitting && <span className="w-3.5 h-3.5 rounded-full border-2 border-eth-gold/30 border-t-eth-gold animate-spin inline-block" />}
            {t("product.add.save")}
          </button>
        </div>
      </aside>

      {toast && <Toast message={toast} onDismiss={() => setToast(null)} />}
    </>
  );
}
