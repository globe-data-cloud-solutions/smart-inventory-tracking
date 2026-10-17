import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";

const inter = Inter({ subsets: ["latin"], display: "swap" });

export const metadata: Metadata = {
  title: "SMART Inventory Tracker",
  description: "Multi-tenant inventory management platform",
  manifest: "/manifest.json",
};

export const viewport: Viewport = {
  themeColor: "#1B4332",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link rel="manifest" href="/manifest.json" />
      </head>
      <body className={`${inter.className} min-h-screen bg-gray-50 antialiased`}>
        <Providers>{children}</Providers>
        <script
          dangerouslySetInnerHTML={{
            // NODE_ENV is inlined at build time. sw.js serves /_next/static/* cache-first, which is
            // safe for hashed production chunks; in dev the chunk names never change, so a browser
            // would keep running stale JS. Dev therefore removes any leftover worker and its caches.
            __html: process.env.NODE_ENV === "production"
              ? `
              if ('serviceWorker' in navigator) {
                window.addEventListener('load', () => {
                  navigator.serviceWorker.register('/sw.js');
                });
              }
            `
              : `
              if ('serviceWorker' in navigator) {
                // An unregistered worker keeps controlling (and re-filling caches for) this page
                // until it navigates, so reload once when one is controlling it.
                const controlled = !!navigator.serviceWorker.controller;
                navigator.serviceWorker.getRegistrations()
                  .then((regs) => Promise.all(regs.map((r) => r.unregister())))
                  .then(() => (window.caches ? caches.keys() : []))
                  .then((keys) => Promise.all(
                    keys.filter((k) => k.startsWith('smart-')).map((k) => caches.delete(k))
                  ))
                  .then(() => { if (controlled) window.location.reload(); })
                  .catch(() => {});
              }
            `,
          }}
        />
      </body>
    </html>
  );
}
