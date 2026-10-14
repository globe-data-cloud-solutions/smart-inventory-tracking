"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";
import { SA_ORG_SLUG } from "@/lib/demo-auth";
import { IS_GATEWAY_MODE } from "@/lib/api";
import { t } from "@/lib/i18n";
import { DemoLotsView } from "@/components/features/lots/DemoLotsView";
import { LiveLotsView } from "@/components/features/lots/LiveLotsView";

export default function LotsPage() {
  const { org } = useParams() as { org: string };

  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("sa.select_tenant")}</p>;
  if (!IS_GATEWAY_MODE) return <DemoLotsView org={org} />;

  // LiveLotsView reads ?view= via useSearchParams, which needs a Suspense boundary.
  return (
    <Suspense fallback={null}>
      <LiveLotsView org={org} />
    </Suspense>
  );
}
