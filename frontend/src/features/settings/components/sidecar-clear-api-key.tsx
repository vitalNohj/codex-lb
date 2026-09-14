import { useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { Button } from "@/components/ui/button";

export type ClearStoredApiKeyProps = {
  /** Renders nothing when no key is stored - there is nothing to remove. */
  apiKeyConfigured: boolean;
  /** Short integration name used in the confirmation title. */
  integrationName: string;
  /** Optional integration-specific consequence copy. */
  description?: string;
  disabled: boolean;
  /** Performs the removal. Rejections surface through {@link onError}. */
  onClear: () => Promise<unknown>;
  /** Receives a removal failure so the caller can render it inline. */
  onError: (message: string) => void;
};

/**
 * Deliberate, confirmed removal of a stored integration key.
 *
 * Secrets are write-only: the server never returns a key, so the only honest
 * controls are "replace it" and "remove it". Removal sits behind a confirmation
 * because it disables routing until a new key is supplied, and the key cannot
 * be read back to undo the change.
 *
 * Presentational by design - it takes no context - so the compound
 * `SidecarIntegrationCard` module gains no further non-component exports.
 */
export function ClearStoredApiKey({
  apiKeyConfigured,
  integrationName,
  description,
  disabled,
  onClear,
  onError,
}: ClearStoredApiKeyProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pending, setPending] = useState(false);
  if (!apiKeyConfigured) {
    return null;
  }

  const clear = async () => {
    setPending(true);
    try {
      await onClear();
    } catch (error) {
      onError(error instanceof Error ? error.message : "Failed to remove the stored key");
    } finally {
      setPending(false);
    }
  };
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-destructive/20 bg-destructive/5 px-3 py-2">
      <p className="text-xs text-muted-foreground">
        A key is stored for this integration. Removing it stops all routing until a new key is added.
      </p>
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="h-8 shrink-0 text-xs text-destructive"
        disabled={disabled || pending}
        onClick={() => setConfirmOpen(true)}
      >
        Remove stored key
      </Button>
      <ConfirmDialog
        open={confirmOpen}
        title={`Remove the stored ${integrationName} key?`}
        description={
          description ??
          "The stored key is deleted immediately. Requests to this integration fail until a new key is added."
        }
        confirmLabel="Remove key"
        onConfirm={() => {
          setConfirmOpen(false);
          void clear();
        }}
        onOpenChange={setConfirmOpen}
      />
    </div>
  );
}
