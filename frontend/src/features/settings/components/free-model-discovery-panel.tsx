import { useState } from "react";
import { Radar } from "lucide-react";

import { AlertMessage } from "@/components/alert-message";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { FreeModelDiscoveryDialog } from "@/features/settings/components/free-model-discovery-dialog";
import {
  useFreeModelDiscoveryCurrentRun,
  useFreeModelDiscoveryMutations,
  useFreeModelDiscoveryPlan,
} from "@/features/settings/hooks/use-free-model-discovery";
import type {
  FreeModelDiscoveryRun,
  FreeModelDiscoveryRunItem,
  FreeModelItemState,
  FreeModelProvider,
  FreeModelRunStatus,
} from "@/features/settings/free-model-discovery-schemas";
import type { DashboardSettings } from "@/features/settings/schemas";
import { formatDateTimeInline } from "@/utils/formatters";
import { getErrorMessageOrNull } from "@/utils/errors";

export type FreeModelDiscoveryPanelProps = {
  settings: DashboardSettings;
};

const PROVIDER_LABELS: Record<FreeModelProvider, string> = {
  openrouter: "OpenRouter",
  orcarouter: "OrcaRouter",
};

const RUN_STATUS_LABELS: Record<FreeModelRunStatus, string> = {
  running: "Running",
  completed: "Completed",
  cancelled: "Cancelled",
  expired: "Expired",
  failed: "Failed",
};

const ITEM_STATE_LABELS: Record<FreeModelItemState, string> = {
  queued: "Queued",
  passed: "Passed",
  failed: "Failed",
  unresolved: "Unresolved",
};

function runStatusVariant(status: FreeModelRunStatus): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "running":
      return "default";
    case "completed":
      return "secondary";
    case "cancelled":
    case "expired":
      return "outline";
    case "failed":
      return "destructive";
  }
}

function itemStateVariant(state: FreeModelItemState): "default" | "secondary" | "destructive" | "outline" {
  switch (state) {
    case "passed":
      return "secondary";
    case "failed":
      return "destructive";
    case "unresolved":
      return "outline";
    case "queued":
      return "default";
  }
}

export function FreeModelDiscoveryPanel({ settings }: FreeModelDiscoveryPanelProps) {
  const anyProviderUsable =
    ((settings.openrouterSidecarEnabled ?? false) && (settings.openrouterSidecarApiKeyConfigured ?? false)) ||
    ((settings.orcarouterSidecarEnabled ?? false) && (settings.orcarouterSidecarApiKeyConfigured ?? false));
  const [dialogOpen, setDialogOpen] = useState(false);
  const planQuery = useFreeModelDiscoveryPlan({ enabled: dialogOpen });
  const runQuery = useFreeModelDiscoveryCurrentRun();
  const { startMutation, cancelMutation } = useFreeModelDiscoveryMutations();

  const run = runQuery.data ?? null;
  const running = run?.status === "running";
  // One run at a time. The server is the authority (it answers 409
  // `discovery_run_active`, and a partial unique index backs that up), so the
  // button reflects that rule rather than trying to enforce it: a run started
  // from another tab disables this one as soon as the query refreshes.
  const startDisabledReason = !anyProviderUsable
    ? "Enable OpenRouter or OrcaRouter with an API key first"
    : startMutation.isPending
      ? "Starting a run..."
      : running
        ? "A discovery run is already in progress"
        : null;
  const startButtonLabel = startMutation.isPending
    ? "Starting..."
    : running
      ? "Run in progress"
      : "Discover free models";

  return (
    <section aria-label="Free model discovery" className="space-y-3 rounded-md border bg-background/50 p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2.5">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-primary/10">
            <Radar className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
          </div>
          <div>
            <h3 className="text-sm font-semibold">Free model discovery</h3>
            <p className="text-xs text-muted-foreground">
              Compare OpenRouter and OrcaRouter free models against the pinned lists, probe the ones you choose, and
              pin every model that answers. Runs are paced to avoid rate limits and can take hours.
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {running && run ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={cancelMutation.isPending || run.cancelRequested}
              onClick={() => cancelMutation.mutate(run.id)}
            >
              {run.cancelRequested ? "Cancelling..." : "Cancel run"}
            </Button>
          ) : null}
          <Button
            type="button"
            size="sm"
            disabled={startDisabledReason !== null}
            // A disabled control with an unchanged label reads as broken, which
            // is exactly how "nothing happens when I click it" starts. The
            // label names the blocking state, and the tooltip/title carries the
            // same reason for a pointer user.
            title={startDisabledReason ?? undefined}
            onClick={() => setDialogOpen(true)}
          >
            {startButtonLabel}
          </Button>
        </div>
      </div>

      {!anyProviderUsable ? (
        <p className="text-xs text-muted-foreground">
          Enable OpenRouter or OrcaRouter with an API key to discover free models.
        </p>
      ) : null}

      {runQuery.error ? (
        <AlertMessage variant="error">{getErrorMessageOrNull(runQuery.error, "Failed to load run")}</AlertMessage>
      ) : null}

      {run ? <RunSummary run={run} /> : null}

      <FreeModelDiscoveryDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        plan={planQuery.data}
        isLoading={planQuery.isLoading}
        // A rejected start (e.g. background automations disabled) must be as
        // visible as a failed plan, otherwise confirming the dialog silently
        // does nothing.
        error={
          getErrorMessageOrNull(startMutation.error, "Failed to start discovery run") ??
          getErrorMessageOrNull(planQuery.error, "Failed to build discovery plan")
        }
        busy={startMutation.isPending}
        onStart={async (payload) => {
          await startMutation.mutateAsync(payload);
          setDialogOpen(false);
        }}
      />
    </section>
  );
}

