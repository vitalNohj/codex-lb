import { useMemo, useState } from "react";
import { ArrowRightLeft } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useModels } from "@/features/api-keys/hooks/use-models";
import { ModelAliasRow, type ModelAliasRowError } from "@/features/settings/components/model-alias-row";
import { SettingsSection, SettingsSectionHeader } from "@/features/settings/components/settings-section";
import { useAliasPoolsHealth } from "@/features/settings/hooks/use-alias-pools-health";
import { listIntegrationModelTargets } from "@/features/settings/integration-targets";
import type { DashboardSettings, ModelAliasPool, SettingsUpdateRequest } from "@/features/settings/schemas";
import { ApiError } from "@/lib/api-client";

const EMPTY_MODEL_ALIASES: Record<string, ModelAliasPool> = {};

function without<T>(record: Record<string, T>, key: string): Record<string, T> {
  if (!(key in record)) {
    return record;
  }
  const next = { ...record };
  delete next[key];
  return next;
}

/**
 * Server rejection of a pool save, attributed to the alias row it names.
 *
 * The settings PUT reports pool problems as `model_alias_pool_invalid` with
 * the alias (and offending target when it has one) in `details`; anything
 * else is a page-level toast, which the mutation already shows.
 */
function aliasPoolSaveError(error: unknown): { alias: string; error: ModelAliasRowError } | null {
  if (!(error instanceof ApiError) || error.code !== "model_alias_pool_invalid") {
    return null;
  }
  const envelope = error.details;
  const details =
    typeof envelope === "object" && envelope !== null && "details" in envelope
      ? (envelope as { details?: unknown }).details
      : envelope;
  if (typeof details !== "object" || details === null) {
    return null;
  }
  const { alias, target } = details as Record<string, unknown>;
  if (typeof alias !== "string" || alias.length === 0) {
    return null;
  }
  return { alias, error: { message: error.message, target: typeof target === "string" ? target : null } };
}

export type AliasSettingsProps = {
  settings: DashboardSettings;
  busy: boolean;
  onSave: (patch: Partial<SettingsUpdateRequest>) => Promise<DashboardSettings | void>;
};

