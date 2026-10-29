import type { LimitRuleCreate } from "@/features/api-keys/schemas";

type ModelFilterRule = {
  modelFilters?: readonly string[] | null;
  modelFilter?: string | null;
};

type NormalizedLimitRule = {
  limitType: LimitRuleCreate["limitType"];
  limitWindow: LimitRuleCreate["limitWindow"];
  maxValue: number;
  modelFilter: string | null;
  modelFilters: string[];
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

export function limitRuleWithModels(rule: LimitRuleCreate, models: readonly string[]): LimitRuleCreate {
  const modelFilters = ruleModelFilters({ modelFilters: models });
  return {
    ...rule,
    modelFilters,
    modelFilter: modelFilters.length === 1 ? modelFilters[0] : null,
  };
}

function normalizeLimitRule(rule: LimitRuleCreate): NormalizedLimitRule {
  const modelFilters = ruleModelFilters(rule);
  return {
    limitType: rule.limitType,
    limitWindow: rule.limitWindow,
    maxValue: rule.maxValue,
    modelFilters,
    modelFilter: modelFilters.length === 1 ? modelFilters[0] : null,
  };
}

function limitRuleSortKey(rule: NormalizedLimitRule): string {
  return [
    rule.limitType,
    rule.limitWindow,
    JSON.stringify(rule.modelFilters),
    String(rule.maxValue),
  ].join("::");
}

export function normalizeLimitRules(rules: LimitRuleCreate[]): NormalizedLimitRule[] {
  return rules
    .reduce<NormalizedLimitRule[]>((normalizedRules, rule) => {
      if (rule.maxValue > 0) {
        normalizedRules.push(normalizeLimitRule(rule));
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
      || rule.modelFilters.join("\0") !== candidate.modelFilters.join("\0")
    );
  });
}
