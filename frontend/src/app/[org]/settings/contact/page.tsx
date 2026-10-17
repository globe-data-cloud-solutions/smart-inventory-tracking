"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getSession } from "@/lib/demo-auth";
import { t, getCurrentLocale } from "@/lib/i18n";
import { api, publicGet } from "@/lib/api";
import { ContactInfo } from "@/lib/billing-types";
import { ContactDetailsView } from "@/components/features/auth/ContactDetailsView";

interface ContactForm {
  support_email: string;
  phone: string;
  whatsapp: string;
  address_en: string;
  address_am: string;
  hours_en: string;
  hours_am: string;
  note_en: string;
  note_am: string;
}

const EMPTY_FORM: ContactForm = {
  support_email: "", phone: "", whatsapp: "",
  address_en: "", address_am: "", hours_en: "", hours_am: "", note_en: "", note_am: "",
};

const KNOWN_ERROR_CODES = new Set(["REASON_REQUIRED", "INVALID_PHONE", "INVALID_EMAIL", "FIELD_TOO_LONG"]);

function errorMessage(e: unknown): string {
  const code = (e as { code?: string } | undefined)?.code;
  if (code && KNOWN_ERROR_CODES.has(code)) return t(`platform_contact.error.${code}`);
  return t("platform_contact.error_generic");
}

function formToPreview(form: ContactForm): ContactInfo {
  return {
    configured: !!(form.support_email || form.phone),
    support_email: form.support_email || null,
    phone: form.phone || null,
    whatsapp: form.whatsapp || null,
    address: { en: form.address_en || null, am: form.address_am || null },
    hours: { en: form.hours_en || null, am: form.hours_am || null },
    note: { en: form.note_en || null, am: form.note_am || null },
    updated_at: "",
  };
}

export default function PlatformContactPage() {
  const session = getSession();

  if (!session || session.role !== "SA") {
    return <p className="p-8 text-gray-500">{t("platform_contact.restricted")}</p>;
  }

  return <PlatformContactEditor />;
}

function PlatformContactEditor() {
  const qc = useQueryClient();
  const { data, isLoading, isError } = useQuery<ContactInfo>({
    queryKey: ["public-contact"],
    queryFn: () => publicGet<ContactInfo>("/api/v1/tenants/public/contact"),
    staleTime: 0,
  });

  const [form, setForm] = useState<ContactForm>(EMPTY_FORM);
  const [reason, setReason] = useState("");
  const [previewLocale, setPreviewLocale] = useState<"en" | "am">(getCurrentLocale() === "am" ? "am" : "en");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const initialized = useRef(false);

  useEffect(() => {
    if (data && !initialized.current) {
      setForm({
        support_email: data.support_email ?? "",
        phone: data.phone ?? "",
        whatsapp: data.whatsapp ?? "",
        address_en: data.address.en ?? "",
        address_am: data.address.am ?? "",
        hours_en: data.hours.en ?? "",
        hours_am: data.hours.am ?? "",
        note_en: data.note.en ?? "",
        note_am: data.note.am ?? "",
      });
      initialized.current = true;
    }
  }, [data]);

  function update(patch: Partial<ContactForm>) {
    setForm((f) => ({ ...f, ...patch }));
    setSaved(false);
  }

  async function handleSave() {
    if (!reason.trim()) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await api.put<ContactInfo>("/api/v1/tenants/platform/contact", {
        ...form,
        reason: reason.trim(),
      });
      setForm({
        support_email: updated.support_email ?? "",
        phone: updated.phone ?? "",
        whatsapp: updated.whatsapp ?? "",
        address_en: updated.address.en ?? "",
        address_am: updated.address.am ?? "",
        hours_en: updated.hours.en ?? "",
        hours_am: updated.hours.am ?? "",
        note_en: updated.note.en ?? "",
        note_am: updated.note.am ?? "",
      });
      setReason("");
      setSaved(true);
      await qc.invalidateQueries({ queryKey: ["public-contact"] });
    } catch (e: unknown) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  if (isLoading) return <div className="p-8"><p className="text-gray-400 text-sm">{t("common.loading")}</p></div>;
  if (isError) return <div className="p-8"><p className="text-red-500 text-sm">{t("common.error")}</p></div>;

  const FIELDS: { field: keyof ContactForm; labelKey: string; type?: string }[] = [
    { field: "support_email", labelKey: "platform_contact.support_email_label", type: "email" },
    { field: "phone", labelKey: "platform_contact.phone_label" },
    { field: "whatsapp", labelKey: "platform_contact.whatsapp_label" },
    { field: "address_en", labelKey: "platform_contact.address_en_label" },
    { field: "address_am", labelKey: "platform_contact.address_am_label" },
    { field: "hours_en", labelKey: "platform_contact.hours_en_label" },
    { field: "hours_am", labelKey: "platform_contact.hours_am_label" },
    { field: "note_en", labelKey: "platform_contact.note_en_label" },
    { field: "note_am", labelKey: "platform_contact.note_am_label" },
  ];

  return (
    <div className="min-h-screen bg-gray-100">
      <div className="bg-white border-b border-gray-200 px-6 py-6">
        <h1 className="text-2xl font-bold text-gray-900">{t("platform_contact.title")}</h1>
        <p className="text-sm text-gray-600 mt-1">{t("platform_contact.subtitle")}</p>
      </div>

      <div className="p-6 max-w-5xl mx-auto grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
          {FIELDS.map(({ field, labelKey, type }) => (
            <div key={field}>
              <label className="block text-[11px] font-bold text-gray-500 mb-1">{t(labelKey)}</label>
              <input
                type={type ?? "text"}
                value={form[field]}
                onChange={(e) => update({ [field]: e.target.value } as Partial<ContactForm>)}
                className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded outline-none focus:border-[#1B4332] focus:ring-1 focus:ring-[#1B4332]"
              />
            </div>
          ))}

          <div>
            <label className="block text-xs font-bold text-gray-600 mb-1">
              {t("platform_contact.reason_label")} <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={t("platform_contact.reason_placeholder")}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded outline-none focus:border-[#1B4332] focus:ring-1 focus:ring-[#1B4332]"
            />
          </div>

          {error && <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-2 py-1.5">{error}</p>}
          {saved && (
            <p className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-2 py-1.5">
              {t("platform_contact.saved")}
            </p>
          )}

          <div className="flex justify-end">
            <button
              type="button"
              disabled={saving || !reason.trim()}
              onClick={() => void handleSave()}
              className="px-4 py-2 text-xs font-bold text-white bg-[#0f2d1f] rounded hover:bg-[#1a4d35] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving ? t("platform_contact.saving") : t("platform_contact.save_btn")}
            </button>
          </div>
        </div>

        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-bold text-gray-800">{t("platform_contact.preview_heading")}</h3>
            <div className="flex gap-0.5 bg-gray-100 rounded p-0.5">
              {(["en", "am"] as const).map((loc) => (
                <button
                  key={loc}
                  type="button"
                  onClick={() => setPreviewLocale(loc)}
                  className={`text-[11px] font-bold px-2 py-0.5 rounded border-0 cursor-pointer transition-all ${
                    previewLocale === loc ? "bg-brand-600 text-white" : "bg-transparent text-gray-500 hover:text-gray-700"
                  }`}
                >
                  {t(`platform_contact.preview_locale_${loc}`)}
                </button>
              ))}
            </div>
          </div>
          <ContactDetailsView contact={formToPreview(form)} locale={previewLocale} />
        </div>
      </div>
    </div>
  );
}
