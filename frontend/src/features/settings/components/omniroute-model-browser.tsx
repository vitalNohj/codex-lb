import { useMemo, useState } from "react";
import { Check, Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { OmniRouteSidecarModelSummary } from "@/features/settings/schemas";

export type OmniRouteModelBrowserProps = {
  models: OmniRouteSidecarModelSummary[];
  selectedModels: string[];
  isLoading: boolean;
  onAddModel: (modelId: string) => void;
  onRemoveModel: (modelId: string) => void;
};

export function OmniRouteModelBrowser({
  models,
  selectedModels,
  isLoading,
  onAddModel,
  onRemoveModel,
}: OmniRouteModelBrowserProps) {
  const [search, setSearch] = useState("");
  const selected = useMemo(() => new Set(selectedModels), [selectedModels]);

  const filtered = useMemo(() => {
    if (!search.trim()) return models;
    const query = search.toLowerCase();
    return models.filter((model) => model.id.toLowerCase().includes(query));
  }, [models, search]);

  if (models.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        {isLoading ? "Loading models..." : "No models loaded — save API key and test connection"}
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-medium">Discovered models ({models.length})</p>
      <Input
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder="Search models..."
        className="h-8 text-xs"
        aria-label="Search OmniRoute models"
      />
      <div className="max-h-64 divide-y overflow-y-auto rounded-md border">
        {filtered.map((model) => {
          const isSelected = selected.has(model.id);
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
                onClick={() => {
                  if (isSelected) {
                    onRemoveModel(model.id);
                  } else {
                    onAddModel(model.id);
                  }
                }}
              >
                {isSelected ? <Check className="size-3" aria-hidden="true" /> : <Plus className="size-3" aria-hidden="true" />}
                {isSelected ? "Selected" : "Add model"}
              </Button>
            </div>
          );
        })}
        {filtered.length === 0 ? (
          <div className="px-2 py-2 text-xs text-muted-foreground">No models match your search</div>
        ) : null}
      </div>
      {selectedModels.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {selectedModels.map((modelId) => (
            <button
              key={modelId}
              type="button"
              className="inline-flex items-center gap-1 rounded-full border bg-muted/30 px-2 py-1 font-mono text-[11px]"
              onClick={() => onRemoveModel(modelId)}
              aria-label={`Remove ${modelId}`}
            >
              {modelId}
              <X className="size-3" aria-hidden="true" />
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
