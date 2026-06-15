"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getSession, SA_ORG_SLUG } from "@/lib/demo-auth";
import { api, IS_GATEWAY_MODE } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useTenantName } from "@/hooks/useTenantName";
import { useTenantPositions, type TenantPosition } from "@/hooks/useTenantPositions";

const TA_SA_ROLES = new Set(["TA", "SA"]);

interface ApiTransferType {
  id: string;
  underlying_type: "PULL" | "PUSH" | "SISTER";
  display_name: string;
  is_active: boolean;
  level_permissions: Array<{ level_number: number; level_name: string; can_initiate: boolean; can_receive: boolean }>;
}

interface SelfApprovalPolicy {
  id: string;
  role_code: string;
  level_number: number;
  transfer_types: string[];
  threshold_type: string;
  qty_limit: number | null;
  value_limit: number | null;
  is_active: boolean;
}

interface AdjustmentApprovalRule {
  id: string;
  role_code: string;
  level_number: number;
  mode: string;
  threshold_type: string;
  qty_limit: number | null;
  value_limit: number | null;
  approver_role_code: string | null;
  approver_position_id: string | null;
  approver_position_title: string | null;
  priority: number;
  is_active: boolean;
}

interface ApprovalOverride {
  mode: string; // ALWAYS | QUANTITY | VALUE
  threshold: number | null;
  approver_label: string | null;
  note?: string | null;
}

interface ApiProduct {
  id: string;
  sku: string;
  name: string;
  currency?: string | null;
  is_controlled?: boolean;
  approval_overrides?: Record<string, ApprovalOverride>;
}

interface HierarchyLevel {
  id: string;
  level_number: number;
  level_name: string;
  default_role_code: string;
  role_display_label: string;
  is_stock_holding: boolean;
  is_active: boolean;
}

/* ── helpers ───────────────────────────────────────────────────────────── */

function canInitiate(cfg: ApiTransferType, level: number): boolean {
  if (!cfg.level_permissions.length) return true;
  const perm = cfg.level_permissions.find((p) => p.level_number === level);
  if (!perm) return true;
  return perm.can_initiate;
}

function formatQty(n: number): string {
  return n.toLocaleString();
}

function exampleLine(qtyLimit: number | null): string | null {
  if (qtyLimit == null || qtyLimit <= 0) return null;
  const half = Math.max(1, Math.round(qtyLimit / 2));
  const double = qtyLimit * 2;
  return t("approval_policies.example_line")
    .replace("{half}", formatQty(half))
    .replace("{double}", formatQty(double));
}

function selfApproveText(qtyLimit: number | null, valueLimit: number | null, currency: string): string {
  if (qtyLimit == null) return t("approval_policies.no_limit");
  if (valueLimit != null) {
    return t("approval_policies.self_approve_up_to_value")
      .replace("{qty}", formatQty(qtyLimit))
      .replace("{value}", formatQty(valueLimit))
      .replace("{currency}", currency);
  }
  return t("approval_policies.self_approve_up_to").replace("{qty}", formatQty(qtyLimit));
}

/** Resolve a position-title or role-code reference to its tenant display label. */
function resolvePositionLabel(
  positions: TenantPosition[],
  byTitle: string | null | undefined,
  byPositionId: string | null | undefined,
  byRoleCode: string | null | undefined,
  fallback: string,
): string {
  if (byTitle) {
    const pos = positions.find((p) => p.title === byTitle);
    if (pos) return pos.display_label;
    return byTitle;
  }
  if (byPositionId) {
    const pos = positions.find((p) => p.id === byPositionId);
    if (pos) return pos.display_label;
  }
  if (byRoleCode) return byRoleCode;
  return fallback;
}

function levelEscalationLabel(levelNumber: number, hierarchyLevels: HierarchyLevel[]): string {
  const upper = hierarchyLevels.find((l) => l.level_number === levelNumber - 1);
  if (upper) return upper.role_display_label || upper.level_name;
  return t("approval_policies.higher_authority");
}

const cardCls = "bg-white border border-gray-200 rounded-lg p-4 mb-3";

/* ── page ──────────────────────────────────────────────────────────────── */

