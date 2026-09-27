"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { TabProps, TenantContact } from "../types";

const CONTACT_TYPES = {
  primary: { label: "Primary Contact", icon: "👤" },
  billing: { label: "Billing Contact", icon: "💳" },
  technical: { label: "Technical Contact", icon: "🔧" },
};

interface ContactForm {
  contact_type: "primary" | "billing" | "technical";
  name: string;
  email: string;
  phone?: string;
  role?: string;
}

export function ContactTab({ tenantId, isLoading }: TabProps) {
  const qc = useQueryClient();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [formData, setFormData] = useState<ContactForm>({
    contact_type: "primary",
    name: "",
    email: "",
    phone: "",
    role: "",
  });

  const { data: contacts = [], isLoading: loadingContacts } = useQuery<TenantContact[]>({
    queryKey: ["tenant-admin-contacts", tenantId],
    queryFn: () => api.get<TenantContact[]>(`/api/v1/tenants/${tenantId}/contacts`),
    staleTime: 30_000,
  });

  const saveMutation = useMutation({
    mutationFn: (data: ContactForm) => {
      if (editingId) {
        return api.patch(`/api/v1/tenants/${tenantId}/contacts/${editingId}`, data);
      }
      return api.post(`/api/v1/tenants/${tenantId}/contacts`, data);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tenant-admin-contacts", tenantId] });
      setSuccess(editingId ? "Contact updated successfully!" : "Contact added successfully!");
      resetForm();
      setError(null);
      setTimeout(() => setSuccess(null), 3000);
    },
    onError: (e: unknown) => {
      setError(e instanceof Error ? e.message : t("common.error"));
    },
  });

  const resetForm = () => {
    setFormData({ contact_type: "primary", name: "", email: "", phone: "", role: "" });
    setEditingId(null);
    setShowAddForm(false);
  };

  const handleEdit = (contact: TenantContact) => {
    setFormData({
      contact_type: contact.contact_type,
      name: contact.name,
      email: contact.email,
      phone: contact.phone ?? "",
      role: contact.role ?? "",
    });
    setEditingId(contact.id);
    setShowAddForm(false);
  };

  const isValidForm = formData.name && formData.email;

  if (loadingContacts || isLoading) {
    return <div className="flex items-center justify-center py-12 text-gray-500">{t("common.loading")}</div>;
  }

  return (
    <div className="space-y-6">
      {/* Contacts List */}
      <div className="bg-white rounded-lg border border-gray-200">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-800">Contacts</h3>
          {!showAddForm && !editingId && (
            <button
              onClick={() => setShowAddForm(true)}
              className="text-sm font-semibold text-blue-600 hover:text-blue-700"
            >
              + Add Contact
            </button>
          )}
        </div>

        <div className="p-6 space-y-4">
          {contacts.length === 0 ? (
            <p className="text-sm text-gray-500 text-center py-8">No contacts added yet.</p>
          ) : (
            contacts.map((contact) => (
              <div key={contact.id} className="p-4 border border-gray-200 rounded-lg">
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xl">{CONTACT_TYPES[contact.contact_type].icon}</span>
                    <div>
                      <p className="font-semibold text-gray-800">{contact.name}</p>
                      <p className="text-xs text-gray-500">{CONTACT_TYPES[contact.contact_type].label}</p>
                    </div>
                  </div>
                  <button
                    onClick={() => handleEdit(contact)}
                    className="text-sm font-medium text-blue-600 hover:text-blue-700"
                  >
                    Edit
                  </button>
                </div>
                <div className="text-sm text-gray-600">
                  <p>Email: {contact.email}</p>
                  {contact.phone && <p>Phone: {contact.phone}</p>}
                  {contact.role && <p>Role: {contact.role}</p>}
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
            {editingId ? "Edit Contact" : "Add New Contact"}
          </h3>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Contact Type <span className="text-red-600">*</span>
              </label>
              <select
                value={formData.contact_type}
                onChange={(e) =>
                  setFormData({ ...formData, contact_type: e.target.value as "primary" | "billing" | "technical" })
                }
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
              >
                {Object.entries(CONTACT_TYPES).map(([key, val]) => (
                  <option key={key} value={key}>
                    {val.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Name <span className="text-red-600">*</span>
              </label>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                placeholder="Full name"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Email <span className="text-red-600">*</span>
              </label>
              <input
                type="email"
                value={formData.email}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                placeholder="email@example.com"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Phone</label>
              <input
                type="tel"
                value={formData.phone}
                onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                placeholder="+1 (555) 000-0000"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Role/Title</label>
              <input
                type="text"
                value={formData.role}
                onChange={(e) => setFormData({ ...formData, role: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                placeholder="e.g., Account Manager"
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
                Cancel
              </button>
              <button
                onClick={() => {
                  if (!isValidForm) {
                    setError("Please fill in name and email");
                    return;
                  }
                  saveMutation.mutate(formData);
                }}
                disabled={!isValidForm || saveMutation.isPending}
                className="flex-1 px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded hover:bg-blue-700 disabled:opacity-50"
              >
                {saveMutation.isPending ? "Saving..." : "Save Contact"}
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
