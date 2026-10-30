import { useState } from "react";
import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { LimitRuleCard } from "@/features/api-keys/components/limit-rule-card";
import { isOverallBudgetRule, ruleModelFilters } from "@/features/api-keys/components/limit-rules-utils";
import type { LimitRuleCreate } from "@/features/api-keys/schemas";

export type LimitRulesEditorProps = {
  rules: LimitRuleCreate[];
  onChange: (rules: LimitRuleCreate[]) => void;
};

const EMPTY_OVERALL_LIMIT: LimitRuleCreate = {
  limitType: "cost_usd",
  limitWindow: "weekly",
  maxValue: 0,
  modelFilter: null,
  modelFilters: [],
};

function makeDefaultRule(): LimitRuleCreate {
  return {
    limitType: "total_tokens",
    limitWindow: "weekly",
    maxValue: 0,
    modelFilter: null,
  };
}

function isWeeklyOverall(rule: LimitRuleCreate, limitType: LimitRuleCreate["limitType"]): boolean {
  return rule.limitType === limitType && rule.limitWindow === "weekly" && ruleModelFilters(rule).length === 0;
}

function overallRuleShouldPersist(rule: LimitRuleCreate): boolean {
  if (ruleModelFilters(rule).length > 0) return false;
  return isOverallBudgetRule(rule) || rule.reasoningEffort != null;
}

