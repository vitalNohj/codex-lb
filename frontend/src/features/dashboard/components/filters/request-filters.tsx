import { RotateCcw, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MultiSelectFilter, type MultiSelectOption } from "@/features/dashboard/components/filters/multi-select-filter";
import { TimeframeSelect } from "@/features/dashboard/components/filters/timeframe-select";
import type { FilterState } from "@/features/dashboard/schemas";
import type { DashboardRequestLogViewMode } from "@/hooks/use-dashboard-preferences";
import { cn } from "@/lib/utils";

export type RequestFiltersProps = {
  filters: FilterState;
  accountOptions: MultiSelectOption[];
  apiKeyOptions: MultiSelectOption[];
  modelOptions: MultiSelectOption[];
  statusOptions: MultiSelectOption[];
  viewMode: DashboardRequestLogViewMode;
  onSearchChange: (value: string) => void;
  onTimeframeChange: (value: FilterState["timeframe"]) => void;
  onViewModeChange: (value: DashboardRequestLogViewMode) => void;
  onAccountChange: (values: string[]) => void;
  onApiKeyChange: (values: string[]) => void;
  onModelChange: (values: string[]) => void;
  onStatusChange: (values: string[]) => void;
  onReset: () => void;
};

export function RequestFilters({
  filters,
  accountOptions,
  apiKeyOptions,
  modelOptions,
  statusOptions,
  viewMode,
  onSearchChange,
  onTimeframeChange,
  onViewModeChange,
  onAccountChange,
  onApiKeyChange,
  onModelChange,
  onStatusChange,
  onReset,
}: RequestFiltersProps) {
  return (
    <div className="space-y-2 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground/60" aria-hidden="true" />
          <Input
            value={filters.search}
            onChange={(event) => onSearchChange(event.target.value)}
            className="h-8 pl-9"
            placeholder="Search request id, account, API key, model, error..."
          />
        </div>

        <TimeframeSelect value={filters.timeframe} onChange={onTimeframeChange} />
        <div
          className="inline-flex h-8 items-center rounded-md border bg-background p-0.5"
          role="radiogroup"
          aria-label="Request log view mode"
        >
          {(["simplified", "expanded"] as const).map((mode) => {
            const selected = viewMode === mode;
            const label = mode === "simplified" ? "Simplified" : "Expanded";
            return (
              <button
                key={mode}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => onViewModeChange(mode)}
                className={cn(
                  "inline-flex h-6 items-center justify-center rounded-[5px] px-2.5 text-xs text-muted-foreground transition-colors",
                  selected
                    ? "bg-accent text-accent-foreground shadow-sm"
                    : "hover:bg-accent/60 hover:text-accent-foreground",
                )}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <MultiSelectFilter
          label="Accounts"
          values={filters.accountIds}
          options={accountOptions}
          onChange={onAccountChange}
        />
        <MultiSelectFilter
          label="API Keys"
          values={filters.apiKeyIds}
          options={apiKeyOptions}
          onChange={onApiKeyChange}
        />
        <MultiSelectFilter
          label="Models"
          values={filters.modelOptions}
          options={modelOptions}
          onChange={onModelChange}
        />
        <MultiSelectFilter
          label="Statuses"
          values={filters.statuses}
          options={statusOptions}
          onChange={onStatusChange}
        />

        <Button type="button" variant="ghost" size="sm" onClick={onReset} className="h-8 gap-1.5 text-xs text-muted-foreground">
          <RotateCcw className="h-3 w-3" aria-hidden="true" />
          Reset
        </Button>
      </div>
    </div>
  );
}
