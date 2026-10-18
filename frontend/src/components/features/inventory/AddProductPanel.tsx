"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { getSession } from "@/lib/demo-auth";
import { useTenantPositions } from "@/hooks/useTenantPositions";
import { useWriteGuard, guardProps } from "@/hooks/useWriteGuard";
import { useFeatures } from "@/hooks/useFeatures";
import { usePermission } from "@/hooks/usePermission";
import { t } from "@/lib/i18n";
import { notify } from "@/lib/notify";
import { PanelError } from "@/components/ui/PanelError";

const LOT_SETTINGS_ERROR_CODES = new Set([
  "FEATURE_NOT_ENABLED", "EXPIRY_NEEDS_BATCH", "INVALID_DISPATCH_STRATEGY",
  "BATCH_TRACKING_IN_USE", "LOT_CONVERSION_MISMATCH",
]);

interface OpeningLotItem { warehouse_id: string; lot_id: string; lot_number: string; quantity: number | string; }
interface LotSettingsResponse {
  batch_tracking: boolean; expiry_tracking: boolean; dispatch_strategy: string | null;
  opening_lots: OpeningLotItem[];
}

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

interface ApiTransferType {
  id: string;
  underlying_type: "PULL" | "PUSH" | "SISTER";
  display_name: string;
  is_active: boolean;
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
          // i18n-ignore: example product-type codes
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

export interface EditProductData {
  sku: string;
  name: string;
  short_name?: string | null;
  description?: string | null;
  category?: string | null;
  type_code?: string | null;
  brand?: string | null;
  unit: string;
  packaging_type?: string | null;
  units_per_package?: number | null;
  reorder_point?: number | string | null;
  unit_price?: number | string | null;
  currency?: string | null;
  image_url?: string | null;
  batch_tracking?: boolean;
  expiry_tracking?: boolean;
  dispatch_strategy?: string | null;
}

interface AddProductPanelProps {
  apiBase: string;
  onClose?: () => void;
  categories?: string[];
  mode?: "create" | "edit";
  productId?: string;
  initialData?: EditProductData;
  /** Tenant-wide on-hand balance for this product — drives the batch-tracking
   * conversion confirm dialog (edit mode only; undefined/0 in create mode). */
  onHandBalance?: number;
}

export function AddProductPanel({
  apiBase, onClose, mode = "create", productId, initialData, onHandBalance,
}: AddProductPanelProps) {
  const { org = "admin" } = useParams<{ org: string }>();
  const token   = getToken();
  const session = getSession();
  const qc      = useQueryClient();
  const isEdit  = mode === "edit";
  // Use the tenant UUID from the session, not the `org` URL slug — the
  // backend route /tenants/{tenant_id}/positions/flat requires a UUID and
  // 422s on a slug, leaving `positions` permanently empty (matches the
  // working pattern in adjustments/page.tsx).
  const { positions } = useTenantPositions(session?.tenantId ?? "");
  // Create counts against the SKU cap; editing an existing product never does.
  const writeGuard = useWriteGuard();
  const gp = guardProps(writeGuard, isEdit ? undefined : "skus");
  // Image upload is its own write (POST /upload/product-image) but never
  // counts against the SKU cap — read-only gating only.
  const uploadGp = guardProps(writeGuard);
  const { lotTracking } = useFeatures();
  const canUpdateProducts = usePermission("product:update");
  const showLotSection = lotTracking && canUpdateProducts;

  // Tenant's custom transfer type display names (e.g. "Request Stock" for
  // PULL) — same query as NewTransferPanel.tsx and Org Setup Tabs 4/5.
  const isGateway = !!process.env.NEXT_PUBLIC_API_URL;
  const tenantId  = session?.tenantId ?? "";
  const { data: transferTypes = [] } = useQuery<ApiTransferType[]>({
    queryKey: ["transfer-types", tenantId],
    queryFn:  () => api.get<ApiTransferType[]>(`/api/v1/tenants/${tenantId}/transfer-types`),
    enabled:  isGateway && !!tenantId,
    staleTime: 60_000,
  });
  const getTransferTypeLabel = (type: "PULL" | "PUSH" | "SISTER") =>
    transferTypes.find((tt) => tt.underlying_type === type && tt.is_active)?.display_name
    ?? t(`product.tx_type_${type.toLowerCase()}`);

  // ── form state ─────────────────────────────────────────────────────────
  const [open, setOpen]             = useState(isEdit);
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
  const [unitPrice, setCostPrice]   = useState("");
  const [currency, setCurrency]     = useState("ETB");
  const [skuOverride, setSkuOvr]    = useState("");
  const [skuEditing, setSkuEditing] = useState(false);
  const [imageUrl, setImageUrl]     = useState<string | null>(null);
  const [imageUploading, setImageUploading] = useState(false);
  const [imageError, setImageError] = useState("");

  // ── lot tracking state ─────────────────────────────────────────────────
  const [batchTracking, setBatchTrackingState] = useState(false);
  const [expiryTracking, setExpiryTracking]    = useState(false);
  const [dispatchStrategy, setDispatchStrategy] = useState<"FIFO" | "LIFO" | "FEFO">("FIFO");
  const [lotConfirmOpen, setLotConfirmOpen]     = useState(false);
  const [openingLots, setOpeningLots]           = useState<OpeningLotItem[] | null>(null);

  const initialBatchTracking    = initialData?.batch_tracking ?? false;
  const initialExpiryTracking   = initialData?.expiry_tracking ?? false;
  const initialDispatchStrategy = initialBatchTracking ? (initialData?.dispatch_strategy ?? "FIFO") : null;

  // Turning batch tracking ON for an edited product that already carries
  // on-hand stock triggers the opening-lot-conversion confirm dialog instead
  // of flipping the toggle immediately.
  const setBatchTracking = (checked: boolean) => {
    if (checked && !batchTracking && isEdit && (onHandBalance ?? 0) > 0) {
      setLotConfirmOpen(true);
      return;
    }
    setBatchTrackingState(checked);
    if (!checked) { setExpiryTracking(false); setDispatchStrategy("FIFO"); }
  };
  const confirmBatchTrackingOn = () => { setBatchTrackingState(true); setLotConfirmOpen(false); };
  const cancelBatchTrackingOn  = () => setLotConfirmOpen(false);

  // ── approval minimums state ────────────────────────────────────────────
  const MIN_TX_TYPES = [
    { key: "PULL",       label: getTransferTypeLabel("PULL") },
    { key: "PUSH",       label: getTransferTypeLabel("PUSH") },
    { key: "SISTER",     label: getTransferTypeLabel("SISTER") },
    { key: "ADJUSTMENT", label: t("product.tx_type_adjustment") },
    { key: "RECEIVE",    label: t("product.tx_type_receive") },
    { key: "ISSUE",      label: t("product.tx_type_issue") },
  ] as const;
  type ThresholdType = "ALWAYS" | "QUANTITY" | "VALUE";
  type MinimumRow = {
    transaction_type:     string;
    override_enabled:     boolean;
    threshold_type:       ThresholdType;
    qty_threshold:        string;
    value_threshold:      string;
    approver_position_id: string;
    note:                 string;
  };
  const emptyMinimumRows = (): MinimumRow[] =>
    MIN_TX_TYPES.map((tx) => ({
      transaction_type:     tx.key,
      override_enabled:     false,
      threshold_type:       "ALWAYS",
      qty_threshold:        "",
      value_threshold:      "",
      approver_position_id: "",
      note:                 "",
    }));
  const [minimumRows, setMinimumRows] = useState<MinimumRow[]>(emptyMinimumRows());
  const updateMinimumRow = (i: number, patch: Partial<MinimumRow>) =>
    setMinimumRows((rows) => rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));

