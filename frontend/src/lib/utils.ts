import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/**
 * Format a stock/adjustment quantity for display.
 * Whole numbers (22.0) → "22"   Decimals (22.5) → "22.5"   Large (1000) → "1,000"
 */
export function formatQty(qty: number): string {
  if (Number.isInteger(qty)) return qty.toLocaleString();
  return parseFloat(qty.toFixed(2)).toLocaleString();
}
