import { createContext, type ReactNode, use, useEffect, useMemo, useRef, useState } from "react";
import { ExternalLink, X, type LucideIcon } from "lucide-react";

import { AlertMessage } from "@/components/alert-message";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { DiscoveredModelsBrowser, type DiscoveredModelSummary } from "@/features/settings/components/discovered-models-browser";
import { buildSettingsUpdateRequest } from "@/features/settings/payload";
import {
  REASONING_EFFORT_OPTIONS,
  REASONING_EFFORT_UNSET,
} from "@/features/settings/reasoning-effort";
import type {
  DashboardSettings,
  SettingsUpdateRequest,
  SidecarReasoningEffort,
  SidecarModelPrefix,
  ClaudeSidecarRoutingAccount,
  ClaudeSidecarRoutingStrategy,
} from "@/features/settings/schemas";
import { ApiError } from "@/lib/api-client";

export type SidecarIntegrationId = "claude" | "openrouter" | "omniroute" | "ollama";

type SidecarIntegrationMeta = {
  id: SidecarIntegrationId;
  title: string;
  conflictName: string;
  description: string;
  icon: LucideIcon;
  sectionId: string;
  enableLabel: string;
  enableDescription: string;
  callout: ReactNode;
  baseUrlPlaceholder: string;
  apiKeyPlaceholder: string;
  apiKeyConfigured: boolean;
  managementKeyConfigured?: boolean;
  externalLink?: {
    href: string;
    label: string;
  };
};

type SidecarIntegrationState = {
  enabled: boolean;
  baseUrl: string;
  apiKey: string;
  managementKey: string;
  prefixes: SidecarModelPrefix[];
  fullModels: string[];
  connectTimeout: string;
  requestTimeout: string;
  cacheTtl: string;
  pollInterval: string;
  manualPrefix: string;
  manualFullModel: string;
  defaultReasoningEffort: SidecarReasoningEffort | null;
  inlineError: string | null;
  saveError: string | null;
};

type SidecarIntegrationActions = {
  setEnabled: (enabled: boolean) => void;
  setBaseUrl: (value: string) => void;
  setApiKey: (value: string) => void;
  setManagementKey: (value: string) => void;
  setConnectTimeout: (value: string) => void;
  setRequestTimeout: (value: string) => void;
  setCacheTtl: (value: string) => void;
  setPollInterval: (value: string) => void;
  setManualPrefix: (value: string) => void;
  setManualFullModel: (value: string) => void;
  addPrefix: () => void;
  removePrefix: (prefix: string) => void;
  setPrefixStrip: (prefix: string, strip: boolean) => void;
  addFullModel: (modelId?: string) => void;
  removeFullModel: (modelId: string) => void;
  setDefaultReasoningEffort: (effort: SidecarReasoningEffort | null) => void;
  persistField: () => void;
  addApiKey: () => void;
  addManagementKey: () => void;
};

type SidecarIntegrationContextValue = {
  settings: DashboardSettings;
  busy: boolean;
  meta: SidecarIntegrationMeta;
  state: SidecarIntegrationState;
  actions: SidecarIntegrationActions;
  models: {
    rows: DiscoveredModelSummary[];
    isLoading: boolean;
  };
  form: {
    isValid: boolean;
    hasConflict: boolean;
    conflictMessage: string | null;
    savePending: boolean;
  };
};

type SidecarIntegrationCardProviderProps = {
  settings: DashboardSettings;
  busy: boolean;
  meta: SidecarIntegrationMeta;
  initial: {
    enabled: boolean;
    baseUrl: string;
    prefixes: SidecarModelPrefix[];
    fullModels: string[];
    connectTimeout: number;
    requestTimeout: number;
    cacheTtl: number;
    pollInterval?: number;
    defaultReasoningEffort?: SidecarReasoningEffort | null;
  };
  models: {
    rows: DiscoveredModelSummary[];
    isLoading: boolean;
  };
  onSave: (payload: SettingsUpdateRequest) => Promise<void>;
  onTestConnection: () => Promise<unknown>;
  buildPatch: (state: {
    baseUrl: string;
    apiKey: string;
    managementKey: string;
    prefixes: SidecarModelPrefix[];
    fullModels: string[];
    connectTimeout: number;
    requestTimeout: number;
    cacheTtl: number;
    pollInterval: number | null;
  }) => Partial<SettingsUpdateRequest>;
  buildEnablePatch: (enabled: boolean) => Partial<SettingsUpdateRequest>;
  buildEffortPatch: (
    effort: SidecarReasoningEffort | null,
  ) => Partial<SettingsUpdateRequest>;
  children: ReactNode;
};

