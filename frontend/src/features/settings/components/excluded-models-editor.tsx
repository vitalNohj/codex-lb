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
import type { ExcludedModelsState } from "@/features/settings/lib/excluded-models-state";

/** Mirrors `MAX_PATTERN_LENGTH` in app/modules/claude_sidecar/excluded_models.py. */
export const MAX_PATTERN_LENGTH = 128;
/** Mirrors `MAX_PATTERNS` in app/modules/claude_sidecar/excluded_models.py. */
export const MAX_PATTERNS = 32;

export type ExcludedModelsEditorProps = {
  /** CLIProxyAPI auth-file name this list belongs to. */
  name: string;
  /** Human label for this account, used in accessible control names. */
  emailLabel: string;
  excludedModels: string[];
  disabled?: boolean;
  /**
   * How this account's stored list must be presented.
   *
   * `unreadable` means codex-lb could not read the real list, so saving the
   * list shown would wipe exclusions set by hand: report the failure and lock
   * every control. `unsupported` means this row has no CLIProxyAPI auth file to
   * edit; that is not a failure, so it is stated neutrally.
   */
  state?: ExcludedModelsState;
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
  state = "available",
  onChange,
}: ExcludedModelsEditorProps) {
  const [draft, setDraft] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  const inputId = useId();
  const custom = customPatterns(excludedModels);
  const locked = disabled || state !== "available";

  const addDraft = () => {
    const pattern = draft.trim();
    if (!pattern) return;
    // The backend silently drops a pattern containing a comma or longer than
    // MAX_PATTERN_LENGTH, and rejects a list beyond MAX_PATTERNS, so refuse
    // them here rather than let a pattern vanish after a successful save.
    if (pattern.includes(",")) {
      setHint("One pattern at a time; a comma is not allowed");
      return;
    }
    if (pattern.length > MAX_PATTERN_LENGTH) {
      setHint(`Keep the pattern under ${MAX_PATTERN_LENGTH} characters`);
      return;
    }
    // CLIProxyAPI matches wire model ids; a cc/-prefixed alias would never
    // match, so the exclusion would silently do nothing.
    if (pattern.toLowerCase().startsWith("cc/")) {
      setHint("Use the CLIProxyAPI wire id (claude-...), not the cc/ prefix");
      return;
    }
    const exists = excludedModels.some(
      (entry) => entry.toLowerCase() === pattern.toLowerCase(),
    );
    if (!exists && excludedModels.length >= MAX_PATTERNS) {
      setHint(`At most ${MAX_PATTERNS} patterns; remove one first`);
      return;
    }
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
      {state === "unreadable" ? (
        <p role="alert" className="text-[11px] text-destructive">
          Could not read this account&apos;s excluded models. Editing is disabled so a
          save cannot overwrite them.
        </p>
      ) : null}
      {state === "unsupported" ? (
        <p className="text-[11px] text-muted-foreground">
          Excluded models are not available for this row.
        </p>
      ) : null}
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
                disabled={locked}
                aria-label={`Exclude ${family.label} on ${emailLabel}`}
                onCheckedChange={(next) => {
                  const updated = toggleFamily(family.id, excludedModels, next);
                  if (updated.length > MAX_PATTERNS) {
                    setHint(`At most ${MAX_PATTERNS} patterns; remove one first`);
                    return;
                  }
                  setHint(null);
                  onChange(updated);
                }}
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
                disabled={locked}
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
          disabled={locked}
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
          disabled={locked}
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
