import { useId, useState } from "react";
import { X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  EXCLUDED_MODEL_FAMILIES,
  customPatterns,
  isFamilyExcluded,
  toggleFamily,
} from "@/features/settings/lib/excluded-model-families";

export type ExcludedModelsEditorProps = {
  /** CLIProxyAPI auth-file name this list belongs to. */
  name: string;
  /** Human label for this account, used in accessible control names. */
  emailLabel: string;
  excludedModels: string[];
  disabled?: boolean;
  onChange: (next: string[]) => void;
};

/**
 * Add and remove per-account CLIProxyAPI model exclusions.
 *
 * Every toggle, add, and removal autosaves through `onChange` with the account's
 * full resulting list; there is deliberately no Save button, matching the pause
 * control this editor sits beside.
 */
export function ExcludedModelsEditor({
  name,
  emailLabel,
  excludedModels,
  disabled = false,
  onChange,
}: ExcludedModelsEditorProps) {
  const [draft, setDraft] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  const inputId = useId();
  const custom = customPatterns(excludedModels);

  const addDraft = () => {
    const pattern = draft.trim();
    if (!pattern) return;
    // CLIProxyAPI matches wire model ids; a cc/-prefixed alias would never
    // match, so the exclusion would silently do nothing.
    if (pattern.toLowerCase().startsWith("cc/")) {
      setHint("Use the CLIProxyAPI wire id (claude-...), not the cc/ prefix");
      return;
    }
    const exists = excludedModels.some(
      (entry) => entry.toLowerCase() === pattern.toLowerCase(),
    );
    setHint(null);
    setDraft("");
    if (exists) return;
    onChange([...excludedModels, pattern]);
  };

  return (
    <div className="space-y-2" aria-label={`Excluded models for ${emailLabel}`}>
      <div>
        <p className="text-xs font-medium">Excluded models</p>
        <p className="text-[11px] text-muted-foreground">
          CLIProxyAPI will not route these models to this account.
        </p>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1.5">
        {EXCLUDED_MODEL_FAMILIES.map((family) => {
          const excluded = isFamilyExcluded(family.id, excludedModels);
          return (
            <label
              key={family.id}
              className="flex items-center gap-1.5 text-[11px] font-medium"
              htmlFor={`${inputId}-${family.id}`}
            >
              <Switch
                id={`${inputId}-${family.id}`}
                size="sm"
                checked={excluded}
                disabled={disabled}
                aria-label={`Exclude ${family.label} on ${emailLabel}`}
                onCheckedChange={(next) =>
                  onChange(toggleFamily(family.id, excludedModels, next))
                }
              />
              {family.label}
            </label>
          );
        })}
      </div>
      {custom.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {custom.map((pattern) => (
            <Badge key={pattern} variant="secondary" className="gap-1 font-mono text-[11px]">
              {pattern}
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="-mr-1.5 h-4 w-4 p-0"
                disabled={disabled}
                aria-label={`Remove ${pattern} from ${emailLabel}`}
                onClick={() => onChange(excludedModels.filter((entry) => entry !== pattern))}
              >
                <X className="h-3 w-3" />
              </Button>
            </Badge>
          ))}
        </div>
      ) : null}
      <div className="flex items-center gap-1.5">
        <Input
          id={inputId}
          value={draft}
          disabled={disabled}
          aria-label={`Add excluded model pattern for ${emailLabel}`}
          placeholder="claude-fable-*"
          className="h-8 flex-1 font-mono text-xs"
          onChange={(event) => {
            setDraft(event.target.value);
            setHint(null);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              addDraft();
            }
          }}
        />
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-8 text-xs"
          disabled={disabled}
          aria-label={`Add excluded model pattern to ${name}`}
          onClick={addDraft}
        >
          Add
        </Button>
      </div>
      {hint ? (
        <p role="alert" className="text-[11px] text-destructive">
          {hint}
        </p>
      ) : null}
      <p className="text-[11px] text-muted-foreground">
        Wildcards: exact, prefix-*, *-suffix, *substr*. Stored as CLIProxyAPI wire ids, not cc/.
      </p>
    </div>
  );
}
