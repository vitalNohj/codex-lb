import { useQuery } from "@tanstack/react-query";
import { useRef, useState, type ChangeEvent, type FormEvent } from "react";

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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { CliproxyAuthorizeDialog } from "@/features/settings/components/cliproxy-authorize-dialog";
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
import { formatPercentNullable, formatQuotaResetLabel } from "@/utils/formatters";

const HEALTH_LABELS: Record<string, string> = {
  active: "Healthy",
  paused: "Paused",
  reauth_required: "Re-auth required",
  quota_exceeded: "Quota exceeded",
  unavailable: "Unavailable",
  rate_limited: "Rate limited",
};

function healthLabel(health: string): string {
  return HEALTH_LABELS[health] ?? health;
}

function healthVariant(health: string): "secondary" | "outline" | "destructive" {
  if (health === "reauth_required" || health === "quota_exceeded" || health === "unavailable") {
    return "destructive";
  }
  if (health === "paused" || health === "rate_limited") {
    return "outline";
  }
  return "secondary";
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

function CredentialEditor({
  credential,
  lastEnabled,
  busy,
  refreshStatus,
  refreshMessage,
  onSave,
  onStatus,
  onRefresh,
  onDelete,
}: {
  credential: CliproxyCredential;
  lastEnabled: boolean;
  busy: boolean;
  refreshStatus: CliproxyRefreshStatus | null;
  refreshMessage: string | null;
  onSave: (body: CliproxyCredentialFieldsUpdate) => void;
  onStatus: (disabled: boolean, confirm: boolean) => void;
  onRefresh: () => void;
  onDelete: () => void;
}) {
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
  const [prefixOpen, setPrefixOpen] = useState(false);
  const [prefix, setPrefix] = useState(serverPrefix);
  const [prefixBaseline, setPrefixBaseline] = useState(serverPrefix);
  const nextPrefix = adoptServerDraft(serverPrefix, prefix, prefixBaseline);
  if (nextPrefix.baseline !== prefixBaseline || nextPrefix.draft !== prefix) {
    setPrefixBaseline(nextPrefix.baseline);
    setPrefix(nextPrefix.draft);
  }
  const [formError, setFormError] = useState<string | null>(null);
  const [pendingLastDisable, setPendingLastDisable] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(false);
  const refreshLabel =
    refreshStatus === "pending"
      ? "Refreshing"
      : refreshStatus === "ok"
        ? "Refreshed"
        : refreshStatus === "error"
          ? refreshMessage || "Refresh failed"
          : null;

  function commitNumber(kind: "weight" | "priority", raw: string, current: number | null | undefined) {
    const parsed = integerOrEmpty(raw);
    if (parsed === undefined) {
      setFormError("Weight and priority must be whole numbers.");
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

  function onEnabledChange(enabled: boolean) {
    if (!enabled && lastEnabled) {
      setPendingLastDisable(true);
      return;
    }
    onStatus(!enabled, false);
  }

  return (
    <div className="space-y-3">
      <label className="flex items-center justify-between gap-3 text-sm font-medium" htmlFor={`cliproxy-enabled-${credential.name}`}>
        Enabled
        <Switch
          id={`cliproxy-enabled-${credential.name}`}
          checked={!credential.disabled}
          disabled={busy}
          aria-label={`Enabled for ${label}`}
          onCheckedChange={onEnabledChange}
        />
      </label>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor={`cliproxy-weight-${credential.name}`}>Weight</Label>
          <Input
            id={`cliproxy-weight-${credential.name}`}
            inputMode="numeric"
            value={weight}
            placeholder="1"
            aria-label={`Weight for ${label}`}
            onChange={(event) => setWeight(event.target.value)}
            onBlur={() => commitNumber("weight", weight, credential.weight)}
            disabled={busy}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`cliproxy-priority-${credential.name}`}>Priority</Label>
          <Input
            id={`cliproxy-priority-${credential.name}`}
            inputMode="numeric"
            value={priority}
            placeholder="0"
            aria-label={`Priority for ${label}`}
            onChange={(event) => setPriority(event.target.value)}
            onBlur={() => commitNumber("priority", priority, credential.priority)}
            disabled={busy}
          />
        </div>
      </div>
      <ExcludedModelsEditor
        name={credential.name}
        emailLabel={label}
        excludedModels={credential.excludedModels}
        disabled={busy}
        state={credential.excludedModelsState}
        onChange={(excludedModels) => onSave({ excludedModels })}
      />
      <div className="text-sm">
        <button
          type="button"
          className="cursor-pointer text-muted-foreground"
          aria-expanded={prefixOpen}
          onClick={() => setPrefixOpen((open) => !open)}
        >
          Advanced
        </button>
        {prefixOpen ? (
          <div className="mt-2 space-y-1">
            <Label htmlFor={`cliproxy-prefix-${credential.name}`}>Prefix</Label>
            <Input
              id={`cliproxy-prefix-${credential.name}`}
              value={prefix}
              placeholder="Assigned when routing"
              aria-label={`Prefix for ${label}`}
              onChange={(event) => setPrefix(event.target.value)}
              onBlur={commitPrefix}
              disabled={busy}
            />
            <p className="text-xs text-muted-foreground">
              Replacing the prefix moves later requests. An empty value is left unchanged.
            </p>
          </div>
        ) : null}
      </div>
      {formError ? <p className="text-sm text-destructive">{formError}</p> : null}
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy || refreshStatus === "pending"}
          aria-label={`Refresh ${label}`}
          onClick={onRefresh}
        >
          Refresh
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy}
          aria-label={`Delete ${label}`}
          onClick={() => setPendingDelete(true)}
        >
          Delete
        </Button>
      </div>
      {refreshLabel ? (
        <p className="text-[13px] text-muted-foreground" aria-live="polite">
          {refreshLabel}
        </p>
      ) : null}
      <AlertDialog open={pendingLastDisable} onOpenChange={setPendingLastDisable}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Turn off the last enabled account?</AlertDialogTitle>
            <AlertDialogDescription>
              {label} is the only enabled CLIProxyAPI account. Turning it off leaves none enabled.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setPendingLastDisable(false);
                onStatus(true, true);
              }}
            >
              Turn off
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <AlertDialog open={pendingDelete} onOpenChange={setPendingDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {label}?</AlertDialogTitle>
            <AlertDialogDescription>
              This turns the credential off and deletes it. One confirmation does both.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={onDelete}>Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function ModelChips({
  models,
  shared,
  catalog,
  busy,
  onAdd,
  label,
}: {
  models: string[];
  shared: ReadonlySet<string>;
  catalog: ReadonlySet<string>;
  busy: boolean;
  onAdd: (model: string) => void;
  label: string;
}) {
  if (models.length === 0) {
    return null;
  }
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label={`Models for ${label}`}>
      {models.map((model) => {
        const key = modelKey(model);
        const listed = catalog.has(key);
        const isShared = shared.has(key);
        return (
          <li key={model} className="flex items-center gap-1">
            <Badge variant="secondary">
              {model}
              {isShared ? " · shared" : ""}
            </Badge>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-6 px-2 text-xs"
              disabled={busy || listed}
              aria-label={listed ? `${model} is in the model list` : `Add ${model} to the model list`}
              onClick={() => onAdd(model)}
            >
              {listed ? "Listed" : "Add"}
            </Button>
          </li>
        );
      })}
    </ul>
  );
}