const INTEGRATION_NAMES: Record<SidecarIntegrationId, string> = {
  claude: "CLIProxyAPI",
  openrouter: "OpenRouter",
  omniroute: "OmniRoute",
  ollama: "Ollama",
};

const SidecarIntegrationContext = createContext<SidecarIntegrationContextValue | null>(null);

function useSidecarIntegration() {
  const value = use(SidecarIntegrationContext);
  if (!value) {
    throw new Error("SidecarIntegrationCard subcomponents must be used inside Provider");
  }
  return value;
}

function normalizePrefixes(prefixes: SidecarModelPrefix[]): SidecarModelPrefix[] {
  const seen = new Set<string>();
  const next: SidecarModelPrefix[] = [];
  for (const entry of prefixes) {
    const prefix = entry.prefix.trim().toLowerCase();
    if (!prefix || seen.has(prefix)) {
      continue;
    }
    seen.add(prefix);
    next.push({ prefix, strip: entry.strip });
  }
  return next;
}

function normalizeFullModels(models: string[]): string[] {
  const seen = new Set<string>();
  const next: string[] = [];
  for (const model of models) {
    const trimmed = model.trim();
    const key = trimmed.toLowerCase();
    if (!trimmed || seen.has(key)) {
      continue;
    }
    seen.add(key);
    next.push(trimmed);
  }
  return next;
}

type IntegrationValues = {
  id: SidecarIntegrationId;
  name: string;
  prefixes: SidecarModelPrefix[];
  fullModels: string[];
};

function integrationValues(settings: DashboardSettings, current?: IntegrationValues): IntegrationValues[] {
  const values: IntegrationValues[] = [
    {
      id: "claude",
      name: INTEGRATION_NAMES.claude,
      prefixes: settings.claudeSidecarModelPrefixes ?? [],
      fullModels: settings.claudeSidecarFullModels ?? [],
    },
    {
      id: "openrouter",
      name: INTEGRATION_NAMES.openrouter,
      prefixes: settings.openrouterSidecarModelPrefixes ?? [],
      fullModels: settings.openrouterSidecarFullModels ?? [],
    },
    {
      id: "omniroute",
      name: INTEGRATION_NAMES.omniroute,
      prefixes: settings.omnirouteSidecarModelPrefixes ?? [],
      fullModels: settings.omnirouteSidecarFullModels ?? settings.omnirouteSidecarSelectedModels ?? [],
    },
    {
      id: "ollama",
      name: INTEGRATION_NAMES.ollama,
      prefixes: settings.ollamaSidecarModelPrefixes ?? [],
      fullModels: settings.ollamaSidecarFullModels ?? [],
    },
  ];
  if (!current) {
    return values;
  }
  return values.map((value) => (value.id === current.id ? current : value));
}

function findDuplicateOwner(params: {
  settings: DashboardSettings;
  currentId: SidecarIntegrationId;
  kind: "prefix" | "full_model";
  value: string;
  currentPrefixes?: SidecarModelPrefix[];
  currentFullModels?: string[];
}): string | null {
  const key = params.value.trim().toLowerCase();
  if (!key) {
    return null;
  }
  const values = integrationValues(params.settings, {
    id: params.currentId,
    name: INTEGRATION_NAMES[params.currentId],
    prefixes: params.currentPrefixes ?? [],
    fullModels: params.currentFullModels ?? [],
  });
  for (const integration of values) {
    if (integration.id === params.currentId) {
      continue;
    }
    const matches =
      params.kind === "prefix"
        ? integration.prefixes.some((entry) => entry.prefix.toLowerCase() === key)
        : integration.fullModels.some((model) => model.toLowerCase() === key);
    if (matches) {
      return integration.name;
    }
  }
  return null;
}

function currentConflict(settings: DashboardSettings, current: IntegrationValues): {
  kind: "prefix" | "full_model";
  value: string;
  owner: string;
} | null {
  for (const prefix of current.prefixes) {
    const owner = findDuplicateOwner({
      settings,
      currentId: current.id,
      kind: "prefix",
      value: prefix.prefix,
      currentPrefixes: current.prefixes,
      currentFullModels: current.fullModels,
    });
    if (owner) {
      return { kind: "prefix", value: prefix.prefix, owner };
    }
  }
  for (const model of current.fullModels) {
    const owner = findDuplicateOwner({
      settings,
      currentId: current.id,
      kind: "full_model",
      value: model,
      currentPrefixes: current.prefixes,
      currentFullModels: current.fullModels,
    });
    if (owner) {
      return { kind: "full_model", value: model, owner };
    }
  }
  return null;
}

