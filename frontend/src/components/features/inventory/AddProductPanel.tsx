"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { t } from "@/lib/i18n";

// ── Org abbreviation: "addis-water" → "AW", "muger-cement" → "MC" ────────────

function toOrgAbbr(orgSlug: string): string {
  return orgSlug
    .split("-")
    .map((w) => (w[0] ?? "").toUpperCase())
    .join("")
    .slice(0, 4);
}

// ── Validation schema ─────────────────────────────────────────────────────────

const schema = z.object({
  name: z.string().min(1, "name_required").max(255).trim(),
  type_code: z
    .string()
    .min(2, "type_code_min")
    .max(5, "type_code_max")
    .regex(/^[A-Za-z]+$/, "type_code_letters_only")
    .transform((s) => s.toUpperCase()),
  unit: z.enum(["KG", "PACK", "QTL", "MT"]),
  pack_size: z.coerce
    .number()
    .refine((v) => [1, 4, 6, 12].includes(v), "invalid_pack_size"),
});

type FormValues = z.infer<typeof schema>;

const UNIT_OPTIONS: Array<{ value: "KG" | "PACK" | "QTL" | "MT"; labelKey: string }> = [
  { value: "KG",   labelKey: "product.unit.KG" },
  { value: "PACK", labelKey: "product.unit.PACK" },
  { value: "QTL",  labelKey: "product.unit.QTL" },
  { value: "MT",   labelKey: "product.unit.MT" },
];

const PACK_OPTIONS: Array<{ value: 1 | 4 | 6 | 12; labelKey: string }> = [
  { value: 1,  labelKey: "product.pack_size.1" },
  { value: 4,  labelKey: "product.pack_size.4" },
  { value: 6,  labelKey: "product.pack_size.6" },
  { value: 12, labelKey: "product.pack_size.12" },
];

// ── Toast ─────────────────────────────────────────────────────────────────────

function Toast({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  useEffect(() => {
    const id = setTimeout(onDismiss, 4000);
    return () => clearTimeout(id);
  }, [onDismiss]);
  return (
    <div role="status" aria-live="polite" style={{
      position: "fixed", bottom: 24, right: 24, zIndex: 9999,
      background: "#059669", color: "#fff",
      padding: "12px 20px", borderRadius: 6,
      fontSize: 14, fontWeight: 600, boxShadow: "0 4px 16px rgba(0,0,0,0.2)",
    }}>
      {message}
    </div>
  );
}

// ── Primitive field components ────────────────────────────────────────────────

function Label({ children, hint }: { children: React.ReactNode; hint?: string }) {
  return (
    <label style={{ display: "block", fontSize: 12, fontWeight: 700,
      textTransform: "uppercase", letterSpacing: "0.05em", color: "#374151", marginBottom: 4 }}>
      {children}
      {hint && (
        <span style={{ fontSize: 11, fontWeight: 400, textTransform: "none",
          letterSpacing: 0, color: "#9CA3AF", marginLeft: 6 }}>
          {hint}
        </span>
      )}
    </label>
  );
}

function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  const key = `product.add.error.${message}`;
  const resolved = t(key);
  return (
    <p role="alert" style={{ fontSize: 12, color: "#DC2626", marginTop: 4 }}>
      {resolved !== key ? resolved : message}
    </p>
  );
}

function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input {...props} style={{
      width: "100%", boxSizing: "border-box",
      padding: "9px 12px", borderRadius: 4,
      border: "1px solid #D1D5DB", fontSize: 13,
      outline: "none", ...props.style,
    }} />
  );
}

