"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { nanoid } from "nanoid";
import { api } from "@/lib/api";
import { useInventoryStore } from "@/lib/inventory-state";
import { useAuditStore } from "@/lib/audit-log-state";
import { getSession } from "@/lib/demo-auth";
import type { DemoProduct, DemoWarehouse } from "@/lib/demo-data";
import type { ImportBatch } from "@/app/api/v1/imports/_demo-state";

interface Props {
  products: DemoProduct[];
  warehouses: DemoWarehouse[];
  orgSlug: string;
}

type ValidationSeverity = "ERROR" | "WARNING";

interface ValidationIssue {
  rowNumber: number;
  field: string;
  severity: ValidationSeverity;
  message: string;
}

interface ParsedRow {
  rowNumber: number;
  warehouseCode: string;
  warehouseId: string | null;
  skuCode: string;
  productId: string | null;
  productName: string | null;
  productUnit: string | null;
  productBatchTracking: boolean;
  openingQuantity: number;
  uom: string;
  batchNumber: string | null;
  manufactureDate: string | null;
  expiryDate: string | null;
  notes: string | null;
  referenceDocument: string | null;
  idempotencyKey: string;
  issues: ValidationIssue[];
  status: "VALID" | "ERROR" | "WARNING";
}

const PANEL_W = 600;

const CSV_COLUMNS = [
  "warehouse_code",
  "sku_code",
  "opening_quantity",
  "uom",
  "batch_number",
  "manufacture_date",
  "expiry_date",
  "notes",
  "reference_document",
] as const;

const TEMPLATE_HEADER = CSV_COLUMNS.join(",");
const TEMPLATE_EXAMPLE =
  "MAIN-WH-001,SKU-0001,500,Bag,,,,Initial go-live,PHYS-COUNT-001\n" +
  "NORTH-WH,SKU-0002,250,Carton,LOT-2026-001,2026-01-10,2026-12-31,Batch tracked product,";

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label
        style={{
          display: "block",
          fontSize: 12,
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          color: "#374151",
          marginBottom: 4,
        }}
      >
        {label}
        {hint && (
          <span
            style={{
              fontSize: 11,
              fontWeight: 400,
              textTransform: "none",
              color: "#9CA3AF",
              marginLeft: 6,
            }}
          >
            {hint}
          </span>
        )}
      </label>
      {children}
    </div>
  );
}

function parseCsvLine(line: string): string[] {
  // Handle both comma and tab separators; trim each cell
  const separator = line.includes("\t") ? "\t" : ",";
  return line.split(separator).map((c) => c.trim());
}

