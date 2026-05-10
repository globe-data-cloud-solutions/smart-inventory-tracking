import Link from "next/link";

export default function NotFound() {
  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center px-4 text-center"
      style={{ background: "#1B4332" }}
    >
      <div className="mb-6">
        <svg width="56" height="56" viewBox="0 0 48 48" fill="none" aria-hidden="true">
          <rect width="48" height="48" rx="10" fill="#FCDD09" />
          <path d="M24 6L42 15V27L24 36L6 27V15Z" fill="#12291E" />
          <path d="M24 13L36 19.5V27L24 33L12 27V19.5Z" fill="#FCDD09" />
          <path d="M24 20L30 23.5V27L24 30L18 27V23.5Z" fill="#12291E" />
        </svg>
      </div>

      <h1 className="text-6xl font-extrabold text-white mb-2">404</h1>
      <p className="text-xl font-semibold text-green-200 mb-2">Page not found</p>
      <p className="text-green-400 text-sm mb-8 max-w-sm">
        This page doesn't exist or your session expired. Sign in to continue.
      </p>

      <div className="flex gap-3">
        <Link
          href="/login"
          className="px-6 py-3 font-bold text-sm"
          style={{ background: "#FCDD09", color: "#12291E", borderRadius: 4 }}
        >
          Sign in →
        </Link>
        <Link
          href="/"
          className="px-6 py-3 font-semibold text-sm border-2 border-white/30 text-white hover:bg-white/10 transition"
          style={{ borderRadius: 4 }}
        >
          Home
        </Link>
      </div>

      <p className="mt-8 text-xs text-green-700">SMART Inventory Tracker</p>
    </div>
  );
}
