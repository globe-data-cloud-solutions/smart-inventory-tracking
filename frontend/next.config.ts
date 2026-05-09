import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // PWA headers — actual service worker registration is in public/sw.js
  headers: async () => [
    {
      source: "/sw.js",
      headers: [
        { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
        { key: "Content-Type",  value: "application/javascript; charset=utf-8" },
      ],
    },
  ],
  // i18n locale detection — actual language loading is handled client-side via i18n.ts
  env: {
    NEXT_PUBLIC_DEFAULT_LOCALE: process.env.NEXT_PUBLIC_DEFAULT_LOCALE ?? "en",
  },
};

export default nextConfig;
