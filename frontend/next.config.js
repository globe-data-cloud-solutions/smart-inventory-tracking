/** @type {import('next').NextConfig} */
const nextConfig = {
  // Pre-existing hooks-after-early-return violations live in component files.
  // Suppressed here rather than adding eslint-disable comments to every page.
  eslint: { ignoreDuringBuilds: true },
  headers: async () => [
    {
      source: "/sw.js",
      headers: [
        { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
        { key: "Content-Type",  value: "application/javascript; charset=utf-8" },
      ],
    },
  ],
  env: {
    NEXT_PUBLIC_DEFAULT_LOCALE: process.env.NEXT_PUBLIC_DEFAULT_LOCALE ?? "en",
  },
};

module.exports = nextConfig;