export function AliasSettings({ settings, busy, onSave }: AliasSettingsProps) {
  const { t } = useTranslation();

  // New-alias form fields; cleared as soon as the add is submitted.
  const [aliasTarget, setAliasTarget] = useState("");
  const [aliasName, setAliasName] = useState("");
  // Unsaved pool edits (reorder, add, remove target) live here until the
  // save round-trips; a server rejection keeps them so the operator can fix
  // the list instead of re-entering it. Keyed by alias.
  const [aliasDrafts, setAliasDrafts] = useState<Record<string, string[]>>({});
  const [aliasErrors, setAliasErrors] = useState<Record<string, ModelAliasRowError>>({});
  const savedModelAliases = settings.modelAliases ?? EMPTY_MODEL_ALIASES;
  const modelsQuery = useModels();
  const knownModelIds = modelsQuery.data?.map((model) => model.id) ?? [];
  // Per-integration routes, so a model carried by more than one card can be
  // picked explicitly (``openrouter::z-ai/glm-5.3`` vs ``orcarouter::...``).
  const integrationTargets = useMemo(() => listIntegrationModelTargets(settings), [settings]);
  const aliasHealth = useAliasPoolsHealth({ enabled: Object.keys(savedModelAliases).length > 0 });

  const save = (patch: Partial<SettingsUpdateRequest>) =>
    void onSave(
      settings.version === undefined ? patch : { ...patch, expectedVersion: settings.version },
    );
  const saveModelAliases = async (
    aliasName: string,
    modelAliases: Record<string, ModelAliasPool>,
    extra: Partial<SettingsUpdateRequest> = {},
  ) => {
    const patch: Partial<SettingsUpdateRequest> = { modelAliases, ...extra };
    try {
      await onSave(
        settings.version === undefined ? patch : { ...patch, expectedVersion: settings.version },
      );
      setAliasDrafts((current) => without(current, aliasName));
      setAliasErrors((current) => without(current, aliasName));
    } catch (error) {
      // The mutation has already toasted; a pool rejection is additionally
      // pinned to its row. Other failures leave the draft in place too.
      const rowError = aliasPoolSaveError(error);
      if (rowError !== null) {
        setAliasErrors((current) => ({ ...current, [rowError.alias]: rowError.error }));
      }
    }
  };
  const updateModelAliasTargets = (aliasName: string, targets: string[]) => {
    setAliasDrafts((current) => ({ ...current, [aliasName]: targets }));
    void saveModelAliases(aliasName, { ...savedModelAliases, [aliasName]: { targets } });
  };
  const saveModelAlias = (targetModel: string, aliasName: string) => {
    const normalizedTarget = targetModel.trim();
    const normalizedAlias = aliasName.trim();
    if (!normalizedTarget || !normalizedAlias) {
      return;
    }
    void saveModelAliases(normalizedAlias, {
      ...savedModelAliases,
      [normalizedAlias]: { targets: [normalizedTarget] },
    });
  };
  const saveModelAliasCatalog = (aliasName: string, contextLength: number | null) => {
    const nextCatalog = { ...(settings.customAliasCatalog ?? {}) };
    if (contextLength === null) {
      delete nextCatalog[aliasName];
    } else {
      nextCatalog[aliasName] = { contextLength };
    }
    save({ customAliasCatalog: nextCatalog });
  };
  const removeModelAlias = (aliasName: string) => {
    const next = { ...savedModelAliases };
    delete next[aliasName];
    const nextCatalog = { ...(settings.customAliasCatalog ?? {}) };
    delete nextCatalog[aliasName];
    void saveModelAliases(aliasName, next, { customAliasCatalog: nextCatalog });
  };

  const modelAliasRows = Object.entries(savedModelAliases)
    .map(([alias, pool]) => ({ alias, targets: aliasDrafts[alias] ?? pool.targets }))
    .sort((a, b) => a.alias.localeCompare(b.alias));
  const trimmedModelAliasName = aliasName.trim();
  const trimmedModelAliasTarget = aliasTarget.trim();
  const modelAliasNameConflict = modelAliasRows.some(
    (row) => row.alias.toLowerCase() === trimmedModelAliasName.toLowerCase(),
  );
  const modelAliasAddValid =
    trimmedModelAliasName.length > 0 &&
    trimmedModelAliasTarget.length > 0 &&
    !modelAliasNameConflict;

  return (
    <SettingsSection id="model-aliases" aria-label={t("settings.aliases.title")}>
      <SettingsSectionHeader
        icon={ArrowRightLeft}
        title={t("settings.aliases.title")}
        description={t("settings.aliases.description")}
      />
      <div className="space-y-3">
        <p className="text-xs text-muted-foreground">{t("settings.routing.modelAliases.poolDescription")}</p>
        <div className="space-y-2">
          {modelAliasRows.map(({ alias, targets }) => (
            <ModelAliasRow
              key={alias}
              alias={alias}
              targets={targets}
              health={aliasHealth.data?.aliases[alias]}
              knownModelIds={knownModelIds}
              integrationTargets={integrationTargets}
              catalogEntry={settings.customAliasCatalog?.[alias]}
              error={aliasErrors[alias]}
              busy={busy}
              onTargetsChange={(next) => updateModelAliasTargets(alias, next)}
              onRemove={() => removeModelAlias(alias)}
              onContextLengthChange={(contextLength) => saveModelAliasCatalog(alias, contextLength)}
            />
          ))}
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <Input
              value={aliasTarget}
              disabled={busy}
              onChange={(event) => setAliasTarget(event.target.value)}
              className="h-8 flex-1 text-xs"
              aria-label="Real model"
              placeholder="Real model (e.g. cx/claude-opus-4.8)"
            />
            <span className="text-xs text-muted-foreground sm:px-1" aria-hidden="true">
              →
            </span>
            <Input
              value={aliasName}
              disabled={busy}
              onChange={(event) => setAliasName(event.target.value)}
              className="h-8 flex-1 text-xs"
              aria-label="Alias name"
              placeholder="Alias (e.g. custom_r1)"
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-8 text-xs sm:w-24"
              disabled={busy || !modelAliasAddValid}
              onClick={() => {
                saveModelAlias(aliasTarget, aliasName);
                setAliasTarget("");
                setAliasName("");
              }}
            >
              Add alias
            </Button>
          </div>
          {modelAliasNameConflict ? (
            <p className="text-xs text-destructive">An alias with this name already exists.</p>
          ) : null}
        </div>
      </div>
    </SettingsSection>
  );
}
