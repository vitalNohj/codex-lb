import { useState } from "react";
import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { LimitRuleCard } from "@/features/api-keys/components/limit-rule-card";
import { ruleModelFilters } from "@/features/api-keys/components/limit-rules-utils";
import { limitWindowLabel } from "@/features/api-keys/limit-windows";
import {
  LIMIT_WINDOWS,
  type LimitRuleCreate,
  type LimitWindowType,
} from "@/features/api-keys/schemas";

export type LimitRulesEditorProps = {
  rules: LimitRuleCreate[];
  onChange: (rules: LimitRuleCreate[]) => void;
};

type OverallLimitType = "total_tokens" | "cost_usd";

function isLimitWindow(value: string): value is LimitWindowType {
  return (LIMIT_WINDOWS as readonly string[]).includes(value);
}

/** Token or cost cap with no model filter. These are the two boxes at the top. */
function isOverallBoxRule(rule: LimitRuleCreate, limitType: OverallLimitType): boolean {
  return (
    rule.limitType === limitType
    && rule.limitWindow != null
    && (rule.maxValue ?? 0) > 0
    && ruleModelFilters(rule).length === 0
  );
}

function overallBoxIndexes(rules: readonly LimitRuleCreate[]): { token: number; cost: number } {
  return {
    token: rules.findIndex((rule) => isOverallBoxRule(rule, "total_tokens")),
    cost: rules.findIndex((rule) => isOverallBoxRule(rule, "cost_usd")),
  };
}

function firstOverallWindow(rules: readonly LimitRuleCreate[]): LimitWindowType | null {
  for (const rule of rules) {
    if (
      (isOverallBoxRule(rule, "total_tokens") || isOverallBoxRule(rule, "cost_usd"))
      && rule.limitWindow != null
    ) {
      return rule.limitWindow;
    }
  }
  return null;
}

function hasRulesOutsideOverall(rules: readonly LimitRuleCreate[]): boolean {
  const indexes = overallBoxIndexes(rules);
  return rules.some((rule, index) => {
    if (index === indexes.token || index === indexes.cost) return false;
    return (rule.maxValue ?? 0) > 0 || rule.reasoningEffort != null || ruleModelFilters(rule).length > 0;
  });
}

function makeDefaultRule(limitWindow: LimitWindowType): LimitRuleCreate {
  return {
    limitType: "total_tokens",
    limitWindow,
    maxValue: 0,
    modelFilter: null,
  };
}

