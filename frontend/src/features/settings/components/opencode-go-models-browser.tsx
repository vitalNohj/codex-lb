import { useMemo, useState } from "react";
import { Check, ChevronDown, Plus } from "lucide-react";

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
  /**
   * False while the integration is switched off.
   *
   * The backend returns an empty catalogue without any upstream call when the
   * integration is disabled or unconfigured, so an empty list in that state
   * means "not asked", not "the provider has no models".
   */
  enabled: boolean;
  onAddModel: (modelId: string) => void;
};

const PROTOCOL_LABELS: Record<OpenCodeGoSidecarProtocol, string> = {
  chat_completions: "Chat Completions",
  messages: "Messages",
  responses: "Responses",
  unknown: "Protocol unknown",
};

/**
 * Why an advertised model cannot be selected.
 *
 * The backend sends `supported` and `protocol` but no prose reason, so the
 * wording is derived here from the protocol it did send. `unknown` means the
 * live listing returned an id the pinned docs map does not classify.
 */
function unsupportedReason(protocol: OpenCodeGoSidecarProtocol): string {
  return protocol === "unknown"
    ? "Not classified by the pinned model map"
    : `${PROTOCOL_LABELS[protocol]} routing not supported yet`;
}

/**
 * Discovered-model browser for OpenCode Go.
 *
 * Differs from the shared browser because OpenCode Go serves models across
 * three wire protocols and only `chat_completions` is dispatchable at this
 * milestone. A model the backend did not mark `supported` is listed and
 * visibly unavailable rather than hidden or offered, so an unsupported model is
 * never silently sent to a guessed endpoint.
 */
export function OpenCodeGoModelsBrowser({
  models,
  selectedModels,
  isLoading,
  configured,
  enabled,
  onAddModel,
}: OpenCodeGoModelsBrowserProps) {
  const [search, setSearch] = useState("");
  const [isOpen, setIsOpen] = useState(false);
  const selected = useMemo(
    () => new Set(selectedModels.map((model) => model.toLowerCase())),
    [selectedModels],
  );
  const supportedCount = useMemo(
    () => models.filter((model) => model.supported).length,
    [models],
  );
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) {
      return models;
    }
    return models.filter((model) => model.id.toLowerCase().includes(query));
  }, [models, search]);

  // Each empty state has a distinct cause, and saying "no models" when nothing
  // was ever requested would be untrue.
  const emptyMessage = isLoading
    ? "Loading models..."
    : !configured
      ? "No models loaded - add an API key to discover models"
      : !enabled
        ? "Models are not discovered while the integration is disabled. Enable it to load the catalogue."
        : "No models returned by OpenCode Go.";

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
              - {supportedCount} supported
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
                  return (
                    <li key={model.id} className="flex items-center justify-between gap-2 px-2 py-1.5">
                      <div className="min-w-0">
                        <div className="truncate font-mono text-xs">{model.id}</div>
                        <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[10px] text-muted-foreground">
                          <span>{PROTOCOL_LABELS[model.protocol]}</span>
                          {model.ownedBy ? <span>- {model.ownedBy}</span> : null}
                          {model.supported ? null : (
                            <span className="font-medium text-amber-600 dark:text-amber-400">
                              - Unavailable: {unsupportedReason(model.protocol)}
                            </span>
                          )}
                        </div>
                      </div>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="h-6 shrink-0 gap-1 px-2 text-[11px]"
                        aria-label={
                          !model.supported
                            ? `Unavailable ${model.id}`
                            : isSelected
                              ? `Added ${model.id}`
                              : `Add full model ${model.id}`
                        }
                        disabled={isSelected || !model.supported}
                        onClick={() => onAddModel(model.id)}
                      >
                        {isSelected ? (
                          <Check className="size-3" aria-hidden="true" />
                        ) : model.supported ? (
                          <Plus className="size-3" aria-hidden="true" />
                        ) : null}
                        {!model.supported ? "Unavailable" : isSelected ? "Added" : "Add full model"}
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
