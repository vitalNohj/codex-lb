import { useMemo, useState } from "react";
import { Check, ChevronDown, Plus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export type DiscoveredModelSummary = {
  id: string;
  created?: number | null;
  ownedBy?: string | null;
  /** Short tags shown next to the id, e.g. "shared". */
  tags?: string[];
};

/**
 * Copy overrides for hosts that list something other than an integration's
 * discovered catalog (e.g. one CLIProxyAPI account's models). Every field
 * falls back to the integration wording.
 */
export type DiscoveredModelsBrowserLabels = {
  title?: string;
  searchPlaceholder?: string;
  emptyMessage?: string;
  loadingMessage?: string;
  noMatchMessage?: string;
  addAction?: string;
  addedAction?: string;
  addAriaLabel?: (modelId: string) => string;
  addedAriaLabel?: (modelId: string) => string;
};

export type DiscoveredModelsBrowserProps = {
  models: DiscoveredModelSummary[];
  selectedModels: string[];
  isLoading: boolean;
  searchLabel?: string;
  /** Disables every add button, e.g. while a catalog write is in flight. */
  disabled?: boolean;
  labels?: DiscoveredModelsBrowserLabels;
  /** Extra summary appended to the header, e.g. "2 listed". */
  summary?: string;
  onAddModel: (modelId: string) => void;
};

export function DiscoveredModelsBrowser({
  models,
  selectedModels,
  isLoading,
  searchLabel = "Search models",
  disabled = false,
  labels = {},
  summary,
  onAddModel,
}: DiscoveredModelsBrowserProps) {
  const [search, setSearch] = useState("");
  const [isOpen, setIsOpen] = useState(false);
  const selected = useMemo(() => new Set(selectedModels.map((model) => model.toLowerCase())), [selectedModels]);
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) {
      return models;
    }
    return models.filter((model) => model.id.toLowerCase().includes(query));
  }, [models, search]);
  const title = labels.title ?? "Discovered models";
  const addAction = labels.addAction ?? "Add full model";
  const addedAction = labels.addedAction ?? "Added";
  const addAriaLabel = labels.addAriaLabel ?? ((id: string) => `${addAction} ${id}`);
  const addedAriaLabel = labels.addedAriaLabel ?? ((id: string) => `${addedAction} ${id}`);

  return (
    <div className="rounded-md border bg-background/50">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs font-medium"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((current) => !current)}
      >
        <span className="min-w-0 truncate">
          {title} ({models.length})
          {summary ? <span className="ml-1.5 font-normal text-muted-foreground">· {summary}</span> : null}
        </span>
        <ChevronDown className={`size-3 shrink-0 transition-transform ${isOpen ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      {isOpen ? (
        <div className="space-y-2 border-t p-2">
          {models.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              {isLoading
                ? (labels.loadingMessage ?? "Loading models...")
                : (labels.emptyMessage ?? "No models loaded - add an API key to discover models")}
            </p>
          ) : (
            <>
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder={labels.searchPlaceholder ?? "Search models..."}
                className="h-8 text-xs"
                aria-label={searchLabel}
              />
              <div className="max-h-64 divide-y overflow-y-auto rounded-md border">
                {filtered.map((model) => {
                  const isSelected = selected.has(model.id.toLowerCase());
                  return (
                    <div key={model.id} className="flex items-center justify-between gap-2 px-2 py-1.5">
                      <div className="min-w-0">
                        <div className="flex min-w-0 items-center gap-1.5">
                          <span className="truncate font-mono text-xs">{model.id}</span>
                          {model.tags?.map((tag) => (
                            <Badge key={tag} variant="secondary" className="h-4 shrink-0 px-1.5 text-[10px] font-normal">
                              {tag}
                            </Badge>
                          ))}
                        </div>
                        {model.ownedBy ? (
                          <div className="truncate text-[10px] text-muted-foreground">{model.ownedBy}</div>
                        ) : null}
                      </div>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="h-6 shrink-0 gap-1 px-2 text-[11px]"
                        aria-label={isSelected ? addedAriaLabel(model.id) : addAriaLabel(model.id)}
                        disabled={isSelected || disabled}
                        onClick={() => onAddModel(model.id)}
                      >
                        {isSelected ? (
                          <Check className="size-3" aria-hidden="true" />
                        ) : (
                          <Plus className="size-3" aria-hidden="true" />
                        )}
                        {isSelected ? addedAction : addAction}
                        <span className="sr-only"> {model.id}</span>
                      </Button>
                    </div>
                  );
                })}
                {filtered.length === 0 ? (
                  <div className="px-2 py-2 text-xs text-muted-foreground">
                    {labels.noMatchMessage ?? "No models match your search"}
                  </div>
                ) : null}
              </div>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
