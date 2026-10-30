import type { LimitRuleCreate } from "@/features/api-keys/schemas";

type ModelFilterRule = {
  modelFilters?: readonly string[] | null;
  modelFilter?: string | null;
};

type NormalizedLimitRule = {
  limitType: LimitRuleCreate["limitType"];
  limitWindow: LimitRuleCreate["limitWindow"];
  maxValue: number | null;
  modelFilter: string | null;
  modelFilters: string[];
  reasoningEffort: NonNullable<LimitRuleCreate["reasoningEffort"]> | null;
};

export function ruleModelFilters(rule: ModelFilterRule): string[] {
  if (rule.modelFilters != null) {
    const seen = new Set<string>();
    const models: string[] = [];
    for (const model of rule.modelFilters) {
      const cleaned = model.trim();
      if (!cleaned || seen.has(cleaned)) {
        continue;
      }
      seen.add(cleaned);
      models.push(cleaned);
    }
    return models;
  }
  const single = typeof rule.modelFilter === "string" ? rule.modelFilter.trim() : "";
  return single ? [single] : [];
}

export function formatRuleModels(rule: ModelFilterRule, allLabel: string): string {
  const models = ruleModelFilters(rule);
  return models.length > 0 ? models.join(", ") : allLabel;
}

/** A spending cap with no model filter. It applies to every model. */
export function isOverallBudgetRule(rule: LimitRuleCreate): boolean {
  return (
    ruleModelFilters(rule).length === 0
    && (rule.maxValue ?? 0) > 0
    && rule.limitType != null
    && rule.limitWindow != null
  );
}

/** Overall caps first, then each model rule, keeping the original order inside each group. */
export function withOverallLimitsFirst<T extends LimitRuleCreate>(limits: readonly T[]): T[] {
  return limits
    .map((limit, index) => ({ limit, index, overall: isOverallBudgetRule(limit) }))
    .sort((left, right) => {
      if (left.overall !== right.overall) return left.overall ? -1 : 1;
      return left.index - right.index;
    })
    .map(({ limit }) => limit);
}

export function limitRuleWithModels(rule: LimitRuleCreate, models: readonly string[]): LimitRuleCreate {
  const modelFilters = ruleModelFilters({ modelFilters: models });
  return {
    ...rule,
    modelFilters,
    modelFilter: modelFilters.length === 1 ? modelFilters[0] : null,
  };
}

function ruleReasoningEffort(rule: LimitRuleCreate): NormalizedLimitRule["reasoningEffort"] {
  return rule.reasoningEffort ?? null;
}

function normalizeLimitRule(rule: LimitRuleCreate, hasBudget: boolean): NormalizedLimitRule {
  const modelFilters = ruleModelFilters(rule);
  return {
    limitType: hasBudget ? rule.limitType : null,
    limitWindow: hasBudget ? rule.limitWindow : null,
    maxValue: hasBudget ? (rule.maxValue ?? null) : null,
    modelFilters,
    modelFilter: modelFilters.length === 1 ? modelFilters[0] : null,
    reasoningEffort: ruleReasoningEffort(rule),
  };
}

function limitRuleSortKey(rule: NormalizedLimitRule): string {
  return [
    rule.limitType,
    rule.limitWindow,
    JSON.stringify(rule.modelFilters),
    String(rule.maxValue),
    rule.reasoningEffort ?? "",
  ].join("::");
}

export function normalizeLimitRules(rules: LimitRuleCreate[]): NormalizedLimitRule[] {
  return rules
    .reduce<NormalizedLimitRule[]>((normalizedRules, rule) => {
      const hasBudget = (rule.maxValue ?? 0) > 0 && rule.limitType != null && rule.limitWindow != null;
      if (hasBudget || ruleReasoningEffort(rule) != null) {
        normalizedRules.push(normalizeLimitRule(rule, hasBudget));
      }
      return normalizedRules;
    }, [])
    .sort((left, right) => limitRuleSortKey(left).localeCompare(limitRuleSortKey(right)));
}

export function hasLimitRuleChanges(
  initialRules: LimitRuleCreate[],
  currentRules: LimitRuleCreate[],
): boolean {
  const initial = normalizeLimitRules(initialRules);
  const current = normalizeLimitRules(currentRules);
  if (initial.length !== current.length) {
    return true;
  }
  return initial.some((rule, index) => {
    const candidate = current[index];
    if (!candidate) {
      return true;
    }
    return (
      rule.limitType !== candidate.limitType
      || rule.limitWindow !== candidate.limitWindow
      || rule.maxValue !== candidate.maxValue
      || rule.reasoningEffort !== candidate.reasoningEffort
      || rule.modelFilters.join("\0") !== candidate.modelFilters.join("\0")
    );
  });
}