function validateRows(
  rawRows: string[][],
  products: DemoProduct[],
  warehouses: DemoWarehouse[]
): ParsedRow[] {
  const seen = new Map<string, number>(); // "skuCode|warehouseCode" → first row number

  return rawRows.map((cells, idx): ParsedRow => {
    const rowNumber = idx + 1;
    const issues: ValidationIssue[] = [];

    const warehouseCode    = cells[0] ?? "";
    const skuCode          = cells[1] ?? "";
    const openingQtyRaw    = cells[2] ?? "";
    const uom              = cells[3] ?? "";
    const batchNumber      = cells[4] || null;
    const manufactureDate  = cells[5] || null;
    const expiryDate       = cells[6] || null;
    const notes            = cells[7] || null;
    const referenceDoc     = cells[8] || null;

    // Resolve warehouse — match by id OR name (case-insensitive)
    const warehouse = warehouses.find(
      (w) =>
        w.id.toLowerCase() === warehouseCode.toLowerCase() ||
        w.name.toLowerCase() === warehouseCode.toLowerCase()
    );

    if (!warehouseCode) {
      issues.push({ rowNumber, field: "warehouse_code", severity: "ERROR", message: "warehouse_code is required" });
    } else if (!warehouse) {
      issues.push({ rowNumber, field: "warehouse_code", severity: "ERROR", message: `No warehouse found matching '${warehouseCode}'` });
    }

    // Resolve product by SKU
    const product = products.find(
      (p) => p.sku.toLowerCase() === skuCode.toLowerCase()
    );

    if (!skuCode) {
      issues.push({ rowNumber, field: "sku_code", severity: "ERROR", message: "sku_code is required" });
    } else if (!product) {
      issues.push({ rowNumber, field: "sku_code", severity: "ERROR", message: `No product found with SKU '${skuCode}'` });
    }

    // Quantity
    const openingQuantity = parseInt(openingQtyRaw, 10);
    if (!openingQtyRaw) {
      issues.push({ rowNumber, field: "opening_quantity", severity: "ERROR", message: "opening_quantity is required" });
    } else if (isNaN(openingQuantity) || openingQuantity <= 0) {
      issues.push({ rowNumber, field: "opening_quantity", severity: "ERROR", message: `opening_quantity must be a positive integer (got '${openingQtyRaw}')` });
    }

    // UOM match
    if (product && uom && product.unit.toLowerCase() !== uom.toLowerCase()) {
      issues.push({
        rowNumber,
        field: "uom",
        severity: "WARNING",
        message: `UOM '${uom}' does not match product unit '${product.unit}'`,
      });
    }
    if (!uom) {
      issues.push({ rowNumber, field: "uom", severity: "ERROR", message: "uom is required" });
    }

    // Batch tracking requirements
    if (product?.batchTracking) {
      if (!batchNumber) {
        issues.push({ rowNumber, field: "batch_number", severity: "ERROR", message: "batch_number required for batch-tracked product" });
      }
      if (!manufactureDate) {
        issues.push({ rowNumber, field: "manufacture_date", severity: "ERROR", message: "manufacture_date required for batch-tracked product" });
      }
    }

    // Duplicate SKU + warehouse in same import
    const dupeKey = `${skuCode.toLowerCase()}|${warehouseCode.toLowerCase()}`;
    if (seen.has(dupeKey)) {
      issues.push({
        rowNumber,
        field: "sku_code",
        severity: "WARNING",
        message: `Duplicate: SKU '${skuCode}' + warehouse '${warehouseCode}' already appears in row ${seen.get(dupeKey)!}`,
      });
    } else {
      seen.set(dupeKey, rowNumber);
    }

    const hasError   = issues.some((i) => i.severity === "ERROR");
    const hasWarning = issues.some((i) => i.severity === "WARNING");
    const status: ParsedRow["status"] = hasError ? "ERROR" : hasWarning ? "WARNING" : "VALID";

    return {
      rowNumber,
      warehouseCode,
      warehouseId: warehouse?.id ?? null,
      skuCode,
      productId: product?.id ?? null,
      productName: product?.name ?? null,
      productUnit: product?.unit ?? null,
      productBatchTracking: product?.batchTracking ?? false,
      openingQuantity: isNaN(openingQuantity) ? 0 : openingQuantity,
      uom: uom || (product?.unit ?? ""),
      batchNumber,
      manufactureDate,
      expiryDate,
      notes,
      referenceDocument: referenceDoc,
      idempotencyKey: `bulk:${skuCode}:${warehouseCode}:${Date.now()}:${nanoid(6)}`,
      issues,
      status,
    };
  });
}

