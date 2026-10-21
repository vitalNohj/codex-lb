import type { TFunction } from "i18next";

import type { LimitWindowType } from "@/features/api-keys/schemas";

export const LIMIT_WINDOW_LABELS: Record<LimitWindowType, string> = {
  daily: "Daily",
  weekly: "Weekly",
  monthly: "Monthly",
  "5h": "5h",
  "7d": "7d",
  lifetime: "One-time (never resets)",
};

/** The display label for a limit window, translated when a translation exists. */
export function limitWindowLabel(window: LimitWindowType, t: TFunction): string {
  return t(`apiKeys.limitWindows.${window}`, { defaultValue: LIMIT_WINDOW_LABELS[window] });
}
