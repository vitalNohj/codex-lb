/**
 * Well-known CLIProxyAPI model families offered as switches in the
 * excluded-models editor.
 *
 * This map is a frontend convenience only. The backend stores whatever pattern
 * strings it is given and knows nothing about families, so adding a family here
 * needs no backend change. Patterns are CLIProxyAPI wire model ids, never
 * `cc/`-prefixed alias ids: a `cc/` value would never match and the exclusion
 * would silently do nothing.
 */

export type ExcludedModelFamily = {
  /** Stable id used as the switch key. */
  id: string;
  /** Human label rendered on the switch and on compact badges. */
  label: string;
  /** Pattern written to `excludedModels` when the switch is turned on. */
  pattern: string;
  /** Every pattern this family owns; turning the switch off removes all of them. */
  matches: (pattern: string) => boolean;
};

/**
 * Match only the exact patterns a family owns.
 *
 * Family ownership is deliberately exact rather than a substring test: a
 * narrower operator-typed pattern such as `claude-fable-5` must stay a
 * removable custom chip instead of being swallowed by - and deletable through -
 * the family switch.
 */
function exactMatcher(...patterns: readonly string[]): (pattern: string) => boolean {
  const owned = new Set(patterns.map((entry) => entry.toLowerCase()));
  return (pattern) => owned.has(pattern.trim().toLowerCase());
}

export const EXCLUDED_MODEL_FAMILIES: readonly ExcludedModelFamily[] = [
  {
    id: "fable",
    label: "Fable",
    pattern: "claude-fable-*",
    matches: exactMatcher("claude-fable-*", "claude-fable"),
  },
  {
    id: "opus-5",
    label: "Opus 5",
    pattern: "claude-opus-5*",
    matches: exactMatcher("claude-opus-5*", "claude-opus-5"),
  },
  {
    id: "sonnet-5",
    label: "Sonnet 5",
    pattern: "claude-sonnet-5*",
    matches: exactMatcher("claude-sonnet-5*", "claude-sonnet-5"),
  },
  {
    id: "haiku",
    label: "Haiku",
    pattern: "claude-haiku-*",
    matches: exactMatcher("claude-haiku-*", "claude-haiku"),
  },
] as const;

function familyById(id: string): ExcludedModelFamily | undefined {
  return EXCLUDED_MODEL_FAMILIES.find((family) => family.id === id);
}

/** Return the family a pattern belongs to, or undefined when it is a custom pattern. */
export function familyForPattern(pattern: string): ExcludedModelFamily | undefined {
  return EXCLUDED_MODEL_FAMILIES.find((family) => family.matches(pattern));
}

/** Return true when the exclusion list already excludes this family. */
export function isFamilyExcluded(id: string, excludedModels: readonly string[]): boolean {
  const family = familyById(id);
  if (!family) return false;
  return excludedModels.some((pattern) => family.matches(pattern));
}

/**
 * Return the exclusion list with a family switched on or off.
 *
 * Turning a family on appends its canonical pattern when nothing in the list
 * already covers it. Turning it off drops every pattern the family owns and
 * leaves every other entry, including custom patterns, untouched.
 */
export function toggleFamily(
  id: string,
  excludedModels: readonly string[],
  excluded: boolean,
): string[] {
  const family = familyById(id);
  if (!family) return [...excludedModels];
  if (!excluded) {
    return excludedModels.filter((pattern) => !family.matches(pattern));
  }
  if (excludedModels.some((pattern) => family.matches(pattern))) {
    return [...excludedModels];
  }
  return [...excludedModels, family.pattern];
}

/** Return the patterns in the list that no family switch represents. */
export function customPatterns(excludedModels: readonly string[]): string[] {
  return excludedModels.filter((pattern) => familyForPattern(pattern) === undefined);
}

/** Return the compact labels for an exclusion list: family label, else raw pattern. */
export function excludedModelLabels(excludedModels: readonly string[]): string[] {
  const labels: string[] = [];
  for (const pattern of excludedModels) {
    const label = familyForPattern(pattern)?.label ?? pattern;
    if (!labels.includes(label)) labels.push(label);
  }
  return labels;
}
