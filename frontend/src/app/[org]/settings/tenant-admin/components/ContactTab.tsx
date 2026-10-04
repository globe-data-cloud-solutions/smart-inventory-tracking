"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { TabProps, TenantContact } from "../types";

// Unused by this component today — kept for a future contact-type selector.
// Labels stored as i18n keys per CLAUDE.md §1; call t() at render time.
const CONTACT_TYPES = {
  Primary: { labelKey: "tenant_admin.contact.type.Primary", icon: "👤" },
  Billing: { labelKey: "tenant_admin.contact.type.Billing", icon: "💳" },
  Technical: { labelKey: "tenant_admin.contact.type.Technical", icon: "🔧" },
};

interface ContactForm {
  is_primary: boolean;
  full_name: string;
  email: string;
  phone?: string;
  position_title?: string;
}

export function ContactTab({ tenantId, isLoading }: TabProps) {
  const qc = useQueryClient();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [formData, setFormData] = useState<ContactForm>({
    is_primary: false,
    full_name: "",
    email: "",
    phone: "",
    position_title: "",
  });

  const { data: contacts = [], isLoading: loadingContacts } = useQuery<TenantContact[]>({
    queryKey: ["tenant-admin-contacts", tenantId],
    queryFn: () => api.get<TenantContact[]>(`/api/v1/tenants/me/contacts`),
    staleTime: 30_000,
  });

  const saveMutation = useMutation({
    mutationFn: (data: ContactForm) => {
      if (editingId) {
        return api.patch(`/api/v1/tenants/me/contacts/${editingId}`, data);
      }
      return api.post(`/api/v1/tenants/me/contacts`, data);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tenant-admin-contacts", tenantId] });
      setSuccess(editingId ? t("tenant_admin.contact.updated_success") : t("tenant_admin.contact.added_success"));
      resetForm();
      setError(null);
      setTimeout(() => setSuccess(null), 3000);
    },
    onError: (e: unknown) => {
      setError(e instanceof Error ? e.message : t("common.error"));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (contactId: string) => api.delete(`/api/v1/tenants/me/contacts/${contactId}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tenant-admin-contacts", tenantId] });
      setSuccess(t("tenant_admin.contact.deleted_success"));
      setError(null);
      setTimeout(() => setSuccess(null), 3000);
    },
    onError: (e: unknown) => {
      setError(e instanceof Error ? e.message : t("common.error"));
    },
  });

  const resetForm = () => {
    setFormData({ is_primary: false, full_name: "", email: "", phone: "", position_title: "" });
    setEditingId(null);
    setShowAddForm(false);
  };

  const handleEdit = (contact: TenantContact) => {
    setFormData({
      is_primary: contact.is_primary ?? false,
      full_name: contact.full_name,
      email: contact.email,
      phone: contact.phone ?? "",
      position_title: contact.position_title ?? "",
    });
    setEditingId(contact.id);
    setShowAddForm(false);
  };

  const isValidForm = formData.full_name && formData.email;

  if (loadingContacts || isLoading) {
    return <div className="flex items-center justify-center py-12 text-gray-500">{t("common.loading")}</div>;
  }

  return (
    <div className="space-y-6">
      {/* Contacts List */}
      <div className="bg-white rounded-lg border border-gray-200">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-800">{t("sa.admin_sub_contacts")}</h3>
          {!showAddForm && !editingId && (
            <button
              onClick={() => setShowAddForm(true)}
              className="text-sm font-semibold text-blue-600 hover:text-blue-700"
            >
              + {t("sa.contacts_add_btn")}
            </button>
          )}
        </div>

        <div className="p-6 space-y-4">
          {contacts.length === 0 ? (
            <p className="text-sm text-gray-500 text-center py-8">{t("sa.contacts_empty")}</p>
          ) : (
            contacts.map((contact) => (
              <div key={contact.id} className="p-4 border border-gray-200 rounded-lg">
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xl">{contact.is_primary ? "⭐" : "👤"}</span>
                    <div>
                      <p className="font-semibold text-gray-800">{contact.full_name}</p>
                      {contact.is_primary && <p className="text-xs text-amber-600">{t("tenant_admin.contact.primary_badge")}</p>}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleEdit(contact)}
                      className="text-sm font-medium text-blue-600 hover:text-blue-700"
                    >
                      {t("common.edit")}
                    </button>
                    <button
                      onClick={() => {
                        if (confirm(t("tenant_admin.contact.confirm_delete"))) {
                          deleteMutation.mutate(contact.id);
                        }
                      }}
                      disabled={deleteMutation.isPending}
                      className="text-sm font-medium text-red-600 hover:text-red-700 disabled:opacity-50"
                    >
                      {t("common.delete")}
                    </button>
                  </div>
                </div>
                <div className="text-sm text-gray-600">
                  <p>{t("sa.contacts_field_email")}: {contact.email}</p>
                  {contact.phone && <p>{t("sa.contacts_field_phone")}: {contact.phone}</p>}
                  {contact.position_title && <p>{t("tenant_admin.contact.title_label")}: {contact.position_title}</p>}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Add/Edit Form */}
      {(showAddForm || editingId) && (
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">
            {editingId ? t("sa.contacts_edit_title") : t("tenant_admin.contact.form_add_title")}
          </h3>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                <input
                  type="checkbox"
                  checked={formData.is_primary}
                  onChange={(e) => setFormData({ ...formData, is_primary: e.target.checked })}
                  className="mr-2"
                />
                {t("tenant_admin.contact.set_primary_checkbox")}
              </label>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                {t("tenant_admin.contact.form_name_label")} <span className="text-red-600">*</span>
              </label>
              <input
                type="text"
                value={formData.full_name}
                onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                placeholder={t("sa.contacts_field_name")}
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                {t("sa.contacts_field_email")} <span className="text-red-600">*</span>
              </label>
              <input
                type="email"
                value={formData.email}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                placeholder={t("tenant_admin.contact.form_email_placeholder")}
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t("sa.contacts_field_phone")}</label>
              <input
                type="tel"
                value={formData.phone}
                onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                placeholder={t("tenant_admin.contact.form_phone_placeholder")}
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t("tenant_admin.contact.form_position_label")}</label>
              <input
                type="text"
                value={formData.position_title}
                onChange={(e) => setFormData({ ...formData, position_title: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                placeholder={t("tenant_admin.contact.form_position_placeholder")}
              />
            </div>

            {error && (
              <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
                {error}
              </div>
            )}

            <div className="flex gap-3 pt-4 border-t border-gray-200">
              <button
                onClick={resetForm}
                className="flex-1 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded hover:bg-gray-50"
              >
                {t("common.cancel")}
              </button>
              <button
                onClick={() => {
                  if (!isValidForm) {
                    setError(t("tenant_admin.contact.form_validation_error"));
                    return;
                  }
                  saveMutation.mutate(formData);
                }}
                disabled={!isValidForm || saveMutation.isPending}
                className="flex-1 px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded hover:bg-blue-700 disabled:opacity-50"
              >
                {saveMutation.isPending ? t("common.saving") : t("tenant_admin.contact.form_save_btn")}
              </button>
            </div>
          </div>
        </div>
      )}

      {success && (
        <div className="p-4 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700">
          ✅ {success}
        </div>
      )}
    </div>
  );
}
