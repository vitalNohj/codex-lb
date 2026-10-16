import { Check, CircleAlert, Copy, ExternalLink, Loader2, RefreshCw } from "lucide-react";
import { useCallback, useState, type MouseEvent } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { CliproxyOauthState } from "@/features/settings/schemas";
import { cn } from "@/lib/utils";
import { copyToClipboard } from "@/utils/clipboard";
import { formatCountdown } from "@/utils/formatters";

const PROVIDER_LABELS: Record<string, string> = {
  claude: "Claude",
  xai: "xAI",
  codex: "Codex",
  antigravity: "Antigravity",
  devin: "Devin",
  meta: "Meta",
  kimi: "Kimi",
  "kimi-ai": "Kimi AI",
};

type Stage = "intro" | "browser" | "device" | "success" | "error";

function providerLabel(provider: string): string {
  return PROVIDER_LABELS[provider] ?? provider;
}

function getStage(state: CliproxyOauthState): Stage {
  if (state.status === "success") return "success";
  if (state.status === "error") return "error";
  if (state.method === "browser" && (state.status === "pending" || state.status === "starting")) return "browser";
  if (state.method === "device" && (state.status === "pending" || state.status === "starting")) return "device";
  return "intro";
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(async (event: MouseEvent<HTMLButtonElement>) => {
    const trigger = event.currentTarget;
    const dialogContainer = trigger.closest("[role='dialog']");
    const copiedToClipboard = await copyToClipboard(text, {
      container: dialogContainer instanceof HTMLElement ? dialogContainer : undefined,
    });
    if (!copiedToClipboard) {
      return;
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }, [text]);

  return (
    <Button
      type="button"
      size="sm"
      variant="ghost"
      className="h-7 cursor-pointer gap-1 px-2 text-xs"
      onMouseDown={(event) => event.preventDefault()}
      onClick={(event) => void handleCopy(event)}
    >
      {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
      {copied ? "Copied" : "Copy"}
    </Button>
  );
}

function ManualCallbackInput({
  onSubmit,
  disabled = false,
}: {
  onSubmit: (callbackUrl: string) => Promise<void>;
  disabled?: boolean;
}) {
  const [callbackUrl, setCallbackUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const handleSubmit = useCallback(async () => {
    if (!callbackUrl.trim()) return;
    setSubmitting(true);
    try {
      await onSubmit(callbackUrl.trim());
      setCallbackUrl("");
    } catch {
      // The dialog state renders the error.
    } finally {
      setSubmitting(false);
    }
  }, [callbackUrl, onSubmit]);

  return (
    <div className="space-y-1.5">
      <p className="text-xs font-medium text-muted-foreground">Paste the callback URL</p>
      <div className="flex items-center gap-2">
        <input
          type="text"
          aria-label="Sign-in callback URL"
          value={callbackUrl}
          onChange={(event) => setCallbackUrl(event.target.value)}
          disabled={disabled}
          placeholder="http://127.0.0.1:54545/callback?code=...&state=..."
          className="flex-1 rounded-lg border bg-muted/20 px-3 py-2 font-mono text-xs outline-none focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-60"
        />
        <Button
          type="button"
          size="sm"
          className="h-8 cursor-pointer px-3 text-xs"
          disabled={disabled || !callbackUrl.trim() || submitting}
          onClick={() => void handleSubmit()}
        >
          {submitting ? "Submitting" : "Submit"}
        </Button>
      </div>
    </div>
  );
}

export type CliproxyAuthorizeDialogProps = {
  open: boolean;
  providers: Array<{ provider: string; method: "browser" | "device" }>;
  providersLoading: boolean;
  providersError: boolean;
  state: CliproxyOauthState;
  onOpenChange: (open: boolean) => void;
  onStart: (provider: string) => Promise<void>;
  onManualCallback: (callbackUrl: string) => Promise<void>;
  onReset: () => void;
};

export function CliproxyAuthorizeDialog({
  open,
  providers,
  providersLoading,
  providersError,
  state,
  onOpenChange,
  onStart,
  onManualCallback,
  onReset,
}: CliproxyAuthorizeDialogProps) {
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null);
  const stage = getStage(state);
  const activeProvider = selectedProvider ?? providers[0]?.provider ?? null;
  const browserRefreshInProgress = stage === "browser" && state.status === "starting";

  const close = (next: boolean) => {
    onOpenChange(next);
    if (!next) {
      onReset();
      setSelectedProvider(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {stage === "success" ? "Sign-in complete" : stage === "error" ? "Sign-in failed" : "Sign in a CLIProxyAPI account"}
          </DialogTitle>
          {stage === "intro" ? (
            <DialogDescription>
              Each sign-in adds an account. xAI and the other providers here can have more than one.
            </DialogDescription>
          ) : null}
        </DialogHeader>

        {stage === "intro" ? (
          <div className="space-y-2">
            {providersLoading ? <p className="text-sm text-muted-foreground">Loading providers...</p> : null}
            {providersError ? <p className="text-sm text-destructive">Could not load sign-in providers.</p> : null}
            {providers.map((provider) => (
              <button
                key={provider.provider}
                type="button"
                onClick={() => setSelectedProvider(provider.provider)}
                className={cn(
                  "w-full cursor-pointer rounded-lg border p-3 text-left transition-colors",
                  activeProvider === provider.provider ? "border-primary bg-primary/5" : "hover:bg-muted/50",
                )}
              >
                <p className="text-sm font-medium">{providerLabel(provider.provider)}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {provider.method === "device" ? "Device code" : "Browser sign-in"}
                </p>
              </button>
            ))}
          </div>
        ) : null}

        {stage === "browser" ? (
          <div className="min-w-0 space-y-3 text-sm">
            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-medium text-muted-foreground">Authorization URL</p>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="h-7 cursor-pointer gap-1 px-2 text-xs"
                  disabled={browserRefreshInProgress || !state.provider}
                  onClick={() => {
                    if (state.provider) void onStart(state.provider);
                  }}
                >
                  {browserRefreshInProgress ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
                  Refresh link
                </Button>
              </div>
              {state.authorizationUrl ? (
                <div className="flex min-w-0 items-center gap-2 rounded-lg border bg-muted/20 px-3 py-2">
                  <p className="min-w-0 flex-1 truncate font-mono text-xs">{state.authorizationUrl}</p>
                  <CopyButton text={state.authorizationUrl} />
                </div>
              ) : null}
            </div>
            <ManualCallbackInput onSubmit={onManualCallback} disabled={browserRefreshInProgress} />
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              <span>Waiting for sign-in to finish</span>
            </div>
          </div>
        ) : null}

        {stage === "device" ? (
          <div className="space-y-3 text-sm">
            <ol className="list-inside list-decimal space-y-1 text-xs text-muted-foreground">
              <li>Open the verification page.</li>
              <li>Enter the code.</li>
              <li>Finish sign-in in the browser. This page updates on its own.</li>
            </ol>
            {state.userCode ? (
              <div className="space-y-1.5">
                <p className="text-xs font-medium text-muted-foreground">Code</p>
                <div className="flex items-center gap-2 rounded-lg border bg-muted/20 px-3 py-2">
                  <p className="min-w-0 flex-1 font-mono text-lg font-bold tracking-widest">{state.userCode}</p>
                  <CopyButton text={state.userCode} />
                </div>
              </div>
            ) : null}
            {state.verificationUrl ? (
              <div className="space-y-1.5">
                <p className="text-xs font-medium text-muted-foreground">Verification URL</p>
                <div className="flex min-w-0 items-center gap-2 rounded-lg border bg-muted/20 px-3 py-2">
                  <p className="min-w-0 flex-1 truncate font-mono text-xs">{state.verificationUrl}</p>
                  <CopyButton text={state.verificationUrl} />
                </div>
              </div>
            ) : null}
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              <span>
                Waiting
                {state.expiresInSeconds != null && state.expiresInSeconds > 0
                  ? ` · expires in ${formatCountdown(state.expiresInSeconds)}`
                  : "..."}
              </span>
            </div>
          </div>
        ) : null}

        {stage === "success" ? (
          <div className="flex items-center gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-3 py-3 text-sm text-emerald-700 dark:text-emerald-400">
            <Check className="h-4 w-4 shrink-0" />
            <p>The account was added. Its credential appears in the list.</p>
          </div>
        ) : null}

        {stage === "error" ? (
          <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-3 text-sm text-destructive">
            <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />
            <p>{state.errorMessage || "Sign-in failed"}</p>
          </div>
        ) : null}

        <DialogFooter>
          {stage === "intro" ? (
            <>
              <Button type="button" variant="outline" onClick={() => close(false)}>
                Cancel
              </Button>
              <Button
                type="button"
                disabled={!activeProvider || providersLoading}
                onClick={() => {
                  if (activeProvider) void onStart(activeProvider);
                }}
              >
                Start sign-in
              </Button>
            </>
          ) : null}
          {stage === "browser" ? (
            <>
              <Button type="button" variant="outline" onClick={() => close(false)} disabled={browserRefreshInProgress}>
                Cancel
              </Button>
              {state.authorizationUrl && !browserRefreshInProgress ? (
                <Button type="button" asChild>
                  <a href={state.authorizationUrl} target="_blank" rel="noreferrer">
                    <ExternalLink className="mr-1.5 h-3.5 w-3.5" />
                    Open sign-in page
                  </a>
                </Button>
              ) : null}
            </>
          ) : null}
          {stage === "device" ? (
            <>
              <Button type="button" variant="outline" onClick={() => close(false)}>
                Cancel
              </Button>
              {state.verificationUrl ? (
                <Button type="button" asChild>
                  <a href={state.verificationUrl} target="_blank" rel="noreferrer">
                    <ExternalLink className="mr-1.5 h-3.5 w-3.5" />
                    Open verification page
                  </a>
                </Button>
              ) : null}
            </>
          ) : null}
          {stage === "success" ? (
            <Button type="button" onClick={() => close(false)}>
              Done
            </Button>
          ) : null}
          {stage === "error" ? (
            <>
              <Button type="button" variant="outline" onClick={() => onReset()}>
                Try again
              </Button>
              <Button type="button" onClick={() => close(false)}>
                Close
              </Button>
            </>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
