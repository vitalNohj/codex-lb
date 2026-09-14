import { useMemo, useState } from "react";
import { Check, ChevronDown, Plus, ShieldAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type {
  OpenCodeGoSidecarModelSummary,
  OpenCodeGoSidecarProtocol,
} from "@/features/settings/schemas";

export type OpenCodeGoModelsBrowserProps = {
  models: OpenCodeGoSidecarModelSummary[];
  selectedModels: string[];
  isLoading: boolean;
  /** False while the integration has no key, so discovery cannot run at all. */
  configured: boolean;
  onAddModel: (modelId: string) => void;
};

const PROTOCOL_LABELS: Record<OpenCodeGoSidecarProtocol, string> = {
  chat_completions: "Chat Completions",
  messages: "Messages",
  responses: "Responses",
};

/**
 * Discovered-model browser for OpenCode Go.
 *
 * Differs from the shared browser in exactly the ways the provider forces:
 *
 * - OpenCode Go serves models on three different wire protocols and the
 *   published mapping is known to drift, so a model the backend has not marked
 *   routable is shown as unavailable rather than silently offered. An unknown
 *   protocol is never treated as a working default.
 * - Some models are documented as training on prompts and lacking zero data
 *   retention. Those are labelled and still selectable, but never preselected.
 */
export function OpenCodeGoModelsBrowser({
  models,
  selectedModels,
  isLoading,
  configured,
  onAddModel,
}: OpenCodeGoModelsBrowserProps) {
  const [search, setSearch] = useState("");
  const [isOpen, setIsOpen] = useState(false);
  const selected = useMemo(
    () => new Set(selectedModels.map((model) => model.toLowerCase())),
    [selectedModels],
  );
  const routableCount = useMemo(() => models.filter((model) => model.routable).length, [models]);
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) {
      return models;
    }
    return models.filter((model) => model.id.toLowerCase().includes(query));
  }, [models, search]);

  const emptyMessage = isLoading
    ? "Loading models..."
    : configured
      ? "No models returned by OpenCode Go."
      : "No models loaded - add an API key to discover models";

  return (
    <div className="rounded-md border bg-background/50">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs font-medium"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((current) => !current)}
      >
        <span>
          Discovered models ({models.length})
          {models.length > 0 ? (
            <span className="ml-1 font-normal text-muted-foreground">
              - {routableCount} routable
            </span>
          ) : null}
        </span>
        <ChevronDown
          className={`size-3 transition-transform ${isOpen ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
      </button>
      {isOpen ? (
        <div className="space-y-2 border-t p-2">
          {models.length === 0 ? (
            <p className="text-xs text-muted-foreground">{emptyMessage}</p>
          ) : (
            <>
              <p className="text-xs text-muted-foreground">
                Only models codex-lb can route today are selectable. The rest are listed so an
                unsupported model is visibly unavailable rather than silently sent to a guessed
                endpoint.
              </p>
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search models..."
                className="h-8 text-xs"
                aria-label="Search OpenCode Go models"
              />
              <ul className="max-h-64 divide-y overflow-y-auto rounded-md border">
                {filtered.map((model) => {
                  const isSelected = selected.has(model.id.toLowerCase());
                  const protocolLabel = model.protocol
                    ? PROTOCOL_LABELS[model.protocol]
                    : "Protocol unknown";
                  return (
                    <li key={model.id} className="flex items-center justify-between gap-2 px-2 py-1.5">
                      <div className="min-w-0">
                        <div className="truncate font-mono text-xs">{model.id}</div>
                        <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[10px] text-muted-foreground">
                          <span>{protocolLabel}</span>
                          {model.ownedBy ? <span>- {model.ownedBy}</span> : null}
                          {model.routable ? null : (
                            <span className="font-medium text-amber-600 dark:text-amber-400">
                              - Unavailable
                              {model.unavailableReason ? `: ${model.unavailableReason}` : ""}
                            </span>
                          )}
                          {model.privacySensitive ? (
                            <span className="inline-flex items-center gap-0.5 font-medium text-amber-600 dark:text-amber-400">
                              <ShieldAlert className="size-2.5" aria-hidden="true" />
                              {model.privacyNote ?? "Prompts may be used for training"}
                            </span>
                          ) : null}
                        </div>
                      </div>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="h-6 shrink-0 gap-1 px-2 text-[11px]"
                        aria-label={
                          !model.routable
                            ? `Unavailable ${model.id}`
                            : isSelected
                              ? `Added ${model.id}`
                              : `Add full model ${model.id}`
                        }
                        disabled={isSelected || !model.routable}
                        onClick={() => onAddModel(model.id)}
                      >
                        {isSelected ? (
                          <Check className="size-3" aria-hidden="true" />
                        ) : model.routable ? (
                          <Plus className="size-3" aria-hidden="true" />
                        ) : null}
                        {!model.routable ? "Unavailable" : isSelected ? "Added" : "Add full model"}
                      </Button>
                    </li>
                  );
                })}
                {filtered.length === 0 ? (
                  <li className="px-2 py-2 text-xs text-muted-foreground">
                    No models match your search
                  </li>
                ) : null}
              </ul>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
