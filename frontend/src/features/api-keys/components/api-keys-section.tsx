import { KeySquare } from "lucide-react";
import { lazy, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { AlertMessage } from "@/components/alert-message";
import { Button } from "@/components/ui/button";
import { useDialogState } from "@/hooks/use-dialog-state";
import { ApiKeyAuthToggle } from "@/features/api-keys/components/api-key-auth-toggle";
import { ApiKeyQuotaPrivacyToggle } from "@/features/api-keys/components/api-key-quota-privacy-toggle";
import { ApiKeyCreatedDialog } from "@/features/api-keys/components/api-key-created-dialog";
import { ApiKeyTable } from "@/features/api-keys/components/api-key-table";
import { useApiKeys } from "@/features/api-keys/hooks/use-api-keys";
import type { ApiKey, ApiKeyCreateRequest, ApiKeyUpdateRequest } from "@/features/api-keys/schemas";
import { getErrorMessageOrNull } from "@/utils/errors";
import { SettingsRowGroup, SettingsSection, SettingsSectionHeader } from "@/features/settings/components/settings-section";

const ApiKeyCreateDialog = lazy(() =>
  import("@/features/api-keys/components/api-key-create-dialog").then((m) => ({ default: m.ApiKeyCreateDialog })),
);
const ApiKeyEditDialog = lazy(() =>
  import("@/features/api-keys/components/api-key-edit-dialog").then((m) => ({ default: m.ApiKeyEditDialog })),
);

export type ApiKeysSectionProps = {
  apiKeyAuthEnabled: boolean;
  hideUpstreamQuotaFromApiKeys: boolean;
  disabled?: boolean;
  onApiKeyAuthEnabledChange: (enabled: boolean) => void;
  onHideUpstreamQuotaFromApiKeysChange: (enabled: boolean) => void;
};

export function ApiKeysSection({
  apiKeyAuthEnabled,
  hideUpstreamQuotaFromApiKeys,
  disabled = false,
  onApiKeyAuthEnabledChange,
  onHideUpstreamQuotaFromApiKeysChange,
}: ApiKeysSectionProps) {
  const { t } = useTranslation();
  const {
    apiKeysQuery,
    createMutation,
    updateMutation,
    deleteMutation,
    regenerateMutation,
  } = useApiKeys();

  const createDialog = useDialogState();
  const editDialog = useDialogState<ApiKey>();
  const deleteDialog = useDialogState<ApiKey>();
  const createdDialog = useDialogState<string>();

  const keys = apiKeysQuery.data ?? [];
  const busy =
    disabled ||
    apiKeysQuery.isFetching ||
    createMutation.isPending ||
    updateMutation.isPending ||
    deleteMutation.isPending ||
    regenerateMutation.isPending;

  const mutationError = useMemo(
    () =>
      getErrorMessageOrNull(createMutation.error) ||
      getErrorMessageOrNull(updateMutation.error) ||
      getErrorMessageOrNull(deleteMutation.error) ||
      getErrorMessageOrNull(regenerateMutation.error),
    [createMutation.error, deleteMutation.error, regenerateMutation.error, updateMutation.error],
  );

  const handleCreate = async (payload: ApiKeyCreateRequest) => {
    const created = await createMutation.mutateAsync(payload);
    createdDialog.show(created.key);
  };

  const handleUpdate = async (payload: ApiKeyUpdateRequest) => {
    if (!editDialog.data) {
      return;
    }
    await updateMutation.mutateAsync({ keyId: editDialog.data.id, payload });
  };

  return (
    <SettingsSection>
      <SettingsSectionHeader
        icon={KeySquare}
        title={t("apiKeys.section.title")}
        description={t("apiKeys.section.description")}
        actions={
          <Button type="button" size="sm" className="h-9 text-xs" onClick={() => createDialog.show()} disabled={busy}>
            {t("apiKeys.section.createKey")}
          </Button>
        }
      />

      <SettingsRowGroup>
        <ApiKeyAuthToggle
          enabled={apiKeyAuthEnabled}
          disabled={busy}
          onChange={onApiKeyAuthEnabledChange}
        />
        <ApiKeyQuotaPrivacyToggle
          enabled={hideUpstreamQuotaFromApiKeys}
          disabled={busy}
          onChange={onHideUpstreamQuotaFromApiKeysChange}
        />
      </SettingsRowGroup>

      {mutationError ? <AlertMessage variant="error">{mutationError}</AlertMessage> : null}

      <ApiKeyTable
        keys={keys}
        busy={busy}
        onEdit={(apiKey) => editDialog.show(apiKey)}
        onDelete={(apiKey) => deleteDialog.show(apiKey)}
        onRegenerate={(apiKey) => {
          void regenerateMutation.mutateAsync(apiKey.id).then((result) => {
            createdDialog.show(result.key);
          });
        }}
      />

      <ApiKeyCreateDialog
        open={createDialog.open}
        busy={createMutation.isPending}
        onOpenChange={createDialog.onOpenChange}
        onSubmit={handleCreate}
      />

      <ApiKeyEditDialog
        open={editDialog.open}
        busy={updateMutation.isPending}
        apiKey={editDialog.data}
        onOpenChange={editDialog.onOpenChange}
        onSubmit={handleUpdate}
      />

      <ApiKeyCreatedDialog
        open={createdDialog.open}
        apiKey={createdDialog.data}
        onOpenChange={createdDialog.onOpenChange}
      />

      <ConfirmDialog
        open={deleteDialog.open}
        title={t("apiKeys.deleteDialog.title")}
        description={t("apiKeys.deleteDialog.description")}
        confirmLabel={t("common.actions.delete")}
        onOpenChange={deleteDialog.onOpenChange}
        onConfirm={() => {
          if (!deleteDialog.data) {
            return;
          }
          void deleteMutation.mutateAsync(deleteDialog.data.id).finally(() => {
            deleteDialog.hide();
          });
        }}
      />
    </SettingsSection>
  );
}
