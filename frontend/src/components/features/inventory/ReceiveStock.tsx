"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { nanoid } from "nanoid";
import { api } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { enqueueOfflineTransaction } from "@/store/offlineQueue";
import { useOfflineSync } from "@/hooks/useOfflineSync";
import { t } from "@/lib/i18n";
import { Button } from "@/components/ui/Button";

const schema = z.object({
  productId: z.string().uuid(),
  warehouseId: z.string().uuid(),
  quantity: z.coerce.number().positive(),
  lotNumber: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

export function ReceiveStock() {
  const { isOnline } = useOfflineSync();
  const [submitted, setSubmitted] = useState(false);

  const form = useForm<FormValues>({ resolver: zodResolver(schema) });

  const onSubmit = async (values: FormValues) => {
    const idempotencyKey = `receive:${values.productId}:${Date.now()}:${nanoid(8)}`;

    if (!isOnline) {
      await enqueueOfflineTransaction({
        idempotencyKey,
        action: "inventory:receive",
        payload: { ...values, idempotency_key: idempotencyKey },
      });
      setSubmitted(true);
      return;
    }

    const token = getToken();
    await api.post(
      "/api/v1/inventory/receive/",
      {
        product_id: values.productId,
        warehouse_id: values.warehouseId,
        quantity: values.quantity.toFixed(4),
        lot_number: values.lotNumber,
        idempotency_key: idempotencyKey,
      },
      token ?? undefined
    );
    setSubmitted(true);
  };

  if (submitted) {
    return <p className="text-green-600">{t("inventory.receive.success")}</p>;
  }

  return (
    <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-700">
          {t("inventory.receive.product_id")}
        </label>
        <input
          {...form.register("productId")}
          className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          placeholder="UUID"
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700">
          {t("inventory.receive.warehouse_id")}
        </label>
        <input
          {...form.register("warehouseId")}
          className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          placeholder="UUID"
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700">
          {t("inventory.receive.quantity")}
        </label>
        <input
          {...form.register("quantity")}
          type="number"
          step="0.0001"
          className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
        />
      </div>
      <Button type="submit" isLoading={form.formState.isSubmitting}>
        {isOnline ? t("inventory.receive.submit") : t("inventory.receive.queue_offline")}
      </Button>
    </form>
  );
}
