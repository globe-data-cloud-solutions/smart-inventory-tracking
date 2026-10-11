"use client";

import Link from "next/link";
import { useContactInfo } from "@/hooks/useContactInfo";
import { t } from "@/lib/i18n";

/**
 * Shared "Contact SMART" link for public and in-app placements — renders
 * nothing until the platform contact details are configured (CLAUDE.md §29
 * "never add mock/demo data to make a screen work"; demo mode is also
 * treated as not configured, see useContactInfo).
 *
 * Public placements navigate to /contact (the default). In-app placements
 * pass `onClick` (e.g. to open ContactModal) so a signed-in user is never
 * routed out of the app.
 */
export function PublicContactLink({
  className,
  prefix,
  labelKey = "contact.footer_link",
  onClick,
}: { className?: string; prefix?: string; labelKey?: string; onClick?: () => void }) {
  const { contact } = useContactInfo();
  if (!contact?.configured) return null;

  return (
    <>
      {prefix}
      {onClick ? (
        <button type="button" onClick={onClick} className={className}>
          {t(labelKey)}
        </button>
      ) : (
        <Link href="/contact" className={className}>
          {t(labelKey)}
        </Link>
      )}
    </>
  );
}
