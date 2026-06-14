"use client";

import { t } from "@/lib/i18n";
import { formatQty } from "@/lib/utils";
import type { ProductApprovalOverride } from "@/lib/demo-data";

export type ProductTransactionType = "PULL" | "PUSH" | "SISTER" | "ADJUSTMENT" | "RECEIVE" | "ISSUE";

// Builds the lock-icon tooltip text for a Design-B per-product approval override.
export function buildOverrideTooltip(o: ProductApprovalOverride): string {
  const approver = o.approver_label ?? t("common.unknown");
  let text: string;
  if (o.mode === "QUANTITY") {
    text = t("product.override_quantity")
      .replace("{approver}", approver)
      .replace("{threshold}", formatQty(Number(o.threshold ?? 0)));
  } else if (o.mode === "VALUE") {
    text = t("product.override_value")
      .replace("{approver}", approver)
      .replace("{threshold}", String(o.threshold ?? ""));
  } else {
    text = t("product.override_always")
      .replace("{approver}", approver)
      .replace("{transaction}", t("common.transaction"));
  }
  if (o.note) text += ` — ${o.note}`;
  return text;
}

interface ProductLabelProps {
  name: string;
  isControlled?: boolean;
  approvalOverrides?: Record<string, ProductApprovalOverride>;
  transactionType?: ProductTransactionType;
  className?: string;
}

// Shared 🔒 indicator for controlled (Design-B per-product approval override) products.
// Renders the plain name when the product is not controlled; otherwise appends a 🔒
// with a tooltip describing the override that applies to transactionType (if any),
// falling back to the generic product.controlled_tooltip.
export function ProductLabel({ name, isControlled, approvalOverrides, transactionType, className }: ProductLabelProps) {
  const override = transactionType ? approvalOverrides?.[transactionType] : undefined;
  const controlled = isControlled ?? !!(approvalOverrides && Object.keys(approvalOverrides).length > 0);

  if (!controlled) {
    return <span className={className}>{name}</span>;
  }

  const tooltip = override ? buildOverrideTooltip(override) : t("product.controlled_tooltip");

  return (
    <span className={className}>
      {name}
      <span title={tooltip} className="ml-1.5 text-xs">🔒</span>
    </span>
  );
}
