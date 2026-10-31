import { Trash2 } from "lucide-react";
import { useId } from "react";
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
import { ModelMultiSelect } from "@/features/api-keys/components/model-multi-select";
import { limitRuleWithModels, ruleModelFilters } from "@/features/api-keys/components/limit-rules-utils";
import {
  ENFORCED_REASONING_EFFORTS,
  LIMIT_TYPES,
  LIMIT_WINDOWS,
  type LimitRuleCreate,
  type LimitType,
  type LimitWindowType,
} from "@/features/api-keys/schemas";
import { limitWindowLabel } from "@/features/api-keys/limit-windows";

const LIMIT_TYPE_LABELS: Record<LimitType, string> = {
  total_tokens: "Total Tokens",
  input_tokens: "Input Tokens",
  output_tokens: "Output Tokens",
  cost_usd: "Cost ($)",
  credits: "Credits",
};

const CLIENT_CHOICE = "client";
const LIMIT_TYPE_SET: ReadonlySet<string> = new Set(LIMIT_TYPES);
const LIMIT_WINDOW_SET: ReadonlySet<string> = new Set(LIMIT_WINDOWS);
const EFFORT_SET: ReadonlySet<string> = new Set(ENFORCED_REASONING_EFFORTS);

const EFFORT_LABELS: Record<(typeof ENFORCED_REASONING_EFFORTS)[number], string> = {
  none: "common.reasoning.none",
  minimal: "common.reasoning.minimal",
  low: "common.reasoning.low",
  medium: "common.reasoning.medium",
  high: "common.reasoning.high",
  xhigh: "common.reasoning.xhigh",
  max: "common.reasoning.max",
  ultra: "common.reasoning.ultra",
};

function isLimitType(v: string): v is LimitType {
  return LIMIT_TYPE_SET.has(v);
}

function isLimitWindow(v: string): v is LimitWindowType {
  return LIMIT_WINDOW_SET.has(v);
}

function isReasoningEffort(v: string): v is NonNullable<LimitRuleCreate["reasoningEffort"]> {
  return EFFORT_SET.has(v);
}

export type LimitRuleCardProps = {
  rule: LimitRuleCreate;
  onChange: (rule: LimitRuleCreate) => void;
  onRemove: () => void;
};

export function LimitRuleCard({ rule, onChange, onRemove }: LimitRuleCardProps) {
  const { t } = useTranslation();
  const fieldId = useId();
  const isCost = rule.limitType === "cost_usd";
  const isCredits = rule.limitType === "credits";
  const maxValue = rule.maxValue ?? 0;
  const displayValue = isCost && maxValue > 0
    ? String(maxValue / 1_000_000)
    : maxValue > 0
      ? String(maxValue)
      : "";
  const effortOnly = rule.reasoningEffort != null && maxValue <= 0;

  const handleValueChange = (raw: string) => {
    if (!raw) {
      onChange({ ...rule, maxValue: 0 });
      return;
    }
    const budgetDefaults = {
      limitType: rule.limitType ?? "total_tokens",
      limitWindow: rule.limitWindow ?? "weekly",
    };
    if (isCost) {
      const usd = parseFloat(raw);
      if (!isNaN(usd)) {
        onChange({ ...rule, ...budgetDefaults, maxValue: Math.round(usd * 1_000_000) });
      }
    } else {
      const val = parseInt(raw, 10);
      if (!isNaN(val)) {
        onChange({ ...rule, ...budgetDefaults, maxValue: val });
      }
    }
  };

  const handleLimitTypeChange = (v: string) => {
    if (isLimitType(v)) {
      onChange(limitRuleWithModels(
        { ...rule, limitType: v },
        v === "credits" ? [] : ruleModelFilters(rule),
      ));
    }
  };

  const handleWindowChange = (v: string) => {
    if (isLimitWindow(v)) {
      onChange({ ...rule, limitWindow: v });
    }
  };

  const modelFilterArray = isCredits ? [] : ruleModelFilters(rule);

  return (
    <div className="flex flex-col gap-2 rounded-lg border p-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">{t("apiKeys.limitRule.title")}</span>
        <Button type="button" variant="ghost" size="sm" onClick={onRemove} aria-label={t("apiKeys.limitRules.removeRule")}>
          <Trash2 className="size-3.5" />
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label htmlFor={`${fieldId}-type`} className="text-xs text-muted-foreground">{t("apiKeys.limitRule.type")}</label>
          <Select value={rule.limitType ?? undefined} onValueChange={handleLimitTypeChange}>
            <SelectTrigger id={`${fieldId}-type`} className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {LIMIT_TYPES.map((k) => (
                <SelectItem key={k} value={k}>
                  {t(`apiKeys.limitTypes.${k}`, { defaultValue: LIMIT_TYPE_LABELS[k] })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div>
          <label htmlFor={`${fieldId}-window`} className="text-xs text-muted-foreground">{t("apiKeys.limitRule.window")}</label>
          <Select value={rule.limitWindow ?? undefined} onValueChange={handleWindowChange}>
            <SelectTrigger id={`${fieldId}-window`} className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {LIMIT_WINDOWS.map((k) => (
                <SelectItem key={k} value={k}>
                  {limitWindowLabel(k, t)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div>
        <label htmlFor={`${fieldId}-max-value`} className="text-xs text-muted-foreground">
          {isCost
            ? t("apiKeys.limitRule.maxValueUsd")
            : isCredits
              ? t("apiKeys.limitRule.maxValueCredits")
              : t("apiKeys.limitRule.maxValueTokens")}
        </label>
        <Input
          id={`${fieldId}-max-value`}
          type="number"
          min={isCost ? 0.01 : 1}
          step={isCost ? 0.01 : 1}
          value={displayValue}
          onChange={(e) => handleValueChange(e.target.value)}
          className="h-8 text-xs"
        />
      </div>

      <div>
        <label htmlFor={`${fieldId}-effort`} className="text-xs text-muted-foreground">
          {t("apiKeys.limitRule.reasoningEffort")}
        </label>
        <Select
          value={rule.reasoningEffort ?? CLIENT_CHOICE}
          onValueChange={(value) => {
            onChange({
              ...rule,
              reasoningEffort: value === CLIENT_CHOICE || !isReasoningEffort(value) ? null : value,
            });
          }}
        >
          <SelectTrigger id={`${fieldId}-effort`} className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={CLIENT_CHOICE}>{t("apiKeys.limitRule.clientChoice")}</SelectItem>
            {ENFORCED_REASONING_EFFORTS.map((effort) => (
              <SelectItem key={effort} value={effort}>
                {t(EFFORT_LABELS[effort])}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {effortOnly ? (
          <p className="mt-1 text-xs text-muted-foreground">{t("apiKeys.limitRule.effortOnlyHint")}</p>
        ) : null}
      </div>

      <div>
        <p className="text-xs text-muted-foreground">{t("apiKeys.limitRule.modelFilter")}</p>
        <ModelMultiSelect
          value={modelFilterArray}
          onChange={(models) => {
            if (isCredits) return;
            onChange(limitRuleWithModels(rule, models));
          }}
          placeholder={isCredits ? t("apiKeys.limitRule.creditsGlobal") : t("apiKeys.modelSelect.all")}
          scope="subscriptions"
        />
      </div>
    </div>
  );
}
