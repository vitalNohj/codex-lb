import { useMemo, useState } from "react";
import { Check, ChevronDown, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export type DiscoveredModelSummary = {
  id: string;
  created?: number | null;
  ownedBy?: string | null;
};

export type DiscoveredModelsBrowserProps = {
  models: DiscoveredModelSummary[];
  selectedModels: string[];
  isLoading: boolean;
  searchLabel?: string;
  onAddModel: (modelId: string) => void;
};

export function DiscoveredModelsBrowser({
  models,
  selectedModels,
  isLoading,
  searchLabel = "Search models",
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

  return (
    <div className="rounded-md border bg-background/50">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs font-medium"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((current) => !current)}
      >
        <span>Discovered models ({models.length})</span>
        <ChevronDown className={`size-3 transition-transform ${isOpen ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      {isOpen ? (
        <div className="space-y-2 border-t p-2">
          {models.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              {isLoading ? "Loading models..." : "No models loaded - add an API key to discover models"}
            </p>
          ) : (
            <>
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search models..."
                className="h-8 text-xs"
                aria-label={searchLabel}
              />
              <div className="max-h-64 divide-y overflow-y-auto rounded-md border">
                {filtered.map((model) => {
                  const isSelected = selected.has(model.id.toLowerCase());
                  return (
                    <div key={model.id} className="flex items-center justify-between gap-2 px-2 py-1.5">
                      <div className="min-w-0">
                        <div className="truncate font-mono text-xs">{model.id}</div>
                        {model.ownedBy ? (
                          <div className="truncate text-[10px] text-muted-foreground">{model.ownedBy}</div>
                        ) : null}
                      </div>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="h-6 shrink-0 gap-1 px-2 text-[11px]"
                        aria-label={`${isSelected ? "Added" : "Add full model"} ${model.id}`}
                        disabled={isSelected}
                        onClick={() => onAddModel(model.id)}
                      >
                        {isSelected ? (
                          <Check className="size-3" aria-hidden="true" />
                        ) : (
                          <Plus className="size-3" aria-hidden="true" />
                        )}
                        {isSelected ? "Added" : "Add full model"}
                        <span className="sr-only"> {model.id}</span>
                      </Button>
                    </div>
                  );
                })}
                {filtered.length === 0 ? (
                  <div className="px-2 py-2 text-xs text-muted-foreground">No models match your search</div>
                ) : null}
              </div>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
