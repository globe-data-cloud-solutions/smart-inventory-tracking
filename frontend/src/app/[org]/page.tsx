"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";

/**
 * Redirect /{org} → /{org}/dashboard
 *
 * There is no page at the bare /{org} level — the app always shows
 * the dashboard sub-page.  Without this redirect Next.js would render
 * the built-in 404 when someone navigates to /addis-water or /admin
 * without a sub-path (e.g. after a partial page reload or a history-back
 * from a deeper page).
 */
export default function OrgRoot() {
  const { org } = useParams() as { org: string };
  const router  = useRouter();

  useEffect(() => {
    router.replace(`/${org}/dashboard`);
  }, [org, router]);

  return null;
}