function Select(props: React.SelectHTMLAttributes<HTMLSelectElement> & { children: React.ReactNode }) {
  return (
    <select {...props} style={{
      width: "100%", boxSizing: "border-box",
      padding: "9px 12px", borderRadius: 4,
      border: "1px solid #D1D5DB", fontSize: 13,
      background: "#fff", appearance: "auto",
      outline: "none", ...props.style,
    }} />
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface AddProductPanelProps {
  apiBase: string;
  onClose?: () => void;
}

export function AddProductPanel({ apiBase, onClose }: AddProductPanelProps) {
  const params = useParams() as { org?: string };
  const orgSlug = params.org ?? "admin";
  const orgAbbr = toOrgAbbr(orgSlug);

  const [open, setOpen]             = useState(false);
  const [toast, setToast]           = useState<string | null>(null);
  const [panelError, setPanelError] = useState<string | null>(null);
  const [copied, setCopied]         = useState(false);
  const qc                          = useQueryClient();
  const token                       = getToken();

  const {
    control,
    register,
    handleSubmit,
    formState: { errors, isDirty, isSubmitting },
    reset,
    setError,
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    mode: "onChange",
    defaultValues: { unit: "KG", pack_size: 1, type_code: "", name: "" },
  });

  // useWatch creates an explicit subscription — re-renders on every field change
  const watchedName     = useWatch({ control, name: "name" }) ?? "";
  const watchedTypeCode = useWatch({ control, name: "type_code" }) ?? "";
  const watchedUnit     = useWatch({ control, name: "unit" }) ?? "KG";
  const watchedPackSize = useWatch({ control, name: "pack_size" }) ?? 1;

  // ── Server: fetch next counter ────────────────────────────────────────────
  const { data: counterData, isFetching: skuLoading, error: skuError } = useQuery({
    queryKey: ["next-sku-counter", apiBase],
    queryFn:  () => api.get<{ counter: number }>(`${apiBase}/next-sku`, token ?? undefined),
    enabled:  open,
    staleTime: 0,
    refetchOnWindowFocus: false,
  });

  const counter = counterData?.counter;

  // Assemble preview: {ORG}-{TYPE}-{UNIT}{PACK}-{COUNTER}
  const typeDisplay = watchedTypeCode.toUpperCase() || "???";
  const previewSku = counter != null
    ? `${orgAbbr}-${typeDisplay}-${watchedUnit}${watchedPackSize}-${String(counter).padStart(4, "0")}`
    : "";

  // ── Save gate: derive from live field values, not RHF's isValid flag ────────
  const nameOk     = watchedName.trim().length > 0;
  const typeCodeOk = /^[A-Za-z]{2,5}$/.test(watchedTypeCode.trim());
  const noErrors   = Object.keys(errors).length === 0;
  const saveDisabled = !nameOk || !typeCodeOk || !noErrors || isSubmitting || skuLoading;

  // ── Copy SKU to clipboard ─────────────────────────────────────────────────
  const handleCopy = async () => {
    if (!previewSku) return;
    await navigator.clipboard.writeText(previewSku);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // ── Create mutation ───────────────────────────────────────────────────────
  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      api.post<{ id: string; sku: string }>(apiBase, {
        ...values,
        org_slug: orgSlug,
      }, token ?? undefined),
    onSuccess: (data) => {
      const msg = t("product.add.success").replace("{{sku}}", data.sku);
      setToast(msg);
      qc.invalidateQueries({ queryKey: ["products"] });
      reset();
      setOpen(false);
      onClose?.();
    },
    onError: (err: Error & { status?: number }) => {
      if (err.status === 409) {
        setError("name", { message: "duplicate_name" });
      } else if (err.status === 429) {
        setPanelError(t("product.add.error.sku_cap_reached"));
      } else {
        setPanelError(t("product.add.error.generic"));
      }
    },
  });

  const openPanel = () => {
    setPanelError(null);
    reset({ unit: "KG", pack_size: 1, type_code: "", name: "" });
    setOpen(true);
  };

  const closePanel = () => {
    if (isDirty) {
      if (!window.confirm(t("product.add.confirm.discard"))) return;
    }
    reset();
    setPanelError(null);
    setOpen(false);
    onClose?.();
  };

  const onSubmit = (values: FormValues) => {
    setPanelError(null);
    mutation.mutate(values);
  };

  return (
    <>
      {/* ── Trigger ── */}
      <button onClick={openPanel} style={{
        padding: "8px 16px", background: "#FCDD09", color: "#0f2d1f",
        fontWeight: 700, fontSize: 13, borderRadius: 4, border: "none", cursor: "pointer",
      }}>
        {t("product.add.button")}
      </button>

      {/* ── Backdrop ── */}
      {open && (
        <div aria-hidden="true" onClick={closePanel} style={{
          position: "fixed", inset: 0, zIndex: 100, background: "rgba(0,0,0,0.4)",
        }} />
      )}

      {/* ── Slide-over ── */}
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
          padding: "16px 20px", borderBottom: "1px solid #E5E7EB",
          display: "flex", alignItems: "center", justifyContent: "space-between",
          background: "#0f2d1f",
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
            fontFamily: "monospace", fontSize: 15, fontWeight: 800,
            color: previewSku ? "#059669" : "#9CA3AF", flex: 1,
            letterSpacing: "0.08em",
          }}>
            {skuLoading
              ? t("product.add.loading_sku")
              : (previewSku || t("product.add.field.sku_placeholder"))}
          </span>
          <button type="button" onClick={handleCopy}
            disabled={!previewSku || previewSku.includes("???")}
            aria-label={t("product.add.field.sku_copy")}
            style={{
              padding: "5px 10px", border: "1px solid #BBF7D0",
              borderRadius: 4, background: "#fff", cursor: previewSku ? "pointer" : "not-allowed",
              fontSize: 12, color: "#059669", fontWeight: 600, flexShrink: 0,
            }}
          >
            {copied ? t("product.add.field.sku_copied") : t("product.add.field.sku_copy")}
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit(onSubmit)} noValidate style={{
          flex: 1, overflowY: "auto", padding: 20,
          display: "flex", flexDirection: "column", gap: 18,
        }}>
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
            <Label>{t("product.add.field.name")}</Label>
            <Input
              {...register("name")}
              placeholder={t("product.add.field.name_placeholder")}
              maxLength={255}
              aria-required="true"
              aria-invalid={!!errors.name}
              style={errors.name ? { borderColor: "#DC2626" } : {}}
            />
            <FieldError message={errors.name?.message} />
          </div>

          {/* Product Type Code */}
          <div>
            <Label hint={t("product.add.field.type_code_hint")}>
              {t("product.add.field.type_code")}
            </Label>
            <Input
              {...register("type_code")}
              placeholder={t("product.add.field.type_code_placeholder")}
              maxLength={5}
              style={{
                textTransform: "uppercase",
                ...(errors.type_code ? { borderColor: "#DC2626" } : {}),
              }}
              aria-required="true"
              aria-invalid={!!errors.type_code}
            />
            <FieldError message={errors.type_code?.message} />
          </div>

          {/* Unit and Pack Size side-by-side */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <Label>{t("product.add.field.unit")}</Label>
              <Select {...register("unit")} aria-required="true">
                {UNIT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{t(o.labelKey)}</option>
                ))}
              </Select>
              <FieldError message={errors.unit?.message} />
            </div>
            <div>
              <Label>{t("product.add.field.pack_size")}</Label>
              <Select {...register("pack_size")} aria-required="true">
                {PACK_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{t(o.labelKey)}</option>
                ))}
              </Select>
              <FieldError message={errors.pack_size?.message} />
            </div>
          </div>

          {/* SKU preview: live update as type_code/unit/pack_size change */}
          {watchedTypeCode.length >= 2 && (
            <div style={{
              background: "#F9FAFB", border: "1px solid #E5E7EB", borderRadius: 4,
              padding: "8px 12px", fontSize: 12, color: "#6B7280",
            }}>
              <span style={{ fontWeight: 600 }}>{t("product.add.sku_preview_label")}: </span>
              <span style={{ fontFamily: "monospace", color: "#059669", fontWeight: 700 }}>
                {previewSku}
              </span>
            </div>
          )}
        </form>

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
            onClick={handleSubmit(onSubmit)}
            disabled={saveDisabled || mutation.isPending}
            style={{
              padding: "9px 18px", borderRadius: 4, border: "none",
              background: (saveDisabled || mutation.isPending) ? "#D1D5DB" : "#0f2d1f",
              color:      (saveDisabled || mutation.isPending) ? "#9CA3AF" : "#FCDD09",
              fontSize: 13, fontWeight: 700,
              cursor: (saveDisabled || mutation.isPending) ? "not-allowed" : "pointer",
              display: "flex", alignItems: "center", gap: 8,
            }}
          >
            {mutation.isPending && (
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
