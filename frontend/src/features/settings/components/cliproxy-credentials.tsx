import { useQuery } from "@tanstack/react-query";
import { ChevronDown, KeyRound, Layers, LogIn, Pencil, Plus, RefreshCw, Trash2, Upload } from "lucide-react";
import { useRef, useState, type ChangeEvent, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AlertMessage } from "@/components/alert-message";
import { EmptyState } from "@/components/empty-state";
import { QuotaBar } from "@/components/quota-bar";
import { StatusBadge, type StatusValue } from "@/components/status-badge";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { CliproxyAuthorizeDialog } from "@/features/settings/components/cliproxy-authorize-dialog";
import {
  DiscoveredModelsBrowser,
  type DiscoveredModelsBrowserLabels,
} from "@/features/settings/components/discovered-models-browser";
import { ExcludedModelsEditor } from "@/features/settings/components/excluded-models-editor";
import { useCliproxyOauth } from "@/features/settings/hooks/use-cliproxy-oauth";
import { getSettings } from "@/features/settings/api";
import { useCliproxyCredentials } from "@/features/settings/hooks/use-settings";
import type {
  CliproxyApiKeyAccount,
  CliproxyCredential,
  CliproxyCredentialFieldsUpdate,
  CliproxyRefreshStatus,
} from "@/features/settings/schemas";
import { cn } from "@/lib/utils";
import { formatQuotaResetLabel } from "@/utils/formatters";

type Translate = ReturnType<typeof useTranslation>["t"];

const HEALTH_STATUS: Record<string, StatusValue> = {
  active: "active",
  paused: "paused",
  reauth_required: "reauth",
  quota_exceeded: "exceeded",
  unavailable: "deactivated",
  rate_limited: "limited",
};

function healthStatus(health: string): StatusValue {
  return HEALTH_STATUS[health] ?? "deactivated";
}

function healthLabel(t: Translate, health: string): string {
  return t(`settings.cliproxy.health.${health}`, { defaultValue: health });
}

const PROVIDER_LABELS: Record<string, string> = {
  claude: "Claude",
  gemini: "Gemini",
  "gemini-cli": "Gemini CLI",
  codex: "Codex",
  xai: "xAI",
  qwen: "Qwen",
  iflow: "iFlow",
  antigravity: "Antigravity",
  vertex: "Vertex",
};

function providerLabel(provider: string): string {
  return PROVIDER_LABELS[provider] ?? provider;
}

function credentialLabel(credential: CliproxyCredential): string {
  return credential.email || credential.name;
}

function adoptServerDraft(server: string, draft: string, baseline: string): { draft: string; baseline: string } {
  if (server === baseline) {
    return { draft, baseline };
  }
  return { baseline: server, draft: draft === baseline ? server : draft };
}

const API_KEY_KINDS = [
  { slug: "openai-compatibility", label: "OpenAI-compatible", named: true },
  { slug: "claude", label: "Claude", named: false },
  { slug: "gemini", label: "Gemini", named: false },
  { slug: "codex", label: "Codex", named: false },
  { slug: "xai", label: "xAI", named: false },
] as const;

function modelKey(model: string): string {
  return model.trim().toLowerCase();
}

function clientModelIds(account: CliproxyApiKeyAccount): string[] {
  return account.models.map((model) => model.alias || model.name).filter((model) => model.length > 0);
}

function sameModelIds(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((model, index) => model === right[index]);
}

function integerOrEmpty(value: string): number | null | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  if (!/^-?\d+$/.test(trimmed)) {
    return undefined;
  }
  return Number(trimmed);
}

function kindLabel(slug: string): string {
  return API_KEY_KINDS.find((kind) => kind.slug === slug)?.label ?? slug;
}

function splitModels(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter((item) => item.length > 0);
}

/* ------------------------------------------------------------------------ */
/* Shared building blocks                                                    */
/* ------------------------------------------------------------------------ */