function conflictLabel(kind: "prefix" | "full_model") {
  return kind === "prefix" ? "Prefix" : "Full model";
}

function conflictMessage(kind: "prefix" | "full_model", value: string, owner: string) {
  return `${conflictLabel(kind)} ${value} is already used by ${owner}.`;
}

function backendConflictMessage(error: unknown, currentName: string): string | null {
  if (!(error instanceof ApiError)) {
    return null;
  }
  const errorDetails = error.details;
  const details =
    typeof errorDetails === "object" && errorDetails !== null && "details" in errorDetails
      ? (errorDetails as { details?: unknown }).details
      : errorDetails;
  if (typeof details !== "object" || details === null) {
    return null;
  }
  const conflict = details as Record<string, unknown>;
  if (conflict.code !== "sidecar_routing_conflict") {
    return null;
  }
  const kind = conflict.kind === "full_model" ? "full_model" : conflict.kind === "prefix" ? "prefix" : null;
  const value = typeof conflict.value === "string" ? conflict.value : null;
  const owner = typeof conflict.owning_integration === "string" ? conflict.owning_integration : null;
  const challenger =
    typeof conflict.challenging_integration === "string" ? conflict.challenging_integration : currentName;
  if (!kind || !value || !owner) {
    return null;
  }
  return `${conflictLabel(kind)} ${value} conflicts with ${owner} while saving ${challenger}.`;
}

