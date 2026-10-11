"use client";

import Link from "next/link";
import { useContactInfo } from "@/hooks/useContactInfo";
import { t, getCurrentLocale } from "@/lib/i18n";
import { AuthLangSwitcher } from "@/components/features/auth/AuthLangSwitcher";
import { ContactDetailsView } from "@/components/features/auth/ContactDetailsView";
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

export default function ContactPage() {
  const { contact, isLoading } = useContactInfo();
  const locale = getCurrentLocale();

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-brand-900 to-slate-900 flex items-center justify-center p-4 md:p-8">
      <div className="bg-white rounded-2xl shadow-2xl p-6 md:p-8 max-w-lg w-full">
        <div className="flex items-start justify-between mb-4">
          <h1 className="text-2xl font-bold text-gray-900">{t("contact.title")}</h1>
          <AuthLangSwitcher />
        </div>

        {isLoading && <p className="text-sm text-gray-500">{t("common.loading")}</p>}
        {!isLoading && <ContactDetailsView contact={contact ?? NOT_CONFIGURED} locale={locale} />}

        <div className="flex gap-4 mt-6 text-sm">
          <Link href="/getting-started" className="underline text-brand-600 hover:text-brand-700">
            {t("contact.back_getting_started_link")}
          </Link>
          <Link href="/signup" className="underline text-brand-600 hover:text-brand-700">
            {t("contact.back_signup_link")}
          </Link>
        </div>
      </div>
    </div>
  );
}
