"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { nanoid } from "nanoid";
import { api } from "@/lib/api";
import { useInventoryStore } from "@/lib/inventory-state";
import { getSession } from "@/lib/demo-auth";
import { useWriteGuard, guardProps } from "@/hooks/useWriteGuard";
import { t } from "@/lib/i18n";
import type { DemoProduct, DemoWarehouse } from "@/lib/demo-data";
import type { ImportBatch } from "@/app/api/v1/imports/_demo-state";

const isGatewayMode = !!process.env.NEXT_PUBLIC_API_URL;

interface Props { products: DemoProduct[]; warehouses: DemoWarehouse[]; orgSlug: string; }

type ValidationSeverity = "ERROR" | "WARNING";
interface ValidationIssue { rowNumber: number; field: string; severity: ValidationSeverity; message: string; }
interface ParsedRow { rowNumber: number; warehouseCode: string; warehouseId: string | null; skuCode: string; productId: string | null; productName: string | null; productUnit: string | null; productBatchTracking: boolean; openingQuantity: number; uom: string; batchNumber: string | null; manufactureDate: string | null; expiryDate: string | null; notes: string | null; referenceDocument: string | null; idempotencyKey: string; issues: ValidationIssue[]; status: "VALID" | "ERROR" | "WARNING"; }

const CSV_COLUMNS = ["warehouse_code","sku_code","opening_quantity","uom","batch_number","manufacture_date","expiry_date","notes","reference_document"] as const;
const TEMPLATE_HEADER  = CSV_COLUMNS.join(",");
const TEMPLATE_EXAMPLE = "MAIN-WH-001,SKU-0001,500,Bag,,,,Initial go-live,PHYS-COUNT-001\nNORTH-WH,SKU-0002,250,Carton,LOT-2026-001,2026-01-10,2026-12-31,Batch tracked product,";

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <label className="block text-xs font-bold uppercase tracking-wide text-gray-700 mb-1">
        {label}{hint && <span className="text-[11px] font-normal normal-case text-gray-400 ml-1.5">{hint}</span>}
      </label>
      {children}
    </div>
  );
}

function parseCsvLine(line: string): string[] {
  const sep = line.includes("\t") ? "\t" : ",";
  return line.split(sep).map((c) => c.trim());
}

