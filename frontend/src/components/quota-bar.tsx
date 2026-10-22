import { Clock } from "lucide-react";

import { cn } from "@/lib/utils";
import { quotaBarColor, quotaBarTrack } from "@/utils/account-status";
import { formatPercentNullable } from "@/utils/formatters";

export type QuotaBarProps = {
  label: string;
  percent: number | null;
  /** Reset hint shown under the bar; omit to hide the row. */
  resetLabel?: string | null;
  /** Accessible label for the progress value, e.g. "Weekly quota for alice". */
  "aria-label"?: string;
  /**
   * The caller already tweens ``percent`` (``useSmoothPercent``): show one
   * decimal and let the bar width follow the tween instead of a CSS transition.
   */
  smoothed?: boolean;
};

/**
 * Labelled remaining-quota bar used by dashboard account cards and the
 * CLIProxyAPI credential cards: coloured percentage, a thin bar, and an
 * optional reset hint.
 */
export function QuotaBar({ label, percent, resetLabel, "aria-label": ariaLabel, smoothed = false }: QuotaBarProps) {
  const clamped = percent === null ? 0 : Math.max(0, Math.min(100, percent));
  const hasPercent = percent !== null;
  return (
    <div className="min-w-0 space-y-1">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="truncate text-muted-foreground">{label}</span>
        <span
          className={cn(
            "tabular-nums font-medium",
            !hasPercent
              ? "text-muted-foreground"
              : clamped >= 70
                ? "text-emerald-600 dark:text-emerald-400"
                : clamped >= 30
                  ? "text-amber-600 dark:text-amber-400"
                  : "text-red-600 dark:text-red-400",
          )}
        >
          {formatPercentNullable(percent, smoothed ? 1 : 0)}
        </span>
      </div>
      {ariaLabel && hasPercent ? (
        <progress className="sr-only" aria-label={ariaLabel} value={clamped} max={100} />
      ) : null}
      <div className={cn("h-1.5 w-full overflow-hidden rounded-full", quotaBarTrack(clamped))} aria-hidden="true">
        <div
          className={cn(
            "h-full rounded-full duration-500 ease-out",
            smoothed ? "transition-colors" : "transition-all",
            quotaBarColor(clamped),
          )}
          style={{ width: `${clamped}%` }}
        />
      </div>
      {resetLabel ? (
        <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
          <Clock className="h-3 w-3 shrink-0" aria-hidden="true" />
          <span className="truncate">{resetLabel}</span>
        </div>
      ) : null}
    </div>
  );
}
