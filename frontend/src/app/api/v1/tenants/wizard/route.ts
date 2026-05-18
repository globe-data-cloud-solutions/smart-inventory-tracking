import { NextRequest, NextResponse } from "next/server";

interface OnboardedTenant {
  id: string;
  name: string;
  slug: string;
  industry: string;
  org_type: "PRODUCER" | "RETAILER" | "HYBRID";
  default_locale: "en" | "am" | "or";
  sku_limit: number | null;
  feature_flags: Record<string, boolean>;
  approval_thresholds: Record<string, unknown>;
  onboarding_complete: boolean;
  created_at: string;
}

const FEATURE_FLAG_DEFAULTS: Record<string, Record<string, boolean>> = {
  PRODUCER: { LOGISTICS: false, AI_ANALYTICS: false, ADVANCED_BATCH_TRACKING: true,  FLEET_MANAGEMENT: false },
  RETAILER: { LOGISTICS: true,  AI_ANALYTICS: true,  ADVANCED_BATCH_TRACKING: false, FLEET_MANAGEMENT: true  },
  HYBRID:   { LOGISTICS: true,  AI_ANALYTICS: true,  ADVANCED_BATCH_TRACKING: true,  FLEET_MANAGEMENT: true  },
};

const APPROVAL_DEFAULTS: Record<string, Record<string, unknown>> = {
  PRODUCER: { "inventory:adjust": { low: 100,  medium: 500   } },
  RETAILER: { "inventory:adjust": { low: 500,  medium: 5000  } },
  HYBRID:   { "inventory:adjust": { low: 250,  medium: 2000  } },
};

// In-memory store
export const onboardedTenants: OnboardedTenant[] = [];

function toSlug(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

export async function POST(req: NextRequest) {
  const body = (await req.json()) as {
    name?: string;
    industry?: string;
    org_type?: string;
    default_locale?: string;
    sku_limit?: number | null;
  };

  if (!body.name?.trim()) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "name is required" } },
      { status: 422 }
    );
  }

  const orgType = body.org_type as "PRODUCER" | "RETAILER" | "HYBRID";
  if (!["PRODUCER", "RETAILER", "HYBRID"].includes(orgType)) {
    return NextResponse.json(
      { success: false, error: { code: "VALIDATION_ERROR", message: "org_type must be PRODUCER, RETAILER, or HYBRID" } },
      { status: 422 }
    );
  }

  const locale = (body.default_locale ?? "en") as "en" | "am" | "or";
  const now = new Date().toISOString();

  const tenant: OnboardedTenant = {
    id: crypto.randomUUID(),
    name: body.name.trim(),
    slug: toSlug(body.name.trim()),
    industry: body.industry?.trim() ?? "",
    org_type: orgType,
    default_locale: locale,
    sku_limit: orgType === "PRODUCER" ? (body.sku_limit ?? 500) : null,
    feature_flags: FEATURE_FLAG_DEFAULTS[orgType] ?? {},
    approval_thresholds: APPROVAL_DEFAULTS[orgType] ?? {},
    onboarding_complete: true,
    created_at: now,
  };

  onboardedTenants.push(tenant);

  return NextResponse.json(
    { success: true, data: tenant, request_id: crypto.randomUUID(), timestamp: now },
    { status: 201 }
  );
}

export async function GET() {
  return NextResponse.json({
    success: true,
    data: onboardedTenants,
    request_id: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
  });
}