function validateRows(rawRows: string[][], products: DemoProduct[], warehouses: DemoWarehouse[]): ParsedRow[] {
  const seen = new Map<string, number>();
  return rawRows.map((cells, idx): ParsedRow => {
    const rowNumber = idx + 1; const issues: ValidationIssue[] = [];
    const warehouseCode = cells[0] ?? ""; const skuCode = cells[1] ?? ""; const openingQtyRaw = cells[2] ?? "";
    const uom = cells[3] ?? ""; const batchNumber = cells[4] || null; const manufactureDate = cells[5] || null;
    const expiryDate = cells[6] || null; const notes = cells[7] || null; const referenceDoc = cells[8] || null;
    const warehouse = warehouses.find((w) => w.id.toLowerCase() === warehouseCode.toLowerCase() || w.name.toLowerCase() === warehouseCode.toLowerCase());
    if (!warehouseCode) issues.push({ rowNumber, field: "warehouse_code", severity: "ERROR", message: "warehouse_code is required" });
    else if (!warehouse) issues.push({ rowNumber, field: "warehouse_code", severity: "ERROR", message: `No warehouse found matching '${warehouseCode}'` });
    const product = products.find((p) => p.sku.toLowerCase() === skuCode.toLowerCase());
    if (!skuCode) issues.push({ rowNumber, field: "sku_code", severity: "ERROR", message: "sku_code is required" });
    else if (!product) issues.push({ rowNumber, field: "sku_code", severity: "ERROR", message: `No product found with SKU '${skuCode}'` });
    const openingQuantity = parseInt(openingQtyRaw, 10);
    if (!openingQtyRaw) issues.push({ rowNumber, field: "opening_quantity", severity: "ERROR", message: "opening_quantity is required" });
    else if (isNaN(openingQuantity) || openingQuantity <= 0) issues.push({ rowNumber, field: "opening_quantity", severity: "ERROR", message: `opening_quantity must be a positive integer (got '${openingQtyRaw}')` });
    if (product && uom && product.unit.toLowerCase() !== uom.toLowerCase()) issues.push({ rowNumber, field: "uom", severity: "WARNING", message: `UOM '${uom}' does not match product unit '${product.unit}'` });
    if (!uom) issues.push({ rowNumber, field: "uom", severity: "ERROR", message: "uom is required" });
    if (product?.batchTracking) {
      if (!batchNumber) issues.push({ rowNumber, field: "batch_number", severity: "ERROR", message: "batch_number required for batch-tracked product" });
      if (!manufactureDate) issues.push({ rowNumber, field: "manufacture_date", severity: "ERROR", message: "manufacture_date required for batch-tracked product" });
    }
    const dupeKey = `${skuCode.toLowerCase()}|${warehouseCode.toLowerCase()}`;
    if (seen.has(dupeKey)) issues.push({ rowNumber, field: "sku_code", severity: "WARNING", message: `Duplicate: SKU '${skuCode}' + warehouse '${warehouseCode}' already appears in row ${seen.get(dupeKey)!}` });
    else seen.set(dupeKey, rowNumber);
    const hasError = issues.some((i) => i.severity === "ERROR"); const hasWarning = issues.some((i) => i.severity === "WARNING");
    return { rowNumber, warehouseCode, warehouseId: warehouse?.id ?? null, skuCode, productId: product?.id ?? null, productName: product?.name ?? null, productUnit: product?.unit ?? null, productBatchTracking: product?.batchTracking ?? false, openingQuantity: isNaN(openingQuantity) ? 0 : openingQuantity, uom: uom || (product?.unit ?? ""), batchNumber, manufactureDate, expiryDate, notes, referenceDocument: referenceDoc, idempotencyKey: `bulk:${skuCode}:${warehouseCode}:${Date.now()}:${nanoid(6)}`, issues, status: hasError ? "ERROR" : hasWarning ? "WARNING" : "VALID" };
  });
}

