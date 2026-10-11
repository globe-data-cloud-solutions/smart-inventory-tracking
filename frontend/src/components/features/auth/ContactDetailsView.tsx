"use client";

import { ContactInfo, pickLocalized } from "@/lib/billing-types";
import { t } from "@/lib/i18n";

/**
 * Renders the configured contact fields for a given locale — shared by the
 * public /contact page and the SA editor's live preview panel so both stay
 * in sync by construction.
 */
export function ContactDetailsView({ contact, locale }: { contact: ContactInfo; locale: string }) {
  const whatsappDigits = contact.whatsapp ? contact.whatsapp.replace(/[^0-9]/g, "") : null;
  const address = pickLocalized(contact.address, locale);
  const hours = pickLocalized(contact.hours, locale);
  const note = pickLocalized(contact.note, locale);

  if (!contact.configured) {
    return <p className="text-sm text-gray-600">{t("contact.coming_soon")}</p>;
  }

  return (
    <div className="space-y-3">
      {contact.support_email && (
        <p className="text-sm text-gray-700 m-0">
          <span className="font-semibold text-gray-500">{t("contact.email_label")}: </span>
          <a href={`mailto:${contact.support_email}`} className="text-brand-600 hover:text-brand-700">
            {contact.support_email}
          </a>
        </p>
      )}
      {contact.phone && (
        <p className="text-sm text-gray-700 m-0">
          <span className="font-semibold text-gray-500">{t("contact.phone_label")}: </span>
          <a href={`tel:${contact.phone}`} className="text-brand-600 hover:text-brand-700">
            {contact.phone}
          </a>
        </p>
      )}
      {contact.whatsapp && whatsappDigits && (
        <p className="text-sm text-gray-700 m-0">
          <span className="font-semibold text-gray-500">{t("contact.whatsapp_label")}: </span>
          <a
            href={`https://wa.me/${whatsappDigits}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-brand-600 hover:text-brand-700"
          >
            {contact.whatsapp}
          </a>
        </p>
      )}
      {address && (
        <p className="text-sm text-gray-700 m-0">
          <span className="font-semibold text-gray-500">{t("contact.address_label")}: </span>
          {address}
        </p>
      )}
      {hours && (
        <p className="text-sm text-gray-700 m-0">
          <span className="font-semibold text-gray-500">{t("contact.hours_label")}: </span>
          {hours}
        </p>
      )}
      {note && <p className="text-sm text-gray-500 italic m-0">{note}</p>}
    </div>
  );
}
