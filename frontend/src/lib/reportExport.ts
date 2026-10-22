// CSV export of the table a report already shows (2026-10-22). The file contains
// exactly the text on screen: same labels, same formatting, nothing extra.

export function csvCell(value: string | number): string {
  const text = String(value);
  // Quote anything with a delimiter, quote or line break; double the quotes.
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function toCsv(headers: string[], rows: (string | number)[][]): string {
  const lines = [headers, ...rows].map((line) => line.map(csvCell).join(","));
  // BOM so Excel reads the file as UTF-8 (Amharic and Oromo labels).
  return "﻿" + lines.join("\r\n") + "\r\n";
}

export function downloadCsv(fileName: string, csv: string): void {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function exportFileName(base: string, date: Date = new Date()): string {
  const day = date.toISOString().slice(0, 10);
  return `${base}-${day}.csv`;
}
