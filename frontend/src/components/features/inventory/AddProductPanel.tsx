"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { t } from "@/lib/i18n";

// ── small presentational helpers ─────────────────────────────────────────────

function FieldLabel({ text, hint, required }: { text: string; hint?: string; required?: boolean }) {
  return (
    <label className="block text-xs font-bold uppercase tracking-wide text-gray-700 mb-1">
      {text}
      {required && <span className="text-red-500 ml-0.5">*</span>}
      {hint && (
        <span className="text-[11px] font-normal normal-case tracking-normal text-gray-400 ml-1.5">
          {hint}
        </span>
      )}
    </label>
  );
}

function FieldErr({ msg }: { msg?: string }) {
  if (!msg) return null;
  const key = `product.add.error.${msg}`;
  const resolved = t(key);
  return (
    <p role="alert" className="text-xs text-red-600 mt-1">
      {resolved !== key ? resolved : msg}
    </p>
  );
}

function Toast({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  useEffect(() => {
    const id = setTimeout(onDismiss, 4000);
    return () => clearTimeout(id);
  }, [onDismiss]);
  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed bottom-6 right-6 z-[9999] bg-emerald-600 text-white px-5 py-3 rounded-md text-sm font-semibold shadow-xl"
    >
      {message}
    </div>
  );
}

// ── create-or-select component ────────────────────────────────────────────────
// Reusable dropdown that renders "existing options + + Create new" entry.

interface SelectOrCreateProps {
  options: string[];
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  inputPlaceholder?: string;
  hasError?: boolean;
  createLabel?: string;
  backLabel?: string;
}

const selectCls = "w-full px-3 py-2 rounded text-sm border border-gray-300 bg-white outline-none cursor-pointer";
const fieldOk   = "w-full px-3 py-2 rounded text-sm outline-none border border-gray-300";
const fieldErr  = "w-full px-3 py-2 rounded text-sm outline-none border border-red-600";

function SelectOrCreate({
  options, value, onChange, placeholder, inputPlaceholder,
  hasError, createLabel = "+ Create new", backLabel = "← Back",
}: SelectOrCreateProps) {
  const [custom, setCustom] = useState(false);

  if (custom || (options.length === 0)) {
    return (
      <div className="flex gap-1.5">
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={inputPlaceholder ?? "Type to create new…"}
          className={`flex-1 ${hasError ? fieldErr : fieldOk}`}
        />
        {options.length > 0 && (
          <button
            type="button"
            onClick={() => { setCustom(false); onChange(""); }}
            className="px-2.5 text-xs bg-gray-100 border border-gray-300 rounded cursor-pointer text-gray-500 whitespace-nowrap"
          >
            {backLabel}
          </button>
        )}
      </div>
    );
  }

  return (
    <select
      value={value}
      onChange={(e) => {
        if (e.target.value === "__new__") { setCustom(true); onChange(""); }
        else onChange(e.target.value);
      }}
      className={hasError ? selectCls.replace("border-gray-300", "border-red-600") : selectCls}
    >
      <option value="">— {placeholder ?? "Select…"} —</option>
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
      <option value="__new__">{createLabel}</option>
    </select>
  );
}

// ── type code selector (shows code + description) ─────────────────────────────

interface TypeCodeOption { id: string; code: string; description?: string | null }

interface TypeCodeSelectProps {
  options: TypeCodeOption[];
  value: string;
  onChange: (code: string) => void;
  hasError?: boolean;
}