function SidecarIntegrationCardProvider({
  settings,
  busy,
  meta,
  initial,
  models,
  onSave,
  onTestConnection,
  buildPatch,
  buildEnablePatch,
  buildEffortPatch,
  children,
}: SidecarIntegrationCardProviderProps) {
  const [enabled, setEnabledState] = useState(initial.enabled);
  const [baseUrl, setBaseUrl] = useState(initial.baseUrl);
  const [apiKey, setApiKey] = useState("");
  const [managementKey, setManagementKey] = useState("");
  const [prefixes, setPrefixes] = useState(() => normalizePrefixes(initial.prefixes));
  const [fullModels, setFullModels] = useState(() => normalizeFullModels(initial.fullModels));
  const [connectTimeout, setConnectTimeout] = useState(String(initial.connectTimeout));
  const [requestTimeout, setRequestTimeout] = useState(String(initial.requestTimeout));
  const [cacheTtl, setCacheTtl] = useState(String(initial.cacheTtl));
  const [pollInterval, setPollInterval] = useState(String(initial.pollInterval ?? 0));
  const [manualPrefix, setManualPrefix] = useState("");
  const [manualFullModel, setManualFullModel] = useState("");
  const [defaultReasoningEffort, setDefaultReasoningEffortState] = useState<
    SidecarReasoningEffort | null
  >(initial.defaultReasoningEffort ?? null);
  const [inlineError, setInlineError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savePending, setSavePending] = useState(false);

  const parsedConnectTimeout = Number(connectTimeout);
  const parsedRequestTimeout = Number(requestTimeout);
  const parsedCacheTtl = Number(cacheTtl);
  const parsedPollInterval = Number(pollInterval);
  const current = useMemo(
    () => ({
      id: meta.id,
      name: meta.conflictName,
      prefixes,
      fullModels,
    }),
    [fullModels, meta.conflictName, meta.id, prefixes],
  );
  const conflict = useMemo(() => currentConflict(settings, current), [current, settings]);
  const conflictText = conflict ? conflictMessage(conflict.kind, conflict.value, conflict.owner) : null;
  const formValid =
    baseUrl.trim().length > 0 &&
    (meta.id !== "claude" || prefixes.length > 0) &&
    Number.isFinite(parsedConnectTimeout) &&
    parsedConnectTimeout > 0 &&
    Number.isFinite(parsedRequestTimeout) &&
    parsedRequestTimeout > 0 &&
    Number.isFinite(parsedCacheTtl) &&
    parsedCacheTtl >= 0 &&
    (initial.pollInterval === undefined || (Number.isFinite(parsedPollInterval) && parsedPollInterval > 0));

  type PersistOverrides = {
    prefixes?: SidecarModelPrefix[];
    fullModels?: string[];
    apiKey?: string;
    managementKey?: string;
  };

  const persistConfig = async (overrides: PersistOverrides = {}) => {
    const nextPrefixes = overrides.prefixes ?? prefixes;
    const nextFullModels = overrides.fullModels ?? fullModels;
    const hasConflict = Boolean(currentConflict(settings, { id: meta.id, name: meta.conflictName, prefixes: nextPrefixes, fullModels: nextFullModels }));
    if (!formValid || hasConflict) {
      return;
    }
    setSaveError(null);
    setSavePending(true);
    try {
      await onSave(
        buildSettingsUpdateRequest(
          settings,
          buildPatch({
            baseUrl: baseUrl.trim(),
            apiKey: (overrides.apiKey ?? "").trim(),
            managementKey: (overrides.managementKey ?? "").trim(),
            prefixes: nextPrefixes,
            fullModels: nextFullModels,
            connectTimeout: parsedConnectTimeout,
            requestTimeout: parsedRequestTimeout,
            cacheTtl: parsedCacheTtl,
            pollInterval: initial.pollInterval === undefined ? null : parsedPollInterval,
          }),
        ),
      );
      await onTestConnection().catch(() => null);
    } catch (error) {
      setSaveError(
        backendConflictMessage(error, meta.conflictName) ??
          (error instanceof Error ? error.message : "Failed to save settings"),
      );
    } finally {
      setSavePending(false);
    }
  };

  const setEnabled = (nextEnabled: boolean) => {
    setEnabledState(nextEnabled);
    void onSave(buildSettingsUpdateRequest(settings, buildEnablePatch(nextEnabled)));
  };

  const setDefaultReasoningEffort = (effort: SidecarReasoningEffort | null) => {
    setDefaultReasoningEffortState(effort);
    void onSave(buildSettingsUpdateRequest(settings, buildEffortPatch(effort)));
  };

  const addPrefix = () => {
    const prefix = manualPrefix.trim().toLowerCase();
    if (!prefix) {
      return;
    }
    const owner = findDuplicateOwner({
      settings,
      currentId: meta.id,
      kind: "prefix",
      value: prefix,
      currentPrefixes: prefixes,
      currentFullModels: fullModels,
    });
    if (owner) {
      setInlineError(conflictMessage("prefix", prefix, owner));
      return;
    }
    setInlineError(null);
    const nextPrefixes = normalizePrefixes([...prefixes, { prefix, strip: false }]);
    setPrefixes(nextPrefixes);
    setManualPrefix("");
    void persistConfig({ prefixes: nextPrefixes });
  };

  const removePrefix = (prefix: string) => {
    const nextPrefixes = prefixes.filter((entry) => entry.prefix !== prefix);
    setPrefixes(nextPrefixes);
    void persistConfig({ prefixes: nextPrefixes });
  };

  const setPrefixStrip = (prefix: string, strip: boolean) => {
    const nextPrefixes = prefixes.map((entry) => (entry.prefix === prefix ? { ...entry, strip } : entry));
    setPrefixes(nextPrefixes);
    void persistConfig({ prefixes: nextPrefixes });
  };

  const addFullModel = (modelId?: string) => {
    const fullModel = (modelId ?? manualFullModel).trim();
    if (!fullModel) {
      return;
    }
    const owner = findDuplicateOwner({
      settings,
      currentId: meta.id,
      kind: "full_model",
      value: fullModel,
      currentPrefixes: prefixes,
      currentFullModels: fullModels,
    });
    if (owner) {
      setInlineError(conflictMessage("full_model", fullModel, owner));
      return;
    }
    setInlineError(null);
    const nextFullModels = normalizeFullModels([...fullModels, fullModel]);
    setFullModels(nextFullModels);
    if (!modelId) {
      setManualFullModel("");
    }
    void persistConfig({ fullModels: nextFullModels });
  };

  const removeFullModel = (modelId: string) => {
    const nextFullModels = fullModels.filter((candidate) => candidate !== modelId);
    setFullModels(nextFullModels);
    void persistConfig({ fullModels: nextFullModels });
  };

  const persistField = () => {
    void persistConfig();
  };

  const addApiKey = () => {
    const key = apiKey.trim();
    if (!key) {
      return;
    }
    setApiKey("");
    void persistConfig({ apiKey: key });
  };

  const addManagementKey = () => {
    const key = managementKey.trim();
    if (!key) {
      return;
    }
    setManagementKey("");
    void persistConfig({ managementKey: key });
  };

  const value: SidecarIntegrationContextValue = {
    settings,
    busy,
    meta,
    state: {
      enabled,
      baseUrl,
      apiKey,
      managementKey,
      prefixes,
      fullModels,
      connectTimeout,
      requestTimeout,
      cacheTtl,
      pollInterval,
      manualPrefix,
      manualFullModel,
      defaultReasoningEffort,
      inlineError,
      saveError,
    },
    actions: {
      setEnabled,
      setBaseUrl,
      setApiKey,
      setManagementKey,
      setConnectTimeout,
      setRequestTimeout,
      setCacheTtl,
      setPollInterval,
      setManualPrefix,
      setManualFullModel,
      addPrefix,
      removePrefix,
      setPrefixStrip,
      addFullModel,
      removeFullModel,
      setDefaultReasoningEffort,
      persistField,
      addApiKey,
      addManagementKey,
    },
    models,
    form: {
      isValid: formValid,
      hasConflict: Boolean(conflict),
      conflictMessage: conflictText,
      savePending,
    },
  };

  return <SidecarIntegrationContext value={value}>{children}</SidecarIntegrationContext>;
}

