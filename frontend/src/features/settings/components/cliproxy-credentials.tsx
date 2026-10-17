import { useRef, useState, type ChangeEvent } from "react";

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
import { useCliproxyCredentials } from "@/features/settings/hooks/use-settings";
import type { CliproxyCredential, CliproxyCredentialFieldsUpdate, CliproxyRefreshStatus } from "@/features/settings/schemas";
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

function nextAccountPrefix(prefixes: Array<string | null | undefined>): string {
  const taken = new Set(prefixes.filter((prefix): prefix is string => Boolean(prefix)).map((prefix) => prefix.toLowerCase()));
  for (let index = 1; index < 100000; index += 1) {
    const candidate = `acct${index}`;
    if (!taken.has(candidate)) {
      return candidate;
    }
  }
  return "acct1";
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
  suggestedPrefix,
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
  suggestedPrefix: string;
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
  const serverPrefix = credential.prefix ?? "";
  const serverWeight = credential.weight == null ? "" : String(credential.weight);
  const serverPriority = credential.priority == null ? "" : String(credential.priority);
  const [prefix, setPrefix] = useState(serverPrefix);
  const [prefixBaseline, setPrefixBaseline] = useState(serverPrefix);
  const [weight, setWeight] = useState(serverWeight);
  const [weightBaseline, setWeightBaseline] = useState(serverWeight);
  const [priority, setPriority] = useState(serverPriority);
  const [priorityBaseline, setPriorityBaseline] = useState(serverPriority);
  const nextPrefix = adoptServerDraft(serverPrefix, prefix, prefixBaseline);
  if (nextPrefix.baseline !== prefixBaseline || nextPrefix.draft !== prefix) {
    setPrefixBaseline(nextPrefix.baseline);
    setPrefix(nextPrefix.draft);
  }
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
  const [formError, setFormError] = useState<string | null>(null);
  const [pendingTag, setPendingTag] = useState<string | null>(null);
  const [pendingLastDisable, setPendingLastDisable] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(false);
  const tagDirty = prefix.trim() !== (credential.prefix ?? "");
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

  function requestTagSave() {
    const nextPrefix = prefix.trim();
    if (nextPrefix === (credential.prefix ?? "")) {
      return;
    }
    setPendingTag(nextPrefix);
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
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="space-y-1 sm:col-span-1">
          <Label htmlFor={`cliproxy-prefix-${credential.name}`}>Tag</Label>
          <div className="flex gap-2">
            <Input
              id={`cliproxy-prefix-${credential.name}`}
              value={prefix}
              placeholder={suggestedPrefix}
              aria-label={`Prefix for ${label}`}
              onChange={(event) => setPrefix(event.target.value)}
              disabled={busy}
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy || !tagDirty}
              aria-label={`Save tag for ${label}`}
              onClick={requestTagSave}
            >
              Save tag
            </Button>
          </div>
        </div>
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
      <AlertDialog open={pendingTag !== null} onOpenChange={(open) => { if (!open) setPendingTag(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Change the tag for {label}?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingTag
                ? `Clients target this account as ${pendingTag}/model. The previous tag stops matching.`
                : "Clearing the tag stops clients from targeting this account by its current tag."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                const next = pendingTag;
                setPendingTag(null);
                if (next === null) {
                  return;
                }
                onSave({ prefix: next.length === 0 ? null : next, confirm: true });
              }}
            >
              Change tag
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
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

function CredentialRow({
  credential,
  suggestedPrefix,
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
  suggestedPrefix: string;
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
      ) : null}
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
        <ul className="flex flex-wrap gap-1.5" aria-label={`Models for ${label}`}>
          {credential.models.map((model) => (
            <li key={model}>
              <Badge variant="secondary">{model}</Badge>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-muted-foreground">
          {credential.modelsError ?? "No models reported for this credential."}
        </p>
      )}
      <CredentialEditor
        credential={credential}
        suggestedPrefix={suggestedPrefix}
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

export function CliproxyCredentials({ enabled }: { enabled: boolean }) {
  const {
    credentialsQuery,
    fieldsMutation,
    statusMutation,
    refreshMutation,
    refreshQuery,
    deleteMutation,
    uploadMutation,
  } = useCliproxyCredentials(enabled);
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
  const suggestedPrefix = nextAccountPrefix(credentials.map((credential) => credential.prefix));
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
              suggestedPrefix={suggestedPrefix}
              lastEnabled={enabledCount <= 1 && !credential.disabled}
              busy={pendingName === credential.name || statusMutation.isPending}
              refreshStatus={refreshObservation?.name === credential.name ? refreshObservation.status : null}
              refreshMessage={refreshObservation?.name === credential.name ? refreshObservation.message ?? null : null}
              onSave={(body) => fieldsMutation.mutate({ name: credential.name, body })}
              onStatus={(disabled, confirm) => statusMutation.mutate({ name: credential.name, disabled, confirm })}
              onRefresh={() => refreshMutation.mutate(credential.name)}
              onDelete={() => deleteMutation.mutate(credential.name)}
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