export function LimitRulesEditor({ rules, onChange }: LimitRulesEditorProps) {
  const { t } = useTranslation();
  const [ruleKeys, setRuleKeys] = useState(() =>
    rules.map((_, index) => `limit-rule-${index}`),
  );
  const [nextRuleKey, setNextRuleKey] = useState(() => rules.length);
  const [overallKeys, setOverallKeys] = useState(() => new Set(
    rules.flatMap((rule, index) => (isOverallBudgetRule(rule) ? [`limit-rule-${index}`] : [])),
  ));
  const [draft, setDraft] = useState<LimitRuleCreate>(EMPTY_OVERALL_LIMIT);
  const [draftRuleKey, setDraftRuleKey] = useState<string | null>(null);
  const [advanced, setAdvanced] = useState(() => {
    if (rules.length === 0) return false;
    // If any non-standard rule exists, start in advanced mode
    return rules.some(
      (r) =>
        r.reasoningEffort != null ||
        (r.limitType !== "total_tokens" && r.limitType !== "cost_usd") ||
        r.limitWindow !== "weekly" ||
        ruleModelFilters(r).length > 0,
    );
  });

  const keyedRules = rules.map((rule, index) => ({
    rule,
    index,
    key: ruleKeys[index] ?? `limit-rule-${index}`,
  }));
  const overallEntries = keyedRules.filter((entry) => overallKeys.has(entry.key));
  const groupEntries = keyedRules.filter((entry) => !overallKeys.has(entry.key));

  // Derive basic mode values from rules
  const weeklyTokenRule = rules.find((rule) => isWeeklyOverall(rule, "total_tokens"));
  const weeklyCostRule = rules.find((rule) => isWeeklyOverall(rule, "cost_usd"));
  const weeklyCostMax = weeklyCostRule?.maxValue ?? 0;
  const weeklyTokenMax = weeklyTokenRule?.maxValue ?? 0;

  const updateRule = (index: number, updated: LimitRuleCreate) => {
    const next = [...rules];
    next[index] = updated;
    onChange(next);
  };

  const appendRule = (rule: LimitRuleCreate, bucket: "overall" | "group"): string => {
    const key = `limit-rule-${nextRuleKey}`;
    setRuleKeys((current) => [...current, key]);
    setNextRuleKey((current) => current + 1);
    if (bucket === "overall") {
      setOverallKeys((current) => new Set(current).add(key));
    }
    onChange([...rules, rule]);
    return key;
  };

  const removeRule = (index: number) => {
    const key = ruleKeys[index];
    setRuleKeys((current) => current.filter((_, ruleIndex) => ruleIndex !== index));
    if (key !== undefined) {
      setOverallKeys((current) => {
        const next = new Set(current);
        next.delete(key);
        return next;
      });
    }
    onChange(rules.filter((_, ruleIndex) => ruleIndex !== index));
  };

  const handleBasicTokenChange = (raw: string) => {
    const val = raw ? parseInt(raw, 10) : 0;
    const index = rules.findIndex((rule) => isWeeklyOverall(rule, "total_tokens"));
    if (val > 0) {
      const next = {
        limitType: "total_tokens" as const,
        limitWindow: "weekly" as const,
        maxValue: val,
        modelFilter: null,
        modelFilters: [] as string[],
        reasoningEffort: weeklyTokenRule?.reasoningEffort ?? null,
      };
      if (index >= 0) updateRule(index, next);
      else appendRule(next, "overall");
    } else if (index >= 0) {
      removeRule(index);
    }
  };

  const handleBasicCostChange = (raw: string) => {
    const usd = raw ? parseFloat(raw) : 0;
    const index = rules.findIndex((rule) => isWeeklyOverall(rule, "cost_usd"));
    if (usd > 0) {
      const next = {
        limitType: "cost_usd" as const,
        limitWindow: "weekly" as const,
        maxValue: Math.round(usd * 1_000_000),
        modelFilter: null,
        modelFilters: [] as string[],
        reasoningEffort: weeklyCostRule?.reasoningEffort ?? null,
      };
      if (index >= 0) updateRule(index, next);
      else appendRule(next, "overall");
    } else if (index >= 0) {
      removeRule(index);
    }
  };

  const addRule = () => {
    appendRule(makeDefaultRule(), "group");
  };

  const handleOverallChange = (slotIndex: number, updated: LimitRuleCreate) => {
    if (slotIndex < 0) {
      if (!overallRuleShouldPersist(updated)) {
        setDraft(updated);
        return;
      }
      const key = appendRule(updated, "overall");
      setDraftRuleKey(key);
      // The saved rule is the source of truth. Leaving the typed amount in
      // draft makes a later delete show a cap that save would omit.
      setDraft(EMPTY_OVERALL_LIMIT);
      return;
    }
    updateRule(slotIndex, updated);
  };

  const overallSlots = overallEntries.length === 0
    ? [{ key: "overall-draft", rule: draft, index: -1 }]
    : overallEntries.map((entry) => ({
      key: entry.key === draftRuleKey ? "overall-draft" : entry.key,
      rule: entry.rule,
      index: entry.index,
    }));

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{t("apiKeys.form.limits")}</span>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">{t("apiKeys.limitRules.advanced")}</span>
          <Switch
            checked={advanced}
            onCheckedChange={setAdvanced}
            aria-label={t("apiKeys.limitRules.advanced")}
          />
        </div>
      </div>

      {!advanced ? (
        <div className="space-y-2">
          <div>
            <label htmlFor="weekly-token-limit" className="text-xs text-muted-foreground">{t("apiKeys.limitRules.weeklyTokenLimit")}</label>
            <Input
              id="weekly-token-limit"
              type="number"
              min={1}
              value={weeklyTokenMax > 0 ? String(weeklyTokenMax) : ""}
              onChange={(e) => handleBasicTokenChange(e.target.value)}
              placeholder={t("apiKeys.limitRules.noLimit")}
            />
          </div>
          <div>
            <label htmlFor="weekly-cost-limit" className="text-xs text-muted-foreground">{t("apiKeys.limitRules.weeklyCostLimit")}</label>
            <Input
              id="weekly-cost-limit"
              type="number"
              min={0.01}
              step={0.01}
              value={weeklyCostMax > 0 ? String(weeklyCostMax / 1_000_000) : ""}
              onChange={(e) => handleBasicCostChange(e.target.value)}
              placeholder={t("apiKeys.limitRules.noLimit")}
            />
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="space-y-2" role="group" aria-label={t("apiKeys.limitRules.overallLimit")}>
            {overallSlots.map((slot) => (
              <LimitRuleCard
                key={slot.key}
                overall
                rule={slot.rule}
                onChange={(updated) => handleOverallChange(slot.index, updated)}
                onRemove={() => {
                  if (slot.index < 0) {
                    setDraft(EMPTY_OVERALL_LIMIT);
                    return;
                  }
                  setDraft(EMPTY_OVERALL_LIMIT);
                  if (draftRuleKey === ruleKeys[slot.index]) setDraftRuleKey(null);
                  removeRule(slot.index);
                }}
              />
            ))}
          </div>
          <div className="space-y-2">
            {groupEntries.map((entry) => (
              <LimitRuleCard
                key={entry.key}
                rule={entry.rule}
                onChange={(updated) => updateRule(entry.index, updated)}
                onRemove={() => removeRule(entry.index)}
              />
            ))}
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="w-full"
              onClick={addRule}
            >
              <Plus className="mr-1 size-3.5" />
              {t("apiKeys.limitRules.addRule")}
            </Button>
          </div>
          {rules.length > 1 ? (
            <p className="text-xs text-muted-foreground">
              {t("apiKeys.limitRules.andHint")}
            </p>
          ) : null}
        </div>
      )}
    </div>
  );
}
