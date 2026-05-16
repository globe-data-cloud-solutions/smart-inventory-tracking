"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { t } from "@/lib/i18n";
import { useInventoryStore } from "@/lib/inventory-state";
import { getSession } from "@/lib/demo-auth";

// ── Helpers ───────────────────────────────────────────────────────────────────

function toOrgAbbr(slug: string): string {
  return slug.split("-").map((w) => (w[0] ?? "").toUpperCase()).join("").slice(0, 4);
}

type Unit     = "KG" | "PACK" | "QTL" | "MT";
type PackSize = 1 | 4 | 6 | 12;

const UNITS: Array<{ value: Unit; label: string }> = [
  { value: "KG",   label: "product.unit.KG" },
  { value: "PACK", label: "product.unit.PACK" },
  { value: "QTL",  label: "product.unit.QTL" },
  { value: "MT",   label: "product.unit.MT" },
];

const PACKS: Array<{ value: PackSize; label: string }> = [
  { value: 1,  label: "product.pack_size.1" },
  { value: 4,  label: "product.pack_size.4" },
  { value: 6,  label: "product.pack_size.6" },
  { value: 12, label: "product.pack_size.12" },
];

// ── Tiny UI primitives ────────────────────────────────────────────────────────

function FieldLabel({ text, hint }: { text: string; hint?: string }) {
  return (
    <label style={{ display: "block", fontSize: 12, fontWeight: 700,
      textTransform: "uppercase", letterSpacing: "0.05em", color: "#374151", marginBottom: 4 }}>
      {text}
      {hint && <span style={{ fontSize: 11, fontWeight: 400, textTransform: "none",
        letterSpacing: 0, color: "#9CA3AF", marginLeft: 6 }}>{hint}</span>}
    </label>
  );
}

function FieldErr({ msg }: { msg?: string }) {
  if (!msg) return null;
  const key      = `product.add.error.${msg}`;
  const resolved = t(key);
  return (
    <p role="alert" style={{ fontSize: 12, color: "#DC2626", marginTop: 4 }}>
      {resolved !== key ? resolved : msg}
    </p>
  );
}