function TypeCodeSelect({ options, value, onChange, hasError }: TypeCodeSelectProps) {
  const [custom, setCustom] = useState(false);

  if (custom || options.length === 0) {
    return (
      <div className="flex gap-1.5">
        <input
          value={value}
          onChange={(e) => onChange(e.target.value.replace(/[^A-Za-z]/g, "").toUpperCase().slice(0, 10))}
          placeholder="e.g. BRD, CEM, PKG"
          maxLength={10}
          className={`flex-1 uppercase ${hasError ? fieldErr : fieldOk}`}
        />
        {options.length > 0 && (
          <button
            type="button"
            onClick={() => { setCustom(false); onChange(""); }}
            className="px-2.5 text-xs bg-gray-100 border border-gray-300 rounded cursor-pointer text-gray-500 whitespace-nowrap"
          >
            ← {t("add_product.back")}
          </button>
        )}
      </div>
    );
  }

  return (
    <select
      value={value}
      onChange={(e) => {
        if (e.target.value === "__new__") { setCustom(true); onChange(""); }
        else onChange(e.target.value);
      }}
      className={hasError ? selectCls.replace("border-gray-300", "border-red-600") : selectCls}
    >
      <option value="">— {t("receive_panel.select_type")} —</option>
      {options.map((o) => (
        <option key={o.id} value={o.code}>
          {o.code}{o.description ? ` — ${o.description}` : ""}
        </option>
      ))}
      <option value="__new__">+ {t("add_product.new_category")}</option>
    </select>
  );
}

// ── packaging type selector ───────────────────────────────────────────────────

interface PackagingTypeOption { id: string; name: string; units_per_package: number }

// ── main component ────────────────────────────────────────────────────────────

interface AddProductPanelProps { apiBase: string; onClose?: () => void; categories?: string[] }