function CredentialRow({
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
  const label = credentialLabel(credential);
  return (
    <article
      className="space-y-3 rounded-md border bg-card px-3 py-2.5"
      aria-label={`${credential.provider} credential ${label}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="flex min-w-0 flex-wrap items-baseline gap-2">
            <span className="truncate text-sm font-medium">{label}</span>
            {credential.prefix ? (
              <span className="font-mono text-xs text-muted-foreground">{credential.prefix}</span>
            ) : null}
          </p>
          <p className="truncate font-mono text-xs text-muted-foreground">{credential.name}</p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="outline">{credential.provider}</Badge>
          <Badge variant={healthVariant(credential.health)}>{healthLabel(credential.health)}</Badge>
        </div>
      </div>
      {(credential.quotaWindows?.length ?? 0) > 0 ? (
        <ul className="space-y-1" aria-label={`Quota for ${label}`}>
          {credential.quotaWindows.map((window) => (
            <li key={window.id} className="flex items-center justify-between gap-2 text-xs">
              <span className="text-muted-foreground">{window.label}</span>
              <span className="tabular-nums font-medium">
                {formatPercentNullable(window.percentRemaining)} left
                {window.resetsAt ? ` · resets ${formatQuotaResetLabel(window.resetsAt)}` : ""}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground">Quota unknown</p>
      )}
      {credential.prepaidCredits != null ? (
        <p className="text-xs text-muted-foreground">
          Prepaid <span className="font-medium tabular-nums text-foreground">{credential.prepaidCredits}</span>
        </p>
      ) : null}
      {credential.usageTokens != null || credential.usageRequests != null ? (
        <p className="text-xs text-muted-foreground">
          This window{" "}
          <span className="font-medium tabular-nums text-foreground">
            {credential.usageRequests ?? 0} requests · {(credential.usageTokens ?? 0).toLocaleString()} tokens
          </span>
        </p>
      ) : null}
      {credential.models.length > 0 ? (
        <ModelChips
          models={credential.models}
          shared={shared}
          catalog={catalog}
          busy={busy}
          onAdd={onAddModel}
          label={label}
        />
      ) : (
        <p className="text-[13px] text-muted-foreground">
          {credential.modelsError ?? "No models reported for this credential."}
        </p>
      )}
      <CredentialEditor
        credential={credential}
        lastEnabled={lastEnabled}
        busy={busy}
        refreshStatus={refreshStatus}
        refreshMessage={refreshMessage}
        onSave={onSave}
        onStatus={onStatus}
        onRefresh={onRefresh}
        onDelete={onDelete}
      />
    </article>
  );
}

function kindLabel(slug: string): string {
  return API_KEY_KINDS.find((kind) => kind.slug === slug)?.label ?? slug;
}

function splitModels(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter((item) => item.length > 0);
}

function ApiKeyForm({
  busy,
  onCreate,
}: {
  busy: boolean;
  onCreate: (body: {
    kind: string;
    name: string | null;
    baseUrl: string;
    apiKey: string;
    models: string[];
  }) => void;
}) {
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
    <form className="space-y-3 rounded-md border bg-card px-3 py-2.5" onSubmit={submit} aria-label="Add API-key account">
      <p className="text-sm font-medium">API-key account</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="cliproxy-api-key-kind">Provider</Label>
          <select
            id="cliproxy-api-key-kind"
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
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
            <Label htmlFor="cliproxy-api-key-name">Name</Label>
            <Input id="cliproxy-api-key-name" value={name} disabled={busy} onChange={(event) => setName(event.target.value)} />
          </div>
        ) : null}
        <div className="space-y-1">
          <Label htmlFor="cliproxy-api-key-base-url">Base URL</Label>
          <Input
            id="cliproxy-api-key-base-url"
            value={baseUrl}
            disabled={busy}
            placeholder="https://openrouter.ai/api/v1"
            onChange={(event) => setBaseUrl(event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="cliproxy-api-key-secret">API key</Label>
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
          <Label htmlFor="cliproxy-api-key-models">Models</Label>
          <Input
            id="cliproxy-api-key-models"
            value={models}
            disabled={busy}
            placeholder="openai/gpt-4o, openrouter/auto"
            onChange={(event) => setModels(event.target.value)}
          />
        </div>
      </div>
      <Button type="submit" size="sm" disabled={busy}>
        Add account
      </Button>
    </form>
  );
}

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
  onSave: (body: {
    kind: string;
    accountId: string;
    name?: string | null;
    baseUrl: string;
    apiKey?: string;
    models?: string[];
    disabled?: boolean | null;
    prefix?: string;
    supportPromptCacheKey?: boolean;
  }) => void;
  onDelete: () => void;
  onAddModel: (model: string) => void;
}) {
  const named = API_KEY_KINDS.find((kind) => kind.slug === account.kind)?.named ?? false;
  const serverModels = clientModelIds(account);
  const [boundId, setBoundId] = useState(account.id);
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

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body: {
      kind: string;
      accountId: string;
      name?: string | null;
      baseUrl: string;
      apiKey?: string;
      models?: string[];
      prefix?: string;
    } = {
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
    <article className="space-y-3 rounded-md border bg-card px-3 py-2.5" aria-label={`${kindLabel(account.kind)} API-key account ${label}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{label}</p>
          <p className="truncate font-mono text-xs text-muted-foreground">{account.baseUrl || "Base URL unknown"}</p>
          {account.group ? <p className="truncate text-xs text-muted-foreground">Group {account.group}</p> : null}
          {account.prefix ? <p className="font-mono text-xs text-muted-foreground">{account.prefix}</p> : null}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="outline">{kindLabel(account.kind)}</Badge>
          <Badge variant={account.disabled ? "outline" : "secondary"}>{account.disabled ? "Paused" : "Healthy"}</Badge>
          <Badge variant="outline">{account.hasApiKey ? "Key stored" : "No key"}</Badge>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">Quota unknown</p>
      {account.supportsDisable ? (
        <label className="flex items-center justify-between gap-3 text-sm font-medium" htmlFor={`cliproxy-api-key-enabled-${account.id}`}>
          Enabled
          <Switch
            id={`cliproxy-api-key-enabled-${account.id}`}
            checked={account.disabled !== true}
            disabled={busy}
            aria-label={`Enabled for ${label}`}
            onCheckedChange={(enabled) =>
              onSave({
                kind: account.kind,
                accountId: account.id,
                baseUrl: account.baseUrl,
                disabled: !enabled,
              })
            }
          />
        </label>
      ) : null}
      {account.supportPromptCacheKey != null ? (
        <div className="space-y-1">
          <label className="flex items-center justify-between gap-3 text-sm font-medium" htmlFor={`cliproxy-api-key-cache-key-${account.id}`}>
            Send prompt cache key
            <Switch
              id={`cliproxy-api-key-cache-key-${account.id}`}
              checked={account.supportPromptCacheKey}
              disabled={busy}
              aria-label={`Send prompt cache key for ${label}`}
              onCheckedChange={(checked) =>
                onSave({
                  kind: account.kind,
                  accountId: account.id,
                  baseUrl: account.baseUrl,
                  supportPromptCacheKey: checked,
                })
              }
            />
          </label>
          <p className="text-xs text-muted-foreground">
            {(account.keyCount ?? 1) > 1
              ? `Routing pins this group, not one of its ${account.keyCount} keys. `
              : ""}
            Adds a stable prompt_cache_key upstream so the provider can reuse its cache. Turn on only if the upstream accepts the field.
          </p>
        </div>
      ) : null}
      {discovered.length > 0 ? (
        <ModelChips models={discovered} shared={shared} catalog={catalog} busy={busy} onAdd={onAddModel} label={label} />
      ) : (
        <p className="text-[13px] text-muted-foreground">{account.modelsError ?? "No models reported for this account."}</p>
      )}
      <form className="grid gap-3 sm:grid-cols-2" onSubmit={save}>
        {named ? (
          <div className="space-y-1">
            <Label htmlFor={`cliproxy-api-key-name-${account.id}`}>Name</Label>
            <Input id={`cliproxy-api-key-name-${account.id}`} value={name} disabled={busy} onChange={(event) => setName(event.target.value)} />
          </div>
        ) : null}
        <div className="space-y-1">
            <Label htmlFor={`cliproxy-api-key-url-${account.id}`}>Base URL</Label>
            <Input id={`cliproxy-api-key-url-${account.id}`} value={baseUrl} disabled={busy} onChange={(event) => setBaseUrl(event.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`cliproxy-api-key-secret-${account.id}`}>Replace API key</Label>
          <Input
            id={`cliproxy-api-key-secret-${account.id}`}
            type="password"
            autoComplete="off"
            value={apiKey}
            disabled={busy}
            placeholder="Leave blank to keep the stored key"
            onChange={(event) => setApiKey(event.target.value)}
          />
        </div>
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor={`cliproxy-api-key-prefix-${account.id}`}>Prefix</Label>
          <Input
            id={`cliproxy-api-key-prefix-${account.id}`}
            value={prefix}
            disabled={busy}
            placeholder="Assigned when routing"
            aria-label={`Prefix for ${label}`}
            onChange={(event) => setPrefix(event.target.value)}
          />
        </div>
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor={`cliproxy-api-key-models-${account.id}`}>Models</Label>
          <Input
            id={`cliproxy-api-key-models-${account.id}`}
            value={models}
            disabled={busy}
            onChange={(event) => setModels(event.target.value)}
          />
        </div>
        <div className="flex flex-wrap gap-2 sm:col-span-2">
          <Button type="submit" size="sm" variant="outline" disabled={busy}>
            Save
          </Button>
          <Button type="button" size="sm" variant="outline" disabled={busy} aria-label={`Delete ${label}`} onClick={() => setPendingDelete(true)}>
            Remove
          </Button>
        </div>
      </form>
      <AlertDialog open={pendingDelete} onOpenChange={setPendingDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove {label}?</AlertDialogTitle>
            <AlertDialogDescription>This deletes the API-key account from CLIProxyAPI. The key is not shown here.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={onDelete}>Remove</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </article>
  );
}

export function CliproxyCredentials({ enabled }: { enabled: boolean }) {
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
  const oauth = useCliproxyOauth(authorizeOpen);
  const fileInputRef = useRef<HTMLInputElement>(null);

  if (!enabled) {
    return (
      <p className="text-sm text-muted-foreground">
        Add a management key to list CLIProxyAPI credentials. Tokens stay on the sidecar and are not shown here.
      </p>
    );
  }

  const payload = credentialsQuery.data;
  const healthy = payload?.status === "healthy";
  const credentials = payload?.status === "healthy" ? payload.providers.flatMap((group) => group.credentials) : [];
  const apiKeys = payload?.status === "healthy" ? payload.apiKeys : [];
  const shared = new Set((payload?.sharedModelIds ?? []).map((model) => modelKey(model)));
  const catalog = new Set((catalogQuery.data?.claudeSidecarFullModels ?? []).map((model) => modelKey(model)));
  const enabledCount = credentials.filter((credential) => !credential.disabled).length;
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

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Button type="button" size="sm" onClick={() => setAuthorizeOpen(true)}>
          Sign in
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={uploadMutation.isPending}
          onClick={() => fileInputRef.current?.click()}
        >
          {uploadMutation.isPending ? "Uploading" : "Upload credential"}
        </Button>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/json,.json"
          className="hidden"
          aria-label="Upload credential file"
          onChange={(event) => void uploadFile(event)}
        />
      </div>
      {healthy && (payload?.sharedModelIds.length ?? 0) > 0 ? (
        <p className="text-sm text-muted-foreground">
          CLIProxyAPI load-balances these model ids across every account that serves them: {payload?.sharedModelIds.join(", ")}.
        </p>
      ) : null}
      {credentialsQuery.isLoading ? <p className="text-sm text-muted-foreground">Loading credentials...</p> : null}
      {credentialsQuery.isError ? (
        <p className="text-sm text-destructive">Could not load CLIProxyAPI credentials.</p>
      ) : null}
      {!credentialsQuery.isLoading && !credentialsQuery.isError && !healthy ? (
        <p className="text-sm text-muted-foreground">{payload?.message ?? "CLIProxyAPI credentials are unavailable."}</p>
      ) : null}
      {healthy && credentials.length === 0 ? (
        <p className="text-sm text-muted-foreground">No CLIProxyAPI credentials.</p>
      ) : null}
      {healthy && credentials.length > 0 ? (
        <div className="@container grid gap-2 @3xl:grid-cols-2">
          {credentials.map((credential) => (
            <CredentialRow
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
        </div>
      ) : null}
      {healthy && payload?.apiKeysMessage ? (
        <p className="text-sm text-muted-foreground">{payload.apiKeysMessage}</p>
      ) : null}
      {healthy ? (
        <div className="space-y-2">
          <ApiKeyForm
            busy={apiKeyMutation.isPending}
            onCreate={(body) => apiKeyMutation.mutate({ action: "create", body })}
          />
          {apiKeys.map((account) => (
            <ApiKeyAccountCard
              key={account.id}
              account={account}
              busy={apiKeyMutation.isPending || catalogMutation.isPending}
              shared={shared}
              catalog={catalog}
              onSave={(body) => apiKeyMutation.mutate({ action: "update", kind: account.kind, index: account.index, body })}
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
        </div>
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
