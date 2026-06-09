import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function formatQty(qty: number | string | null | undefined): string {
  const n = Number(qty);
  if (!isFinite(n)) return "0";
  if (Number.isInteger(n)) return n.toLocaleString();
  return parseFloat(n.toFixed(2)).toLocaleString();
}

export function formatCurrency(value: number | string | null | undefined, currency = "ETB"): string {
  const n = Number(value);
  if (!isFinite(n)) return `0.00 ${currency}`;
  return (
    new Intl.NumberFormat("en-ET", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n) +
    " " +
    currency
  );
}
