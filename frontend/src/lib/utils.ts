import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function formatQty(qty: number | string | null | undefined): string {
  if (qty === null || qty === undefined || qty === "") return "0";
  const s = String(qty);
  const n = parseFloat(s);
  if (!isFinite(n)) return "0";
  const dotIdx = s.indexOf(".");
  if (dotIdx === -1 || Math.floor(n) === n) return Math.floor(n).toLocaleString();
  const decimals = s.slice(dotIdx + 1).replace(/0+$/, "");
  if (!decimals) return Math.floor(n).toLocaleString();
  const rounded = parseFloat(n.toFixed(2));
  const whole = Math.floor(Math.abs(rounded));
  const sign = rounded < 0 ? "-" : "";
  const dec = String(Math.round(Math.abs(rounded) * 100) % 100).padStart(2, "0").replace(/0+$/, "");
  return dec ? `${sign}${whole.toLocaleString()}.${dec}` : `${sign}${whole.toLocaleString()}`;
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
