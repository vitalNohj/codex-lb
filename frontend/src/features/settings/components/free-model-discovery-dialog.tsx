import { useMemo, useState } from "react";
import { ChevronDown } from "lucide-react";

import { AlertMessage } from "@/components/alert-message";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { SpinnerBlock } from "@/components/ui/spinner";
import type {
  FreeModelCandidate,
  FreeModelCandidateGroup,
  FreeModelDiscoveryPlan,
  FreeModelDiscoveryStartRequest,
  FreeModelProvider,
  FreeModelProviderPlan,
} from "@/features/settings/free-model-discovery-schemas";
import { formatDateTimeInline } from "@/utils/formatters";
import { cn } from "@/lib/utils";

export type FreeModelDiscoveryDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  plan: FreeModelDiscoveryPlan | undefined;
  isLoading: boolean;
  error: string | null;
  busy: boolean;
  onStart: (payload: FreeModelDiscoveryStartRequest) => Promise<unknown>;
};

const PROVIDER_LABELS: Record<FreeModelProvider, string> = {
  openrouter: "OpenRouter",
  orcarouter: "OrcaRouter",
};

const GROUP_ORDER: FreeModelCandidateGroup[] = ["new", "unresolved", "due", "cooldown"];

const GROUP_META: Record<FreeModelCandidateGroup, { label: string; description: string; defaultChecked: boolean }> = {
  new: { label: "New", description: "Never probed.", defaultChecked: true },
  unresolved: {
    label: "Unresolved",
    description: "The last run could not get a clean answer.",
    defaultChecked: true,
  },
  due: { label: "Due for re-test", description: "Probed before and eligible again.", defaultChecked: true },
  cooldown: {
    label: "In cooldown",
    description: "Failed recently. Checking these re-tests them early.",
    defaultChecked: false,
  },
};

function selectionKey(candidate: Pick<FreeModelCandidate, "provider" | "modelId">): string {
  return `${candidate.provider}\u0000${candidate.modelId}`;
}

/**
 * Selection is derived: each candidate defaults by group, and the operator's
 * explicit checks/unchecks are kept as overrides keyed by candidate. A fresh
 * plan therefore reapplies group defaults without an effect.
 */
function deriveSelection(plan: FreeModelDiscoveryPlan | undefined, overrides: Map<string, boolean>): Set<string> {
  const selected = new Set<string>();
  for (const providerPlan of plan?.providers ?? []) {
    for (const candidate of providerPlan.candidates) {
      const key = selectionKey(candidate);
      const checked = overrides.get(key) ?? GROUP_META[candidate.group].defaultChecked;
      if (checked) {
        selected.add(key);
      }
    }
  }
  return selected;
}

function providerStatusMessage(providerPlan: FreeModelProviderPlan): string | null {
  switch (providerPlan.status) {
    case "ok":
      return null;
    case "disabled":
      return "Integration is disabled.";
    case "missing_api_key":
      return "No API key configured.";
    case "unreachable":
      return `Unreachable: ${providerPlan.message ?? "connection failed"}`;
    case "error":
      return `Error: ${providerPlan.message ?? "request failed"}`;
  }
}

