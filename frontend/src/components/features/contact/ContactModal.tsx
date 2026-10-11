"use client";

import { useEffect, useRef } from "react";
import { useContactInfo } from "@/hooks/useContactInfo";
import { ContactDetailsView } from "@/components/features/auth/ContactDetailsView";
import { t, getCurrentLocale } from "@/lib/i18n";
import { ContactInfo } from "@/lib/billing-types";

const NOT_CONFIGURED: ContactInfo = {
  configured: false,
  support_email: null,
  phone: null,
  whatsapp: null,
  address: { en: null, am: null },
  hours: { en: null, am: null },
  note: { en: null, am: null },
  updated_at: "",
};

interface ContactModalProps {
  open: boolean;
  onClose: () => void;
}

/**
 * In-app "Contact SMART" modal — same ContactDetailsView/useContactInfo data
 * as the public /contact page, details only (no Getting started/Sign up
 * links), so an in-app placement never navigates a signed-in user out of
 * the app. Follows the PlanComparisonModal pattern/styling.
 */
export function ContactModal({ open, onClose }: ContactModalProps) {
  const closeBtnRef = useRef<HTMLButtonElement>(null);
  const triggerRef = useRef<HTMLElement | null>(null);
  const { contact, isLoading } = useContactInfo();
  const locale = getCurrentLocale();

  useEffect(() => {
    if (open) {
      triggerRef.current = document.activeElement as HTMLElement | null;
      closeBtnRef.current?.focus();
    } else {
      triggerRef.current?.focus?.();
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("contact.title")}
        onClick={(e) => e.stopPropagation()}
        className="bg-white rounded-xl shadow-2xl w-full max-w-md max-h-[90vh] overflow-y-auto p-6"
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-gray-900">{t("contact.title")}</h2>
          <button
            ref={closeBtnRef}
            type="button"
            onClick={onClose}
            aria-label={t("common.close")}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none px-2"
          >
            ×
          </button>
        </div>

        {isLoading ? (
          <p className="text-sm text-gray-400 py-4 text-center">{t("common.loading")}</p>
        ) : (
          <ContactDetailsView contact={contact ?? NOT_CONFIGURED} locale={locale} />
        )}

        <div className="flex justify-end mt-6">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded hover:bg-gray-200"
          >
            {t("common.close")}
          </button>
        </div>
      </div>
    </div>
  );
}