export function LimitRulesEditor({ rules, onChange }: LimitRulesEditorProps) {
  const { t } = useTranslation();
  const [ruleKeys, setRuleKeys] = useState(() =>
    rules.map((_, index) => `limit-rule-${index}`),
  );
  const [nextRuleKey, setNextRuleKey] = useState(() => rules.length);
  const [windowOverride, setWindowOverride] = useState<LimitWindowType | null>(null);
  const [advanced, setAdvanced] = useState(() => hasRulesOutsideOverall(rules));

  const storedWindow = firstOverallWindow(rules);
  const overallWindow = windowOverride ?? storedWindow ?? "weekly";
  const indexes = overallBoxIndexes(rules);
  const tokenRule = indexes.token >= 0 ? rules[indexes.token] : undefined;
  const costRule = indexes.cost >= 0 ? rules[indexes.cost] : undefined;
  const tokenMax = tokenRule?.maxValue ?? 0;
  const costMax = costRule?.maxValue ?? 0;
  const tokenLabel = t("apiKeys.limitRules.tokenLimit", {
    window: limitWindowLabel(overallWindow, t),
    defaultValue: "{{window}} token limit",
  });
  const costLabel = t("apiKeys.limitRules.costLimit", {
    window: limitWindowLabel(overallWindow, t),
    defaultValue: "{{window}} cost limit ($)",
  });

  const groupEntries = rules.flatMap((rule, index) => {
    if (index === indexes.token || index === indexes.cost) return [];
    return [{
      rule,
      index,
      key: ruleKeys[index] ?? `limit-rule-${index}`,
    }];
  });

  const updateRule = (index: number, updated: LimitRuleCreate) => {
    const next = [...rules];
    next[index] = updated;
    onChange(next);
  };

  const appendRule = (rule: LimitRuleCreate) => {
    const key = `limit-rule-${nextRuleKey}`;
    setRuleKeys((current) => [...current, key]);
    setNextRuleKey((current) => current + 1);
    onChange([...rules, rule]);
  };

  const removeRule = (index: number) => {
    setRuleKeys((current) => current.filter((_, ruleIndex) => ruleIndex !== index));
    onChange(rules.filter((_, ruleIndex) => ruleIndex !== index));
  };

  const writeOverall = (limitType: OverallLimitType, maxValue: number) => {
    const index = rules.findIndex((rule) => isOverallBoxRule(rule, limitType));
    if (maxValue <= 0) {
      if (index >= 0) {
        const remaining = rules.filter((_, ruleIndex) => ruleIndex !== index);
        const removedWindow = rules[index]?.limitWindow;
        if (windowOverride == null && firstOverallWindow(remaining) == null && removedWindow != null) {
          setWindowOverride(removedWindow);
        }
        removeRule(index);
      }
      return;
    }
    const existing = index >= 0 ? rules[index] : undefined;
    const nextRule: LimitRuleCreate = {
      ...existing,
      limitType,
      limitWindow: overallWindow,
      maxValue,
      modelFilter: null,
      modelFilters: [],
      reasoningEffort: existing?.reasoningEffort ?? null,
    };
    if (index >= 0) updateRule(index, nextRule);
    else appendRule(nextRule);
  };

  const handleTokenChange = (raw: string) => {
    const val = raw ? parseInt(raw, 10) : 0;
    writeOverall("total_tokens", Number.isFinite(val) ? val : 0);
  };

  const handleCostChange = (raw: string) => {
    const usd = raw ? parseFloat(raw) : 0;
    writeOverall("cost_usd", Number.isFinite(usd) && usd > 0 ? Math.round(usd * 1_000_000) : 0);
  };

  const handleWindowChange = (value: string) => {
    if (!isLimitWindow(value)) return;
    setWindowOverride(value);
    if (indexes.token < 0 && indexes.cost < 0) return;
    let changed = false;
    const next = rules.map((rule, index) => {
      if (index !== indexes.token && index !== indexes.cost) return rule;
      if (rule.limitWindow === value) return rule;
      changed = true;
      return { ...rule, limitWindow: value };
    });
    if (changed) onChange(next);
  };

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

      <div className="space-y-2">
        <div>
          <label htmlFor="overall-limit-window" className="text-xs text-muted-foreground">{t("apiKeys.limitRule.window")}</label>
          <Select value={overallWindow} onValueChange={handleWindowChange}>
            <SelectTrigger id="overall-limit-window" className="h-8 w-full text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {LIMIT_WINDOWS.map((limitWindow) => (
                <SelectItem key={limitWindow} value={limitWindow}>
                  {limitWindowLabel(limitWindow, t)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <label htmlFor="overall-token-limit" className="text-xs text-muted-foreground">{tokenLabel}</label>
          <Input
            id="overall-token-limit"
            type="number"
            min={1}
            value={tokenMax > 0 ? String(tokenMax) : ""}
            onChange={(event) => handleTokenChange(event.target.value)}
            placeholder={t("apiKeys.limitRules.noLimit")}
          />
        </div>
        <div>
          <label htmlFor="overall-cost-limit" className="text-xs text-muted-foreground">{costLabel}</label>
          <Input
            id="overall-cost-limit"
            type="number"
            min={0.01}
            step={0.01}
            value={costMax > 0 ? String(costMax / 1_000_000) : ""}
            onChange={(event) => handleCostChange(event.target.value)}
            placeholder={t("apiKeys.limitRules.noLimit")}
          />
        </div>
      </div>

      {advanced ? (
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
            onClick={() => appendRule(makeDefaultRule(overallWindow))}
          >
            <Plus className="mr-1 size-3.5" />
            {t("apiKeys.limitRules.addRule")}
          </Button>
          {rules.length > 1 ? (
            <p className="text-xs text-muted-foreground">
              {t("apiKeys.limitRules.andHint")}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
