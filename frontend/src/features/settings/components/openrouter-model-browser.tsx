import { useMemo, useState } from "react";
import { ChevronDown, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { prefixFromModelId } from "@/features/settings/components/openrouter-popular-models";
import type { OpenRouterSidecarModelSummary } from "@/features/settings/schemas";

export type OpenRouterModelBrowserProps = {
  models: OpenRouterSidecarModelSummary[];
  isLoading: boolean;
  onAddPrefix: (prefix: string) => void;
};

export function OpenRouterModelBrowser({ models, isLoading, onAddPrefix }: OpenRouterModelBrowserProps) {
  const [search, setSearch] = useState("");
  const [isOpen, setIsOpen] = useState(false);

  const filtered = useMemo(() => {
    if (!search.trim()) return models;
    const q = search.toLowerCase();
    return models.filter((model) => model.id.toLowerCase().includes(q));
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
              {isLoading ? "Loading models..." : "No models loaded — save API key and test connection"}
            </p>
          ) : (
            <>
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search models..."
                className="h-8 text-xs"
                aria-label="Search models"
              />
              <div className="max-h-64 divide-y overflow-y-auto rounded-md border">
                {filtered.map((model) => (
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
                      onClick={() => onAddPrefix(prefixFromModelId(model.id))}
                    >
                      <Plus className="size-3" aria-hidden="true" />
                      Add prefix
                    </Button>
                  </div>
                ))}
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