  // ── pre-populate from initialData in edit mode ─────────────────────────
  useEffect(() => {
    if (!isEdit || !initialData) return;
    setName(initialData.name ?? "");
    setShortName(initialData.short_name ?? "");
    setDesc(initialData.description ?? "");
    setCategory(initialData.category ?? "");
    setTypeCode(initialData.type_code ?? "");
    setBrand(initialData.brand ?? "");
    setUnit(initialData.unit ?? "");
    setPkgType(initialData.packaging_type ?? "");
    setUpp(initialData.units_per_package ? String(initialData.units_per_package) : "1");
    setReorder(initialData.reorder_point != null ? String(initialData.reorder_point) : "");
    setCostPrice(initialData.unit_price != null ? String(initialData.unit_price) : "");
    setCurrency(initialData.currency ?? "ETB");
    setSkuOvr(initialData.sku ?? "");
    setImageUrl(initialData.image_url ?? null);
    setBatchTrackingState(initialData.batch_tracking ?? false);
    setExpiryTracking(initialData.expiry_tracking ?? false);
    setDispatchStrategy((initialData.dispatch_strategy as "FIFO" | "LIFO" | "FEFO" | null) ?? "FIFO");
    setOpen(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── error state ────────────────────────────────────────────────────────
  const [nameErr, setNameErr]       = useState("");
  const [typeCodeErr, setTcErr]     = useState("");
  const [categoryErr, setCatErr]    = useState("");
  const [submitting, setSub]        = useState(false);
  const [panelError, setPanelError] = useState("");
  const [copied, setCopied]         = useState(false);

  const skuInputRef = useRef<HTMLInputElement>(null);

  // ── API lookups ────────────────────────────────────────────────────────
  const { data: categoriesData } = useQuery<{ id: string; name: string }[]>({
    queryKey:  ["product-categories", org],   // org-scoped so different tenants don't share cache
    queryFn:   async () => {
      // Use relative path so api.ts prepends BASE_URL correctly.
      // Falls back to apiBase for backward compat with non-gateway deployments.
      const path = apiBase.startsWith("/") ? `${apiBase}/categories/` : "/api/v1/products/categories/";
      const r = await api.get<unknown>(path, token ?? undefined);
      return ((r as { data?: unknown }).data ?? r) as { id: string; name: string }[];
    },
    enabled:   open,
    staleTime: 60_000,
  });

  const { data: brandsData } = useQuery<{ id: string; name: string }[]>({
    queryKey:  ["product-brands", org],
    queryFn:   async () => {
      const r = await api.get<unknown>(`${apiBase}/brands/`, token ?? undefined);
      return ((r as { data?: unknown }).data ?? r) as { id: string; name: string }[];
    },
    enabled:   open,
    staleTime: 30_000,
  });

  const { data: typeCodesData } = useQuery<TypeCodeOption[]>({
    queryKey:  ["product-type-codes", org],
    queryFn:   async () => {
      const r = await api.get<unknown>(`${apiBase}/type-codes/`, token ?? undefined);
      return ((r as { data?: unknown }).data ?? r) as TypeCodeOption[];
    },
    enabled:   open,
    staleTime: 30_000,
  });

  const { data: uomsData } = useQuery<{ id: string; name: string }[]>({
    queryKey:  ["product-uoms", org],
    queryFn:   async () => {
      const r = await api.get<unknown>(`${apiBase}/uoms/`, token ?? undefined);
      return ((r as { data?: unknown }).data ?? r) as { id: string; name: string }[];
    },
    enabled:   open,
    staleTime: 30_000,
  });

  const { data: packagingTypesData } = useQuery<PackagingTypeOption[]>({
    queryKey:  ["product-packaging-types", org],
    queryFn:   async () => {
      const r = await api.get<unknown>(`${apiBase}/packaging-types/`, token ?? undefined);
      return ((r as { data?: unknown }).data ?? r) as PackagingTypeOption[];
    },
    enabled:   open,
    staleTime: 30_000,
  });

  // ── existing per-product approval-minimum overrides (edit mode only) ────
  type ApprovalMinimumEntry = {
    transaction_type:     string;
    override_enabled:     boolean;
    threshold_type:       ThresholdType | null;
    qty_threshold:        number | string | null;
    value_threshold:      number | string | null;
    approver_position_id: string | null;
    note:                 string | null;
  };
  const { data: approvalMinimumsData } = useQuery<{ minimums: ApprovalMinimumEntry[] }>({
    queryKey:  ["product-approval-minimums", productId],
    queryFn:   async () => {
      const r = await api.get<unknown>(`${apiBase}/${productId}/approval-minimums`, token ?? undefined);
      return ((r as { data?: unknown }).data ?? r) as { minimums: ApprovalMinimumEntry[] };
    },
    enabled:   isEdit && !!productId && open,
    staleTime: 0,
  });

  // Pre-populate the override rows from the server response. Transaction
  // types with no existing override row stay at the emptyMinimumRows()
  // default (override_enabled: false).
  useEffect(() => {
    if (!isEdit || !approvalMinimumsData) return;
    setMinimumRows((rows) =>
      rows.map((row) => {
        const match = approvalMinimumsData.minimums.find((m) => m.transaction_type === row.transaction_type);
        if (!match) return row;
        return {
          ...row,
          override_enabled:     match.override_enabled,
          threshold_type:       match.threshold_type ?? "ALWAYS",
          qty_threshold:        match.qty_threshold != null ? String(match.qty_threshold) : "",
          value_threshold:      match.value_threshold != null ? String(match.value_threshold) : "",
          approver_position_id: match.approver_position_id ?? "",
          note:                 match.note ?? "",
        };
      }),
    );
  }, [isEdit, approvalMinimumsData]);

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
    enabled:   open && !isEdit && typeCode.trim().length >= 2,
    staleTime: 0,
    refetchOnWindowFocus: false,
  });

  const generatedSku = skuPreviewData?.sku ?? "";
  // In edit mode the SKU is immutable — always show the existing SKU.
  const displaySku   = isEdit ? (initialData?.sku ?? "") : (skuEditing ? skuOverride : (generatedSku || ""));
  const skuOk        = isEdit ? true : displaySku.trim().length > 0;

  // When generated SKU changes, sync into override field if not manually editing.
  useEffect(() => {
    if (!isEdit && !skuEditing && generatedSku) setSkuOvr(generatedSku);
  }, [generatedSku, skuEditing, isEdit]);

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
  const typeCodeOk  = /^[A-Za-z0-9]{2,10}$/.test(typeCode.trim());
  const categoryOk  = category.trim().length > 0;
  const saveDisabled = !name.trim() || !categoryOk || !typeCodeOk || !skuOk || submitting || skuLoading;

  const resetForm = () => {
    setName(""); setShortName(""); setDesc(""); setCategory("");
    setTypeCode(""); setBrand(""); setUnit(""); setPkgType("");
    setUpp("1"); setReorder(""); setSkuOvr(""); setSkuEditing(false);
    setCostPrice(""); setCurrency("ETB");
    setNameErr(""); setTcErr(""); setCatErr(""); setPanelError("");
    setMinimumRows(emptyMinimumRows());
    setBatchTrackingState(false); setExpiryTracking(false); setDispatchStrategy("FIFO");
    setLotConfirmOpen(false); setOpeningLots(null);
  };

  const openPanel  = () => { resetForm(); setOpen(true); };
  const closePanel = () => {
    if (!isEdit && (name.trim() || typeCode.trim()) && !window.confirm(t("product.add.confirm.discard"))) return;
    resetForm(); setOpen(false); onClose?.();
  };

  const handleSave = async () => {
    if (submitting) return;
    let valid = true;
    if (!name.trim())    { setNameErr("name_required"); valid = false; }
    if (!categoryOk)     { setCatErr("Category is required."); valid = false; }
    if (!typeCodeOk)     { setTcErr("type_code_min"); valid = false; }
    if (!valid) return;

    setSub(true); setPanelError("");
    try {
      const reorderQty = parseFloat(reorderPoint);
      const uppVal     = parseInt(unitsPerPkg, 10);

      let productRefId: string;
      let productSku: string;

      if (isEdit && productId) {
        const updated = await api.patch<{ id: string; sku: string }>(
          `${apiBase}/${productId}`,
          {
            name:              name.trim(),
            short_name:        shortName.trim() || undefined,
            description:       description.trim() || undefined,
            category:          category.trim() || undefined,
            type_code:         typeCode.trim().toUpperCase() || undefined,
            brand:             brand.trim() || undefined,
            unit:              unit.trim() || undefined,
            packaging_type:    packagingType.trim() || undefined,
            units_per_package: packagingType.trim() && !isNaN(uppVal) && uppVal > 0 ? uppVal : undefined,
            reorder_point:     !isNaN(reorderQty) && reorderQty >= 0 ? reorderQty : undefined,
            unit_price:        parseFloat(unitPrice) >= 0 && unitPrice !== "" ? parseFloat(unitPrice) : undefined,
            currency:          currency.trim() || undefined,
            image_url:         imageUrl ?? undefined,
          },
          token ?? undefined,
        );
        productRefId = updated.id;
        productSku   = updated.sku;
      } else {
        const created = await api.post<{ id: string; sku: string }>(
          `${apiBase}/`,
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
            unit_price:        parseFloat(unitPrice) >= 0 && unitPrice !== "" ? parseFloat(unitPrice) : undefined,
            currency:          currency.trim() || undefined,
            sku_override:      skuEditing && skuOverride.trim() ? skuOverride.trim() : undefined,
          },
          token ?? undefined,
        );
        productRefId = created.id;
        productSku   = created.sku;
      }

      // Lot tracking settings — a separate endpoint from the product PATCH/POST.
      const effectiveStrategy = batchTracking ? dispatchStrategy : null;
      const lotSettingsChanged =
        batchTracking !== initialBatchTracking ||
        expiryTracking !== initialExpiryTracking ||
        effectiveStrategy !== initialDispatchStrategy;

      let newOpeningLots: OpeningLotItem[] | null = null;
      // Create mode only: steps that ran after the product POST succeeded and then failed.
      const failedSteps: { step: string; detail: string }[] = [];

      if (isEdit && lotSettingsChanged) {
        // Let a failure here (e.g. 409 BATCH_TRACKING_IN_USE) fall through to the
        // outer catch — the product PATCH already succeeded, so the form stays
        // open with the translated error, same as any other save failure.
        const lotResult = await api.put<LotSettingsResponse>(
          `/api/v1/inventory/products/${productRefId}/lot-settings`,
          { batch_tracking: batchTracking, expiry_tracking: expiryTracking, dispatch_strategy: effectiveStrategy },
          token ?? undefined,
        );
        if (lotResult.opening_lots.length > 0) newOpeningLots = lotResult.opening_lots;
      } else if (!isEdit && batchTracking) {
        // Create mode: a brand-new product has no stock to convert, so failure
        // here never rolls back the product that was just created.
        try {
          await api.put<LotSettingsResponse>(
            `/api/v1/inventory/products/${productRefId}/lot-settings`,
            { batch_tracking: true, expiry_tracking: expiryTracking, dispatch_strategy: effectiveStrategy },
            token ?? undefined,
          );
        } catch (lotErr) {
          const le = lotErr as Error & { code?: string };
          failedSteps.push({
            step:   t("product.add.step_lot_settings"),
            detail: le.code && LOT_SETTINGS_ERROR_CODES.has(le.code) ? t(`errors.${le.code}`) : t("errors.INTERNAL_ERROR"),
          });
        }
      }

      // Save product-level approval minimums / overrides. Only TA can manage
      // them (product:manage_approval_minimums; the section renders for TA only),
      // so any other role never sends this PUT — it would 403 after the product
      // was already created. For TA: edit mode always sends (so clearing a
      // previously configured override works); create mode sends only when at
      // least one override is active, since a new product has nothing to clear.
      // All 6 transaction types are sent (override_enabled=false for unconfigured
      // rows) so entries is never empty — this satisfies the backend's
      // EMPTY_ENTRIES validation. An override is only persisted if a position
      // has been chosen — the backend's check_product_override() requires
      // approver_position_id IS NOT NULL, so a checked-but-unconfigured
      // override is sent as override_enabled=false here.
      const hasActiveOverride = minimumRows.some((r) => r.override_enabled && r.approver_position_id !== "");
      const sendMinimums = session?.role === "TA" && (isEdit || hasActiveOverride);
      const putMinimums = () => api.put<unknown>(
        `${apiBase}/${productRefId}/approval-minimums`,
        {
          entries: minimumRows.map((r) => {
            const overrideActive = r.override_enabled && r.approver_position_id !== "";
            return {
              transaction_type:     r.transaction_type,
              override_enabled:    overrideActive,
              threshold_type:      r.threshold_type,
              qty_threshold:       overrideActive && r.threshold_type === "QUANTITY" && r.qty_threshold !== ""
                                     ? Number(r.qty_threshold) : undefined,
              value_threshold:     overrideActive && r.threshold_type === "VALUE" && r.value_threshold !== ""
                                     ? Number(r.value_threshold) : undefined,
              approver_position_id: overrideActive ? r.approver_position_id : undefined,
              note:                 overrideActive && r.note.trim() ? r.note.trim() : undefined,
            };
          }),
        },
        token ?? undefined,
      );
      if (sendMinimums) {
        if (isEdit) {
          await putMinimums();
        } else {
          // Create mode: the product already exists, so a failure here must not
          // leave the panel open on a generic error (re-saving would duplicate it).
          try {
            await putMinimums();
          } catch (minErr) {
            const me = minErr as Error & { code?: string };
            const coded = me.code ? t(`errors.${me.code}`) : "";
            failedSteps.push({
              step:   t("product.add.step_approval_minimums"),
              detail: coded && coded !== `errors.${me.code}` ? coded : t("errors.INTERNAL_ERROR"),
            });
          }
        }
      }

      void qc.invalidateQueries({ queryKey: ["products"] });
      void qc.invalidateQueries({ queryKey: ["product-categories"] });
      void qc.invalidateQueries({ queryKey: ["product-brands"] });
      void qc.invalidateQueries({ queryKey: ["product-type-codes"] });
      void qc.invalidateQueries({ queryKey: ["product-uoms"] });
      void qc.invalidateQueries({ queryKey: ["product-packaging-types"] });
      void qc.invalidateQueries({ queryKey: ["next-sku"] });

      if (failedSteps.length > 0) {
        // Product exists but a follow-up step failed: close and warn, naming the
        // SKU, so the user does not re-save and duplicate the product.
        resetForm(); setOpen(false); onClose?.();
        notify({
          kind: "warning",
          message: t("product.add.partial_failure")
            .replace("{{sku}}", productSku)
            .replace("{{step}}", failedSteps.map((f) => f.step).join(" + "))
            .replace("{{detail}}", failedSteps.map((f) => f.detail).join("; ")),
        });
      } else if (newOpeningLots) {
        // A batch-tracking conversion just ran — list the opening lots and
        // keep the panel open until the user closes it themselves.
        setOpeningLots(newOpeningLots);
      } else {
        notify({
          kind: "success",
          message: isEdit
            ? `${t("product.edit_success")} — ${productSku}`
            : t("product.add.success").replace("{{sku}}", productSku),
        });
        resetForm(); setOpen(false); onClose?.();
      }
    } catch (err) {
      const e = err as Error & { status?: number; code?: string };
      if (e.code && LOT_SETTINGS_ERROR_CODES.has(e.code)) setPanelError(t(`errors.${e.code}`));
      else if (e.status === 409 && e.code === "duplicate_sku") setPanelError(t("product.add.error.duplicate_sku"));
      else if (e.status === 409) setNameErr("duplicate_name");
      else if (e.status === 402 && e.code === "PLAN_LIMIT_REACHED") setPanelError(t("product.add.error.sku_cap_reached"));
      else if (e.status === 429) setPanelError(t("common.rate_limited"));
      else if (e.status === 403 && e.code === "PRODUCT_CONTROLLED") setPanelError(t("product.controlled_edit_denied"));
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
  const panelTitle = isEdit ? t("product.edit_title") : t("product.add.title");

  return (
    <>
      {!isEdit && (
        <button
          onClick={openPanel}
          {...gp}
          className="px-4 py-2 bg-eth-gold text-[#0f2d1f] font-bold text-sm rounded border-0 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {t("product.add.button")}
        </button>
      )}

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
        aria-label={panelTitle}
        className={`fixed top-0 right-0 bottom-0 z-[101] w-[460px] bg-white shadow-2xl flex flex-col transition-transform duration-[250ms] ease-out ${open ? "translate-x-0" : "translate-x-full"}`}
      >
        {/* Header */}
        <div className="flex-shrink-0 px-5 py-4 bg-[#0f2d1f] border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-base font-bold text-white m-0">{panelTitle}</h2>
          <button
            onClick={closePanel}
            aria-label={t("product.add.cancel")}
            className="bg-transparent border-0 text-white/70 text-xl cursor-pointer p-1 leading-none"
          >
            ×
          </button>
        </div>

        {/* SKU preview banner */}
        <div className="flex-shrink-0 px-5 py-2.5 bg-green-50 border-b border-emerald-200 flex items-center gap-2.5">
          <span className="text-[11px] font-bold text-gray-500 uppercase tracking-wide shrink-0">
            {t("product.add.field.sku")}
          </span>
          {isEdit ? (
            <span className="font-mono text-[15px] font-extrabold flex-1 tracking-widest text-emerald-600">
              {displaySku}
            </span>
          ) : skuEditing ? (
            <input
              ref={skuInputRef}
              value={skuOverride}
              onChange={(e) => setSkuOvr(e.target.value.toUpperCase())}
              className="font-mono text-[13px] font-extrabold flex-1 tracking-widest text-emerald-600 border border-emerald-300 rounded px-1.5 py-0.5 outline-none bg-white"
              // i18n-ignore: example SKU code
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
          {!isEdit && (
            <button
              type="button"
              onClick={startSkuEdit}
              title={t("product.add.edit_sku_tooltip")}
              className="px-2 py-1 border border-emerald-200 rounded bg-white text-[11px] text-emerald-600 font-semibold shrink-0 cursor-pointer"
            >
              ✎
            </button>
          )}
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
        <div className="flex-1 min-h-0 overflow-y-auto p-5 flex flex-col gap-4">
          {gp.disabled && gp.title && (
            <div role="alert" className="bg-amber-50 border border-amber-200 rounded px-3.5 py-2.5 text-sm text-amber-800">
              {gp.title}
            </div>
          )}
          <PanelError message={panelError} />

          {/* ── Product Image ────────────────────────────────────── */}
          <div>
            <FieldLabel text={t("product.upload_image") || "Product Image"} />
            <div className="flex items-center gap-3">
              {imageUrl ? (
                <img src={imageUrl} alt="" className="w-14 h-14 rounded object-cover border border-gray-200" />
              ) : (
                <div className="w-14 h-14 rounded border-2 border-dashed border-gray-300 flex items-center justify-center text-gray-400 text-xl">
                  📷
                </div>
              )}
              <div className="flex flex-col gap-1">
                <label className="cursor-pointer" title={uploadGp.title}>
                  <span className={`px-3 py-1.5 text-xs font-semibold bg-gray-100 border border-gray-300 rounded cursor-pointer hover:bg-gray-200 ${uploadGp.disabled ? "opacity-50 cursor-not-allowed" : ""}`}>
                    {imageUploading ? (t("product.image_uploading") || "Uploading...") : (t("product.upload_image") || "Upload Image")}
                  </span>
                  <input
                    type="file"
                    accept="image/jpeg,image/png,image/webp"
                    className="hidden"
                    disabled={imageUploading || uploadGp.disabled}
                    onChange={async (e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      if (file.size > 2 * 1024 * 1024) {
                        setImageError(t("product.image_too_large") || "Image must be under 2MB");
                        return;
                      }
                      if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
                        setImageError(t("product.image_invalid_type") || "Only JPG, PNG, WebP accepted");
                        return;
                      }
                      setImageError("");
                      setImageUploading(true);
                      try {
                        const fd = new FormData();
                        fd.append("file", file);
                        const uploadJwt = getSession()?.jwtToken ?? token;
                        const res = await fetch(
                          `${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/v1/upload/product-image`,
                          { method: "POST", headers: uploadJwt ? { Authorization: `Bearer ${uploadJwt}` } : {}, body: fd },
                        );
                        const json = await res.json() as { success?: boolean; data?: { url: string } };
                        if (json.success && json.data?.url) {
                          setImageUrl(json.data.url);
                        } else {
                          setImageError("Upload failed");
                        }
                      } catch {
                        setImageError("Upload failed");
                      } finally {
                        setImageUploading(false);
                      }
                    }}
                  />
                </label>
                {imageUrl && (
                  <button
                    type="button"
                    onClick={() => setImageUrl(null)}
                    className="text-xs text-red-500 bg-transparent border-0 cursor-pointer text-left p-0"
                  >
                    {t("common.remove") || "Remove"}
                  </button>
                )}
              </div>
            </div>
            {imageError && <p className="text-xs text-red-600 mt-1">{imageError}</p>}
          </div>

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
              placeholder={t("product.add.field.brand_placeholder")}
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
              placeholder={t("product.add.field.unit_placeholder")}
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
              placeholder={t("product.add.field.packaging_type_placeholder")}
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

          {/* ── Cost Price ───────────────────────────────────────── */}
          <div>
            <FieldLabel
              text={t("product.cost_price")}
              hint={`(${t("receive_panel.optional")})`}
            />
            <div className="flex gap-2">
              <input
                type="number"
                min="0"
                step="0.01"
                value={unitPrice}
                onChange={(e) => setCostPrice(e.target.value)}
                placeholder="0.00"
                className={`flex-1 ${fieldOk}`}
              />
              <select
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
                className="w-20 px-2 py-2 rounded text-sm border border-gray-300 bg-white outline-none cursor-pointer"
              >
                {/* i18n-ignore: currency code */}
                <option value="ETB">ETB</option>
                {/* i18n-ignore: currency code */}
                <option value="USD">USD</option>
                {/* i18n-ignore: currency code */}
                <option value="EUR">EUR</option>
              </select>
            </div>
            <p className="text-[11px] text-gray-400 mt-1">{t("product.cost_price_hint")}</p>
          </div>

          {/* ── Minimum Approval Level (TA only) ─────────────────── */}
          {session?.role === "TA" && (
            <div className="border border-gray-200 rounded-md overflow-hidden flex-shrink-0">
              <div className="px-3.5 py-2.5 bg-gray-50 border-b border-gray-200">
                <span className="text-xs font-bold uppercase tracking-wide text-gray-600">
                  {t("product.approval_override_title")}
                </span>
                <p className="text-[11px] text-gray-400 mt-0.5">
                  {t("product.approval_override_desc")}
                </p>
                <p className="text-[10px] text-gray-400 mt-1 italic">{t("product.ta_only_notice")}</p>
              </div>

              <div className="px-3.5 py-3 space-y-2.5">
                {MIN_TX_TYPES.map((tx, i) => {
                  const row = minimumRows[i];
                  if (!row) return null;
                  return (
                    <div key={tx.key} className="border border-gray-100 rounded p-2.5 space-y-2">
                      <label className="flex items-center gap-2 text-xs font-semibold text-gray-700 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={row.override_enabled}
                          onChange={(e) => updateMinimumRow(i, { override_enabled: e.target.checked })}
                        />
                        {tx.label} — {t("product.enable_override")}
                      </label>

                      {row.override_enabled && (
                        <div className="pl-5 space-y-2">
                          <div className="flex flex-col gap-1.5">
                            {(["ALWAYS", "QUANTITY", "VALUE"] as const).map((mode) => (
                              <label key={mode} className="flex items-center gap-2 text-[11px] text-gray-600">
                                <input
                                  type="radio"
                                  name={`override-trigger-${tx.key}`}
                                  checked={row.threshold_type === mode}
                                  onChange={() => updateMinimumRow(i, { threshold_type: mode })}
                                />
                                {mode === "ALWAYS" && t("product.trigger_always")}
                                {mode === "QUANTITY" && (
                                  <>
                                    {t("product.trigger_quantity")}
                                    <input
                                      type="number"
                                      min="0"
                                      step="1"
                                      value={row.qty_threshold}
                                      onFocus={() => updateMinimumRow(i, { threshold_type: "QUANTITY" })}
                                      onChange={(e) => updateMinimumRow(i, { threshold_type: "QUANTITY", qty_threshold: e.target.value })}
                                      className="w-20 px-1.5 py-0.5 border border-gray-300 rounded text-[11px] outline-none"
                                    />
                                    {unit.trim() || "units"}
                                  </>
                                )}
                                {mode === "VALUE" && (
                                  <>
                                    {t("product.trigger_value")}
                                    <input
                                      type="number"
                                      min="0"
                                      step="0.01"
                                      value={row.value_threshold}
                                      onFocus={() => updateMinimumRow(i, { threshold_type: "VALUE" })}
                                      onChange={(e) => updateMinimumRow(i, { threshold_type: "VALUE", value_threshold: e.target.value })}
                                      className="w-24 px-1.5 py-0.5 border border-gray-300 rounded text-[11px] outline-none"
                                    />
                                    {currency}
                                  </>
                                )}
                              </label>
                            ))}
                          </div>

                          <div>
                            <label className="block text-[11px] font-semibold text-gray-500 mb-0.5">
                              {t("product.requires_approval_from")}
                            </label>
                            <select
                              value={row.approver_position_id}
                              onChange={(e) => updateMinimumRow(i, { approver_position_id: e.target.value })}
                              className="w-full px-2 py-1 text-xs border border-gray-300 rounded bg-white outline-none cursor-pointer"
                            >
                              <option value="">— {t("receive_panel.select_type")} —</option>
                              {positions.map((p) => (
                                <option key={p.id} value={p.id}>
                                  {p.title} ({p.node_name})
                                </option>
                              ))}
                            </select>
                          </div>

                          <input
                            value={row.note}
                            onChange={(e) => updateMinimumRow(i, { note: e.target.value })}
                            placeholder={t("product.override_note_placeholder")}
                            maxLength={255}
                            className="w-full px-2 py-1 text-xs border border-gray-300 rounded outline-none"
                          />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ── Lot tracking (FEATURE_LOT_TRACKING + product:update) ──── */}
          {showLotSection && (
            <div className="border border-gray-200 rounded-md overflow-hidden flex-shrink-0">
              <div className="px-3.5 py-2.5 bg-gray-50 border-b border-gray-200">
                <span className="text-xs font-bold uppercase tracking-wide text-gray-600">
                  {t("product.lot_settings.title")}
                </span>
              </div>

              <div className="px-3.5 py-3 space-y-3">
                {openingLots ? (
                  <div className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded p-2.5 space-y-1">
                    <p className="font-semibold">{t("product.lot_settings.conversion_success")}</p>
                    <ul className="list-disc pl-4">
                      {openingLots.map((ol) => (
                        <li key={ol.lot_id}>
                          {ol.lot_number} — {String(ol.quantity)}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <>
                    <label className="flex items-center gap-2 text-xs font-semibold text-gray-700 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={batchTracking}
                        onChange={(e) => setBatchTracking(e.target.checked)}
                      />
                      {t("product.lot_settings.batch_tracking")}
                    </label>

                    <label
                      className={`flex items-center gap-2 text-xs font-semibold cursor-pointer ${
                        batchTracking ? "text-gray-700" : "text-gray-400"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={expiryTracking}
                        disabled={!batchTracking}
                        onChange={(e) => {
                          const checked = e.target.checked;
                          setExpiryTracking(checked);
                          setDispatchStrategy(checked ? "FEFO" : "FIFO");
                        }}
                      />
                      {t("product.lot_settings.expiry_tracking")}
                    </label>

                    {batchTracking && (
                      <div>
                        <FieldLabel text={t("product.lot_settings.dispatch_strategy")} />
                        <div className="flex gap-3">
                          {(["FEFO", "FIFO", "LIFO"] as const).map((strategy) => (
                            <label
                              key={strategy}
                              className={`flex items-center gap-1.5 text-xs ${
                                (strategy === "FEFO") !== expiryTracking ? "text-gray-400" : "text-gray-700"
                              }`}
                            >
                              <input
                                type="radio"
                                name="dispatch-strategy"
                                checked={dispatchStrategy === strategy}
                                disabled={expiryTracking ? strategy !== "FEFO" : strategy === "FEFO"}
                                onChange={() => setDispatchStrategy(strategy)}
                              />
                              {strategy}
                            </label>
                          ))}
                        </div>
                        {expiryTracking && (
                          <p className="text-[11px] text-gray-400 mt-1">{t("product.lot_settings.fefo_hint")}</p>
                        )}
                      </div>
                    )}

                  </>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex-shrink-0 px-5 py-3.5 border-t border-gray-200 flex justify-end gap-2.5">
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
            disabled={saveDisabled || gp.disabled}
            title={gp.title}
            className={`px-4 py-2 rounded border-0 text-sm font-bold flex items-center gap-2 ${saveDisabled || gp.disabled ? "bg-gray-300 text-gray-400 cursor-not-allowed" : "bg-[#0f2d1f] text-eth-gold cursor-pointer"}`}
          >
            {submitting && (
              <span className="w-3.5 h-3.5 rounded-full border-2 border-eth-gold/30 border-t-eth-gold animate-spin inline-block" />
            )}
            {submitting ? t("common.saving") : t("product.add.save")}
          </button>
        </div>
      </aside>

      {lotConfirmOpen && (
        <div className="fixed inset-0 z-[9998] bg-black/40 flex items-center justify-center">
          <div className="bg-white rounded-md shadow-xl p-5 max-w-sm space-y-3">
            <p className="text-sm text-gray-700">{t("product.lot_settings.confirm_conversion")}</p>
            <div className="flex justify-end gap-2.5">
              <button
                type="button"
                onClick={cancelBatchTrackingOn}
                className="px-3.5 py-1.5 rounded border border-gray-300 bg-white text-sm font-semibold text-gray-700 cursor-pointer"
              >
                {t("product.add.cancel")}
              </button>
              <button
                type="button"
                onClick={confirmBatchTrackingOn}
                className="px-3.5 py-1.5 rounded border-0 bg-[#0f2d1f] text-eth-gold text-sm font-bold cursor-pointer"
              >
                {t("product.lot_settings.confirm_conversion_ok")}
              </button>
            </div>
          </div>
        </div>
      )}

    </>
  );
}