function Frame({ children, bare = false }: { children: ReactNode; bare?: boolean }) {
  const { meta } = useSidecarIntegration();
  if (bare) {
    return (
      <div id={meta.sectionId} className="space-y-3">
        {children}
      </div>
    );
  }
  return (
    <section id={meta.sectionId} className="rounded-xl border bg-card p-5">
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function Header() {
  const { busy, meta, state, actions } = useSidecarIntegration();
  const Icon = meta.icon;
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
      <div className="flex items-center gap-2.5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
          <Icon className="h-4 w-4 text-primary" aria-hidden="true" />
        </div>
        <div>
          <h3 className="text-sm font-semibold">{meta.title}</h3>
          <p className="text-xs text-muted-foreground">{meta.description}</p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        {meta.externalLink ? (
          <Button asChild type="button" size="sm" variant="outline" className="h-8 gap-1.5 text-xs">
            <a href={meta.externalLink.href} target="_blank" rel="noopener noreferrer">
              {meta.externalLink.label}
              <ExternalLink className="size-3" aria-hidden="true" />
            </a>
          </Button>
        ) : null}
        <label className="flex items-center gap-2 text-xs font-medium" htmlFor={`${meta.sectionId}-enable`}>
          {meta.enableLabel}
          <Switch
            id={`${meta.sectionId}-enable`}
            aria-label={meta.enableLabel}
            checked={state.enabled}
            disabled={busy}
            onCheckedChange={(checked) => actions.setEnabled(checked)}
          />
        </label>
      </div>
    </div>
  );
}

function Callout() {
  const { meta } = useSidecarIntegration();
  return (
    <div className="space-y-1.5 rounded-lg border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
      <p className="font-medium text-foreground">{meta.enableDescription}</p>
      <p>{meta.callout}</p>
    </div>
  );
}

function Fields({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border">
      <div className="space-y-3 p-3">{children}</div>
    </div>
  );
}

function BaseUrl() {
  const { busy, meta, state, actions } = useSidecarIntegration();
  return (
    <label className="space-y-1 text-xs font-medium" htmlFor={`${meta.sectionId}-base-url`}>
      Base URL
      <Input
        id={`${meta.sectionId}-base-url`}
        value={state.baseUrl}
        onChange={(event) => actions.setBaseUrl(event.target.value)}
        onBlur={() => actions.persistField()}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            actions.persistField();
          }
        }}
        placeholder={meta.baseUrlPlaceholder}
        disabled={busy}
        className="h-8 text-xs"
      />
    </label>
  );
}

