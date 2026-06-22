import type { SidecarReasoningEffort } from "@/features/settings/schemas";

export const REASONING_EFFORT_UNSET = "default";

export const REASONING_EFFORT_OPTIONS: ReadonlyArray<{
  value: SidecarReasoningEffort;
  label: string;
}> = [
  { value: "none", label: "None" },
  { value: "minimal", label: "Minimal" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "xhigh", label: "Extra high" },
];

export function reasoningEffortSelectValue(
  effort: SidecarReasoningEffort | null | undefined,
): string {
  return effort ?? REASONING_EFFORT_UNSET;
}

export function reasoningEffortFromSelectValue(
  value: string,
): SidecarReasoningEffort | null {
  return value === REASONING_EFFORT_UNSET
    ? null
    : (value as SidecarReasoningEffort);
}