export function AddProductPanel({ apiBase, onClose }: AddProductPanelProps) {
  const { org = "admin" } = useParams<{ org: string }>();
  const token = getToken();
  const qc    = useQueryClient();

  // ── form state ─────────────────────────────────────────────────────────
  const [open, setOpen]             = useState(false);
  const [name, setName]             = useState("");
  const [shortName, setShortName]   = useState("");
  const [description, setDesc]      = useState("");
  const [category, setCategory]     = useState("");
  const [typeCode, setTypeCode]     = useState("");
  const [brand, setBrand]           = useState("");
  const [unit, setUnit]             = useState("");
  const [packagingType, setPkgType] = useState("");
  const [unitsPerPkg, setUpp]       = useState<string>("1");
  const [reorderPoint, setReorder]  = useState("");
  const [skuOverride, setSkuOvr]    = useState("");
  const [skuEditing, setSkuEditing] = useState(false);

  // ── approval minimums state ────────────────────────────────────────────
  interface HierarchyLevelInfo {
    level_number: number;
    level_name: string;
    default_role_code: string;
    role_display_label: string;
    is_stock_holding: boolean;
  }
  const ROLE_AUTH_MAP: Record<string, number> = {
    SA: 1, TA: 1, NM: 1, RM: 2, LM: 3, WM: 4,
  };
  const MIN_TX_TYPES = [
    { key: "PULL",       label: "PULL Transfer" },
    { key: "PUSH",       label: "PUSH Transfer" },
    { key: "SISTER",     label: "SISTER Transfer" },
    { key: "ADJUSTMENT", label: "Adjustment" },
    { key: "RECEIVE",    label: "Receive Stock" },
    { key: "ISSUE",      label: "Issue Stock" },
  ] as const;
  type MinimumRow = { transaction_type: string; min_authority_level: string };
  const [minimumRows, setMinimumRows] = useState<MinimumRow[]>(
    MIN_TX_TYPES.map((tx) => ({ transaction_type: tx.key, min_authority_level: "" }))
  );

  // ── error state ────────────────────────────────────────────────────────
  const [nameErr, setNameErr]       = useState("");
  const [typeCodeErr, setTcErr]     = useState("");
  const [categoryErr, setCatErr]    = useState("");
  const [submitting, setSub]        = useState(false);
  const [panelError, setPanelError] = useState("");
  const [toast, setToast]           = useState<string | null>(null);
  const [copied, setCopied]         = useState(false);

  const skuInputRef = useRef<HTMLInputElement>(null);

  // ── API lookups ────────────────────────────────────────────────────────
  const { data: categoriesData } = useQuery<{ id: string; name: string }[]>({
    queryKey:  ["product-categories"],
    queryFn:   async () => {
      const r = await api.get<unknown>(`${apiBase}/categories/`, token ?? undefined);
      return ((r as { data?: unknown }).data ?? r) as { id: string; name: string }[];
    },
    enabled:   open && !!token,
    staleTime: 30_000,
  });

  const { data: brandsData } = useQuery<{ id: string; name: string }[]>({
    queryKey:  ["product-brands"],
    queryFn:   async () => {
      const r = await api.get<unknown>(`${apiBase}/brands/`, token ?? undefined);
      return ((r as { data?: unknown }).data ?? r) as { id: string; name: string }[];
    },
    enabled:   open && !!token,
    staleTime: 30_000,
  });

  const { data: typeCodesData } = useQuery<TypeCodeOption[]>({
    queryKey:  ["product-type-codes"],
    queryFn:   async () => {
      const r = await api.get<unknown>(`${apiBase}/type-codes/`, token ?? undefined);
      return ((r as { data?: unknown }).data ?? r) as TypeCodeOption[];
    },
    enabled:   open && !!token,
    staleTime: 30_000,
  });

  const { data: uomsData } = useQuery<{ id: string; name: string }[]>({
    queryKey:  ["product-uoms"],
    queryFn:   async () => {
      const r = await api.get<unknown>(`${apiBase}/uoms/`, token ?? undefined);
      return ((r as { data?: unknown }).data ?? r) as { id: string; name: string }[];
    },
    enabled:   open && !!token,
    staleTime: 30_000,
  });

  const { data: packagingTypesData } = useQuery<PackagingTypeOption[]>({
    queryKey:  ["product-packaging-types"],
    queryFn:   async () => {
      const r = await api.get<unknown>(`${apiBase}/packaging-types/`, token ?? undefined);
      return ((r as { data?: unknown }).data ?? r) as PackagingTypeOption[];
    },
    enabled:   open && !!token,
    staleTime: 30_000,
  });

  // ── Hierarchy levels for approval minimum dropdown ────────────────────
  const { data: hierarchyLevels = [] } = useQuery<HierarchyLevelInfo[]>({
    queryKey:  ["hierarchy-config", org],
    queryFn:   async () => {
      const r = await api.get<unknown>(`/api/v1/tenants/${org}/hierarchy/config`, token ?? undefined);
      return ((r as { data?: unknown }).data ?? r) as HierarchyLevelInfo[];
    },
    enabled:   open && !!token,
    staleTime: 60_000,
  });

  // ── Tenant default approval rules for preview ──────────────────────────
  type TenantRulePreview = { transaction_type: string; max_quantity: number | null; approver_role: string };
  const { data: tenantDefaultRules = [] } = useQuery<TenantRulePreview[]>({
    queryKey:  ["tenant-approval-rules", org],
    queryFn:   async () => {
      const r = await api.get<unknown>(`/api/v1/tenants/${org}/approval-rules`, token ?? undefined);
      return ((r as { data?: unknown }).data ?? r) as TenantRulePreview[];
    },
    enabled:   open && !!token,
    staleTime: 60_000,
  });

  // ── Pre-populate from latest product minimums ──────────────────────────
  type LatestMinimumsResp = { minimums: { transaction_type: string; min_authority_level: number }[] };
  const { data: latestMinimumsData } = useQuery<LatestMinimumsResp>({
    queryKey:  ["product-minimums-latest", apiBase],
    queryFn:   async () => {
      const r = await api.get<unknown>(`${apiBase}/approval-minimums/latest`, token ?? undefined);
      return ((r as { data?: unknown }).data ?? r) as LatestMinimumsResp;
    },
    enabled:   open && !!token,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (!latestMinimumsData?.minimums?.length) return;
    setMinimumRows((prev) =>
      prev.map((row) => {
        const match = latestMinimumsData.minimums.find(
          (m) => m.transaction_type === row.transaction_type
        );
        if (!match) return row;
        return { ...row, min_authority_level: String(match.min_authority_level) };
      })
    );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latestMinimumsData]);

  // ── SKU preview via /next-sku?type_code=BRD ────────────────────────────
  const { data: skuPreviewData, isFetching: skuLoading } = useQuery<{ sku: string; counter: number | null }>({
    queryKey:  ["next-sku", apiBase, typeCode],
    queryFn:   async () => {
      if (!typeCode.trim()) return { sku: "", counter: null };
      const r = await api.get<unknown>(
        `${apiBase}/next-sku?type_code=${encodeURIComponent(typeCode.trim())}`,
        token ?? undefined,
      );
      return ((r as { data?: unknown }).data ?? r) as { sku: string; counter: number | null };
    },
    enabled:   open && typeCode.trim().length >= 2,
    staleTime: 0,
    refetchOnWindowFocus: false,
  });

  const generatedSku = skuPreviewData?.sku ?? "";
  const displaySku   = skuEditing ? skuOverride : (generatedSku || "");
  const skuOk        = displaySku.trim().length > 0;

  // When generated SKU changes, sync into override field if not manually editing.
  useEffect(() => {
    if (!skuEditing && generatedSku) setSkuOvr(generatedSku);
  }, [generatedSku, skuEditing]);

  // ── derived options ────────────────────────────────────────────────────
  const categoryOptions = (categoriesData ?? []).map((c) => c.name);
  const brandOptions    = (brandsData ?? []).map((b) => b.name);
  const uomOptions      = (uomsData ?? []).map((u) => u.name);
  const typeCodeOptions = typeCodesData ?? [];
  const pkgTypeOptions  = packagingTypesData ?? [];
  const pkgTypeNames    = pkgTypeOptions.map((p) => p.name);

  const selectedPkg = pkgTypeOptions.find(
    (p) => p.name.toLowerCase() === packagingType.toLowerCase(),
  );

  // Auto-fill units_per_package from existing record.
  useEffect(() => {
    if (selectedPkg) setUpp(String(selectedPkg.units_per_package));
  }, [selectedPkg]);

  const packagingPreview =
    packagingType.trim() && unit.trim()
      ? `${t("product.add.sold_as")}: ${packagingType} of ${unitsPerPkg || "?"} ${unit}`
      : null;

  // ── validation & save ─────────────────────────────────────────────────
  const typeCodeOk  = /^[A-Za-z]{2,10}$/.test(typeCode.trim());
  const categoryOk  = category.trim().length > 0;
  const saveDisabled = !name.trim() || !categoryOk || !typeCodeOk || !skuOk || submitting || skuLoading;

  const resetForm = () => {
    setName(""); setShortName(""); setDesc(""); setCategory("");
    setTypeCode(""); setBrand(""); setUnit(""); setPkgType("");
    setUpp("1"); setReorder(""); setSkuOvr(""); setSkuEditing(false);
    setNameErr(""); setTcErr(""); setCatErr(""); setPanelError("");
    setMinimumRows(MIN_TX_TYPES.map((tx) => ({ transaction_type: tx.key, min_authority_level: "" })));
  };

  const openPanel  = () => { resetForm(); setOpen(true); };
  const closePanel = () => {
    if ((name.trim() || typeCode.trim()) && !window.confirm(t("product.add.confirm.discard"))) return;
    resetForm(); setOpen(false); onClose?.();
  };

  const handleSave = async () => {
    let valid = true;
    if (!name.trim())    { setNameErr("name_required"); valid = false; }
    if (!categoryOk)     { setCatErr("Category is required."); valid = false; }
    if (!typeCodeOk)     { setTcErr("type_code_min"); valid = false; }
    if (!valid) return;

    setSub(true); setPanelError("");
    try {
      const reorderQty = parseFloat(reorderPoint);
      const uppVal     = parseInt(unitsPerPkg, 10);
      const product = await api.post<{ id: string; sku: string }>(
        apiBase,
        {
          name:              name.trim(),
          short_name:        shortName.trim() || undefined,
          description:       description.trim() || undefined,
          category:          category.trim() || undefined,
          type_code:         typeCode.trim().toUpperCase(),
          brand:             brand.trim() || undefined,
          unit:              unit.trim() || "units",
          packaging_type:    packagingType.trim() || undefined,
          units_per_package: packagingType.trim() && !isNaN(uppVal) && uppVal > 0 ? uppVal : undefined,
          reorder_point:     !isNaN(reorderQty) && reorderQty > 0 ? reorderQty : undefined,
          sku_override:      skuEditing && skuOverride.trim() ? skuOverride.trim() : undefined,
        },
        token ?? undefined,
      );

      // Save product-level approval minimums if any were set
      const filledMinimums = minimumRows.filter((r) => r.min_authority_level !== "");
      if (filledMinimums.length > 0) {
        await api.put<unknown>(
          `${apiBase}/${product.id}/approval-minimums`,
          {
            entries: filledMinimums.map((r) => ({
              transaction_type:    r.transaction_type,
              min_authority_level: Number(r.min_authority_level),
            })),
          },
          token ?? undefined,
        );
      }

      setToast(t("product.add.success").replace("{{sku}}", product.sku));
      void qc.invalidateQueries({ queryKey: ["products"] });
      void qc.invalidateQueries({ queryKey: ["product-categories"] });
      void qc.invalidateQueries({ queryKey: ["product-brands"] });
      void qc.invalidateQueries({ queryKey: ["product-type-codes"] });
      void qc.invalidateQueries({ queryKey: ["product-uoms"] });
      void qc.invalidateQueries({ queryKey: ["product-packaging-types"] });
      void qc.invalidateQueries({ queryKey: ["next-sku"] });
      void qc.invalidateQueries({ queryKey: ["product-minimums-latest"] });
      resetForm(); setOpen(false); onClose?.();
    } catch (err) {
      const e = err as Error & { status?: number; code?: string };
      if (e.status === 409 && e.code === "duplicate_sku") setPanelError(t("product.add.error.duplicate_sku") || `SKU '${displaySku}' already exists. Edit the SKU and try again.`);
      else if (e.status === 409) setNameErr("duplicate_name");
      else if (e.status === 429) setPanelError(t("product.add.error.sku_cap_reached"));
      else setPanelError(t("product.add.error.generic"));
    } finally { setSub(false); }
  };

  const handleCopy = async () => {
    if (!displaySku) return;
    await navigator.clipboard.writeText(displaySku);
    setCopied(true); setTimeout(() => setCopied(false), 2000);
  };

  const startSkuEdit = () => {
    setSkuEditing(true);
    setTimeout(() => skuInputRef.current?.focus(), 50);
  };

  // ── render ────────────────────────────────────────────────────────────
  return (
    <>
      <button
        onClick={openPanel}
        className="px-4 py-2 bg-eth-gold text-[#0f2d1f] font-bold text-sm rounded border-0 cursor-pointer"
      >
        {t("product.add.button")}
      </button>

      {open && (
        <div
          aria-hidden="true"
          onClick={closePanel}
          className="fixed inset-0 z-[100] bg-black/40"
        />
      )}

      <aside
        role="dialog"
        aria-modal="true"
        aria-label={t("product.add.title")}
        className={`fixed top-0 right-0 bottom-0 z-[101] w-[460px] bg-white shadow-2xl flex flex-col transition-transform duration-[250ms] ease-out ${open ? "translate-x-0" : "translate-x-full"}`}
      >
        {/* Header */}
        <div className="px-5 py-4 bg-[#0f2d1f] border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-base font-bold text-white m-0">{t("product.add.title")}</h2>
          <button
            onClick={closePanel}
            aria-label={t("product.add.cancel")}
            className="bg-transparent border-0 text-white/70 text-xl cursor-pointer p-1 leading-none"
          >
            ×
          </button>
        </div>

        {/* SKU preview banner */}
        <div className="px-5 py-2.5 bg-green-50 border-b border-emerald-200 flex items-center gap-2.5">
          <span className="text-[11px] font-bold text-gray-500 uppercase tracking-wide shrink-0">
            {t("product.add.field.sku")}
          </span>
          {skuEditing ? (
            <input
              ref={skuInputRef}
              value={skuOverride}
              onChange={(e) => setSkuOvr(e.target.value.toUpperCase())}
              className="font-mono text-[13px] font-extrabold flex-1 tracking-widest text-emerald-600 border border-emerald-300 rounded px-1.5 py-0.5 outline-none bg-white"
              placeholder="BRD-001"
              onBlur={() => { if (!skuOverride.trim()) { setSkuEditing(false); } }}
            />
          ) : (
            <span
              className={`font-mono text-[15px] font-extrabold flex-1 tracking-widest ${displaySku ? "text-emerald-600" : "text-gray-400"}`}
            >
              {skuLoading
                ? t("product.add.loading_sku")
                : displaySku || (typeCode.trim().length >= 2 ? "…" : t("product.add.field.sku_placeholder"))}
            </span>
          )}
          <button
            type="button"
            onClick={startSkuEdit}
            title="Edit SKU"
            className="px-2 py-1 border border-emerald-200 rounded bg-white text-[11px] text-emerald-600 font-semibold shrink-0 cursor-pointer"
          >
            ✎
          </button>
          <button
            type="button"
            onClick={handleCopy}
            disabled={!displaySku}
            className={`px-2.5 py-1 border border-emerald-200 rounded bg-white text-xs text-emerald-600 font-semibold shrink-0 ${displaySku ? "cursor-pointer" : "cursor-not-allowed opacity-50"}`}
          >
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

          {/* ── Product Name ─────────────────────────────────────── */}
          <div>
            <FieldLabel text={t("product.add.field.name")} required />
            <input
              value={name}
              onChange={(e) => { setName(e.target.value); setNameErr(""); }}
              placeholder={t("product.add.field.name_placeholder")}
              maxLength={255}
              aria-required="true"
              className={nameErr ? fieldErr : fieldOk}
            />
            <FieldErr msg={nameErr} />
          </div>

          {/* ── Short Name ───────────────────────────────────────── */}
          <div>
            <FieldLabel
              text={t("product.add.field.short_name") || "Short Name"}
              hint={`(${t("receive_panel.optional")})`}
            />
            <input
              value={shortName}
              onChange={(e) => setShortName(e.target.value)}
              placeholder={t("product.add.field.short_name_hint") || "Used on labels and compact views"}
              maxLength={50}
              className={fieldOk}
            />
          </div>

          {/* ── Category ─────────────────────────────────────────── */}
          <div>
            <FieldLabel text={t("inventory.category")} />
            <SelectOrCreate
              options={categoryOptions}
              value={category}
              onChange={(v) => { setCategory(v); setCatErr(""); }}
              placeholder={t("receive_panel.select_type")}
              inputPlaceholder="e.g. Beverages, Cement, Packaging"
              hasError={!!categoryErr}
              createLabel={`+ ${t("add_product.new_category")}`}
              backLabel={`← ${t("add_product.back")}`}
            />
            {categoryErr && <p role="alert" className="text-xs text-red-600 mt-1">{categoryErr}</p>}
          </div>

          {/* ── Type Code ────────────────────────────────────────── */}
          <div>
            <FieldLabel
              text={t("product.add.field.type_code")}
              hint={t("product.add.field.type_code_hint")}
              required
            />
            <TypeCodeSelect
              options={typeCodeOptions}
              value={typeCode}
              onChange={(v) => { setTypeCode(v); setTcErr(""); setSkuEditing(false); setSkuOvr(""); }}
              hasError={!!typeCodeErr}
            />
            <FieldErr msg={typeCodeErr} />
            {typeCode.trim().length >= 2 && displaySku && !skuEditing && (
              <p className="text-[11px] text-emerald-700 mt-1 font-semibold">
                {t("product.add.sku_preview_label") || "SKU will be"}: {displaySku}
              </p>
            )}
          </div>

          {/* ── Brand ────────────────────────────────────────────── */}
          <div>
            <FieldLabel
              text={t("product.add.field.brand") || "Brand"}
              hint={`(${t("receive_panel.optional")})`}
            />
            <SelectOrCreate
              options={brandOptions}
              value={brand}
              onChange={setBrand}
              placeholder="Select brand"
              inputPlaceholder="e.g. Horizon, LocalBrand"
              createLabel={`+ ${t("add_product.new_category") || "Create new"}`}
              backLabel={`← ${t("add_product.back") || "Back"}`}
            />
          </div>

          {/* ── Description ──────────────────────────────────────── */}
          <div>
            <FieldLabel
              text={t("product.add.field.description") || "Description"}
              hint={`(${t("receive_panel.optional")})`}
            />
            <textarea
              value={description}
              onChange={(e) => setDesc(e.target.value)}
              placeholder={t("product.add.field.description_placeholder") || "Product description…"}
              rows={2}
              className={`${fieldOk} resize-y`}
            />
          </div>

          {/* ── UOM ──────────────────────────────────────────────── */}
          <div>
            <FieldLabel
              text={t("product.add.field.unit")}
              hint={`(${t("receive_panel.optional")})`}
            />
            <SelectOrCreate
              options={uomOptions}
              value={unit}
              onChange={setUnit}
              placeholder="Select unit"
              inputPlaceholder="e.g. KG, Box, Bag, Litre"
              createLabel={`+ ${t("add_product.new_category") || "Create new"}`}
              backLabel={`← ${t("add_product.back") || "Back"}`}
            />
          </div>

          {/* ── Packaging Type ───────────────────────────────────── */}
          <div>
            <FieldLabel
              text={t("product.add.field.packaging_type") || "Packaging Type"}
              hint={`(${t("receive_panel.optional")})`}
            />
            <SelectOrCreate
              options={pkgTypeNames}
              value={packagingType}
              onChange={(v) => { setPkgType(v); if (!v) setUpp("1"); }}
              placeholder="Select packaging type"
              inputPlaceholder="e.g. Carton, Sack, Drum"
              createLabel={`+ ${t("add_product.new_category") || "Create new"}`}
              backLabel={`← ${t("add_product.back") || "Back"}`}
            />
            {packagingType.trim() && !selectedPkg && (
              <div className="mt-2 flex items-center gap-2">
                <label className="text-[11px] text-gray-500 whitespace-nowrap">
                  {t("product.add.field.units_per_package") || "Units per package"}:
                </label>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={unitsPerPkg}
                  onChange={(e) => setUpp(e.target.value)}
                  className="w-20 px-2 py-1 text-sm border border-gray-300 rounded outline-none"
                />
              </div>
            )}
            {packagingPreview && (
              <p className="text-[11px] text-gray-500 mt-1 italic">{packagingPreview}</p>
            )}
          </div>

          {/* ── Reorder Point ────────────────────────────────────── */}
          <div>
            <FieldLabel
              text={unit.trim() ? `${t("table.reorder_point")} (${unit.trim()})` : t("table.reorder_point")}
              hint={`(${t("receive_panel.optional")})`}
            />
            <input
              type="number"
              min="0"
              step="1"
              value={reorderPoint}
              onChange={(e) => setReorder(e.target.value)}
              placeholder="0"
              className={fieldOk}
            />
          </div>

          {/* ── Minimum Approval Level ───────────────────────────── */}
          <div className="border border-gray-200 rounded-md overflow-hidden">
            <div className="px-3.5 py-2.5 bg-gray-50 border-b border-gray-200">
              <span className="text-xs font-bold uppercase tracking-wide text-gray-600">
                {t("approval.min_level")}
              </span>
              <p className="text-[11px] text-gray-400 mt-0.5">
                Set a floor approval level per transaction type regardless of quantity thresholds.
              </p>
            </div>
            <div className="px-3.5 py-3 space-y-3">
              <table className="w-full text-xs border-collapse">
                <thead>
                  <tr className="text-gray-500">
                    <th className="text-left py-1 pr-2 font-semibold w-[48%]">Transaction Type</th>
                    <th className="text-left py-1 font-semibold">Minimum Approver</th>
                  </tr>
                </thead>
                <tbody>
                  {MIN_TX_TYPES.map((tx, i) => (
                    <tr key={tx.key} className="border-t border-gray-100">
                      <td className="py-1.5 pr-2 text-gray-700 font-medium">{tx.label}</td>
                      <td className="py-1.5">
                        <select
                          value={minimumRows[i]?.min_authority_level ?? ""}
                          onChange={(e) =>
                            setMinimumRows((rows) =>
                              rows.map((r, idx) =>
                                idx === i ? { ...r, min_authority_level: e.target.value } : r
                              )
                            )
                          }
                          className="w-full px-2 py-1 text-xs border border-gray-300 rounded bg-white outline-none cursor-pointer"
                        >
                          <option value="">{t("approval.use_thresholds")}</option>
                          {hierarchyLevels.map((lv) => (
                            <option
                              key={lv.default_role_code}
                              value={String(ROLE_AUTH_MAP[lv.default_role_code] ?? 4)}
                            >
                              {lv.level_name} ({lv.role_display_label})
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {tenantDefaultRules.length > 0 && (
                <div className="pt-2 border-t border-gray-100">
                  <p className="text-[10px] text-gray-400 font-semibold uppercase tracking-wide mb-1">
                    {t("approval.tenant_defaults")}
                  </p>
                  <div className="text-[10px] text-gray-400 space-y-0.5">
                    {(["PULL", "PUSH", "ADJUSTMENT"] as const).map((tx) => {
                      const rules = tenantDefaultRules.filter((r) => r.transaction_type === tx);
                      if (!rules.length) return null;
                      const summary = rules
                        .map((r) =>
                          r.max_quantity != null
                            ? `${r.approver_role} <${r.max_quantity}`
                            : `${r.approver_role}+`
                        )
                        .join(" | ");
                      return (
                        <p key={tx}>
                          <span className="font-medium text-gray-500">{tx}:</span> {summary}
                        </p>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-3.5 border-t border-gray-200 flex justify-end gap-2.5">
          <button
            type="button"
            onClick={closePanel}
            className="px-4 py-2 rounded border border-gray-300 bg-white text-sm font-semibold text-gray-700 cursor-pointer"
          >
            {t("product.add.cancel")}
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saveDisabled}
            className={`px-4 py-2 rounded border-0 text-sm font-bold flex items-center gap-2 ${saveDisabled ? "bg-gray-300 text-gray-400 cursor-not-allowed" : "bg-[#0f2d1f] text-eth-gold cursor-pointer"}`}
          >
            {submitting && (
              <span className="w-3.5 h-3.5 rounded-full border-2 border-eth-gold/30 border-t-eth-gold animate-spin inline-block" />
            )}
            {t("product.add.save")}
          </button>
        </div>
      </aside>

      {toast && <Toast message={toast} onDismiss={() => setToast(null)} />}
    </>
  );
}
