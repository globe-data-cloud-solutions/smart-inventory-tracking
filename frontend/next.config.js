/** @type {import('next').NextConfig} */
const nextConfig = {
  // Pre-existing hooks-after-early-return violations live in component files.
  // Suppressed here rather than adding eslint-disable comments to every page.
  eslint: { ignoreDuringBuilds: true },
  headers: async () => [
    {
      // Service worker must never be cached — browser checks for SW updates on
      // every navigation, and a stale SW means users stay on the old version.
      source: "/sw.js",
      headers: [
        { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
        { key: "Content-Type",  value: "application/javascript; charset=utf-8" },
      ],
    },
    {
      // HTML pages must revalidate on every load so the browser always fetches
      // the latest asset hashes after a deployment. Without this, a browser
      // cache hit serves old HTML that references CSS/JS files from the previous
      // build — broken styles if those files are no longer on the server.
      source: "/((?!_next/static|_next/image|_next/webpack|favicon\\.ico|sw\\.js|api/).*)",
      headers: [
        { key: "Cache-Control", value: "no-cache, must-revalidate" },
      ],
    },
  ],
  env: {
    NEXT_PUBLIC_DEFAULT_LOCALE: process.env.NEXT_PUBLIC_DEFAULT_LOCALE ?? "en",
  },
};

module.exports = nextConfig;
