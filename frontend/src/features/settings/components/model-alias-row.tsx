import { useState } from "react";
import { ChevronDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  CUSTOM_ALIAS_CONTEXT_LENGTH_PRESETS,
  contextLengthSelectionFromValue,
  contextLengthValueFromSelection,
  type CustomAliasContextLengthSelection,
} from "@/features/settings/components/model-alias-catalog-options";
import type { CustomAliasCatalogEntry } from "@/features/settings/schemas";

type ModelAliasRowProps = {
  alias: string;
  target: string;
  catalogEntry?: CustomAliasCatalogEntry;
  busy: boolean;
  onRemove: () => void;
  onContextLengthChange: (contextLength: number | null) => void;
};

export function ModelAliasRow({
  alias,
  target,
  catalogEntry,
  busy,
  onRemove,
  onContextLengthChange,
}: ModelAliasRowProps) {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const selection = contextLengthSelectionFromValue(catalogEntry?.contextLength);

  const handleSelectionChange = (value: string) => {
    onContextLengthChange(
      contextLengthValueFromSelection(value as CustomAliasContextLengthSelection),
    );
  };

  return (
    <div className="rounded-md border bg-muted/10 p-2">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1 truncate rounded-md border bg-muted/20 px-2 py-1.5 text-xs">
          {target}
        </div>
        <span className="text-xs text-muted-foreground sm:px-1" aria-hidden="true">
          →
        </span>
        <div className="min-w-0 flex-1 truncate rounded-md border bg-muted/20 px-2 py-1.5 text-xs">
          {alias}
        </div>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-8 text-xs sm:w-24"
          disabled={busy}
          onClick={() => setAdvancedOpen((open) => !open)}
          aria-expanded={advancedOpen}
          aria-controls={`alias-advanced-${alias}`}
        >
          Advanced
          <ChevronDown className={`ml-1 size-3 transition-transform ${advancedOpen ? "rotate-180" : ""}`} />
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-8 text-xs sm:w-20"
          disabled={busy}
          onClick={onRemove}
        >
          Remove
        </Button>
      </div>
      {advancedOpen ? (
        <div
          id={`alias-advanced-${alias}`}
          className="mt-3 space-y-2 border-t border-border/60 pt-3"
        >
          <div className="space-y-1">
            <p className="text-xs font-medium">Advertised context length</p>
            <p className="text-xs text-muted-foreground">
              Only affects GET /v1/models for this alias. Routing and upstream limits are unchanged.
            </p>
          </div>
          <Select value={selection} onValueChange={handleSelectionChange} disabled={busy}>
            <SelectTrigger className="h-8 text-xs" aria-label={`Context length for ${alias}`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="start">
              {CUSTOM_ALIAS_CONTEXT_LENGTH_PRESETS.map((preset) => (
                <SelectItem key={preset.value} value={preset.value}>
                  {preset.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ) : null}
    </div>
  );
}
