import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { buildSettingsUpdateRequest } from "@/features/settings/payload";
import { useClaudeSidecarQuota, useSettings } from "@/features/settings/hooks/use-settings";
import type { ClaudeSidecarAuthPlan, ClaudeSidecarPlanType } from "@/features/settings/schemas";

const PLAN_DEFAULTS: Record<ClaudeSidecarPlanType, { primary: number; secondary: number }> = {
  pro: { primary: 40_000, secondary: 280_000 },
  max5: { primary: 88_000, secondary: 616_000 },
  max20: { primary: 352_000, secondary: 2_464_000 },
  custom: { primary: 88_000, secondary: 616_000 },
};

type PlanDraft = {
  authIndex?: string | null;
  email?: string | null;
  source?: string | null;
  planType: ClaudeSidecarPlanType;
  primaryTokenBudget: string;
  secondaryTokenBudget: string;
};

function authPlanKey(value: {
  authIndex?: string | null;
  email?: string | null;
  source?: string | null;
  name?: string | null;
}): string {
  if (value.authIndex) {
    return `auth:${value.authIndex}`;
  }
  return `source:${(value.email ?? value.source ?? value.name ?? "unknown").toLowerCase()}`;
}

function planDraftFromPlan(plan: ClaudeSidecarAuthPlan): PlanDraft {
  const defaults = PLAN_DEFAULTS[plan.planType];
  return {
    authIndex: plan.authIndex,
    email: plan.email,
    source: plan.source,
    planType: plan.planType,
    primaryTokenBudget: String(plan.primaryTokenBudget ?? defaults.primary),
    secondaryTokenBudget: String(plan.secondaryTokenBudget ?? defaults.secondary),
  };
}

export function ClaudeSidecarQuotaEstimation() {
  const { quotaQuery } = useClaudeSidecarQuota();
  const { settingsQuery, updateSettingsMutation } = useSettings();
  const settings = settingsQuery.data;
  const quota = quotaQuery.data;
  // Local edits keyed by auth identity; server data is the source of defaults.
  const [edits, setEdits] = useState<Record<string, Partial<PlanDraft>>>({});

  const savedPlans = settings?.claudeSidecarAuthPlans;
  const quotaAccounts = quota?.accounts;
  const baseDrafts = useMemo(() => {
    const next: Record<string, PlanDraft> = {};
    for (const plan of savedPlans ?? []) {
      next[authPlanKey(plan)] = planDraftFromPlan(plan);
    }
    for (const account of quotaAccounts ?? []) {
      const key = authPlanKey(account);
      if (!next[key]) {
        const defaults = PLAN_DEFAULTS.pro;
        next[key] = {
          authIndex: account.authIndex,
          email: account.email,
          source: account.email ?? account.name,
          planType: "pro",
          primaryTokenBudget: String(account.primaryTokenBudget ?? defaults.primary),
          secondaryTokenBudget: String(account.secondaryTokenBudget ?? defaults.secondary),
        };
      }
    }
    return next;
  }, [quotaAccounts, savedPlans]);

  const planDrafts = useMemo(() => {
    const merged: Record<string, PlanDraft> = {};
    for (const [key, base] of Object.entries(baseDrafts)) {
      merged[key] = edits[key] ? { ...base, ...edits[key] } : base;
    }
    return merged;
  }, [baseDrafts, edits]);

  const estimationRows = useMemo(() => Object.entries(planDrafts), [planDrafts]);
  const saving = updateSettingsMutation.isPending;

  const updatePlanDraft = (key: string, patch: Partial<PlanDraft>) => {
    setEdits((current) => ({ ...current, [key]: { ...current[key], ...patch } }));
  };

  const updatePlanType = (key: string, planType: ClaudeSidecarPlanType) => {
    const defaults = PLAN_DEFAULTS[planType];
    updatePlanDraft(key, {
      planType,
      primaryTokenBudget: String(defaults.primary),
      secondaryTokenBudget: String(defaults.secondary),
    });
  };

  const saveEstimationPlans = async () => {
    if (!settings) {
      return;
    }
    const plans: ClaudeSidecarAuthPlan[] = Object.values(planDrafts)
      .map((draft) => ({
        authIndex: draft.authIndex ?? undefined,
        email: draft.email ?? undefined,
        source: draft.source ?? draft.email ?? undefined,
        planType: draft.planType,
        primaryTokenBudget: Number(draft.primaryTokenBudget),
        secondaryTokenBudget: Number(draft.secondaryTokenBudget),
      }))
      .filter(
        (plan) =>
          Number.isFinite(plan.primaryTokenBudget) &&
          Number.isFinite(plan.secondaryTokenBudget) &&
          plan.primaryTokenBudget > 0 &&
          plan.secondaryTokenBudget > 0,
      );
    await updateSettingsMutation
      .mutateAsync(buildSettingsUpdateRequest(settings, { claudeSidecarAuthPlans: plans }))
      .catch(() => null);
  };

  return (
    <div className="space-y-3 rounded-lg border bg-muted/10 p-4 text-sm">
      <div>
        <p className="text-sm font-medium">Quota estimation</p>
        <p className="text-xs text-muted-foreground">
          Percentages are estimates from CLIProxyAPI usage telemetry and configured plan budgets.
        </p>
      </div>
      {!settings ? (
        <p className="text-xs text-muted-foreground">Loading quota settings...</p>
      ) : estimationRows.length > 0 ? (
        <div className="space-y-2">
          {estimationRows.map(([key, draft]) => (
            <div key={key} className="grid gap-2 rounded-md border bg-background/60 p-2 sm:grid-cols-[1.4fr_8rem_9rem_9rem]">
              <div className="min-w-0">
                <div className="truncate text-xs font-medium">{draft.email ?? draft.source ?? draft.authIndex ?? "Claude auth"}</div>
                <div className="truncate text-[11px] text-muted-foreground">
                  {draft.authIndex ? `auth_index ${draft.authIndex}` : draft.source ?? "source unknown"}
                </div>
              </div>
              <label className="space-y-1 text-xs font-medium">
                Plan
                <Select value={draft.planType} onValueChange={(value) => updatePlanType(key, value as ClaudeSidecarPlanType)} disabled={saving}>
                  <SelectTrigger size="sm" className="h-8 w-full text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="pro">Pro</SelectItem>
                    <SelectItem value="max5">Max 5x</SelectItem>
                    <SelectItem value="max20">Max 20x</SelectItem>
                    <SelectItem value="custom">Custom</SelectItem>
                  </SelectContent>
                </Select>
              </label>
              <label className="space-y-1 text-xs font-medium">
                5-hour tokens
                <Input
                  type="number"
                  min={1}
                  step={1000}
                  value={draft.primaryTokenBudget}
                  disabled={saving}
                  onChange={(event) => updatePlanDraft(key, { primaryTokenBudget: event.target.value })}
                  className="h-8 text-xs"
                />
              </label>
              <label className="space-y-1 text-xs font-medium">
                Weekly tokens
                <Input
                  type="number"
                  min={1}
                  step={1000}
                  value={draft.secondaryTokenBudget}
                  disabled={saving}
                  onChange={(event) => updatePlanDraft(key, { secondaryTokenBudget: event.target.value })}
                  className="h-8 text-xs"
                />
              </label>
            </div>
          ))}
          <Button type="button" size="sm" variant="outline" className="h-8 text-xs" disabled={saving} onClick={() => void saveEstimationPlans()}>
            Save quota estimates
          </Button>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          No Claude auths discovered yet. Save the Management key and wait for one quota poll.
        </p>
      )}
    </div>
  );
}
