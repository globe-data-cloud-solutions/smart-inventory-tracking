"use client";

import Link from "next/link";
import { useContactInfo } from "@/hooks/useContactInfo";
import { t } from "@/lib/i18n";

/**
 * Shared "Contact SMART" link for public and in-app placements — renders
 * nothing until the platform contact details are configured (CLAUDE.md §29
 * "never add mock/demo data to make a screen work"; demo mode is also
 * treated as not configured, see useContactInfo).
 */
export function PublicContactLink({
  className,
  prefix,
  labelKey = "contact.footer_link",
}: { className?: string; prefix?: string; labelKey?: string }) {
  const { contact } = useContactInfo();
  if (!contact?.configured) return null;

  return (
    <>
      {prefix}
      <Link href="/contact" className={className}>
        {t(labelKey)}
      </Link>
    </>
  );
}