export function BulkImportPanel({ products, warehouses, orgSlug }: Props) {
  const qc        = useQueryClient();
  const addReceive = useInventoryStore((s) => s.addReceive);
  const user       = getSession();

  const [open, setOpen]             = useState(false);
  const [csvText, setCsvText]       = useState("");
  const [parsedRows, setParsedRows] = useState<ParsedRow[] | null>(null);
  const [error, setError]           = useState("");
  const [success, setSuccess]       = useState("");
  const [importRef, setImportRef]   = useState("");
  const [loading, setLoading]       = useState(false);
  // Bulk-imports opening quantities for EXISTING skus (looked up by sku_code)
  // — it never creates a new product, so read-only gating only, no "skus" cap.
  const writeGuard = useWriteGuard();
  // POST /api/v1/imports/opening-balance has no backend route yet (demo-only
  // BFF handler) — disabled with a "coming soon" tooltip in gateway mode,
  // regardless of contract stage (CLAUDE.md §29 P6). Demo mode unaffected.
  const gp = isGatewayMode
    ? { disabled: true, title: t("common.coming_soon_hint") }
    : guardProps(writeGuard);

  function reset() { setCsvText(""); setParsedRows(null); setError(""); setSuccess(""); setImportRef(""); }

  function handleValidate() {
    setError(""); setParsedRows(null);
    const lines = csvText.split("\n").map((l) => l.trim()).filter((l) => l.length > 0);
    if (lines.length === 0) { setError(t("bulk_import.error_empty")); return; }
    const firstLine = lines[0]?.toLowerCase() ?? "";
    const dataLines = firstLine.startsWith("warehouse_code") || firstLine.startsWith("warehouse code") ? lines.slice(1) : lines;
    if (dataLines.length === 0) { setError(t("bulk_import.error_no_data")); return; }
    setParsedRows(validateRows(dataLines.map((l) => parseCsvLine(l)), products, warehouses));
  }

  const handleSubmit = async () => {
    if (!user) { setError(t("opening_balance.error_session")); return; }
    if (!parsedRows || parsedRows.length === 0) { setError(t("bulk_import.error_validate_first")); return; }
    if (parsedRows.some((r) => r.status === "ERROR")) { setError(t("bulk_import.error_fix_errors")); return; }
    setLoading(true); setError("");
    try {
      const submittableRows = parsedRows.filter((r) => r.status === "VALID" || r.status === "WARNING");
      const payload = { rows: submittableRows.map((r) => ({ row_number: r.rowNumber, warehouse_code: r.warehouseCode, warehouse_id: r.warehouseId, sku_code: r.skuCode, product_id: r.productId, opening_quantity: r.openingQuantity, uom: r.uom, batch_number: r.batchNumber, manufacture_date: r.manufactureDate, expiry_date: r.expiryDate, notes: r.notes, reference_document: r.referenceDocument, idempotency_key: r.idempotencyKey, status: r.status, errors: r.issues.filter((i) => i.severity === "ERROR").map((i) => i.message), warnings: r.issues.filter((i) => i.severity === "WARNING").map((i) => i.message) })) };
      const batch = await api.post<ImportBatch>("/api/v1/imports/opening-balance", payload);
      for (const row of submittableRows) { if (row.productId && row.warehouseId && row.openingQuantity > 0) addReceive(row.productId, row.warehouseId, row.openingQuantity); }
      void qc.invalidateQueries({ queryKey: ["products", orgSlug] });
      setImportRef(batch.reference);
      setSuccess(`Import batch submitted — ref: ${batch.reference}. Status: PENDING_APPROVAL. ${submittableRows.length} rows queued.`);
      setCsvText(""); setParsedRows(null);
    } catch (err: unknown) { setError(err instanceof Error ? err.message : t("errors.INTERNAL_ERROR")); }
    finally { setLoading(false); }
  };

  if (!user) return null;

  const totalRows   = parsedRows?.length ?? 0;
  const validRows   = parsedRows?.filter((r) => r.status === "VALID").length ?? 0;
  const errorRows   = parsedRows?.filter((r) => r.status === "ERROR").length ?? 0;
  const warningRows = parsedRows?.filter((r) => r.status === "WARNING").length ?? 0;
  const uniqueSkus  = parsedRows ? new Set(parsedRows.map((r) => r.skuCode).filter(Boolean)).size : 0;
  const uniqueWhs   = parsedRows ? new Set(parsedRows.map((r) => r.warehouseCode).filter(Boolean)).size : 0;
  const hasErrors   = errorRows > 0;

  return (
    <>
      <button onClick={() => { reset(); setOpen(true); }} {...gp} className="px-4 py-2 bg-violet-600 text-white font-bold text-sm rounded border-0 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed">
        ↑ {t("bulk_import.title")}
        {isGatewayMode && (
          <span className="ml-1.5 text-[9px] font-bold uppercase tracking-wide bg-white/20 px-1 py-0.5 rounded">
            {t("common.coming_soon_badge")}
          </span>
        )}
      </button>

      {open && <div onClick={() => setOpen(false)} className="fixed inset-0 bg-black/35 z-[100] backdrop-blur-sm" />}

      <div className={`fixed top-0 right-0 w-[600px] h-screen bg-white z-[110] shadow-2xl flex flex-col transition-transform duration-[250ms] ease-out ${open ? "translate-x-0" : "translate-x-full"}`}>
        <div className="px-6 py-5 bg-violet-600 flex items-start justify-between">
          <div>
            <p className="font-bold text-base text-white m-0">{t("bulk_import.full_title")}</p>
            <p className="text-xs text-violet-200 mt-0.5">{t("bulk_import.subtitle")}</p>
            <p className="text-[10px] text-violet-300 mt-1 font-mono tracking-wide">
              {t("status.SUBMITTED")} → {t("status.PENDING_APPROVAL")} → {t("status.POSTED")}
            </p>
          </div>
          <button onClick={() => setOpen(false)} className="bg-white/10 border-0 cursor-pointer text-white text-lg w-8 h-8 rounded flex items-center justify-center shrink-0">✕</button>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          {gp.disabled && gp.title && (
            <div role="alert" className="bg-amber-50 border border-amber-200 rounded px-3.5 py-2.5 text-sm text-amber-800 mb-4">
              {gp.title}
            </div>
          )}
          {success && (
            <div className="bg-violet-50 border border-violet-200 rounded-md px-4 py-3.5 text-violet-800 mb-4 leading-relaxed">
              <p className="font-bold mb-1.5 text-sm">✓ {t("bulk_import.submitted")}</p>
              <p className="m-0 mb-2 text-xs"><strong>{t("bulk_import.ref")}:</strong> <code className="font-mono text-xs">{importRef}</code></p>
              <p className="m-0 text-xs">{success}</p>
            </div>
          )}

          <div className="mb-5">
            <p className="text-xs font-bold uppercase tracking-wide text-gray-700 mb-2">{t("bulk_import.csv_columns")}</p>
            <div className="bg-gray-50 border border-gray-200 rounded px-3 py-2.5 font-mono text-xs text-gray-700 leading-relaxed whitespace-pre-wrap break-all">
              <span className="text-violet-700 font-bold">{t("bulk_import.header_label")}</span> {TEMPLATE_HEADER}{"\n"}
              <span className="text-emerald-600 font-bold">{t("bulk_import.examples_label")}</span>{"\n"}{TEMPLATE_EXAMPLE}
            </div>
            <p className="text-[11px] text-gray-400 mt-1.5 leading-relaxed">
              {t("bulk_import.columns_hint")} <code className="text-xs">warehouse_code</code>.
            </p>
          </div>

          <Field label={t("bulk_import.paste_label")}>
            <textarea value={csvText} onChange={(e) => { setCsvText(e.target.value); setParsedRows(null); setError(""); setSuccess(""); }}
              placeholder={`${t("bulk_import.placeholder")}\n\n${TEMPLATE_HEADER}\n${TEMPLATE_EXAMPLE}`}
              rows={8} className="w-full px-2.5 py-2 text-xs font-mono border border-gray-300 rounded outline-none bg-white resize-y leading-relaxed" />
          </Field>

          <button type="button" onClick={handleValidate} disabled={!csvText.trim()}
            className={`w-full py-2.5 font-bold text-sm rounded border-0 mb-5 ${csvText.trim() ? "bg-gray-700 text-white cursor-pointer" : "bg-gray-200 text-gray-400 cursor-not-allowed"}`}>
            {t("bulk_import.validate_btn")}
          </button>

          {error && <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-600 mb-4">{error}</div>}

          {parsedRows && parsedRows.length > 0 && (
            <>
              <div className="bg-gray-50 border border-gray-200 rounded-md px-3.5 py-3 mb-4 text-xs">
                <p className="font-bold text-sm text-gray-900 mb-2 uppercase tracking-wide">{t("bulk_import.summary")}</p>
                <table className="w-full text-xs">
                  <tbody>
                    {[
                      [t("bulk_import.total_rows"), totalRows, "text-gray-700"],
                      [t("bulk_import.valid_rows"), validRows, "text-emerald-600"],
                      [t("bulk_import.error_rows"), errorRows, "text-red-600"],
                      [t("bulk_import.warning_rows"), warningRows, "text-amber-700"],
                      [t("bulk_import.unique_skus"), uniqueSkus, "text-gray-700"],
                      [t("bulk_import.unique_whs"), uniqueWhs, "text-gray-700"],
                    ].map(([label, val, cls]) => (
                      <tr key={String(label)}>
                        <td className="py-0.5 text-gray-500">{label}:</td>
                        <td className={`py-0.5 text-right font-bold ${cls}`}>{String(val)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="mb-4">
                <p className="text-xs font-bold uppercase tracking-wide text-gray-700 mb-2">{t("bulk_import.row_report")}</p>
                <div className="border border-gray-200 rounded-md overflow-hidden">
                  {parsedRows.map((row, idx) => {
                    const rowBg = row.status === "ERROR" ? "bg-red-50" : row.status === "WARNING" ? "bg-yellow-50" : idx % 2 === 0 ? "bg-white" : "bg-gray-50";
                    const statusCls = row.status === "ERROR" ? "text-red-600" : row.status === "WARNING" ? "text-amber-700" : "text-emerald-600";
                    const statusIcon = row.status === "ERROR" ? "✗" : row.status === "WARNING" ? "⚠" : "✓";
                    return (
                      <div key={row.rowNumber} className={`${rowBg} ${idx < parsedRows.length - 1 ? "border-b border-gray-200" : ""} px-3 py-2`}>
                        <div className={`flex items-center gap-2 ${row.issues.length > 0 ? "mb-1" : ""}`}>
                          <span className={`font-bold text-sm min-w-[16px] ${statusCls}`}>{statusIcon}</span>
                          <span className="font-mono text-[11px] text-gray-500 min-w-[52px]">{t("bulk_import.row_label")} {row.rowNumber}</span>
                          <span className="text-xs text-gray-700 font-semibold">{row.skuCode || "—"}</span>
                          <span className="text-[11px] text-gray-400">@ {row.warehouseCode || "—"}</span>
                          {row.productName && <span className="text-[11px] text-gray-500">· {row.productName}</span>}
                          <span className="ml-auto text-[11px] font-bold text-gray-700">{row.openingQuantity > 0 ? `${row.openingQuantity.toLocaleString()} ${row.uom}` : ""}</span>
                        </div>
                        {row.issues.map((issue, iIdx) => (
                          <div key={iIdx} className={`font-mono text-[11px] ml-6 leading-relaxed ${issue.severity === "ERROR" ? "text-red-600" : "text-amber-800"}`}>
                            {t("bulk_import.row_label")} [{row.rowNumber}] | {t("bulk_import.issue_field_label")}: {issue.field} | {t("bulk_import.issue_severity_label")}: {issue.severity} | {t("bulk_import.issue_message_label")}: {issue.message}
                          </div>
                        ))}
                      </div>
                    );
                  })}
                </div>
              </div>

              <button type="button" onClick={handleSubmit} disabled={hasErrors || loading || gp.disabled} title={gp.title}
                className={`w-full py-2.5 font-bold text-sm rounded border-0 mb-2 ${hasErrors || gp.disabled ? "bg-gray-200 text-gray-400 cursor-not-allowed" : `bg-violet-600 text-white ${loading ? "opacity-70 cursor-not-allowed" : "cursor-pointer"}`}`}>
                {loading ? t("common.loading") : hasErrors ? `${t("bulk_import.cannot_submit")} — ${errorRows} ${t("bulk_import.error_row_label")}` : `${t("bulk_import.submit_btn")} (${validRows + warningRows} ${t("bulk_import.rows_label")})`}
              </button>

              {hasErrors && <p className="text-[11px] text-red-600 text-center m-0">{t("bulk_import.fix_hint")}</p>}
            </>
          )}
        </div>

        <div className="px-6 py-3.5 border-t border-gray-200 flex gap-2.5">
          <button type="button" onClick={() => { reset(); setOpen(false); }} className="flex-1 py-2.5 bg-gray-100 border border-gray-200 rounded text-sm font-semibold text-gray-700 cursor-pointer">{t("common.cancel")}</button>
          {parsedRows && !hasErrors && !success && (
            <button type="button" onClick={handleSubmit} disabled={loading || gp.disabled} title={gp.title} className={`flex-[2] py-2.5 bg-violet-600 text-white font-bold text-sm rounded border-0 ${loading || gp.disabled ? "opacity-70 cursor-not-allowed" : "cursor-pointer"}`}>
              {loading ? t("common.loading") : t("bulk_import.submit_btn")}
            </button>
          )}
        </div>
      </div>
    </>
  );
}