export function FreeModelDiscoveryDialog({
  open,
  onOpenChange,
  plan,
  isLoading,
  error,
  busy,
  onStart,
}: FreeModelDiscoveryDialogProps) {
  const [overrides, setOverrides] = useState<Map<string, boolean>>(() => new Map());
  const selected = useMemo(() => deriveSelection(plan, overrides), [plan, overrides]);

  const totalCandidates = useMemo(
    () => (plan?.providers ?? []).reduce((sum, providerPlan) => sum + providerPlan.candidates.length, 0),
    [plan],
  );

  const toggle = (candidate: FreeModelCandidate, checked: boolean) => {
    setOverrides((current) => new Map(current).set(selectionKey(candidate), checked));
  };

  const toggleGroup = (candidates: FreeModelCandidate[], checked: boolean) => {
    setOverrides((current) => {
      const next = new Map(current);
      for (const candidate of candidates) {
        next.set(selectionKey(candidate), checked);
      }
      return next;
    });
  };

  const handleStart = async () => {
    const selections: FreeModelDiscoveryStartRequest["selections"] = [];
    for (const providerPlan of plan?.providers ?? []) {
      for (const candidate of providerPlan.candidates) {
        if (selected.has(selectionKey(candidate))) {
          selections.push({ provider: candidate.provider, modelId: candidate.modelId });
        }
      }
    }
    if (selections.length === 0) {
      return;
    }
    await onStart({ selections });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Discover free models</DialogTitle>
          <DialogDescription>
            Each checked model gets one probe request per attempt. Probes run one at a time per provider with a
            growing delay after rate limits, so a run can take hours. Passed models are added to the provider&apos;s
            full-model list as they pass.
          </DialogDescription>
        </DialogHeader>

        {isLoading ? <SpinnerBlock label="Comparing router catalogs..." /> : null}
        {error ? <AlertMessage variant="error">{error}</AlertMessage> : null}

        {plan && !isLoading ? (
          <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
            {plan.providers.map((providerPlan) => (
              <ProviderSection
                key={providerPlan.provider}
                providerPlan={providerPlan}
                selected={selected}
                onToggle={toggle}
                onToggleGroup={toggleGroup}
              />
            ))}
            {totalCandidates === 0 ? (
              <p className="text-xs text-muted-foreground">
                Nothing to test. Every free model on the enabled routers is already pinned.
              </p>
            ) : null}
          </div>
        ) : null}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button type="button" onClick={() => void handleStart()} disabled={busy || isLoading || selected.size === 0}>
            {busy ? "Starting..." : `Start run (${selected.size})`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

type ProviderSectionProps = {
  providerPlan: FreeModelProviderPlan;
  selected: Set<string>;
  onToggle: (candidate: FreeModelCandidate, checked: boolean) => void;
  onToggleGroup: (candidates: FreeModelCandidate[], checked: boolean) => void;
};

function ProviderSection({ providerPlan, selected, onToggle, onToggleGroup }: ProviderSectionProps) {
  const label = PROVIDER_LABELS[providerPlan.provider];
  const statusMessage = providerStatusMessage(providerPlan);
  const grouped = useMemo(() => {
    const byGroup = new Map<FreeModelCandidateGroup, FreeModelCandidate[]>();
    for (const group of GROUP_ORDER) {
      byGroup.set(group, []);
    }
    for (const candidate of providerPlan.candidates) {
      byGroup.get(candidate.group)?.push(candidate);
    }
    return byGroup;
  }, [providerPlan.candidates]);

  return (
    <section aria-label={`${label} candidates`} className="space-y-2 rounded-md border p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">{label}</h3>
        {statusMessage ? (
          <span className="text-xs text-muted-foreground">{statusMessage}</span>
        ) : (
          <span className="text-xs text-muted-foreground">
            {providerPlan.freeCount} free of {providerPlan.discoveredCount} listed, {providerPlan.alreadyPinnedCount}{" "}
            already pinned
            {providerPlan.skippedSelectorCount > 0
              ? `, ${providerPlan.skippedSelectorCount} router selector skipped`
              : ""}
          </span>
        )}
      </div>
      {!statusMessage && providerPlan.candidates.length === 0 ? (
        <p className="text-xs text-muted-foreground">No untested free models.</p>
      ) : null}
      {GROUP_ORDER.map((group) => {
        const candidates = grouped.get(group) ?? [];
        if (candidates.length === 0) {
          return null;
        }
        return (
          <CandidateGroup
            key={group}
            group={group}
            candidates={candidates}
            selected={selected}
            onToggle={onToggle}
            onToggleGroup={onToggleGroup}
          />
        );
      })}
    </section>
  );
}

type CandidateGroupProps = {
  group: FreeModelCandidateGroup;
  candidates: FreeModelCandidate[];
  selected: Set<string>;
  onToggle: (candidate: FreeModelCandidate, checked: boolean) => void;
  onToggleGroup: (candidates: FreeModelCandidate[], checked: boolean) => void;
};

function CandidateGroup({ group, candidates, selected, onToggle, onToggleGroup }: CandidateGroupProps) {
  const meta = GROUP_META[group];
  const [open, setOpen] = useState(meta.defaultChecked);
  const selectedCount = candidates.filter((candidate) => selected.has(selectionKey(candidate))).length;
  const allSelected = selectedCount === candidates.length;
  const groupCheckboxId = `free-model-group-${candidates[0]?.provider ?? "none"}-${group}`;

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="rounded-md border bg-background/50">
      <div className="flex items-center gap-2 px-2 py-1.5">
        <Checkbox
          id={groupCheckboxId}
          checked={allSelected ? true : selectedCount > 0 ? "indeterminate" : false}
          onCheckedChange={(checked) => onToggleGroup(candidates, checked === true)}
          aria-label={`Select all ${meta.label.toLowerCase()} ${candidates[0]?.provider ?? ""} models`}
        />
        <CollapsibleTrigger asChild>
          <button type="button" className="flex flex-1 items-center justify-between gap-2 text-left">
            <span className="text-xs font-medium">
              {meta.label} ({selectedCount}/{candidates.length})
              <span className="ml-2 font-normal text-muted-foreground">{meta.description}</span>
            </span>
            <ChevronDown
              className={cn("size-3 shrink-0 transition-transform", open ? "rotate-180" : "")}
              aria-hidden="true"
            />
          </button>
        </CollapsibleTrigger>
      </div>
      <CollapsibleContent>
        <ul className="max-h-56 divide-y overflow-y-auto border-t">
          {candidates.map((candidate) => {
            const key = selectionKey(candidate);
            const id = `free-model-${candidate.provider}-${candidate.modelId}`;
            return (
              <li key={key} className="flex items-center gap-2 px-2 py-1.5">
                <Checkbox
                  id={id}
                  checked={selected.has(key)}
                  onCheckedChange={(checked) => onToggle(candidate, checked === true)}
                  aria-label={`Probe ${candidate.modelId}`}
                />
                <label htmlFor={id} className="min-w-0 flex-1 cursor-pointer">
                  <span className="block truncate font-mono text-xs">{candidate.modelId}</span>
                  <span className="block truncate text-[10px] text-muted-foreground">
                    {candidateDetail(candidate)}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}

function candidateDetail(candidate: FreeModelCandidate): string {
  const parts: string[] = [];
  if (candidate.ownedBy) {
    parts.push(candidate.ownedBy);
  }
  if (candidate.lastVerdict && candidate.lastVerdictAt) {
    parts.push(`last ${candidate.lastVerdict} ${formatDateTimeInline(candidate.lastVerdictAt)}`);
  }
  if (candidate.group === "cooldown" && candidate.cooldownUntil) {
    parts.push(`cooldown until ${formatDateTimeInline(candidate.cooldownUntil)}`);
  }
  if (candidate.failureStreak > 1) {
    parts.push(`${candidate.failureStreak} consecutive failures`);
  }
  return parts.join(" / ");
}