export function BulkImportPanel({ products, warehouses, orgSlug }: Props) {
  const qc = useQueryClient();
  const addReceive = useInventoryStore((s) => s.addReceive);
  const logAudit = useAuditStore((s) => s.log);
  const user = getSession();

  const [open, setOpen] = useState(false);
  const [csvText, setCsvText] = useState("");
  const [parsedRows, setParsedRows] = useState<ParsedRow[] | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [importRef, setImportRef] = useState("");
  const [loading, setLoading] = useState(false);

  function reset() {
    setCsvText("");
    setParsedRows(null);
    setError("");
    setSuccess("");
    setImportRef("");
  }

  function handleValidate() {
    setError("");
    setParsedRows(null);

    const lines = csvText
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l.length > 0);

    if (lines.length === 0) {
      setError("Please paste CSV data before validating.");
      return;
    }

    // Skip header row if it matches the template
    const firstLine = lines[0]?.toLowerCase() ?? "";
    const dataLines =
      firstLine.startsWith("warehouse_code") || firstLine.startsWith("warehouse code")
        ? lines.slice(1)
        : lines;

    if (dataLines.length === 0) {
      setError("No data rows found. Please include at least one data row after the header.");
      return;
    }

    const rawRows = dataLines.map((l) => parseCsvLine(l));
    const validated = validateRows(rawRows, products, warehouses);
    setParsedRows(validated);
  }

  const handleSubmit = async () => {
    if (!user) { setError("No session found — please log in again."); return; }
    if (!parsedRows || parsedRows.length === 0) { setError("Please validate the data first."); return; }

    const hasErrors = parsedRows.some((r) => r.status === "ERROR");
    if (hasErrors) { setError("Fix all ERROR rows before submitting."); return; }

    setLoading(true);
    setError("");

    try {
      const submittableRows = parsedRows.filter(
        (r) => r.status === "VALID" || r.status === "WARNING"
      );

      const payload = {
        rows: submittableRows.map((r) => ({
          row_number:         r.rowNumber,
          warehouse_code:     r.warehouseCode,
          warehouse_id:       r.warehouseId,
          sku_code:           r.skuCode,
          product_id:         r.productId,
          opening_quantity:   r.openingQuantity,
          uom:                r.uom,
          batch_number:       r.batchNumber,
          manufacture_date:   r.manufactureDate,
          expiry_date:        r.expiryDate,
          notes:              r.notes,
          reference_document: r.referenceDocument,
          idempotency_key:    r.idempotencyKey,
          status:             r.status,
          errors:             r.issues.filter((i) => i.severity === "ERROR").map((i) => i.message),
          warnings:           r.issues.filter((i) => i.severity === "WARNING").map((i) => i.message),
        })),
      };

      const batch = await api.post<ImportBatch>("/api/v1/imports/opening-balance", payload);

      // Update Zustand store balances immediately for valid rows
      for (const row of submittableRows) {
        if (row.productId && row.warehouseId && row.openingQuantity > 0) {
          addReceive(row.productId, row.warehouseId, row.openingQuantity);
        }
      }

      logAudit({
        tenantSlug:   orgSlug,
        userEmail:    user.email,
        userName:     user.name,
        role:         user.role,
        action:       "inventory:bulk_import",
        category:     "INVENTORY",
        resourceRef:  batch.reference,
        resourceType: "ImportBatch",
        notes:        `Import ref: ${batch.reference}`,
      });

      void qc.invalidateQueries({ queryKey: ["products", orgSlug] });

      setImportRef(batch.reference);
      setSuccess(
        `Import batch submitted — ref: ${batch.reference}. Status: PENDING_APPROVAL. ` +
        `${submittableRows.length} rows queued. Submit this reference to your National Manager for review and approval before the batch is posted to the ledger.`
      );
      setCsvText("");
      setParsedRows(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to submit import batch.");
    } finally {
      setLoading(false);
    }
  };

  if (!user) return null;

  // Computed summary
  const totalRows   = parsedRows?.length ?? 0;
  const validRows   = parsedRows?.filter((r) => r.status === "VALID").length ?? 0;
  const errorRows   = parsedRows?.filter((r) => r.status === "ERROR").length ?? 0;
  const warningRows = parsedRows?.filter((r) => r.status === "WARNING").length ?? 0;
  const uniqueSkus  = parsedRows
    ? new Set(parsedRows.map((r) => r.skuCode).filter(Boolean)).size
    : 0;
  const uniqueWhs   = parsedRows
    ? new Set(parsedRows.map((r) => r.warehouseCode).filter(Boolean)).size
    : 0;
  const hasErrors   = errorRows > 0;

  return (
    <>
      <button
        onClick={() => { reset(); setOpen(true); }}
        style={{
          padding: "8px 16px",
          background: "#7C3AED",
          color: "#fff",
          fontWeight: 700,
          fontSize: 13,
          borderRadius: 4,
          border: "none",
          cursor: "pointer",
        }}
      >
        ↑ Bulk Import
      </button>

      {/* Backdrop */}
      {open && (
        <div
          onClick={() => setOpen(false)}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.35)",
            zIndex: 100,
            backdropFilter: "blur(2px)",
          }}
        />
      )}

      {/* Slide-in panel */}
      <div
        style={{
          position: "fixed",
          top: 0,
          right: open ? 0 : -PANEL_W,
          width: PANEL_W,
          height: "100vh",
          background: "#fff",
          zIndex: 110,
          boxShadow: "-4px 0 24px rgba(0,0,0,0.18)",
          transition: "right 0.25s cubic-bezier(0.4,0,0.2,1)",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "1.25rem 1.5rem",
            background: "#7C3AED",
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
          }}
        >
          <div>
            <p style={{ fontWeight: 700, fontSize: 16, color: "#fff", margin: 0 }}>
              Bulk Import — Opening Balances
            </p>
            <p style={{ fontSize: 12, color: "#DDD6FE", margin: "2px 0 0" }}>
              Paste CSV data to initialise multiple products in one batch
            </p>
            <p
              style={{
                fontSize: 10,
                color: "#C4B5FD",
                margin: "4px 0 0",
                fontFamily: "monospace",
                letterSpacing: "0.03em",
              }}
            >
              SUBMITTED → PENDING_APPROVAL → POSTED
            </p>
          </div>
          <button
            onClick={() => setOpen(false)}
            style={{
              background: "rgba(255,255,255,0.1)",
              border: "none",
              cursor: "pointer",
              color: "#fff",
              fontSize: 18,
              width: 32,
              height: 32,
              borderRadius: 4,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: "auto", padding: "1.5rem" }}>

          {/* Success state */}
          {success && (
            <div
              style={{
                background: "#F5F3FF",
                border: "1px solid #DDD6FE",
                borderRadius: 6,
                padding: "14px 16px",
                fontSize: 13,
                color: "#5B21B6",
                marginBottom: 16,
                lineHeight: 1.6,
              }}
            >
              <p style={{ fontWeight: 700, marginBottom: 6, fontSize: 14 }}>
                ✓ Import Batch Submitted
              </p>
              <p style={{ margin: "0 0 8px" }}>
                <strong>Reference:</strong>{" "}
                <span style={{ fontFamily: "monospace", fontSize: 12 }}>{importRef}</span>
              </p>
              <p style={{ margin: 0, fontSize: 12 }}>{success}</p>
            </div>
          )}

          {/* Template section */}
          <div style={{ marginBottom: 20 }}>
            <p
              style={{
                fontSize: 12,
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                color: "#374151",
                marginBottom: 8,
              }}
            >
              CSV Template Columns
            </p>
            <div
              style={{
                background: "#F9FAFB",
                border: "1px solid #E5E7EB",
                borderRadius: 4,
                padding: "10px 12px",
                fontFamily: "monospace",
                fontSize: 11,
                color: "#374151",
                lineHeight: 1.8,
                whiteSpace: "pre-wrap",
                wordBreak: "break-all",
              }}
            >
              <span style={{ color: "#7C3AED", fontWeight: 700 }}>Header:</span>{" "}
              {TEMPLATE_HEADER}
              {"\n"}
              <span style={{ color: "#059669", fontWeight: 700 }}>Examples:</span>
              {"\n"}
              {TEMPLATE_EXAMPLE}
            </div>
            <p style={{ fontSize: 11, color: "#9CA3AF", marginTop: 6, lineHeight: 1.5 }}>
              Columns with * are required. Use the warehouse name or ID for{" "}
              <code style={{ fontSize: 11 }}>warehouse_code</code>. Leave optional columns
              empty but keep the comma delimiter.
            </p>
          </div>

          {/* CSV input */}
          <Field label="Paste CSV Data">
            <textarea
              value={csvText}
              onChange={(e) => { setCsvText(e.target.value); setParsedRows(null); setError(""); setSuccess(""); }}
              placeholder={`Paste your CSV here (with or without header row):\n\n${TEMPLATE_HEADER}\n${TEMPLATE_EXAMPLE}`}
              rows={8}
              style={{
                width: "100%",
                padding: "10px",
                fontSize: 12,
                fontFamily: "monospace",
                border: "1px solid #D1D5DB",
                borderRadius: 4,
                outline: "none",
                background: "#fff",
                boxSizing: "border-box",
                resize: "vertical",
                lineHeight: 1.5,
              }}
            />
          </Field>

          <button
            type="button"
            onClick={handleValidate}
            disabled={!csvText.trim()}
            style={{
              width: "100%",
              padding: "10px",
              background: csvText.trim() ? "#374151" : "#E5E7EB",
              color: csvText.trim() ? "#fff" : "#9CA3AF",
              fontWeight: 700,
              fontSize: 13,
              borderRadius: 4,
              border: "none",
              cursor: csvText.trim() ? "pointer" : "not-allowed",
              marginBottom: 20,
            }}
          >
            Validate Data
          </button>

          {/* Error banner */}
          {error && (
            <div
              style={{
                background: "#FEF2F2",
                border: "1px solid #FECACA",
                borderRadius: 4,
                padding: "10px 12px",
                fontSize: 13,
                color: "#DC2626",
                marginBottom: 16,
              }}
            >
              {error}
            </div>
          )}

          {/* Validation report */}
          {parsedRows && parsedRows.length > 0 && (
            <>
              {/* Summary */}
              <div
                style={{
                  background: "#F9FAFB",
                  border: "1px solid #E5E7EB",
                  borderRadius: 6,
                  padding: "12px 14px",
                  marginBottom: 16,
                  fontSize: 12,
                }}
              >
                <p
                  style={{
                    fontWeight: 700,
                    fontSize: 13,
                    color: "#111827",
                    margin: "0 0 8px",
                    textTransform: "uppercase",
                    letterSpacing: "0.04em",
                  }}
                >
                  Validation Summary
                </p>
                <table style={{ width: "100%", fontSize: 12 }}>
                  <tbody>
                    {[
                      ["Total rows", totalRows, "#374151"],
                      ["Valid rows", validRows, "#059669"],
                      [`Error rows (blocked)`, errorRows, "#DC2626"],
                      ["Warning rows", warningRows, "#D97706"],
                      ["Unique SKUs", uniqueSkus, "#374151"],
                      ["Unique warehouses", uniqueWhs, "#374151"],
                    ].map(([label, val, color]) => (
                      <tr key={String(label)}>
                        <td style={{ padding: "2px 0", color: "#6B7280" }}>{label}:</td>
                        <td
                          style={{
                            padding: "2px 0",
                            textAlign: "right",
                            fontWeight: 700,
                            color: String(color),
                          }}
                        >
                          {String(val)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Row-by-row report */}
              <div style={{ marginBottom: 16 }}>
                <p
                  style={{
                    fontWeight: 700,
                    fontSize: 12,
                    color: "#374151",
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    marginBottom: 8,
                  }}
                >
                  Row Validation Report
                </p>
                <div
                  style={{
                    border: "1px solid #E5E7EB",
                    borderRadius: 6,
                    overflow: "hidden",
                  }}
                >
                  {parsedRows.map((row, idx) => {
                    const rowBg =
                      row.status === "ERROR"
                        ? "#FEF2F2"
                        : row.status === "WARNING"
                        ? "#FFFBEB"
                        : idx % 2 === 0
                        ? "#fff"
                        : "#F9FAFB";
                    const statusColor =
                      row.status === "ERROR"
                        ? "#DC2626"
                        : row.status === "WARNING"
                        ? "#D97706"
                        : "#059669";
                    const statusIcon =
                      row.status === "ERROR" ? "✗" : row.status === "WARNING" ? "⚠" : "✓";

                    return (
                      <div
                        key={row.rowNumber}
                        style={{
                          background: rowBg,
                          borderBottom:
                            idx < parsedRows.length - 1 ? "1px solid #E5E7EB" : "none",
                          padding: "8px 12px",
                        }}
                      >
                        {/* Row header */}
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                            marginBottom: row.issues.length > 0 ? 4 : 0,
                          }}
                        >
                          <span
                            style={{
                              fontWeight: 700,
                              color: statusColor,
                              fontSize: 13,
                              minWidth: 16,
                            }}
                          >
                            {statusIcon}
                          </span>
                          <span
                            style={{
                              fontFamily: "monospace",
                              fontSize: 11,
                              color: "#6B7280",
                              minWidth: 52,
                            }}
                          >
                            ROW {row.rowNumber}
                          </span>
                          <span style={{ fontSize: 12, color: "#374151", fontWeight: 600 }}>
                            {row.skuCode || "—"}
                          </span>
                          <span style={{ fontSize: 11, color: "#9CA3AF" }}>
                            @ {row.warehouseCode || "—"}
                          </span>
                          {row.productName && (
                            <span style={{ fontSize: 11, color: "#6B7280" }}>
                              · {row.productName}
                            </span>
                          )}
                          <span
                            style={{
                              marginLeft: "auto",
                              fontSize: 11,
                              fontWeight: 700,
                              color: "#374151",
                            }}
                          >
                            {row.openingQuantity > 0
                              ? `${row.openingQuantity.toLocaleString()} ${row.uom}`
                              : ""}
                          </span>
                        </div>

                        {/* Issues */}
                        {row.issues.map((issue, iIdx) => (
                          <div
                            key={iIdx}
                            style={{
                              fontFamily: "monospace",
                              fontSize: 11,
                              color: issue.severity === "ERROR" ? "#DC2626" : "#92400E",
                              marginLeft: 24,
                              lineHeight: 1.6,
                            }}
                          >
                            ROW [{row.rowNumber}] | FIELD: {issue.field} | SEVERITY:{" "}
                            {issue.severity} | MESSAGE: {issue.message}
                          </div>
                        ))}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Submit button */}
              <button
                type="button"
                onClick={handleSubmit}
                disabled={hasErrors || loading}
                style={{
                  width: "100%",
                  padding: "11px",
                  fontWeight: 700,
                  fontSize: 13,
                  borderRadius: 4,
                  border: "none",
                  cursor: hasErrors || loading ? "not-allowed" : "pointer",
                  background: hasErrors ? "#E5E7EB" : "#7C3AED",
                  color: hasErrors ? "#9CA3AF" : "#fff",
                  opacity: loading ? 0.7 : 1,
                  marginBottom: 8,
                }}
              >
                {loading
                  ? "Submitting…"
                  : hasErrors
                  ? `Cannot Submit — ${errorRows} error row${errorRows !== 1 ? "s" : ""} must be fixed`
                  : `Submit Import (${validRows + warningRows} row${validRows + warningRows !== 1 ? "s" : ""})`}
              </button>

              {hasErrors && (
                <p
                  style={{
                    fontSize: 11,
                    color: "#DC2626",
                    textAlign: "center",
                    margin: 0,
                  }}
                >
                  Fix all ERROR rows in your CSV and re-validate before submitting.
                </p>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: "0.875rem 1.5rem",
            borderTop: "1px solid #E5E7EB",
            display: "flex",
            gap: 10,
          }}
        >
          <button
            type="button"
            onClick={() => { reset(); setOpen(false); }}
            style={{
              flex: 1,
              padding: "10px",
              background: "#F3F4F6",
              border: "1px solid #E5E7EB",
              borderRadius: 4,
              fontSize: 13,
              fontWeight: 600,
              color: "#374151",
              cursor: "pointer",
            }}
          >
            Close
          </button>
          {parsedRows && !hasErrors && !success && (
            <button
              type="button"
              onClick={handleSubmit}
              disabled={loading}
              style={{
                flex: 2,
                padding: "10px",
                fontWeight: 700,
                fontSize: 13,
                borderRadius: 4,
                border: "none",
                cursor: loading ? "not-allowed" : "pointer",
                background: "#7C3AED",
                color: "#fff",
                opacity: loading ? 0.7 : 1,
              }}
            >
              {loading ? "Submitting…" : `Submit Import`}
            </button>
          )}
        </div>
      </div>
    </>
  );
}
