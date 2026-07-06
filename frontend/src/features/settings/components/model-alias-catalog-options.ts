export const CUSTOM_ALIAS_CONTEXT_LENGTH_INHERIT = "inherit" as const;

export const CUSTOM_ALIAS_CONTEXT_LENGTH_PRESETS = [
  { value: CUSTOM_ALIAS_CONTEXT_LENGTH_INHERIT, label: "Inherit from target" },
  { value: "128000", label: "128,000" },
  { value: "200000", label: "200,000" },
  { value: "1000000", label: "1,000,000" },
] as const;

export type CustomAliasContextLengthSelection =
  (typeof CUSTOM_ALIAS_CONTEXT_LENGTH_PRESETS)[number]["value"];

export function contextLengthSelectionFromValue(
  contextLength: number | null | undefined,
): CustomAliasContextLengthSelection {
  if (contextLength === 128_000) {
    return "128000";
  }
  if (contextLength === 200_000) {
    return "200000";
  }
  if (contextLength === 1_000_000) {
    return "1000000";
  }
  return CUSTOM_ALIAS_CONTEXT_LENGTH_INHERIT;
}

export function contextLengthValueFromSelection(
  selection: CustomAliasContextLengthSelection,
): number | null {
  if (selection === CUSTOM_ALIAS_CONTEXT_LENGTH_INHERIT) {
    return null;
  }
  return Number.parseInt(selection, 10);
}
