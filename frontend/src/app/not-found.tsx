import Link from "next/link";
import { t } from "@/lib/i18n";

export default function NotFound() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 text-center bg-eth-forest">
      <div className="mb-6">
        <svg width="56" height="56" viewBox="0 0 48 48" fill="none" aria-hidden="true">
          <rect width="48" height="48" rx="10" fill="#FCDD09" />
          <path d="M24 6L42 15V27L24 36L6 27V15Z" fill="#12291E" />
          <path d="M24 13L36 19.5V27L24 33L12 27V19.5Z" fill="#FCDD09" />
          <path d="M24 20L30 23.5V27L24 30L18 27V23.5Z" fill="#12291E" />
        </svg>
      </div>

      <h1 className="text-6xl font-extrabold text-white mb-2">404</h1>
      <p className="text-xl font-semibold text-green-200 mb-2">{t("not_found.heading")}</p>
      <p className="text-green-400 text-sm mb-8 max-w-sm">{t("not_found.description")}</p>

      <div className="flex gap-3">
        <Link
          href="/login"
          className="px-6 py-3 font-bold text-sm bg-eth-gold text-[#12291E] rounded no-underline"
        >
          {t("not_found.sign_in")}
        </Link>
        <Link
          href="/"
          className="px-6 py-3 font-semibold text-sm border-2 border-white/30 text-white hover:bg-white/10 transition rounded no-underline"
        >
          {t("not_found.home")}
        </Link>
      </div>

      {/* i18n-ignore: brand name */}
      <p className="mt-8 text-xs text-green-700">SMART Inventory Tracker</p>
    </div>
  );
}