function Secrets({ showManagementKey = false }: { showManagementKey?: boolean }) {
  const { busy, meta, state, actions, form } = useSidecarIntegration();
  return (
    <div className={showManagementKey ? "grid gap-2 sm:grid-cols-2" : "grid gap-2"}>
      <label className="space-y-1 text-xs font-medium" htmlFor={`${meta.sectionId}-api-key`}>
        API key
        <div className="flex gap-2">
          <Input
            id={`${meta.sectionId}-api-key`}
            type="password"
            value={state.apiKey}
            onChange={(event) => actions.setApiKey(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                actions.addApiKey();
              }
            }}
            placeholder={meta.apiKeyConfigured ? "Configured" : meta.apiKeyPlaceholder}
            disabled={busy}
            className="h-8 text-xs"
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 shrink-0 text-xs"
            disabled={busy || !state.apiKey.trim() || form.savePending}
            onClick={() => actions.addApiKey()}
          >
            Add API key
          </Button>
        </div>
        <span className="block font-normal text-muted-foreground">Adding a key overwrites the stored key. Saved keys are encrypted and never shown again.</span>
      </label>
      {showManagementKey ? (
        <label className="space-y-1 text-xs font-medium" htmlFor={`${meta.sectionId}-management-key`}>
          Management key
          <div className="flex gap-2">
            <Input
              id={`${meta.sectionId}-management-key`}
              type="password"
              value={state.managementKey}
              onChange={(event) => actions.setManagementKey(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  actions.addManagementKey();
                }
              }}
              placeholder={meta.managementKeyConfigured ? "Configured" : "Not configured"}
              disabled={busy}
              className="h-8 text-xs"
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-8 shrink-0 text-xs"
              disabled={busy || !state.managementKey.trim() || form.savePending}
              onClick={() => actions.addManagementKey()}
            >
              Add management key
            </Button>
          </div>
          <span className="block font-normal text-muted-foreground">Must match `remote-management.secret-key`.</span>
        </label>
      ) : null}
    </div>
  );
}

