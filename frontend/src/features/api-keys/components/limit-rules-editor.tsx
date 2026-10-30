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
type OverallSlot = "token" | "cost" | null;

function isLimitWindow(value: string): value is LimitWindowType {
  return (LIMIT_WINDOWS as readonly string[]).includes(value);
}

/** Positive all-models token or cost cap. Model rules and empty rows are not caps. */
function isUnfilteredBudget(rule: LimitRuleCreate, limitType: OverallLimitType): boolean {
  return (
    rule.limitType === limitType
    && rule.limitWindow != null
    && (rule.maxValue ?? 0) > 0
    && ruleModelFilters(rule).length === 0
  );
}

/** The top boxes share the window of the first loaded all-models token or cost cap. */
function sharedWindowForLoadedRules(rules: readonly LimitRuleCreate[]): LimitWindowType | null {
  for (const rule of rules) {
    if (
      (isUnfilteredBudget(rule, "total_tokens") || isUnfilteredBudget(rule, "cost_usd"))
      && rule.limitWindow != null
    ) {
      return rule.limitWindow;
    }
  }
  return null;
}

/**
 * Slot membership is fixed when a rule is loaded or created from a top box.
 * A loaded cap joins a slot only when it uses that shared window. A cap with
 * another window stays an advanced card so its window is not relabeled.
 * Add limit rule does not assign a slot, so typing an amount cannot promote it.
 */
function initialOverallSlots(rules: readonly LimitRuleCreate[]): OverallSlot[] {
  const sharedWindow = sharedWindowForLoadedRules(rules);
  let tokenTaken = false;
  let costTaken = false;
  return rules.map((rule) => {
    if (sharedWindow == null || rule.limitWindow !== sharedWindow) return null;
    if (!tokenTaken && isUnfilteredBudget(rule, "total_tokens")) {
      tokenTaken = true;
      return "token";
    }
    if (!costTaken && isUnfilteredBudget(rule, "cost_usd")) {
      costTaken = true;
      return "cost";
    }
    return null;
  });
}

function hasAdvancedRules(rules: readonly LimitRuleCreate[], slots: readonly OverallSlot[]): boolean {
  return rules.some((rule, index) => {
    if (slots[index] != null) return false;
    return (rule.maxValue ?? 0) > 0 || rule.reasoningEffort != null || ruleModelFilters(rule).length > 0;
  });
}

function slottedWindow(
  rules: readonly LimitRuleCreate[],
  slots: readonly OverallSlot[],
): LimitWindowType | null {
  for (const [index, rule] of rules.entries()) {
    if (slots[index] == null) continue;
    if (rule.limitWindow != null) return rule.limitWindow;
  }
  return null;
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
  const [overallSlots, setOverallSlots] = useState(() => initialOverallSlots(rules));
  const [nextRuleKey, setNextRuleKey] = useState(() => rules.length);
  const [windowOverride, setWindowOverride] = useState<LimitWindowType | null>(null);
  const [advanced, setAdvanced] = useState(() => hasAdvancedRules(rules, initialOverallSlots(rules)));

  const storedWindow = slottedWindow(rules, overallSlots);
  const overallWindow = windowOverride ?? storedWindow ?? "weekly";
  const tokenIndex = overallSlots.indexOf("token");
  const costIndex = overallSlots.indexOf("cost");
  const tokenRule = tokenIndex >= 0 ? rules[tokenIndex] : undefined;
  const costRule = costIndex >= 0 ? rules[costIndex] : undefined;
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
    if (overallSlots[index] != null) return [];
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

  const appendRule = (rule: LimitRuleCreate, slot: OverallSlot = null) => {
    const key = `limit-rule-${nextRuleKey}`;
    setRuleKeys((current) => [...current, key]);
    setOverallSlots((current) => [...current, slot]);
    setNextRuleKey((current) => current + 1);
    onChange([...rules, rule]);
  };

  const removeRule = (index: number) => {
    setRuleKeys((current) => current.filter((_, ruleIndex) => ruleIndex !== index));
    setOverallSlots((current) => current.filter((_, ruleIndex) => ruleIndex !== index));
    onChange(rules.filter((_, ruleIndex) => ruleIndex !== index));
  };

  const writeOverall = (limitType: OverallLimitType, maxValue: number) => {
    const slot: OverallSlot = limitType === "total_tokens" ? "token" : "cost";
    const index = overallSlots.indexOf(slot);
    if (maxValue <= 0) {
      if (index >= 0) {
        const remainingRules = rules.filter((_, ruleIndex) => ruleIndex !== index);
        const remainingSlots = overallSlots.filter((_, ruleIndex) => ruleIndex !== index);
        const removedWindow = rules[index]?.limitWindow;
        if (
          windowOverride == null
          && slottedWindow(remainingRules, remainingSlots) == null
          && removedWindow != null
        ) {
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
      limitWindow: existing?.limitWindow ?? overallWindow,
      maxValue,
      modelFilter: null,
      modelFilters: [],
      reasoningEffort: existing?.reasoningEffort ?? null,
    };
    if (index >= 0) updateRule(index, nextRule);
    else appendRule(nextRule, slot);
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
    if (tokenIndex < 0 && costIndex < 0) return;
    let changed = false;
    const next = rules.map((rule, index) => {
      if (overallSlots[index] == null) return rule;
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