function SectionHeader({
  title,
  count,
  description,
  actions,
}: {
  title: string;
  count?: number;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
      <div className="min-w-0">
        <h5 className="flex items-center gap-2 text-sm font-semibold">
          {title}
          {count !== undefined ? (
            <Badge variant="secondary" className="h-5 px-1.5 text-[11px] tabular-nums">
              {count}
            </Badge>
          ) : null}
        </h5>
        {description ? <p className="mt-0.5 text-xs text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

function AccountCardShell({
  label,
  muted,
  children,
}: {
  label: string;
  muted: boolean;
  children: ReactNode;
}) {
  return (
    <article
      aria-label={label}
      className={cn(
        "flex min-w-0 flex-col gap-3 rounded-xl border bg-card p-4 transition-colors",
        muted && "bg-muted/30",
      )}
    >
      {children}
    </article>
  );
}

function MetaItem({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className="truncate text-xs font-medium tabular-nums">{children}</dd>
    </div>
  );
}

function PrefixChip({ prefix }: { prefix: string }) {
  const { t } = useTranslation();
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1 rounded-md border bg-muted/40 px-1.5 py-0.5 text-[11px]"
      title={t("settings.cliproxy.prefix.hint")}
    >
      <span className="text-muted-foreground">{t("settings.cliproxy.prefix.label")}</span>
      <span className="font-mono">{prefix}</span>
    </span>
  );
}

function DisclosureButton({
  open,
  label,
  ariaLabel,
  icon,
  onToggle,
}: {
  open: boolean;
  label: string;
  ariaLabel: string;
  icon: ReactNode;
  onToggle: () => void;
}) {
  return (
    <Button
      type="button"
      size="sm"
      variant="ghost"
      className="h-7 gap-1.5 rounded-lg px-2 text-xs text-muted-foreground hover:text-foreground"
      aria-expanded={open}
      aria-label={ariaLabel}
      onClick={onToggle}
    >
      {icon}
      {label}
      <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} aria-hidden="true" />
    </Button>
  );
}

function useModelBrowserLabels(): DiscoveredModelsBrowserLabels {
  const { t } = useTranslation();
  return {
    title: t("settings.cliproxy.models.title"),
    searchPlaceholder: t("settings.cliproxy.models.searchPlaceholder"),
    noMatchMessage: t("settings.cliproxy.models.noMatch"),
    addAction: t("settings.cliproxy.models.add"),
    addedAction: t("settings.cliproxy.models.listed"),
    addAriaLabel: (model) => t("settings.cliproxy.models.addAria", { model }),
    addedAriaLabel: (model) => t("settings.cliproxy.models.listedAria", { model }),
  };
}

function AccountModels({
  models,
  error,
  emptyMessage,
  shared,
  catalog,
  busy,
  label,
  onAdd,
}: {
  models: string[];
  error: string | null | undefined;
  emptyMessage: string;
  shared: ReadonlySet<string>;
  catalog: ReadonlySet<string>;
  busy: boolean;
  label: string;
  onAdd: (model: string) => void;
}) {
  const { t } = useTranslation();
  const labels = useModelBrowserLabels();
  if (models.length === 0) {
    return (
      <p className="rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground">
        {error ?? emptyMessage}
      </p>
    );
  }
  const sharedTag = t("settings.cliproxy.models.sharedTag");
  const listedCount = models.filter((model) => catalog.has(modelKey(model))).length;
  const sharedCount = models.filter((model) => shared.has(modelKey(model))).length;
  const summary = [
    listedCount > 0 ? t("settings.cliproxy.models.listedCount", { count: listedCount }) : null,
    sharedCount > 0 ? t("settings.cliproxy.models.sharedCount", { count: sharedCount }) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <DiscoveredModelsBrowser
      models={models.map((id) => ({ id, tags: shared.has(modelKey(id)) ? [sharedTag] : undefined }))}
      selectedModels={models.filter((model) => catalog.has(modelKey(model)))}
      isLoading={false}
      disabled={busy}
      labels={labels}
      summary={summary || undefined}
      searchLabel={t("settings.cliproxy.models.searchAria", { label })}
      onAddModel={onAdd}
    />
  );
}

/* ------------------------------------------------------------------------ */
/* OAuth credential card                                                     */
/* ------------------------------------------------------------------------ */

function CredentialSettings({
  credential,
  busy,
  onSave,
}: {
  credential: CliproxyCredential;
  busy: boolean;
  onSave: (body: CliproxyCredentialFieldsUpdate) => void;
}) {
  const { t } = useTranslation();
  const label = credentialLabel(credential);
  const serverWeight = credential.weight == null ? "" : String(credential.weight);
  const serverPriority = credential.priority == null ? "" : String(credential.priority);
  const [weight, setWeight] = useState(serverWeight);
  const [weightBaseline, setWeightBaseline] = useState(serverWeight);
  const [priority, setPriority] = useState(serverPriority);
  const [priorityBaseline, setPriorityBaseline] = useState(serverPriority);
  const nextWeight = adoptServerDraft(serverWeight, weight, weightBaseline);
  if (nextWeight.baseline !== weightBaseline || nextWeight.draft !== weight) {
    setWeightBaseline(nextWeight.baseline);
    setWeight(nextWeight.draft);
  }
  const nextPriority = adoptServerDraft(serverPriority, priority, priorityBaseline);
  if (nextPriority.baseline !== priorityBaseline || nextPriority.draft !== priority) {
    setPriorityBaseline(nextPriority.baseline);
    setPriority(nextPriority.draft);
  }
  const serverPrefix = credential.prefix ?? "";
  const [prefix, setPrefix] = useState(serverPrefix);
  const [prefixBaseline, setPrefixBaseline] = useState(serverPrefix);
  const nextPrefix = adoptServerDraft(serverPrefix, prefix, prefixBaseline);
  if (nextPrefix.baseline !== prefixBaseline || nextPrefix.draft !== prefix) {
    setPrefixBaseline(nextPrefix.baseline);
    setPrefix(nextPrefix.draft);
  }
  const [formError, setFormError] = useState<string | null>(null);

  function commitNumber(kind: "weight" | "priority", raw: string, current: number | null | undefined) {
    const parsed = integerOrEmpty(raw);
    if (parsed === undefined) {
      setFormError(t("settings.cliproxy.settings.wholeNumbers"));
      return;
    }
    setFormError(null);
    if (parsed === (current ?? null)) {
      return;
    }
    onSave(kind === "weight" ? { weight: parsed } : { priority: parsed });
  }

  function commitPrefix() {
    const next = prefix.trim();
    if (!next || next === (credential.prefix ?? "")) {
      return;
    }
    setFormError(null);
    onSave({ prefix: next });
  }

  return (
    <div className="space-y-4 rounded-lg border bg-muted/20 p-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="space-y-1">
          <Label htmlFor={`cliproxy-weight-${credential.name}`} className="text-xs">
            {t("settings.cliproxy.settings.weight")}
          </Label>
          <Input
            id={`cliproxy-weight-${credential.name}`}
            inputMode="numeric"
            value={weight}
            placeholder="1"
            className="h-8"
            aria-label={t("settings.cliproxy.settings.weightAria", { label })}
            onChange={(event) => setWeight(event.target.value)}
            onBlur={() => commitNumber("weight", weight, credential.weight)}
            disabled={busy}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`cliproxy-priority-${credential.name}`} className="text-xs">
            {t("settings.cliproxy.settings.priority")}
          </Label>
          <Input
            id={`cliproxy-priority-${credential.name}`}
            inputMode="numeric"
            value={priority}
            placeholder="0"
            className="h-8"
            aria-label={t("settings.cliproxy.settings.priorityAria", { label })}
            onChange={(event) => setPriority(event.target.value)}
            onBlur={() => commitNumber("priority", priority, credential.priority)}
            disabled={busy}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`cliproxy-prefix-${credential.name}`} className="text-xs">
            {t("settings.cliproxy.prefix.label")}
          </Label>
          <Input
            id={`cliproxy-prefix-${credential.name}`}
            value={prefix}
            placeholder={t("settings.cliproxy.prefix.placeholder")}
            className="h-8 font-mono"
            aria-label={t("settings.cliproxy.prefix.aria", { label })}
            onChange={(event) => setPrefix(event.target.value)}
            onBlur={commitPrefix}
            disabled={busy}
          />
        </div>
      </div>
      <p className="text-[11px] text-muted-foreground">{t("settings.cliproxy.settings.help")}</p>
      {formError ? (
        <p role="alert" className="text-xs text-destructive">
          {formError}
        </p>
      ) : null}
      <ExcludedModelsEditor
        name={credential.name}
        emailLabel={label}
        excludedModels={credential.excludedModels}
        disabled={busy}
        state={credential.excludedModelsState}
        onChange={(excludedModels) => onSave({ excludedModels })}
      />
    </div>
  );
}