function Prefixes() {
  const { busy, meta, state, actions } = useSidecarIntegration();
  return (
    <div className="space-y-2 rounded-md border bg-muted/10 p-3">
      <div>
        <p className="text-sm font-medium">Model prefixes</p>
        <p className="text-xs text-muted-foreground">
          Full model names take precedence over prefixes across all integrations.
        </p>
      </div>
      <div className="flex gap-2">
        <Input
          aria-label={`New prefix for ${meta.title}`}
          value={state.manualPrefix}
          onChange={(event) => actions.setManualPrefix(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              actions.addPrefix();
            }
          }}
          placeholder="provider/ or cp-"
          disabled={busy}
          className="h-8 text-xs"
        />
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-8 shrink-0 text-xs"
          disabled={busy || !state.manualPrefix.trim()}
          onClick={actions.addPrefix}
        >
          Add prefix
        </Button>
      </div>
      {state.inlineError ? <p className="text-xs font-medium text-destructive">{state.inlineError}</p> : null}
      <div className="space-y-2">
        {state.prefixes.length === 0 ? (
          <p className="text-xs text-muted-foreground">No prefixes configured.</p>
        ) : null}
        {state.prefixes.map((entry) => (
          <div key={entry.prefix} className="flex flex-wrap items-center justify-between gap-2 rounded-md border bg-background/60 px-2 py-1.5">
            <span className="font-mono text-xs">{entry.prefix}</span>
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                <Checkbox
                  aria-label={`Remove prefix ${entry.prefix} before forwarding`}
                  checked={entry.strip}
                  disabled={busy}
                  onCheckedChange={(checked) => actions.setPrefixStrip(entry.prefix, checked === true)}
                />
                Remove before forwarding
              </label>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-6 px-2 text-[11px]"
                disabled={busy || (meta.id === "claude" && state.prefixes.length <= 1)}
                onClick={() => actions.removePrefix(entry.prefix)}
              >
                <X className="size-3" aria-hidden="true" />
                <span className="sr-only">Remove {entry.prefix}</span>
              </Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function FullModels() {
  const { busy, meta, state, actions, form } = useSidecarIntegration();
  return (
    <div className="space-y-2 rounded-md border bg-muted/10 p-3" aria-label={`Configured full models for ${meta.title}`}>
      <div>
        <p className="text-sm font-medium">Full models</p>
        <p className="text-xs text-muted-foreground">
          Exact model IDs route to this integration first and are forwarded unchanged.
        </p>
      </div>
      <div className="flex gap-2">
        <Input
          aria-label={`New full model for ${meta.title}`}
          value={state.manualFullModel}
          onChange={(event) => actions.setManualFullModel(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              actions.addFullModel();
            }
          }}
          placeholder="provider/model-id"
          disabled={busy}
          className="h-8 text-xs"
        />
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-8 shrink-0 text-xs"
          disabled={busy || !state.manualFullModel.trim()}
          onClick={() => actions.addFullModel()}
        >
          Add full model
        </Button>
      </div>
      {form.conflictMessage ? <p className="text-xs font-medium text-destructive">{form.conflictMessage}</p> : null}
      {state.fullModels.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {state.fullModels.map((modelId) => (
            <button
              key={modelId}
              type="button"
              className="inline-flex items-center gap-1 rounded-full border bg-muted/30 px-2 py-1 font-mono text-[11px]"
              onClick={() => actions.removeFullModel(modelId)}
              aria-label={`Remove ${modelId}`}
              disabled={busy}
            >
              {modelId}
              <X className="size-3" aria-hidden="true" />
            </button>
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">No full models configured.</p>
      )}
    </div>
  );
}

function DiscoveredModels() {
  const { actions, models, state } = useSidecarIntegration();
  return (
    <DiscoveredModelsBrowser
      models={models.rows}
      selectedModels={state.fullModels}
      isLoading={models.isLoading}
      onAddModel={actions.addFullModel}
    />
  );
}

function Timeouts({ showPollInterval = false }: { showPollInterval?: boolean }) {
  const { busy, meta, state, actions } = useSidecarIntegration();
  const persistOnEnter = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      actions.persistField();
    }
  };
  return (
    <div className={showPollInterval ? "grid gap-2 sm:grid-cols-4" : "grid gap-2 sm:grid-cols-3"}>
      {showPollInterval ? (
        <label className="space-y-1 text-xs font-medium" htmlFor={`${meta.sectionId}-poll-interval`}>
          Poll interval (s)
          <Input
            id={`${meta.sectionId}-poll-interval`}
            type="number"
            min={5}
            step={5}
            value={state.pollInterval}
            disabled={busy}
            onChange={(event) => actions.setPollInterval(event.target.value)}
            onBlur={() => actions.persistField()}
            onKeyDown={persistOnEnter}
            className="h-8 text-xs"
          />
        </label>
      ) : null}
      <label className="space-y-1 text-xs font-medium" htmlFor={`${meta.sectionId}-connect-timeout`}>
        Connect timeout (s)
        <Input
          id={`${meta.sectionId}-connect-timeout`}
          type="number"
          min={0.1}
          step={0.1}
          value={state.connectTimeout}
          disabled={busy}
          onChange={(event) => actions.setConnectTimeout(event.target.value)}
          onBlur={() => actions.persistField()}
          onKeyDown={persistOnEnter}
          className="h-8 text-xs"
        />
      </label>
      <label className="space-y-1 text-xs font-medium" htmlFor={`${meta.sectionId}-request-timeout`}>
        Request timeout (s)
        <Input
          id={`${meta.sectionId}-request-timeout`}
          type="number"
          min={1}
          step={1}
          value={state.requestTimeout}
          disabled={busy}
          onChange={(event) => actions.setRequestTimeout(event.target.value)}
          onBlur={() => actions.persistField()}
          onKeyDown={persistOnEnter}
          className="h-8 text-xs"
        />
      </label>
      <label className="space-y-1 text-xs font-medium" htmlFor={`${meta.sectionId}-cache-ttl`}>
        Model cache TTL (s)
        <Input
          id={`${meta.sectionId}-cache-ttl`}
          type="number"
          min={0}
          step={1}
          value={state.cacheTtl}
          disabled={busy}
          onChange={(event) => actions.setCacheTtl(event.target.value)}
          onBlur={() => actions.persistField()}
          onKeyDown={persistOnEnter}
          className="h-8 text-xs"
        />
      </label>
    </div>
  );
}

function ReasoningEffort() {
  const { busy, meta, state, actions } = useSidecarIntegration();
  return (
    <label className="space-y-1 text-xs font-medium" htmlFor={`${meta.sectionId}-default-effort`}>
      Reasoning effort override
      <Select
        value={state.defaultReasoningEffort ?? REASONING_EFFORT_UNSET}
        onValueChange={(value) =>
          actions.setDefaultReasoningEffort(
            value === REASONING_EFFORT_UNSET ? null : (value as SidecarReasoningEffort),
          )
        }
      >
        <SelectTrigger id={`${meta.sectionId}-default-effort`} className="h-8 text-xs" disabled={busy}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={REASONING_EFFORT_UNSET}>Use client / model default</SelectItem>
          {REASONING_EFFORT_OPTIONS.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <span className="block font-normal text-muted-foreground">
        Forces this effort on every request, overriding what the client sends (an explicit model-name suffix still wins).
      </span>
    </label>
  );
}

type RoutingProps = {
  strategy?: ClaudeSidecarRoutingStrategy | null;
  accounts: ClaudeSidecarRoutingAccount[];
  busy: boolean;
  isLoading?: boolean;
  message?: string | null;
  onStrategyChange: (strategy: ClaudeSidecarRoutingStrategy) => void;
  onPriorityChange: (name: string, priority: number) => void;
};

type PriorityInputProps = {
  account: ClaudeSidecarRoutingAccount;
  disabled: boolean;
  onCommit: (priority: number) => void;
};

function PriorityInput({ account, disabled, onCommit }: PriorityInputProps) {
  const [value, setValue] = useState(String(account.priority));
  const lastCommitted = useRef(account.priority);

  useEffect(() => {
    setValue(String(account.priority));
    lastCommitted.current = account.priority;
  }, [account.priority]);

  const commit = () => {
    const next = Number.parseInt(value, 10);
    if (!Number.isFinite(next) || next < 0 || next === lastCommitted.current) {
      setValue(String(lastCommitted.current));
      return;
    }
    lastCommitted.current = next;
    onCommit(next);
  };

  return (
    <Input
      aria-label={`Priority for ${account.email || account.name}`}
      type="number"
      min={0}
      value={value}
      disabled={disabled}
      onChange={(event) => setValue(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          commit();
        }
      }}
      className="h-8 w-24 text-xs"
    />
  );
}

function Routing({
  strategy,
  accounts,
  busy,
  isLoading = false,
  message,
  onStrategyChange,
  onPriorityChange,
}: RoutingProps) {
  return (
    <div className="space-y-3 rounded-md border bg-muted/10 p-3" aria-label="CLIProxyAPI routing controls">
      <div>
        <p className="text-sm font-medium">CLIProxyAPI routing</p>
        <p className="text-xs text-muted-foreground">
          Choose how CLIProxyAPI rotates Claude accounts and tune priority live. Higher number = preferred.
        </p>
      </div>
      <label className="space-y-1 text-xs font-medium" htmlFor="claude-sidecar-routing-strategy">
        Routing strategy
        <Select
          value={strategy ?? undefined}
          onValueChange={(value) => onStrategyChange(value as ClaudeSidecarRoutingStrategy)}
          disabled={busy || isLoading || !strategy}
        >
          <SelectTrigger id="claude-sidecar-routing-strategy" className="h-8 text-xs">
            <SelectValue placeholder={isLoading ? "Loading routing..." : "Unknown strategy"} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="round_robin">Round robin</SelectItem>
            <SelectItem value="fill_first">Fill first</SelectItem>
          </SelectContent>
        </Select>
      </label>
      <p className="text-xs text-muted-foreground">
        Fill first burns the highest-priority available account until it cools down; round robin spreads requests within the top-priority group.
      </p>
      {message ? <p className="text-xs text-muted-foreground">{message}</p> : null}
      <div className="space-y-2">
        {isLoading ? <p className="text-xs text-muted-foreground">Loading accounts...</p> : null}
        {!isLoading && accounts.length === 0 ? (
          <p className="text-xs text-muted-foreground">No Claude accounts reported by CLIProxyAPI.</p>
        ) : null}
        {accounts.map((account) => (
          <div
            key={account.name}
            className="flex flex-wrap items-center justify-between gap-2 rounded-md border bg-background/60 px-2 py-1.5"
          >
            <div className="min-w-0">
              <p className="truncate text-xs font-medium">{account.email || account.name}</p>
              <p className="truncate font-mono text-[11px] text-muted-foreground">{account.name}</p>
            </div>
            <PriorityInput
              account={account}
              disabled={busy || isLoading}
              onCommit={(priority) => onPriorityChange(account.name, priority)}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function Status() {
  const { state } = useSidecarIntegration();
  if (!state.saveError) {
    return null;
  }
  return <AlertMessage variant="error">{state.saveError}</AlertMessage>;
}

export const SidecarIntegrationCard = {
  Provider: SidecarIntegrationCardProvider,
  Frame,
  Header,
  Callout,
  Fields,
  BaseUrl,
  Secrets,
  Prefixes,
  FullModels,
  DiscoveredModels,
  Timeouts,
  ReasoningEffort,
  Routing,
  Status,
};
