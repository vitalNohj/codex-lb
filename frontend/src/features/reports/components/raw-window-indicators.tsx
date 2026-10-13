import { History } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ReferenceArea } from "@/components/lazy-recharts";
import { prunedRangeBounds } from "../raw-window";

export function RawWindowBadge({ since }: { since: string }) {
  const { t } = useTranslation();
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1 rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-700 dark:text-amber-300"
      title={t("reports.charts.rawWindowHint", { since })}
    >
      <History aria-hidden="true" className="h-3 w-3" />
      {t("reports.charts.rawWindowBadge", { since })}
    </span>
  );
}

export type PrunedRangeShadeProps = {
  /** Full ISO dates (YYYY-MM-DD) of the plotted days, in order. */
  dates: string[];
  rawMetricsSince: string | null | undefined;
};

export function PrunedRangeShade(props: PrunedRangeShadeProps) {
  const bounds = prunedRangeBounds(props.dates, props.rawMetricsSince);
  if (!bounds) return null;
  return (
    <ReferenceArea
      x1={bounds.x1}
      x2={bounds.x2}
      fill="var(--muted-foreground)"
      fillOpacity={0.07}
      stroke="none"
      ifOverflow="hidden"
    />
  );
}