function Toast({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  useEffect(() => { const id = setTimeout(onDismiss, 4000); return () => clearTimeout(id); }, [onDismiss]);
  return (
    <div role="status" aria-live="polite" style={{
      position: "fixed", bottom: 24, right: 24, zIndex: 9999,
      background: "#059669", color: "#fff", padding: "12px 20px",
      borderRadius: 6, fontSize: 14, fontWeight: 600, boxShadow: "0 4px 16px rgba(0,0,0,0.2)",
    }}>{message}</div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

interface AddProductPanelProps {
  apiBase: string;
  onClose?: () => void;
  /** Existing tenant categories for the dropdown — derived by the parent from mergedProducts. */
  categories?: string[];
}

export function AddProductPanel({ apiBase, onClose, categories = [] }: AddProductPanelProps) {
  const { org = "admin" } = useParams<{ org: string }>();
  const orgAbbr    = toOrgAbbr(org);
  const token      = getToken();
  const qc         = useQueryClient();
  const addReceive = useInventoryStore((s) => s.addReceive);
  const user       = getSession();

  // ── Panel open/close ──────────────────────────────────────────────────────
  const [open, setOpen] = useState(false);

  // ── Form fields ───────────────────────────────────────────────────────────
  const [name,             setName]             = useState("");
  const [category,         setCategory]         = useState("");
  const [isCustomCategory, setIsCustomCategory] = useState(false);
  const [typeCode,     setTypeCode]     = useState("");
  const [unit,         setUnit]         = useState<Unit>("KG");
  const [packSize,     setPackSize]     = useState<PackSize>(1);
  const [onHand,       setOnHand]       = useState("");
  const [reorderPoint, setReorderPoint] = useState("");

  // ── Field-level validation errors ─────────────────────────────────────────
  const [nameErr,     setNameErr]     = useState("");
  const [categoryErr, setCategoryErr] = useState("");
  const [typeCodeErr, setTypeCodeErr] = useState("");

  // ── Submission state ──────────────────────────────────────────────────────
  const [submitting,  setSubmitting]  = useState(false);
  const [panelError,  setPanelError]  = useState("");
  const [toast,       setToast]       = useState<string | null>(null);
  const [copied,      setCopied]      = useState(false);

  // ── SKU counter from server ───────────────────────────────────────────────
  const { data: counterData, isFetching: skuLoading } = useQuery({
    queryKey:  ["next-sku-counter", apiBase],
    queryFn:   () => api.get<{ counter: number }>(`${apiBase}/next-sku`, token ?? undefined),
    enabled:   open,
    staleTime: 0,
    refetchOnWindowFocus: false,
  });
  const counter = counterData?.counter;

  // ── SKU preview — updates live as fields change ───────────────────────────
  const typeDisplay = typeCode.trim().toUpperCase() || "???";
  const previewSku  = counter != null
    ? `${orgAbbr}-${typeDisplay}-${unit}${packSize}-${String(counter).padStart(4, "0")}`
    : "";

  // ── Derived ───────────────────────────────────────────────────────────────
  const parsedOnHand = parseFloat(onHand);
  const availableDisplay = (!isNaN(parsedOnHand) && parsedOnHand > 0)
    ? parsedOnHand.toLocaleString()
    : "—";
  const onHandProvided = !isNaN(parsedOnHand) && parsedOnHand > 0;

  // ── Save gate ─────────────────────────────────────────────────────────────
  const nameOk     = name.trim().length > 0;
  const categoryOk = category.trim().length > 0;
  const typeCodeOk = /^[A-Za-z]{2,5}$/.test(typeCode.trim());
  const saveDisabled = !nameOk || !categoryOk || !typeCodeOk || submitting || skuLoading;

  // ── Handlers ──────────────────────────────────────────────────────────────
  const resetForm = () => {
    setName(""); setCategory(""); setIsCustomCategory(false);
    setTypeCode(""); setUnit("KG"); setPackSize(1);
    setOnHand(""); setReorderPoint("");
    setNameErr(""); setCategoryErr(""); setTypeCodeErr(""); setPanelError("");
  };

  const openPanel = () => { resetForm(); setOpen(true); };

  const closePanel = () => {
    if ((name.trim() || typeCode.trim()) &&
        !window.confirm(t("product.add.confirm.discard"))) return;
    resetForm();
    setOpen(false);
    onClose?.();
  };

  const handleSave = async () => {
    let valid = true;
    if (!name.trim())     { setNameErr("name_required");     valid = false; }
    if (!category.trim()) { setCategoryErr("Category is required."); valid = false; }
    if (!typeCodeOk)      { setTypeCodeErr("type_code_min"); valid = false; }
    if (!valid) return;

    setSubmitting(true);
    setPanelError("");
    try {
      const onHandQty  = parsedOnHand > 0 ? parsedOnHand : 0;
      const reorderQty = parseFloat(reorderPoint);
      const whId       = user?.warehouseId ?? "";

      const data = await api.post<{ id: string; sku: string }>(apiBase, {
        name:          name.trim(),
        category:      category.trim(),
        type_code:     typeCode.trim().toUpperCase(),
        unit,
        pack_size:     packSize,
        org_slug:      org,
        on_hand:       onHandQty,
        reorder_point: !isNaN(reorderQty) && reorderQty > 0 ? reorderQty : 0,
        warehouse_id:  whId || undefined,
      }, token ?? undefined);

      // If on_hand was provided and we have a target warehouse, initialise the
      // Zustand balance immediately — equivalent to an implicit opening receipt.
      if (onHandQty > 0 && whId) {
        addReceive(data.id, whId, onHandQty);
      }

      setToast(t("product.add.success").replace("{{sku}}", data.sku));
      void qc.invalidateQueries({ queryKey: ["products"] });
      resetForm();
      setOpen(false);
      onClose?.();
    } catch (err) {
      const e = err as Error & { status?: number };
      if (e.status === 409)       setNameErr("duplicate_name");
      else if (e.status === 429)  setPanelError(t("product.add.error.sku_cap_reached"));
      else                        setPanelError(t("product.add.error.generic"));
    } finally {
      setSubmitting(false);
    }
  };

  const handleCopy = async () => {
    if (!previewSku || previewSku.includes("???")) return;
    await navigator.clipboard.writeText(previewSku);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <>
      {/* Trigger button */}
      <button onClick={openPanel} style={{
        padding: "8px 16px", background: "#FCDD09", color: "#0f2d1f",
        fontWeight: 700, fontSize: 13, borderRadius: 4, border: "none", cursor: "pointer",
      }}>
        {t("product.add.button")}
      </button>

      {/* Backdrop */}
      {open && (
        <div aria-hidden="true" onClick={closePanel} style={{
          position: "fixed", inset: 0, zIndex: 100, background: "rgba(0,0,0,0.4)",
        }} />
      )}

      {/* Slide-over panel */}
      <aside role="dialog" aria-modal="true" aria-label={t("product.add.title")} style={{
        position: "fixed", top: 0, right: 0, bottom: 0, zIndex: 101,
        width: 440, background: "#fff",
        boxShadow: "-4px 0 24px rgba(0,0,0,0.15)",
        display: "flex", flexDirection: "column",
        transform: open ? "translateX(0)" : "translateX(100%)",
        transition: "transform 0.25s ease-out",
      }}>

        {/* Header */}
        <div style={{
          padding: "16px 20px", background: "#0f2d1f",
          borderBottom: "1px solid #E5E7EB",
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <h2 style={{ fontSize: 16, fontWeight: 700, color: "#fff", margin: 0 }}>
            {t("product.add.title")}
          </h2>
          <button onClick={closePanel} aria-label={t("product.add.cancel")} style={{
            background: "transparent", border: "none", color: "rgba(255,255,255,0.7)",
            fontSize: 20, cursor: "pointer", lineHeight: 1, padding: 4,
          }}>×</button>
        </div>

        {/* SKU preview banner */}
        <div style={{
          padding: "10px 20px", background: "#F0FDF4",
          borderBottom: "1px solid #BBF7D0",
          display: "flex", alignItems: "center", gap: 10,
        }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: "#6B7280",
            textTransform: "uppercase", letterSpacing: "0.05em", flexShrink: 0 }}>
            {t("product.add.field.sku")}
          </span>
          <span style={{
            fontFamily: "monospace", fontSize: 15, fontWeight: 800, flex: 1,
            color: previewSku && !previewSku.includes("???") ? "#059669" : "#9CA3AF",
            letterSpacing: "0.08em",
          }}>
            {skuLoading ? t("product.add.loading_sku") : (previewSku || t("product.add.field.sku_placeholder"))}
          </span>
          <button type="button" onClick={handleCopy}
            disabled={!previewSku || previewSku.includes("???")}
            style={{
              padding: "5px 10px", border: "1px solid #BBF7D0", borderRadius: 4,
              background: "#fff", fontSize: 12, color: "#059669", fontWeight: 600, flexShrink: 0,
              cursor: (previewSku && !previewSku.includes("???")) ? "pointer" : "not-allowed",
            }}>
            {copied ? t("product.add.field.sku_copied") : t("product.add.field.sku_copy")}
          </button>
        </div>

        {/* Form body */}
        <div style={{ flex: 1, overflowY: "auto", padding: 20, display: "flex", flexDirection: "column", gap: 18 }}>
          {panelError && (
            <div role="alert" style={{
              background: "#FEF2F2", border: "1px solid #FECACA",
              borderRadius: 4, padding: "10px 14px", fontSize: 13, color: "#DC2626",
            }}>
              {panelError}
            </div>
          )}

          {/* Product Name */}
          <div>
            <FieldLabel text={t("product.add.field.name")} />
            <input
              value={name}
              onChange={(e) => { setName(e.target.value); setNameErr(""); }}
              placeholder={t("product.add.field.name_placeholder")}
              maxLength={255}
              aria-required="true"
              style={{
                width: "100%", boxSizing: "border-box",
                padding: "9px 12px", borderRadius: 4, fontSize: 13, outline: "none",
                border: `1px solid ${nameErr ? "#DC2626" : "#D1D5DB"}`,
              }}
            />
            <FieldErr msg={nameErr} />
          </div>

          {/* Category (required) — dropdown when categories are available */}
          <div>
            <FieldLabel text="Category" />
            {categories.length > 0 && !isCustomCategory ? (
              <select
                value={category}
                onChange={(e) => {
                  if (e.target.value === "__new__") {
                    setIsCustomCategory(true);
                    setCategory("");
                  } else {
                    setCategory(e.target.value);
                    setCategoryErr("");
                  }
                }}
                aria-required="true"
                style={{
                  width: "100%", boxSizing: "border-box",
                  padding: "9px 12px", borderRadius: 4, fontSize: 13,
                  background: "#fff", outline: "none", cursor: "pointer",
                  border: `1px solid ${categoryErr ? "#DC2626" : "#D1D5DB"}`,
                }}
              >
                <option value="">— select category —</option>
                {categories.map((c) => <option key={c} value={c}>{c}</option>)}
                <option value="__new__">+ Add new category…</option>
              </select>
            ) : (
              <div style={{ display: "flex", gap: 6 }}>
                <input
                  value={category}
                  onChange={(e) => { setCategory(e.target.value); setCategoryErr(""); }}
                  placeholder="e.g. Bottled Water, Cement, Packaging"
                  maxLength={100}
                  aria-required="true"
                  style={{
                    flex: 1, boxSizing: "border-box",
                    padding: "9px 12px", borderRadius: 4, fontSize: 13, outline: "none",
                    border: `1px solid ${categoryErr ? "#DC2626" : "#D1D5DB"}`,
                  }}
                />
                {isCustomCategory && (
                  <button
                    type="button"
                    onClick={() => { setIsCustomCategory(false); setCategory(""); }}
                    style={{ padding: "9px 10px", fontSize: 12, background: "#F3F4F6", border: "1px solid #D1D5DB", borderRadius: 4, cursor: "pointer", color: "#6B7280", whiteSpace: "nowrap" }}
                  >
                    ← Back
                  </button>
                )}
              </div>
            )}
            {categoryErr && <p role="alert" style={{ fontSize: 12, color: "#DC2626", marginTop: 4 }}>{categoryErr}</p>}
          </div>

          {/* Product Type Code */}
          <div>
            <FieldLabel text={t("product.add.field.type_code")} hint={t("product.add.field.type_code_hint")} />
            <input
              value={typeCode}
              onChange={(e) => {
                const v = e.target.value.replace(/[^A-Za-z]/g, "").slice(0, 5);
                setTypeCode(v);
                setTypeCodeErr("");
              }}
              placeholder={t("product.add.field.type_code_placeholder")}
              maxLength={5}
              aria-required="true"
              style={{
                width: "100%", boxSizing: "border-box",
                padding: "9px 12px", borderRadius: 4, fontSize: 13,
                outline: "none", textTransform: "uppercase",
                border: `1px solid ${typeCodeErr ? "#DC2626" : "#D1D5DB"}`,
              }}
            />
            <FieldErr msg={typeCodeErr} />
          </div>

          {/* Unit + Pack Size */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <FieldLabel text={t("product.add.field.unit")} />
              <select
                value={unit}
                onChange={(e) => setUnit(e.target.value as Unit)}
                style={{
                  width: "100%", boxSizing: "border-box", padding: "9px 12px",
                  borderRadius: 4, border: "1px solid #D1D5DB", fontSize: 13,
                  background: "#fff", outline: "none",
                }}
              >
                {UNITS.map((o) => <option key={o.value} value={o.value}>{t(o.label)}</option>)}
              </select>
            </div>
            <div>
              <FieldLabel text={t("product.add.field.pack_size")} />
              <select
                value={packSize}
                onChange={(e) => setPackSize(Number(e.target.value) as PackSize)}
                style={{
                  width: "100%", boxSizing: "border-box", padding: "9px 12px",
                  borderRadius: 4, border: "1px solid #D1D5DB", fontSize: 13,
                  background: "#fff", outline: "none",
                }}
              >
                {PACKS.map((o) => <option key={o.value} value={o.value}>{t(o.label)}</option>)}
              </select>
            </div>
          </div>

          {/* ── Stock initialisation (optional) ──────────────────────────── */}
          <div style={{ borderTop: "1px solid #F3F4F6", paddingTop: 14 }}>
            <p style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "#9CA3AF", margin: "0 0 12px" }}>
              Initial Stock — optional
            </p>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
              {/* On-hand */}
              <div>
                <FieldLabel text="On-hand" hint="optional" />
                <input
                  type="number" min="0" step="1"
                  value={onHand}
                  onChange={(e) => setOnHand(e.target.value)}
                  placeholder="0"
                  style={{ width: "100%", boxSizing: "border-box", padding: "9px 12px", borderRadius: 4, border: "1px solid #D1D5DB", fontSize: 13, outline: "none" }}
                />
              </div>

              {/* Available — read-only, computed from on-hand */}
              <div>
                <FieldLabel text="Available" hint="computed" />
                <div style={{
                  padding: "9px 12px", borderRadius: 4, border: "1px solid #E5E7EB",
                  background: "#F9FAFB", fontSize: 13, color: "#6B7280", fontWeight: 600,
                }}>
                  {availableDisplay}
                </div>
                <p style={{ fontSize: 11, color: "#9CA3AF", marginTop: 3 }}>On-hand minus reservations</p>
              </div>
            </div>

            {/* Reorder point */}
            <div>
              <FieldLabel text={`Reorder when ${unit} is at`} hint="optional" />
              <input
                type="number" min="0" step="1"
                value={reorderPoint}
                onChange={(e) => setReorderPoint(e.target.value)}
                placeholder="0"
                style={{ width: "100%", boxSizing: "border-box", padding: "9px 12px", borderRadius: 4, border: "1px solid #D1D5DB", fontSize: 13, outline: "none" }}
              />
            </div>

            {/* Warehouse note for TA/SA without a locked warehouse */}
            {onHandProvided && !user?.warehouseId && (
              <div style={{ marginTop: 8, background: "#EFF6FF", border: "1px solid #BFDBFE", borderRadius: 4, padding: "8px 12px", fontSize: 12, color: "#1E40AF" }}>
                Stock will be stored in the product record. Use <strong>Opening Balance</strong> on the Inventory page to post it to a specific warehouse.
              </div>
            )}
            {onHandProvided && user?.warehouseId && (
              <div style={{ marginTop: 8, background: "#F0FDF4", border: "1px solid #BBF7D0", borderRadius: 4, padding: "8px 12px", fontSize: 12, color: "#059669" }}>
                On-hand will be posted to <strong>{user.warehouseName ?? "your warehouse"}</strong> on save.
              </div>
            )}
          </div>

          {/* Live SKU inline hint once type_code has ≥2 chars */}
          {typeCode.trim().length >= 2 && previewSku && (
            <div style={{
              background: "#F0FDF4", border: "1px solid #BBF7D0", borderRadius: 4,
              padding: "8px 12px", fontSize: 12, color: "#374151",
            }}>
              <span style={{ fontWeight: 600 }}>{t("product.add.sku_preview_label")}: </span>
              <span style={{ fontFamily: "monospace", color: "#059669", fontWeight: 700 }}>
                {previewSku}
              </span>
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{
          padding: "14px 20px", borderTop: "1px solid #E5E7EB",
          display: "flex", justifyContent: "flex-end", gap: 10,
        }}>
          <button type="button" onClick={closePanel} style={{
            padding: "9px 18px", borderRadius: 4,
            border: "1px solid #D1D5DB", background: "#fff",
            fontSize: 13, fontWeight: 600, color: "#374151", cursor: "pointer",
          }}>
            {t("product.add.cancel")}
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saveDisabled}
            style={{
              padding: "9px 18px", borderRadius: 4, border: "none",
              background: saveDisabled ? "#D1D5DB" : "#0f2d1f",
              color:      saveDisabled ? "#9CA3AF" : "#FCDD09",
              fontSize: 13, fontWeight: 700,
              cursor: saveDisabled ? "not-allowed" : "pointer",
              display: "flex", alignItems: "center", gap: 8,
            }}
          >
            {submitting && (
              <span style={{
                width: 14, height: 14, borderRadius: "50%",
                border: "2px solid rgba(252,221,9,0.3)", borderTopColor: "#FCDD09",
                animation: "spin 0.7s linear infinite", display: "inline-block",
              }} />
            )}
            {t("product.add.save")}
          </button>
        </div>
      </aside>

      {toast && <Toast message={toast} onDismiss={() => setToast(null)} />}
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </>
  );
}
