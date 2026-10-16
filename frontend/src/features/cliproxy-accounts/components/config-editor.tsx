import { useLayoutEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import {
  CLIPROXY_CONFIG_QUERY_KEY,
  getCliproxyConfig,
  patchCliproxyRoutingFlag,
  previewCliproxyConfig,
  replaceCliproxyConfig,
  rollbackCliproxyConfig,
  type CliproxyConfigView,
} from "@/features/cliproxy-accounts/api";
import { ApiError } from "@/lib/api-client";

type ReviewedDraft = { yaml: string; sha: string };
type ConfigDraft = { yaml: string; baseSha: string };

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function applyView(
  queryClient: ReturnType<typeof useQueryClient>,
  view: CliproxyConfigView,
): void {
  queryClient.setQueryData(CLIPROXY_CONFIG_QUERY_KEY, view);
}

export function CliproxyConfigEditor() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: CLIPROXY_CONFIG_QUERY_KEY,
    queryFn: getCliproxyConfig,
  });
  const [draft, setDraft] = useState<ConfigDraft | null>(null);
  const [reviewed, setReviewed] = useState<ReviewedDraft | null>(null);
  const [dialog, setDialog] = useState<"preview" | "rollback" | null>(null);
  const [diff, setDiff] = useState("");
  const [previewChanged, setPreviewChanged] = useState(false);

  const view = query.data;
  const serverYaml = view?.yaml ?? "";
  const serverSha = view?.contentSha256 ?? "";
  const yaml = draft?.yaml ?? serverYaml;
  const dirty = draft !== null && draft.yaml !== serverYaml;
  const draftIsStale = draft !== null && draft.baseSha !== serverSha;
  const yamlRef = useRef(yaml);
  const shaRef = useRef(serverSha);
  const draftRef = useRef(draft);
  useLayoutEffect(() => {
    yamlRef.current = yaml;
    shaRef.current = serverSha;
    draftRef.current = draft;
  }, [yaml, serverSha, draft]);
  const healthy = view?.status === "healthy" && serverSha !== "";
  const affinity =
    view?.sessionAffinity === true ? "on" : view?.sessionAffinity === false ? "off" : "unreadable";

  const previewMutation = useMutation({
    mutationFn: (submitted: ReviewedDraft) =>
      previewCliproxyConfig({ yaml: submitted.yaml, contentSha256: submitted.sha }),
    onSuccess: (preview, submitted) => {
      if (submitted.yaml !== yamlRef.current || submitted.sha !== shaRef.current) {
        toast.error("The draft changed before the preview finished. Review it again.");
        return;
      }
      if (preview.status !== "healthy") {
        toast.error(preview.message || "Could not preview the config");
        return;
      }
      setReviewed(submitted);
      setDiff(preview.diff);
      setPreviewChanged(preview.changed);
      setDialog("preview");
    },
    onError: (error: unknown) => {
      toast.error(errorMessage(error, "Could not preview the config"));
    },
  });

  const replaceMutation = useMutation({
    mutationFn: (submitted: ReviewedDraft) =>
      replaceCliproxyConfig({ yaml: submitted.yaml, contentSha256: submitted.sha, confirm: true }),
    onSuccess: (next) => {
      if (next.status !== "healthy") {
        toast.error(next.message || "CLIProxyAPI rejected the config");
        return;
      }
      applyView(queryClient, next);
      setDraft(null);
      setReviewed(null);
      setDialog(null);
      toast.success("CLIProxyAPI config replaced");
    },
    onError: (error: unknown) => {
      toast.error(errorMessage(error, "Could not replace the config"));
    },
  });

  const rollbackMutation = useMutation({
    mutationFn: rollbackCliproxyConfig,
    onSuccess: (next) => {
      if (next.status !== "healthy") {
        toast.error(next.message || "Could not roll back the config");
        return;
      }
      applyView(queryClient, next);
      setDraft(null);
      setReviewed(null);
      setDialog(null);
      toast.success("CLIProxyAPI config restored");
    },
    onError: (error: unknown) => {
      toast.error(errorMessage(error, "Could not roll back the config"));
    },
  });

  const prefixMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      patchCliproxyRoutingFlag("force-model-prefix", { enabled, contentSha256: serverSha }),
    onSuccess: (next) => {
      if (next.status !== "healthy") {
        toast.error(next.message || "Could not update force model prefix");
        return;
      }
      applyView(queryClient, next);
      setDraft(null);
      setReviewed(null);
    },
    onError: (error: unknown) => {
      toast.error(errorMessage(error, "Could not update force model prefix"));
    },
  });

  const busy =
    previewMutation.isPending || replaceMutation.isPending || rollbackMutation.isPending || prefixMutation.isPending;

  async function reload() {
    setReviewed(null);
    const previousYaml = serverYaml;
    const previousSha = serverSha;
    const result = await query.refetch();
    const fresh = result.data;
    if (!fresh || fresh.status !== "healthy") {
      toast.error(fresh?.message || "Could not reload the config");
      return;
    }
    const freshYaml = fresh.yaml ?? "";
    const freshSha = fresh.contentSha256 ?? "";
    const serverChanged = freshYaml !== previousYaml || freshSha !== previousSha;
    const pending = draftRef.current;
    if (pending !== null && (serverChanged || pending.baseSha !== freshSha)) {
      setDraft(null);
      toast.error("The live config changed, so the draft was dropped.");
      return;
    }
    toast.success("CLIProxyAPI config reloaded");
  }

  return (
    <section aria-label="Config file" className="flex min-w-0 flex-col gap-4 rounded-lg border bg-background/40 p-4">
      <div>
        <h4 className="text-sm font-semibold">Config file</h4>
        <p className="mt-0.5 text-[13px] leading-relaxed text-muted-foreground">
          Read and replace CLIProxyAPI&apos;s config.yaml. Secrets are redacted before they reach this page. A
          placeholder keeps the current secret, and the previous file stays in codex-lb so you can roll it back.
        </p>
      </div>

      {query.isLoading ? <p className="text-sm text-muted-foreground">Loading config…</p> : null}
      {query.isError ? (
        <p className="text-sm text-destructive">
          {query.error instanceof ApiError ? query.error.message : "Could not load the config file."}
        </p>
      ) : null}
      {view && view.status !== "healthy" ? (
        <p className="text-sm text-muted-foreground">{view.message || "CLIProxyAPI config is unavailable."}</p>
      ) : null}

      {healthy ? (
        <>
          <label className="block space-y-1.5 text-sm font-medium" htmlFor="cliproxy-config-yaml">
            config.yaml
            <textarea
              id="cliproxy-config-yaml"
              className="mt-1.5 min-h-72 w-full resize-y rounded-md border bg-background px-3 py-2 font-mono text-[12px] leading-relaxed"
              spellCheck={false}
              autoCapitalize="off"
              autoCorrect="off"
              value={yaml}
              onChange={(event) => {
                const next = event.target.value;
                setReviewed(null);
                if (dialog === "preview") setDialog(null);
                if (next === serverYaml) {
                  setDraft(null);
                  return;
                }
                setDraft((current) => ({ yaml: next, baseSha: current?.baseSha ?? serverSha }));
              }}
            />
          </label>
          <p className="text-[13px] leading-relaxed text-muted-foreground">
            Session affinity is {affinity}. Change it from CLIProxyAPI routing above. Replacing this document creates a
            new config file with the same confirmation.
          </p>
          {draftIsStale ? (
            <p className="text-sm text-destructive">
              The live config changed. Reload to drop this draft before reviewing it.
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              disabled={busy || draftIsStale}
              onClick={() => previewMutation.mutate({ yaml, sha: draft?.baseSha ?? serverSha })}
            >
              Review changes
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy || query.isFetching}
              onClick={() => void reload()}
            >
              Reload
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy || !view.rollbackAvailable}
              onClick={() => setDialog("rollback")}
            >
              Roll back
            </Button>
          </div>
          <label className="flex items-center justify-between gap-3 text-sm font-medium" htmlFor="cliproxy-force-model-prefix">
            Force model prefix
            <Switch
              id="cliproxy-force-model-prefix"
              checked={prefixMutation.isPending ? prefixMutation.variables === true : view.forceModelPrefix === true}
              disabled={busy || dirty || typeof view.forceModelPrefix !== "boolean"}
              onCheckedChange={(enabled) => prefixMutation.mutate(enabled)}
            />
          </label>
          <p className="text-[13px] leading-relaxed text-muted-foreground">
            When on, a request without an account prefix only uses credentials that have no prefix. Leave it off unless
            you mean to stop bare model ids.
            {dirty ? " Review or revert the draft before changing this." : ""}
          </p>
        </>
      ) : null}

      <Dialog open={dialog !== null} onOpenChange={(open) => { if (!open) setDialog(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{dialog === "rollback" ? "Roll back the config file?" : "Replace the config file?"}</DialogTitle>
            <DialogDescription>
              {dialog === "rollback"
                ? "This uploads the previous config.yaml kept in codex-lb and makes that the file you can roll back to next."
                : "This overwrites the live config.yaml. Placeholders stay as the current secrets and are not written into the file."}
            </DialogDescription>
          </DialogHeader>
          {dialog === "preview" ? (
            <pre className="max-h-80 overflow-auto rounded-md border bg-muted/40 p-3 font-mono text-[12px] leading-relaxed whitespace-pre-wrap">
              {diff || "No changes to write."}
            </pre>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" size="sm" onClick={() => setDialog(null)} disabled={busy}>
              Cancel
            </Button>
            {dialog === "rollback" ? (
              <Button
                type="button"
                variant="destructive"
                size="sm"
                disabled={busy}
                onClick={() => rollbackMutation.mutate()}
              >
                Roll back
              </Button>
            ) : (
              <Button
                type="button"
                size="sm"
                disabled={busy || !previewChanged || reviewed === null}
                onClick={() => {
                  if (reviewed) replaceMutation.mutate(reviewed);
                }}
              >
                Replace config
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
