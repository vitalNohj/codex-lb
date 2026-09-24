import { useId, useState } from "react";
import { ArrowDown, ArrowUp, ChevronDown, Plus, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import type { AliasPoolTargetHealth, CustomAliasCatalogEntry } from "@/features/settings/schemas";
import { cn } from "@/lib/utils";
import { formatClockTime } from "@/utils/formatters";

/** Mirrors `MAX_POOL_TARGETS` on the server so the editor stops where the save would. */
export const MAX_POOL_TARGETS = 16;

export type ModelAliasRowError = {
  message: string;
  /** Target the server singled out, when it named one. */
  target: string | null;
};

type ModelAliasRowProps = {
  alias: string;
  targets: string[];
  health?: Record<string, AliasPoolTargetHealth>;
  /** Known model ids offered as completions when adding a target. */
  knownModelIds: string[];
  catalogEntry?: CustomAliasCatalogEntry;
  /** Server rejection for the last save of this row, shown inline. */
  error?: ModelAliasRowError;
  busy: boolean;
  onTargetsChange: (targets: string[]) => void;
  onRemove: () => void;
  onContextLengthChange: (contextLength: number | null) => void;
};

function moveItem<T>(items: T[], from: number, to: number): T[] {
  const next = [...items];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item as T);
  return next;
}

function TargetHealthBadge({ health }: { health: AliasPoolTargetHealth | undefined }) {
  const { t } = useTranslation();
  if (health === undefined || health.state === "healthy") {
    return (
      <span
        className="inline-flex items-center gap-1 text-[11px] text-muted-foreground"
        data-testid="alias-target-health"
        data-state="healthy"
      >
        <span className="size-1.5 rounded-full bg-emerald-500" aria-hidden="true" />
        {t("settings.routing.modelAliases.health.healthy")}
      </span>
    );
  }
  const detail = [
    health.lastStatus === null || health.lastStatus === undefined ? null : String(health.lastStatus),
    health.lastError ?? null,
  ]
    .filter((part): part is string => part !== null && part.length > 0)
    .join(" ");
  return (
    <span
      className="inline-flex items-center gap-1 text-[11px] text-amber-600 dark:text-amber-400"
      data-testid="alias-target-health"
      data-state="cooling"
      title={detail}
    >
      <span className="size-1.5 rounded-full bg-amber-500" aria-hidden="true" />
      {t("settings.routing.modelAliases.health.cooling", {
        until: formatClockTime(health.until),
        status: health.lastStatus ?? "?",
      })}
    </span>
  );
}

export function ModelAliasRow({
  alias,
  targets,
  health,
  knownModelIds,
  catalogEntry,
  error,
  busy,
  onTargetsChange,
  onRemove,
  onContextLengthChange,
}: ModelAliasRowProps) {
  const { t } = useTranslation();
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [newTarget, setNewTarget] = useState("");
  const datalistId = useId();
  const advancedId = useId();
  const selection = contextLengthSelectionFromValue(catalogEntry?.contextLength);

  const trimmedNewTarget = newTarget.trim();
  const newTargetDuplicate = targets.some(
    (target) => target.toLowerCase() === trimmedNewTarget.toLowerCase(),
  );
  const poolFull = targets.length >= MAX_POOL_TARGETS;
  const canAddTarget = trimmedNewTarget.length > 0 && !newTargetDuplicate && !poolFull;
  const isPool = targets.length > 1;

  const handleSelectionChange = (value: string) => {
    onContextLengthChange(
      contextLengthValueFromSelection(value as CustomAliasContextLengthSelection),
    );
  };
  const addTarget = () => {
    if (!canAddTarget) {
      return;
    }
    onTargetsChange([...targets, trimmedNewTarget]);
    setNewTarget("");
  };

  return (
    <div
      className={cn("rounded-md border bg-muted/10 p-2", error ? "border-destructive/60" : undefined)}
      data-testid={`alias-row-${alias}`}
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
        <div className="min-w-0 flex-1 space-y-1">
          <ol className="space-y-1" aria-label={t("settings.routing.modelAliases.targetsFor", { alias })}>
            {targets.map((target, index) => {
              const flagged = error?.target !== null && error?.target !== undefined && error.target === target;
              return (
                <li
                  key={target}
                  className={cn(
                    "flex h-8 items-center gap-1 rounded-md border bg-muted/20 px-2 text-xs",
                    flagged ? "border-destructive/60" : undefined,
                  )}
                >
                  {isPool ? (
                    <span className="w-4 shrink-0 text-right tabular-nums text-muted-foreground" aria-hidden="true">
                      {index + 1}
                    </span>
                  ) : null}
                  <span className="min-w-0 flex-1 truncate" title={target}>
                    {target}
                  </span>
                  <TargetHealthBadge health={health?.[target]} />
                  {isPool ? (
                    <>
                      <Button
                        type="button"
                        size="icon-xs"
                        variant="ghost"
                        disabled={busy || index === 0}
                        aria-label={t("settings.routing.modelAliases.moveUp", { target })}
                        onClick={() => onTargetsChange(moveItem(targets, index, index - 1))}
                      >
                        <ArrowUp />
                      </Button>
                      <Button
                        type="button"
                        size="icon-xs"
                        variant="ghost"
                        disabled={busy || index === targets.length - 1}
                        aria-label={t("settings.routing.modelAliases.moveDown", { target })}
                        onClick={() => onTargetsChange(moveItem(targets, index, index + 1))}
                      >
                        <ArrowDown />
                      </Button>
                    </>
                  ) : null}
                  <Button
                    type="button"
                    size="icon-xs"
                    variant="ghost"
                    disabled={busy || targets.length === 1}
                    aria-label={t("settings.routing.modelAliases.removeTarget", { target })}
                    onClick={() => onTargetsChange(targets.filter((_, other) => other !== index))}
                  >
                    <X />
                  </Button>
                </li>
              );
            })}
          </ol>
          <div className="flex items-center gap-1">
            <Input
              value={newTarget}
              disabled={busy || poolFull}
              list={datalistId}
              onChange={(event) => setNewTarget(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  addTarget();
                }
              }}
              className="h-8 flex-1 text-xs"
              aria-label={t("settings.routing.modelAliases.addTargetFor", { alias })}
              placeholder={t("settings.routing.modelAliases.addTargetPlaceholder")}
            />
            <datalist id={datalistId}>
              {knownModelIds.map((id) => (
                <option key={id} value={id} />
              ))}
            </datalist>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-8 text-xs"
              disabled={busy || !canAddTarget}
              onClick={addTarget}
            >
              <Plus />
              {t("settings.routing.modelAliases.addTarget")}
            </Button>
          </div>
        </div>
        <span className="text-xs text-muted-foreground sm:px-1 sm:py-1.5" aria-hidden="true">
          →
        </span>
        <div className="min-w-0 flex-1 truncate rounded-md border bg-muted/20 px-2 py-1.5 text-xs" title={alias}>
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
          aria-controls={advancedId}
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
      {newTargetDuplicate ? (
        <p className="mt-1 text-xs text-destructive">{t("settings.routing.modelAliases.duplicateTarget")}</p>
      ) : poolFull ? (
        <p className="mt-1 text-xs text-muted-foreground">
          {t("settings.routing.modelAliases.poolFull", { max: MAX_POOL_TARGETS })}
        </p>
      ) : null}
      {error ? (
        <p className="mt-1 text-xs text-destructive" role="alert">
          {error.message}
        </p>
      ) : null}
      {advancedOpen ? (
        <div id={advancedId} className="mt-3 space-y-2 border-t border-border/60 pt-3">
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