function RunSummary({ run }: { run: FreeModelDiscoveryRun }) {
  const [detailsOpen, setDetailsOpen] = useState(run.status === "running");
  const done = run.counts.total - run.counts.queued;
  const percent = run.counts.total === 0 ? 100 : Math.round((done / run.counts.total) * 100);

  return (
    <div className="space-y-2" data-testid="free-model-discovery-run">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge variant={runStatusVariant(run.status)}>{RUN_STATUS_LABELS[run.status]}</Badge>
        <span className="text-muted-foreground">
          Started {formatDateTimeInline(run.startedAt)}
          {run.finishedAt ? ` / finished ${formatDateTimeInline(run.finishedAt)}` : ""}
        </span>
        <span className="ml-auto tabular-nums text-muted-foreground">
          {done}/{run.counts.total} resolved
        </span>
      </div>
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-label="Discovery run progress"
        aria-valuemin={0}
        aria-valuemax={run.counts.total}
        aria-valuenow={done}
      >
        <div className="h-full bg-primary transition-[width]" style={{ width: `${percent}%` }} />
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>
          <span className="font-medium text-foreground">{run.counts.passed}</span> passed
        </span>
        <span>
          <span className="font-medium text-foreground">{run.counts.added}</span> pinned
        </span>
        <span>
          <span className="font-medium text-foreground">{run.counts.failed}</span> failed
        </span>
        <span>
          <span className="font-medium text-foreground">{run.counts.unresolved}</span> unresolved
        </span>
        <span>
          <span className="font-medium text-foreground">{run.counts.queued}</span> queued
        </span>
      </div>
      {run.status === "running" ? (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
          {run.providers.map((provider) => (
            <span key={provider.provider}>
              {PROVIDER_LABELS[provider.provider]}: {provider.counts.queued} queued
              {provider.currentIntervalSeconds != null ? `, pace ${Math.round(provider.currentIntervalSeconds)}s` : ""}
              {provider.nextProbeAt ? `, next ${formatDateTimeInline(provider.nextProbeAt)}` : ""}
            </span>
          ))}
        </div>
      ) : null}
      {run.errorMessage ? <AlertMessage variant="error">{run.errorMessage}</AlertMessage> : null}

      <Collapsible open={detailsOpen} onOpenChange={setDetailsOpen}>
        <CollapsibleTrigger asChild>
          <Button type="button" variant="ghost" size="sm" className="h-7 px-2 text-xs">
            {detailsOpen ? "Hide models" : `Show models (${run.items.length})`}
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <ul className="mt-2 max-h-72 divide-y overflow-y-auto rounded-md border">
            {run.items.map((item) => (
              <RunItemRow key={`${item.provider}:${item.modelId}`} item={item} />
            ))}
          </ul>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}

function RunItemRow({ item }: { item: FreeModelDiscoveryRunItem }) {
  const diagnostics: string[] = [];
  if (item.attempts > 0) {
    diagnostics.push(`${item.attempts} attempt${item.attempts === 1 ? "" : "s"}`);
  }
  if (item.lastHttpStatus != null) {
    diagnostics.push(`HTTP ${item.lastHttpStatus}`);
  }
  if (item.state === "passed") {
    diagnostics.push(item.contentOkMatch ? "said ok" : `${item.contentChars ?? 0} chars`);
    if ((item.reasoningChars ?? 0) > 2) {
      diagnostics.push("reasoned");
    }
  }
  if (item.state === "queued" && item.nextAttemptAt) {
    diagnostics.push(`retry ${formatDateTimeInline(item.nextAttemptAt)}`);
  }
  if (item.lastOutcome && item.state !== "passed") {
    diagnostics.push(item.lastOutcome);
  }
  return (
    <li className="flex items-center justify-between gap-2 px-2 py-1.5">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate font-mono text-xs">{item.modelId}</span>
          <span className="text-[10px] text-muted-foreground">{PROVIDER_LABELS[item.provider]}</span>
          {item.addedToFullModels ? (
            <Badge variant="outline" className="h-4 px-1 text-[10px]">
              pinned
            </Badge>
          ) : null}
        </div>
        {diagnostics.length > 0 ? (
          <div className="truncate text-[10px] text-muted-foreground">{diagnostics.join(" / ")}</div>
        ) : null}
      </div>
      <Badge variant={itemStateVariant(item.state)} className="shrink-0">
        {ITEM_STATE_LABELS[item.state]}
      </Badge>
    </li>
  );
}
