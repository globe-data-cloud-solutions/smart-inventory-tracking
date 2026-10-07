/**
 * Help & Documents manifest (CLAUDE.md §15 S12).
 *
 * Content for a "file" entry lives in frontend/public/help/*.md — everything
 * under frontend/public is readable without login, so NEVER point `file` at
 * anything SA-internal. The SA Operations Manual below has no `file` for
 * exactly this reason: when it's written, it must be served by an
 * authenticated backend route, not a public static file.
 */

export type Audience = "SA" | "TA" | "MANAGER" | "STAFF" | "ALL";

export interface HelpDoc {
  id: string;
  titleKey: string;
  summaryKey: string;
  audience: Audience[];
  /** Filename under frontend/public/help/ — rendered at /[org]/help/[docId]. */
  file?: string;
  /** External path (e.g. /terms) — the card links straight there instead of /help/[docId]. */
  link?: string;
  status: "published" | "coming_soon";
  version?: string;
  updated?: string;
}

export const HELP_MANIFEST: HelpDoc[] = [
  {
    id: "ta-onboarding-guide",
    titleKey: "help.doc.ta_onboarding_guide.title",
    summaryKey: "help.doc.ta_onboarding_guide.summary",
    audience: ["TA"],
    file: "ta-onboarding-guide.md",
    status: "published",
    version: "1.3",
    updated: "2026-10",
  },
  {
    id: "terms",
    titleKey: "help.doc.terms.title",
    summaryKey: "help.doc.terms.summary",
    audience: ["ALL"],
    link: "/terms",
    status: "published",
  },
  {
    id: "privacy",
    titleKey: "help.doc.privacy.title",
    summaryKey: "help.doc.privacy.summary",
    audience: ["ALL"],
    link: "/privacy",
    status: "published",
  },
  {
    id: "sa-operations-manual",
    titleKey: "help.doc.sa_operations_manual.title",
    summaryKey: "help.doc.sa_operations_manual.summary",
    audience: ["SA"],
    status: "coming_soon",
  },
  {
    id: "warehouse-manager-guide",
    titleKey: "help.doc.warehouse_manager_guide.title",
    summaryKey: "help.doc.warehouse_manager_guide.summary",
    audience: ["MANAGER"],
    status: "coming_soon",
  },
  {
    id: "staff-quick-guide",
    titleKey: "help.doc.staff_quick_guide.title",
    summaryKey: "help.doc.staff_quick_guide.summary",
    audience: ["STAFF"],
    status: "coming_soon",
  },
  {
    id: "release-notes",
    titleKey: "help.doc.release_notes.title",
    summaryKey: "help.doc.release_notes.summary",
    audience: ["ALL"],
    status: "coming_soon",
  },
];

/** NM/RM/WM/LM -> MANAGER; SA -> SA; TA -> TA; everyone else -> STAFF. */
export function roleToAudience(role: string): Audience {
  if (role === "SA") return "SA";
  if (role === "TA") return "TA";
  if (role === "NM" || role === "RM" || role === "WM" || role === "LM") return "MANAGER";
  return "STAFF";
}

/** SA sees every document, regardless of audience (CLAUDE.md §15 S12). */
export function isDocVisibleToRole(doc: HelpDoc, role: string): boolean {
  if (role === "SA") return true;
  if (doc.audience.includes("ALL")) return true;
  return doc.audience.includes(roleToAudience(role));
}

export function getHelpDoc(id: string): HelpDoc | undefined {
  return HELP_MANIFEST.find((d) => d.id === id);
}