export default function ApprovalPoliciesPage() {
  const { org } = useParams() as { org: string };
  const tenantName = useTenantName(org);
  const session = getSession();
  const tenantId = session?.tenantId ?? "";
  const [showMatrix, setShowMatrix] = useState(false);

  const enabled = IS_GATEWAY_MODE && org !== SA_ORG_SLUG && !!tenantId;

  const { positions, isLoading: positionsLoading } = useTenantPositions(tenantId);

  const { data: transferTypes = [] } = useQuery<ApiTransferType[]>({
    queryKey: ["approval-policies-transfer-types", tenantId],
    queryFn: () => api.get<ApiTransferType[]>(`/api/v1/tenants/${tenantId}/transfer-types`),
    enabled,
    staleTime: 60_000,
  });

  const { data: selfApprovalPolicies = [] } = useQuery<SelfApprovalPolicy[]>({
    queryKey: ["approval-policies-self-approval", tenantId],
    queryFn: () => api.get<SelfApprovalPolicy[]>(`/api/v1/tenants/${tenantId}/self-approval-policies`),
    enabled,
    staleTime: 60_000,
  });

  const { data: adjustmentRules = [] } = useQuery<AdjustmentApprovalRule[]>({
    queryKey: ["approval-policies-adjustment-rules", tenantId],
    queryFn: () => api.get<AdjustmentApprovalRule[]>(`/api/v1/tenants/${tenantId}/adjustment-approval-rules`),
    enabled,
    staleTime: 60_000,
  });

  const { data: products = [] } = useQuery<ApiProduct[]>({
    queryKey: ["approval-policies-products", tenantId],
    queryFn: () => api.get<ApiProduct[]>(`/api/v1/products/`),
    enabled,
    staleTime: 60_000,
  });

  const isTaSa = TA_SA_ROLES.has(session?.role ?? "");

  const { data: hierarchyLevels = [] } = useQuery<HierarchyLevel[]>({
    queryKey: ["approval-policies-hierarchy", tenantId],
    queryFn: () => api.get<HierarchyLevel[]>(`/api/v1/tenants/${tenantId}/hierarchy/config`),
    enabled: enabled && isTaSa,
    staleTime: 60_000,
  });

  if (!session) return null;
  if (org === SA_ORG_SLUG) return <p className="p-8 text-gray-500">{t("sa.select_tenant")}</p>;

  const viewerPosition = positions.find((p) => p.id === session.positionId);
  const viewerLevel = viewerPosition?.level_number ?? session.levelNumber ?? 99;
  const viewerRole = session.role ?? "";

  const nextApproverLabel = (() => {
    if (viewerPosition?.reports_to_position_id) {
      const pos = positions.find((p) => p.id === viewerPosition.reports_to_position_id);
      if (pos) return pos.display_label;
    }
    return viewerPosition?.reports_to_title ?? t("approval_policies.higher_authority");
  })();

  // Section 1 — transfer types this viewer can initiate, plus ADJUSTMENT always.
  const initiableTransferTypes = transferTypes.filter((tt) => tt.is_active && canInitiate(tt, viewerLevel));
  const adjustmentRule = adjustmentRules.find(
    (r) => r.is_active && r.role_code === viewerRole && r.level_number === viewerLevel
  );
  const adjustmentApprover = adjustmentRule
    ? resolvePositionLabel(
        positions,
        adjustmentRule.approver_position_title,
        adjustmentRule.approver_position_id,
        adjustmentRule.approver_role_code,
        nextApproverLabel
      )
    : nextApproverLabel;

  const controlledProducts = products.filter((p) => p.is_controlled && p.approval_overrides);

  return (
    <div className="p-8 max-w-4xl">
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-[#0f2d1f] m-0">{t("approval_policies.title")}</h2>
        <p className="text-sm text-gray-500 mt-1">
          {tenantName ?? org} · {t("approval_policies.subtitle")}
        </p>
      </div>

      {/* ── Section 1 — Your Approval Limits ───────────────────────────── */}
      <section className="mb-8">
        <h3 className="text-lg font-bold text-[#0f2d1f] mb-1">{t("approval_policies.section1_title")}</h3>
        <p className="text-sm text-gray-600 mb-3">
          {t("approval_policies.your_level").replace(
            "{level}",
            positionsLoading ? t("common.loading") : viewerPosition?.display_label ?? session.positionTitle ?? "—"
          )}
        </p>

        {initiableTransferTypes.map((tt) => {
          const policy = selfApprovalPolicies.find(
            (p) =>
              p.is_active &&
              p.role_code === viewerRole &&
              p.level_number === viewerLevel &&
              p.transfer_types.includes(tt.underlying_type)
          );

          return (
            <div key={tt.id} className={cardCls}>
              <p className="font-semibold text-gray-800 m-0 mb-1">{tt.display_name}</p>
              {policy ? (
                <>
                  <p className="text-sm text-gray-700 m-0">
                    ✓ {selfApproveText(policy.qty_limit, policy.value_limit, "ETB")}
                  </p>
                  {policy.qty_limit != null && (
                    <p className="text-sm text-gray-700 m-0 mt-1">
                      {t("approval_policies.escalates_to").replace("{approver}", nextApproverLabel)}
                    </p>
                  )}
                  {exampleLine(policy.qty_limit) && (
                    <p className="text-xs text-gray-400 m-0 mt-2">{exampleLine(policy.qty_limit)}</p>
                  )}
                </>
              ) : (
                <p className="text-sm text-gray-700 m-0">
                  {t("approval_policies.requires_approval")
                    .replace("{type}", tt.display_name)
                    .replace("{approver}", nextApproverLabel)}
                </p>
              )}
            </div>
          );
        })}

        {/* Adjustment — always shown */}
        <div className={cardCls}>
          <p className="font-semibold text-gray-800 m-0 mb-1">{t("approval_policies.adjustment_label")}</p>
          {adjustmentRule && adjustmentRule.qty_limit != null ? (
            <>
              <p className="text-sm text-gray-700 m-0">
                ✓ {selfApproveText(adjustmentRule.qty_limit, adjustmentRule.value_limit, "ETB")}
              </p>
              <p className="text-sm text-gray-700 m-0 mt-1">
                {t("approval_policies.escalates_to").replace("{approver}", adjustmentApprover)}
              </p>
              {exampleLine(adjustmentRule.qty_limit) && (
                <p className="text-xs text-gray-400 m-0 mt-2">{exampleLine(adjustmentRule.qty_limit)}</p>
              )}
            </>
          ) : adjustmentRule ? (
            <p className="text-sm text-gray-700 m-0">
              {t("approval_policies.requires_approval")
                .replace("{type}", t("approval_policies.adjustment_label"))
                .replace("{approver}", adjustmentApprover)}
            </p>
          ) : (
            <p className="text-sm text-gray-700 m-0">
              ✓ {t("approval_policies.no_limit")}
            </p>
          )}
        </div>
      </section>

      {/* ── Section 2 — Controlled Products ────────────────────────────── */}
      <section className="mb-8">
        <h3 className="text-lg font-bold text-[#0f2d1f] mb-1">{t("approval_policies.controlled_products_title")}</h3>
        <p className="text-sm text-gray-600 mb-3">{t("approval_policies.controlled_products_desc")}</p>

        {controlledProducts.length === 0 ? (
          <div className={cardCls}>
            <p className="text-sm text-gray-500 m-0">{t("approval_policies.no_controlled_products")}</p>
          </div>
        ) : (
          controlledProducts.map((p) => {
            const currency = p.currency ?? "ETB";
            return (
              <div key={p.id} className={cardCls}>
                <p className="font-semibold text-gray-800 m-0 mb-1.5">🔒 {p.name}</p>
                {Object.entries(p.approval_overrides ?? {}).map(([txType, override]) => {
                  const typeLabel =
                    transferTypes.find((tt) => tt.underlying_type === txType)?.display_name ??
                    t(`product.tx_type_${txType.toLowerCase()}`);
                  const approverLabel = resolvePositionLabel(
                    positions,
                    override.approver_label,
                    null,
                    null,
                    override.approver_label ?? t("common.unknown")
                  );

                  let line: string;
                  if (override.mode === "ALWAYS") {
                    line = t("approval_policies.always_requires")
                      .replace("{type}", typeLabel)
                      .replace("{approver}", approverLabel);
                  } else if (override.mode === "VALUE") {
                    line = t("approval_policies.value_requires")
                      .replace("{type}", typeLabel)
                      .replace("{threshold}", formatQty(override.threshold ?? 0))
                      .replace("{currency}", currency)
                      .replace("{approver}", approverLabel);
                  } else {
                    line = t("approval_policies.quantity_requires")
                      .replace("{type}", typeLabel)
                      .replace("{threshold}", formatQty(override.threshold ?? 0))
                      .replace("{approver}", approverLabel);
                  }

                  return (
                    <p key={txType} className="text-sm text-gray-700 m-0 mb-0.5">
                      {line}
                    </p>
                  );
                })}
              </div>
            );
          })
        )}
      </section>

      {/* ── Section 3 — Full Policy Matrix (TA/SA only) ────────────────── */}
      {isTaSa && (
        <section className="mb-8">
          <button
            onClick={() => setShowMatrix((v) => !v)}
            className="text-sm font-semibold text-[#0f2d1f] bg-gray-100 hover:bg-gray-200 rounded-md px-3 py-1.5 cursor-pointer border border-gray-200"
          >
            {showMatrix ? t("approval_policies.hide_full_matrix") : t("approval_policies.show_full_matrix")}
          </button>

          {showMatrix && (
            <div className="bg-white border border-gray-200 rounded-lg mt-3 overflow-x-auto">
              <h3 className="text-lg font-bold text-[#0f2d1f] px-4 pt-4 m-0">
                {t("approval_policies.full_matrix_title")}
              </h3>
              <p className="text-sm text-gray-600 px-4 pb-2 m-0">{t("approval_policies.full_matrix_subtitle")}</p>
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="bg-gray-50 border-y border-gray-200">
                    {["col_level", "col_type", "col_self_approve", "col_escalates"].map((key) => (
                      <th
                        key={key}
                        className="px-4 py-2 text-left text-[11px] font-bold text-gray-500 uppercase tracking-wide"
                      >
                        {t(`approval_policies.${key}`)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {selfApprovalPolicies
                    .filter((p) => p.is_active)
                    .flatMap((p) =>
                      p.transfer_types.map((txType) => ({
                        levelNumber: p.level_number,
                        typeLabel:
                          transferTypes.find((tt) => tt.underlying_type === txType)?.display_name ??
                          t(`product.tx_type_${txType.toLowerCase()}`),
                        selfApprove: selfApproveText(p.qty_limit, p.value_limit, "ETB"),
                        escalatesTo: levelEscalationLabel(p.level_number, hierarchyLevels),
                        key: `${p.id}-${txType}`,
                      }))
                    )
                    .concat(
                      adjustmentRules
                        .filter((r) => r.is_active)
                        .map((r) => ({
                          levelNumber: r.level_number,
                          typeLabel: t("approval_policies.adjustment_label"),
                          selfApprove: selfApproveText(r.qty_limit, r.value_limit, "ETB"),
                          escalatesTo: resolvePositionLabel(
                            positions,
                            r.approver_position_title,
                            r.approver_position_id,
                            r.approver_role_code,
                            levelEscalationLabel(r.level_number, hierarchyLevels)
                          ),
                          key: r.id,
                        }))
                    )
                    .sort((a, b) => a.levelNumber - b.levelNumber)
                    .map((row) => {
                      const level = hierarchyLevels.find((l) => l.level_number === row.levelNumber);
                      const levelLabel = level?.level_name ?? `L${row.levelNumber}`;
                      return (
                        <tr key={row.key} className="border-b border-gray-100">
                          <td className="px-4 py-2 whitespace-nowrap text-gray-700">{levelLabel}</td>
                          <td className="px-4 py-2 whitespace-nowrap text-gray-700">{row.typeLabel}</td>
                          <td className="px-4 py-2 whitespace-nowrap text-gray-700">{row.selfApprove}</td>
                          <td className="px-4 py-2 whitespace-nowrap text-gray-700">{row.escalatesTo}</td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
