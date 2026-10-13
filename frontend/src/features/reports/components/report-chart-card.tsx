import { BarChart3 } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { EmptyState } from "@/components/empty-state";

export type ReportChartCardProps = {
  title: string;
  empty: boolean;
  /** Optional element shown at the right of the title row (badge, legend). */
  aside?: ReactNode;
  children: ReactNode;
};

export function ReportChartCard({ title, empty, aside, children }: ReportChartCardProps) {
  const { t } = useTranslation();

  return (
    <div className="rounded-xl border bg-card p-5">
      <div className="flex min-h-6 flex-wrap items-center justify-between gap-x-3 gap-y-1.5">
        <div className="text-sm font-semibold text-foreground">{title}</div>
        {empty ? null : aside}
      </div>
      {empty ? (
        <div className="mt-4">
          <EmptyState
            icon={BarChart3}
            title={t("reports.charts.emptyTitle")}
            description={t("reports.charts.emptyDescription")}
          />
        </div>
      ) : (
        <div className="mt-4 h-[200px]">{children}</div>
      )}
    </div>
  );
}