function CredentialCard({
  credential,
  lastEnabled,
  busy,
  refreshStatus,
  refreshMessage,
  shared,
  catalog,
  onSave,
  onStatus,
  onRefresh,
  onDelete,
  onAddModel,
}: {
  credential: CliproxyCredential;
  lastEnabled: boolean;
  busy: boolean;
  refreshStatus: CliproxyRefreshStatus | null;
  refreshMessage: string | null;
  shared: ReadonlySet<string>;
  catalog: ReadonlySet<string>;
  onSave: (body: CliproxyCredentialFieldsUpdate) => void;
  onStatus: (disabled: boolean, confirm: boolean) => void;
  onRefresh: () => void;
  onDelete: () => void;
  onAddModel: (model: string) => void;
}) {
  const { t } = useTranslation();
  const label = credentialLabel(credential);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [pendingLastDisable, setPendingLastDisable] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(false);
  const windows = credential.quotaWindows ?? [];
  const refreshLabel =
    refreshStatus === "pending"
      ? t("settings.cliproxy.refresh.pending")
      : refreshStatus === "ok"
        ? t("settings.cliproxy.refresh.ok")
        : refreshStatus === "error"
          ? refreshMessage || t("settings.cliproxy.refresh.failed")
          : null;
  const routingSummary = [
    credential.weight != null ? t("settings.cliproxy.settings.weightSummary", { value: credential.weight }) : null,
    credential.priority != null ? t("settings.cliproxy.settings.prioritySummary", { value: credential.priority }) : null,
    credential.excludedModels.length > 0
      ? t("settings.cliproxy.settings.excludedSummary", { count: credential.excludedModels.length })
      : null,
  ].filter(Boolean);

  function onEnabledChange(enabled: boolean) {
    if (!enabled && lastEnabled) {
      setPendingLastDisable(true);
      return;
    }
    onStatus(!enabled, false);
  }

  return (
    <AccountCardShell label={`${credential.provider} credential ${label}`} muted={credential.disabled}>
      {/* Identity + on/off */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <p className="truncate text-sm font-semibold leading-tight">{label}</p>
            {credential.prefix ? <PrefixChip prefix={credential.prefix} /> : null}
          </div>
          <p className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
            <span className="shrink-0 font-medium text-foreground/80">{providerLabel(credential.provider)}</span>
            <span aria-hidden="true">·</span>
            <span className="truncate font-mono text-[11px]">{credential.name}</span>
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2.5">
          <StatusBadge status={healthStatus(credential.health)} label={healthLabel(t, credential.health)} />
          <Switch
            id={`cliproxy-enabled-${credential.name}`}
            checked={!credential.disabled}
            disabled={busy}
            aria-label={t("settings.cliproxy.enabledAria", { label })}
            onCheckedChange={onEnabledChange}
          />
        </div>
      </div>

      {/* Quota */}
      {windows.length > 0 ? (
        <div
          role="group"
          aria-label={t("settings.cliproxy.quota.aria", { label })}
          className="grid grid-cols-2 gap-3"
        >
          {windows.map((window) => (
            <QuotaBar
              key={window.id}
              label={window.label}
              percent={window.percentRemaining}
              resetLabel={
                window.resetsAt
                  ? t("settings.cliproxy.quota.resets", { label: formatQuotaResetLabel(window.resetsAt) })
                  : null
              }
            />
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">{t("settings.cliproxy.quota.unknown")}</p>
      )}

      {credential.prepaidCredits != null || credential.usageTokens != null || credential.usageRequests != null ? (
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {credential.prepaidCredits != null ? (
            <MetaItem label={t("settings.cliproxy.meta.prepaid")}>{credential.prepaidCredits}</MetaItem>
          ) : null}
          {credential.usageRequests != null || credential.usageTokens != null ? (
            <MetaItem label={t("settings.cliproxy.meta.thisWindow")}>
              {t("settings.cliproxy.meta.usage", {
                requests: credential.usageRequests ?? 0,
                tokens: (credential.usageTokens ?? 0).toLocaleString(),
              })}
            </MetaItem>
          ) : null}
        </dl>
      ) : null}

      <AccountModels
        models={credential.models}
        error={credential.modelsError}
        emptyMessage={t("settings.cliproxy.models.emptyCredential")}
        shared={shared}
        catalog={catalog}
        busy={busy}
        label={label}
        onAdd={onAddModel}
      />

      {settingsOpen ? <CredentialSettings credential={credential} busy={busy} onSave={onSave} /> : null}

      {/* Actions */}
      <div className="mt-auto flex flex-wrap items-center gap-1.5 border-t pt-3">
        <DisclosureButton
          open={settingsOpen}
          label={t("settings.cliproxy.settings.toggle")}
          ariaLabel={t("settings.cliproxy.settings.toggleAria", { label })}
          icon={<Pencil className="h-3 w-3" aria-hidden="true" />}
          onToggle={() => setSettingsOpen((open) => !open)}
        />
        {!settingsOpen && routingSummary.length > 0 ? (
          <span className="min-w-0 truncate text-[11px] text-muted-foreground">{routingSummary.join(" · ")}</span>
        ) : null}
        <div className="ml-auto flex items-center gap-1">
          {refreshLabel ? (
            <span
              className={cn(
                "mr-1 text-[11px]",
                refreshStatus === "error" ? "text-destructive" : "text-muted-foreground",
              )}
              aria-live="polite"
            >
              {refreshLabel}
            </span>
          ) : null}
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 gap-1.5 rounded-lg px-2 text-xs text-muted-foreground hover:text-foreground"
            disabled={busy || refreshStatus === "pending"}
            aria-label={t("settings.cliproxy.refresh.aria", { label })}
            onClick={onRefresh}
          >
            <RefreshCw className={cn("h-3 w-3", refreshStatus === "pending" && "animate-spin")} aria-hidden="true" />
            {t("settings.cliproxy.refresh.action")}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 gap-1.5 rounded-lg px-2 text-xs text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
            disabled={busy}
            aria-label={t("settings.cliproxy.delete.aria", { label })}
            onClick={() => setPendingDelete(true)}
          >
            <Trash2 className="h-3 w-3" aria-hidden="true" />
            {t("settings.cliproxy.delete.action")}
          </Button>
        </div>
      </div>

      <AlertDialog open={pendingLastDisable} onOpenChange={setPendingLastDisable}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.cliproxy.lastEnabled.title")}</AlertDialogTitle>
            <AlertDialogDescription>{t("settings.cliproxy.lastEnabled.description", { label })}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setPendingLastDisable(false);
                onStatus(true, true);
              }}
            >
              {t("settings.cliproxy.lastEnabled.confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <AlertDialog open={pendingDelete} onOpenChange={setPendingDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.cliproxy.delete.title", { label })}</AlertDialogTitle>
            <AlertDialogDescription>{t("settings.cliproxy.delete.description")}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction onClick={onDelete}>{t("settings.cliproxy.delete.action")}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </AccountCardShell>
  );
}

/* ------------------------------------------------------------------------ */
/* API-key accounts                                                          */
/* ------------------------------------------------------------------------ */

type ApiKeyCreateBody = {
  kind: string;
  name: string | null;
  baseUrl: string;
  apiKey: string;
  models: string[];
};

function ApiKeyDialog({
  open,
  busy,
  onOpenChange,
  onCreate,
}: {
  open: boolean;
  busy: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (body: ApiKeyCreateBody) => void;
}) {
  const { t } = useTranslation();
  const [kind, setKind] = useState<(typeof API_KEY_KINDS)[number]["slug"]>("openai-compatibility");
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [models, setModels] = useState("");
  const selected = API_KEY_KINDS.find((item) => item.slug === kind) ?? API_KEY_KINDS[0];

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onCreate({
      kind,
      name: selected.named ? name.trim() : null,
      baseUrl: baseUrl.trim(),
      apiKey: apiKey.trim(),
      models: splitModels(models),
    });
    setApiKey("");
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setApiKey("");
        }
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <form className="space-y-4" onSubmit={submit} aria-label={t("settings.cliproxy.apiKeys.formAria")}>
          <DialogHeader>
            <DialogTitle>{t("settings.cliproxy.apiKeys.addTitle")}</DialogTitle>
            <DialogDescription>{t("settings.cliproxy.apiKeys.addDescription")}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="cliproxy-api-key-kind">{t("settings.cliproxy.apiKeys.provider")}</Label>
              <select
                id="cliproxy-api-key-kind"
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
                value={kind}
                disabled={busy}
                onChange={(event) => setKind(event.target.value as (typeof API_KEY_KINDS)[number]["slug"])}
              >
                {API_KEY_KINDS.map((item) => (
                  <option key={item.slug} value={item.slug}>
                    {item.label}
                  </option>
                ))}
              </select>
            </div>
            {selected.named ? (
              <div className="space-y-1">
                <Label htmlFor="cliproxy-api-key-name">{t("settings.cliproxy.apiKeys.name")}</Label>
                <Input
                  id="cliproxy-api-key-name"
                  value={name}
                  disabled={busy}
                  placeholder="openrouter"
                  onChange={(event) => setName(event.target.value)}
                />
              </div>
            ) : null}
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="cliproxy-api-key-base-url">{t("settings.cliproxy.apiKeys.baseUrl")}</Label>
              <Input
                id="cliproxy-api-key-base-url"
                value={baseUrl}
                disabled={busy}
                placeholder="https://openrouter.ai/api/v1"
                className="font-mono text-xs"
                onChange={(event) => setBaseUrl(event.target.value)}
              />
            </div>
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="cliproxy-api-key-secret">{t("settings.cliproxy.apiKeys.apiKey")}</Label>
              <Input
                id="cliproxy-api-key-secret"
                type="password"
                autoComplete="off"
                value={apiKey}
                disabled={busy}
                onChange={(event) => setApiKey(event.target.value)}
              />
            </div>
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="cliproxy-api-key-models">{t("settings.cliproxy.apiKeys.models")}</Label>
              <Input
                id="cliproxy-api-key-models"
                value={models}
                disabled={busy}
                placeholder="openai/gpt-4o, openrouter/auto"
                className="font-mono text-xs"
                onChange={(event) => setModels(event.target.value)}
              />
              <p className="text-[11px] text-muted-foreground">{t("settings.cliproxy.apiKeys.modelsHint")}</p>
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" size="sm" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" size="sm" disabled={busy}>
              {t("settings.cliproxy.apiKeys.submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

type ApiKeyUpdateBody = {
  kind: string;
  accountId: string;
  name?: string | null;
  baseUrl: string;
  apiKey?: string;
  models?: string[];
  disabled?: boolean | null;
  prefix?: string;
  supportPromptCacheKey?: boolean;
};

function ApiKeyAccountCard({
  account,
  busy,
  shared,
  catalog,
  onSave,
  onDelete,
  onAddModel,
}: {
  account: CliproxyApiKeyAccount;
  busy: boolean;
  shared: ReadonlySet<string>;
  catalog: ReadonlySet<string>;
  onSave: (body: ApiKeyUpdateBody) => void;
  onDelete: () => void;
  onAddModel: (model: string) => void;
}) {
  const { t } = useTranslation();
  const named = API_KEY_KINDS.find((kind) => kind.slug === account.kind)?.named ?? false;
  const serverModels = clientModelIds(account);
  const [boundId, setBoundId] = useState(account.id);
  const [editOpen, setEditOpen] = useState(false);
  const [name, setName] = useState(account.name);
  const [baseUrl, setBaseUrl] = useState(account.baseUrl);
  const [models, setModels] = useState(serverModels.join(", "));
  const [apiKey, setApiKey] = useState("");
  const [prefix, setPrefix] = useState(account.prefix ?? "");
  const [pendingDelete, setPendingDelete] = useState(false);
  if (boundId !== account.id) {
    setBoundId(account.id);
    setName(account.name);
    setBaseUrl(account.baseUrl);
    setModels(serverModels.join(", "));
    setApiKey("");
    setPrefix(account.prefix ?? "");
    setPendingDelete(false);
  }
  const discovered = account.discoveredModels.length > 0
    ? account.discoveredModels
    : account.models.map((model) => model.alias || model.name);
  const label = account.name || kindLabel(account.kind);
  const off = account.disabled === true;

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body: ApiKeyUpdateBody = {
      kind: account.kind,
      accountId: account.id,
      baseUrl: baseUrl.trim(),
    };
    if (named && name.trim() !== account.name) {
      body.name = name.trim();
    }
    const nextModels = splitModels(models);
    if (!sameModelIds(nextModels, serverModels)) {
      body.models = nextModels;
    }
    const secret = apiKey.trim();
    if (secret) {
      body.apiKey = secret;
    }
    const nextPrefix = prefix.trim();
    if (nextPrefix && nextPrefix !== (account.prefix ?? "")) {
      body.prefix = nextPrefix;
    }
    onSave(body);
    setApiKey("");
  }

  return (
    <AccountCardShell label={`${kindLabel(account.kind)} API-key account ${label}`} muted={off}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <p className="truncate text-sm font-semibold leading-tight">{label}</p>
            {account.prefix ? <PrefixChip prefix={account.prefix} /> : null}
          </div>
          <p className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
            <span className="shrink-0 font-medium text-foreground/80">{kindLabel(account.kind)}</span>
            <span aria-hidden="true">·</span>
            <span className="truncate font-mono text-[11px]">
              {account.baseUrl || t("settings.cliproxy.apiKeys.baseUrlUnknown")}
            </span>
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2.5">
          <StatusBadge
            status={off ? "paused" : "active"}
            label={off ? t("settings.cliproxy.health.paused") : t("settings.cliproxy.health.active")}
          />
          {account.supportsDisable ? (
            <Switch
              id={`cliproxy-api-key-enabled-${account.id}`}
              checked={!off}
              disabled={busy}
              aria-label={t("settings.cliproxy.enabledAria", { label })}
              onCheckedChange={(enabled) =>
                onSave({
                  kind: account.kind,
                  accountId: account.id,
                  baseUrl: account.baseUrl,
                  disabled: !enabled,
                })
              }
            />
          ) : null}
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-3">
        <MetaItem label={t("settings.cliproxy.apiKeys.key")}>
          <span className={cn(!account.hasApiKey && "text-amber-600 dark:text-amber-400")}>
            {account.hasApiKey ? t("settings.cliproxy.apiKeys.keyStored") : t("settings.cliproxy.apiKeys.keyMissing")}
          </span>
        </MetaItem>
        <MetaItem label={t("settings.cliproxy.quota.title")}>
          <span className="font-normal text-muted-foreground">{t("settings.cliproxy.quota.unknown")}</span>
        </MetaItem>
        {account.group ? (
          <MetaItem label={t("settings.cliproxy.apiKeys.group")}>
            <span className="font-mono">{account.group}</span>
            {(account.keyCount ?? 1) > 1 ? (
              <span className="font-normal text-muted-foreground">
                {" · "}
                {t("settings.cliproxy.apiKeys.keyCount", { count: account.keyCount })}
              </span>
            ) : null}
          </MetaItem>
        ) : null}
      </dl>

      {account.supportPromptCacheKey != null ? (
        <div className="flex items-start justify-between gap-3 rounded-lg border bg-muted/20 px-3 py-2">
          <div className="min-w-0 space-y-0.5">
            <label className="text-xs font-medium" htmlFor={`cliproxy-api-key-cache-key-${account.id}`}>
              {t("settings.cliproxy.apiKeys.cacheKey")}
            </label>
            <p className="text-[11px] leading-snug text-muted-foreground">
              {(account.keyCount ?? 1) > 1
                ? `${t("settings.cliproxy.apiKeys.cacheKeyGroupHint", { count: account.keyCount })} `
                : ""}
              {t("settings.cliproxy.apiKeys.cacheKeyHint")}
            </p>
          </div>
          <Switch
            id={`cliproxy-api-key-cache-key-${account.id}`}
            checked={account.supportPromptCacheKey}
            disabled={busy}
            aria-label={t("settings.cliproxy.apiKeys.cacheKeyAria", { label })}
            onCheckedChange={(checked) =>
              onSave({
                kind: account.kind,
                accountId: account.id,
                baseUrl: account.baseUrl,
                supportPromptCacheKey: checked,
              })
            }
          />
        </div>
      ) : null}

      <AccountModels
        models={discovered}
        error={account.modelsError}
        emptyMessage={t("settings.cliproxy.models.emptyApiKey")}
        shared={shared}
        catalog={catalog}
        busy={busy}
        label={label}
        onAdd={onAddModel}
      />

      {editOpen ? (
        <form className="grid gap-3 rounded-lg border bg-muted/20 p-3 sm:grid-cols-2" onSubmit={save}>
          {named ? (
            <div className="space-y-1">
              <Label htmlFor={`cliproxy-api-key-name-${account.id}`} className="text-xs">
                {t("settings.cliproxy.apiKeys.name")}
              </Label>
              <Input
                id={`cliproxy-api-key-name-${account.id}`}
                value={name}
                disabled={busy}
                className="h-8"
                onChange={(event) => setName(event.target.value)}
              />
            </div>
          ) : null}
          <div className={cn("space-y-1", !named && "sm:col-span-2")}>
            <Label htmlFor={`cliproxy-api-key-prefix-${account.id}`} className="text-xs">
              {t("settings.cliproxy.prefix.label")}
            </Label>
            <Input
              id={`cliproxy-api-key-prefix-${account.id}`}
              value={prefix}
              disabled={busy}
              placeholder={t("settings.cliproxy.prefix.placeholder")}
              className="h-8 font-mono"
              aria-label={t("settings.cliproxy.prefix.aria", { label })}
              onChange={(event) => setPrefix(event.target.value)}
            />
          </div>
          <div className="space-y-1 sm:col-span-2">
            <Label htmlFor={`cliproxy-api-key-url-${account.id}`} className="text-xs">
              {t("settings.cliproxy.apiKeys.baseUrl")}
            </Label>
            <Input
              id={`cliproxy-api-key-url-${account.id}`}
              value={baseUrl}
              disabled={busy}
              className="h-8 font-mono text-xs"
              onChange={(event) => setBaseUrl(event.target.value)}
            />
          </div>
          <div className="space-y-1 sm:col-span-2">
            <Label htmlFor={`cliproxy-api-key-secret-${account.id}`} className="text-xs">
              {t("settings.cliproxy.apiKeys.replaceKey")}
            </Label>
            <Input
              id={`cliproxy-api-key-secret-${account.id}`}
              type="password"
              autoComplete="off"
              value={apiKey}
              disabled={busy}
              className="h-8"
              placeholder={t("settings.cliproxy.apiKeys.replaceKeyPlaceholder")}
              onChange={(event) => setApiKey(event.target.value)}
            />
          </div>
          <div className="space-y-1 sm:col-span-2">
            <Label htmlFor={`cliproxy-api-key-models-${account.id}`} className="text-xs">
              {t("settings.cliproxy.apiKeys.models")}
            </Label>
            <Input
              id={`cliproxy-api-key-models-${account.id}`}
              value={models}
              disabled={busy}
              className="h-8 font-mono text-xs"
              onChange={(event) => setModels(event.target.value)}
            />
            <p className="text-[11px] text-muted-foreground">{t("settings.cliproxy.apiKeys.modelsHint")}</p>
          </div>
          <div className="flex justify-end sm:col-span-2">
            <Button type="submit" size="sm" disabled={busy}>
              {t("settings.cliproxy.apiKeys.save")}
            </Button>
          </div>
        </form>
      ) : null}

      <div className="mt-auto flex flex-wrap items-center gap-1.5 border-t pt-3">
        <DisclosureButton
          open={editOpen}
          label={t("settings.cliproxy.apiKeys.edit")}
          ariaLabel={t("settings.cliproxy.apiKeys.editAria", { label })}
          icon={<Pencil className="h-3 w-3" aria-hidden="true" />}
          onToggle={() => setEditOpen((open) => !open)}
        />
        <div className="ml-auto">
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 gap-1.5 rounded-lg px-2 text-xs text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
            disabled={busy}
            aria-label={t("settings.cliproxy.delete.aria", { label })}
            onClick={() => setPendingDelete(true)}
          >
            <Trash2 className="h-3 w-3" aria-hidden="true" />
            {t("settings.cliproxy.apiKeys.remove")}
          </Button>
        </div>
      </div>

      <AlertDialog open={pendingDelete} onOpenChange={setPendingDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.cliproxy.apiKeys.removeTitle", { label })}</AlertDialogTitle>
            <AlertDialogDescription>{t("settings.cliproxy.apiKeys.removeDescription")}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction onClick={onDelete}>{t("settings.cliproxy.apiKeys.remove")}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </AccountCardShell>
  );
}

/* ------------------------------------------------------------------------ */
/* Page section                                                              */
/* ------------------------------------------------------------------------ */

function CardGrid({ children }: { children: ReactNode }) {
  return <div className="@container grid items-start gap-3 @3xl:grid-cols-2">{children}</div>;
}

function LoadingCards() {
  const { t } = useTranslation();
  return (
    <CardGrid>
      <span className="sr-only" role="status">
        {t("settings.cliproxy.loading")}
      </span>
      {[0, 1].map((index) => (
        <div key={index} className="space-y-3 rounded-xl border bg-card p-4" aria-hidden="true">
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-2">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-3 w-28" />
            </div>
            <Skeleton className="h-5 w-16 rounded-full" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Skeleton className="h-8" />
            <Skeleton className="h-8" />
          </div>
          <Skeleton className="h-8" />
        </div>
      ))}
    </CardGrid>
  );
}

function SharedModels({ models }: { models: string[] }) {
  const { t } = useTranslation();
  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2.5">
      <Layers className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
      <div className="min-w-0 space-y-1.5">
        <p className="text-xs text-muted-foreground">{t("settings.cliproxy.shared.description")}</p>
        <ul className="flex flex-wrap gap-1.5" aria-label={t("settings.cliproxy.shared.aria")}>
          {models.map((model) => (
            <li key={model}>
              <Badge variant="outline" className="bg-background font-mono text-[11px]">
                {model}
              </Badge>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export function CliproxyCredentials({ enabled }: { enabled: boolean }) {
  const { t } = useTranslation();
  const {
    credentialsQuery,
    fieldsMutation,
    statusMutation,
    refreshMutation,
    refreshQuery,
    deleteMutation,
    uploadMutation,
    apiKeyMutation,
    catalogMutation,
  } = useCliproxyCredentials(enabled);
  const catalogQuery = useQuery({
    queryKey: ["settings", "detail"],
    queryFn: getSettings,
    enabled,
  });
  const [authorizeOpen, setAuthorizeOpen] = useState(false);
  const [addKeyOpen, setAddKeyOpen] = useState(false);
  const oauth = useCliproxyOauth(authorizeOpen);
  const fileInputRef = useRef<HTMLInputElement>(null);

  if (!enabled) {
    return (
      <div className="flex items-start gap-2.5 rounded-lg border border-dashed px-3 py-3">
        <KeyRound className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">{t("settings.cliproxy.needsManagementKey")}</p>
      </div>
    );
  }

  const payload = credentialsQuery.data;
  const healthy = payload?.status === "healthy";
  const credentials = payload?.status === "healthy" ? payload.providers.flatMap((group) => group.credentials) : [];
  const apiKeys = payload?.status === "healthy" ? payload.apiKeys : [];
  const sharedIds = healthy ? (payload?.sharedModelIds ?? []) : [];
  const shared = new Set(sharedIds.map((model) => modelKey(model)));
  const catalog = new Set((catalogQuery.data?.claudeSidecarFullModels ?? []).map((model) => modelKey(model)));
  const enabledCount = credentials.filter((credential) => !credential.disabled).length;
  const attentionCount = credentials.filter(
    (credential) => !credential.disabled && credential.health !== "active",
  ).length;
  const pendingName = fieldsMutation.isPending
    ? fieldsMutation.variables?.name
    : statusMutation.isPending
      ? statusMutation.variables?.name
      : deleteMutation.isPending
        ? deleteMutation.variables
        : refreshMutation.isPending
          ? refreshMutation.variables
          : null;
  const refreshObservation = refreshQuery.data ?? null;

  async function uploadFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    uploadMutation.mutate({ name: file.name, document: await file.text() });
  }

  const oauthSummary = healthy && credentials.length > 0
    ? [
        t("settings.cliproxy.oauth.enabledCount", { count: enabledCount, total: credentials.length }),
        attentionCount > 0 ? t("settings.cliproxy.oauth.attentionCount", { count: attentionCount }) : null,
      ]
        .filter(Boolean)
        .join(" · ")
    : t("settings.cliproxy.oauth.description");

  return (
    <div className="space-y-6">
      {sharedIds.length > 0 ? <SharedModels models={sharedIds} /> : null}

      <section className="space-y-3" aria-label={t("settings.cliproxy.oauth.title")}>
        <SectionHeader
          title={t("settings.cliproxy.oauth.title")}
          count={healthy ? credentials.length : undefined}
          description={oauthSummary}
          actions={
            <>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-8 gap-1.5 text-xs"
                disabled={uploadMutation.isPending}
                onClick={() => fileInputRef.current?.click()}
              >
                <Upload className="h-3.5 w-3.5" aria-hidden="true" />
                {uploadMutation.isPending ? t("settings.cliproxy.oauth.uploading") : t("settings.cliproxy.oauth.upload")}
              </Button>
              <Button type="button" size="sm" className="h-8 gap-1.5 text-xs" onClick={() => setAuthorizeOpen(true)}>
                <LogIn className="h-3.5 w-3.5" aria-hidden="true" />
                {t("settings.cliproxy.oauth.signIn")}
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                accept="application/json,.json"
                className="hidden"
                aria-label={t("settings.cliproxy.oauth.uploadAria")}
                onChange={(event) => void uploadFile(event)}
              />
            </>
          }
        />
        {credentialsQuery.isLoading ? <LoadingCards /> : null}
        {credentialsQuery.isError ? (
          <AlertMessage variant="error">{t("settings.cliproxy.loadError")}</AlertMessage>
        ) : null}
        {!credentialsQuery.isLoading && !credentialsQuery.isError && !healthy ? (
          <AlertMessage variant="warning">{payload?.message ?? t("settings.cliproxy.unavailable")}</AlertMessage>
        ) : null}
        {healthy && credentials.length === 0 ? (
          <EmptyState
            icon={KeyRound}
            title={t("settings.cliproxy.oauth.emptyTitle")}
            description={t("settings.cliproxy.oauth.emptyDescription")}
          />
        ) : null}
        {healthy && credentials.length > 0 ? (
          <CardGrid>
            {credentials.map((credential) => (
              <CredentialCard
                key={`${credential.provider}:${credential.authIndex ?? credential.name}`}
                credential={credential}
                lastEnabled={enabledCount <= 1 && !credential.disabled}
                busy={pendingName === credential.name || statusMutation.isPending || catalogMutation.isPending}
                refreshStatus={refreshObservation?.name === credential.name ? refreshObservation.status : null}
                refreshMessage={refreshObservation?.name === credential.name ? refreshObservation.message ?? null : null}
                shared={shared}
                catalog={catalog}
                onSave={(body) => fieldsMutation.mutate({ name: credential.name, body })}
                onStatus={(disabled, confirm) => statusMutation.mutate({ name: credential.name, disabled, confirm })}
                onRefresh={() => refreshMutation.mutate(credential.name)}
                onDelete={() => deleteMutation.mutate(credential.name)}
                onAddModel={(model) => catalogMutation.mutate(model)}
              />
            ))}
          </CardGrid>
        ) : null}
      </section>

      {healthy ? (
        <section className="space-y-3 border-t pt-5" aria-label={t("settings.cliproxy.apiKeys.title")}>
          <SectionHeader
            title={t("settings.cliproxy.apiKeys.title")}
            count={apiKeys.length}
            description={t("settings.cliproxy.apiKeys.description")}
            actions={
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-8 gap-1.5 text-xs"
                onClick={() => setAddKeyOpen(true)}
              >
                <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                {t("settings.cliproxy.apiKeys.add")}
              </Button>
            }
          />
          {payload?.apiKeysMessage ? <AlertMessage variant="warning">{payload.apiKeysMessage}</AlertMessage> : null}
          {apiKeys.length === 0 ? (
            <p className="rounded-lg border border-dashed px-3 py-3 text-center text-xs text-muted-foreground">
              {t("settings.cliproxy.apiKeys.empty")}
            </p>
          ) : (
            <CardGrid>
              {apiKeys.map((account) => (
                <ApiKeyAccountCard
                  key={account.id}
                  account={account}
                  busy={apiKeyMutation.isPending || catalogMutation.isPending}
                  shared={shared}
                  catalog={catalog}
                  onSave={(body) =>
                    apiKeyMutation.mutate({ action: "update", kind: account.kind, index: account.index, body })
                  }
                  onDelete={() =>
                    apiKeyMutation.mutate({
                      action: "delete",
                      kind: account.kind,
                      index: account.index,
                      accountId: account.id,
                    })
                  }
                  onAddModel={(model) => catalogMutation.mutate(model)}
                />
              ))}
            </CardGrid>
          )}
          <ApiKeyDialog
            open={addKeyOpen}
            busy={apiKeyMutation.isPending}
            onOpenChange={setAddKeyOpen}
            onCreate={(body) =>
              apiKeyMutation.mutate({ action: "create", body }, { onSuccess: () => setAddKeyOpen(false) })
            }
          />
        </section>
      ) : null}

      <CliproxyAuthorizeDialog
        open={authorizeOpen}
        providers={oauth.providers}
        providersLoading={oauth.providersLoading}
        providersError={oauth.providersError}
        state={oauth.state}
        onOpenChange={setAuthorizeOpen}
        onStart={oauth.start}
        onManualCallback={oauth.manualCallback}
        onReset={oauth.reset}
      />
    </div>
  );
}
