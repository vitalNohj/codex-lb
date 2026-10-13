import { useTranslation } from "react-i18next";

import { Skeleton } from "@/components/ui/skeleton";

export type ReportsSkeletonProps = {
  chartCount: number;
};

/** Mirrors the loaded Reports layout so the page does not jump on load. */
export function ReportsSkeleton({ chartCount }: ReportsSkeletonProps) {
  const { t } = useTranslation();

  return (
    <div className="space-y-6" role="status" aria-busy="true">
      <span className="sr-only">{t("common.loading")}</span>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={`card-${i}`} className="rounded-xl border bg-card p-4">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="mt-3 h-7 w-28" />
            <Skeleton className="mt-2 h-3 w-36" />
          </div>
        ))}
      </div>
      {chartCount > 0 ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {Array.from({ length: chartCount }).map((_, i) => (
            <div key={`chart-${i}`} className="rounded-xl border bg-card p-5">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="mt-4 h-[200px] w-full rounded-lg" />
            </div>
          ))}
        </div>
      ) : null}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="space-y-4">
          {Array.from({ length: 2 }).map((_, i) => (
            <div key={`donut-${i}`} className="flex items-center gap-4 rounded-xl border bg-card p-5">
              <Skeleton className="h-[140px] w-[140px] shrink-0 rounded-full" />
              <div className="flex-1 space-y-2.5">
                {Array.from({ length: 4 }).map((_, j) => (
                  <Skeleton key={j} className="h-3 w-full" />
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="space-y-3 rounded-xl border bg-card p-5 lg:col-span-2">
          <Skeleton className="h-4 w-36" />
          {Array.from({ length: 7 }).map((_, i) => (
            <Skeleton key={`row-${i}`} className="h-8 w-full" />
          ))}
        </div>
      </div>
    </div>
  );
}
