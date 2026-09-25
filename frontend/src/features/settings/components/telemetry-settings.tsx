import { Activity } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertMessage } from "@/components/alert-message";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { TelemetryPayloadPreview } from "@/features/settings/components/telemetry-payload-preview";
import { useTelemetryConsent, useTelemetryPreview } from "@/features/settings/hooks/use-settings";
import { SettingsRow, SettingsRowGroup, SettingsSection, SettingsSectionHeader } from "@/features/settings/components/settings-section";

export type TelemetrySettingsProps = {
  disabled: boolean;
};

export function TelemetrySettings({ disabled }: TelemetrySettingsProps) {
  const { t } = useTranslation();
  const [previewOpen, setPreviewOpen] = useState(false);
  const { telemetryConsentQuery, updateTelemetryConsentMutation } = useTelemetryConsent();
  // Building the snapshot is expensive, so the preview is fetched only once
  // the operator opens the dialog.
  const { telemetryPreviewQuery } = useTelemetryPreview(previewOpen);

  const consent = telemetryConsentQuery.data;
  const envControlled = consent?.source === "env";
  const busy = disabled || updateTelemetryConsentMutation.isPending || !consent;
  const previewEnvelope = telemetryPreviewQuery.data?.preview ?? null;

  return (
    <SettingsSection>
      <SettingsSectionHeader
        icon={Activity}
        title={t("settings.telemetry.title")}
        description={t("settings.telemetry.description")}
        actions={
          <Switch
            aria-label={t("settings.telemetry.toggleAria")}
            checked={consent?.active ?? false}
            disabled={busy || envControlled}
            onCheckedChange={(checked) => updateTelemetryConsentMutation.mutate({ enabled: checked })}
          />
        }
      />

      <p className="text-[13px] leading-relaxed text-muted-foreground">{t("settings.telemetry.optOutNotice")}</p>

      {envControlled ? (
        <div className="rounded-lg border border-primary/25 bg-primary/8 px-4 py-3 text-sm font-medium text-foreground">
          {t("settings.telemetry.envNotice")}
        </div>
      ) : null}

      <SettingsRowGroup>
        <SettingsRow
          label={t("settings.telemetry.collectedData.label")}
          description={t("settings.telemetry.collectedData.description")}
        >
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-9 text-xs"
            disabled={!consent}
            onClick={() => setPreviewOpen(true)}
          >
            {t("settings.telemetry.collectedData.view")}
          </Button>
        </SettingsRow>
      </SettingsRowGroup>

      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        {previewOpen ? (
          <DialogContent className="sm:max-w-2xl">
            <DialogHeader>
              <DialogTitle>{t("settings.telemetry.previewDialog.title")}</DialogTitle>
              <DialogDescription>
                {t("settings.telemetry.previewDialog.description")}
              </DialogDescription>
            </DialogHeader>
            {previewEnvelope ? (
              <TelemetryPayloadPreview preview={previewEnvelope} />
            ) : telemetryPreviewQuery.error ? (
              <AlertMessage variant="error">{telemetryPreviewQuery.error.message}</AlertMessage>
            ) : (
              <Skeleton className="h-64 w-full rounded-lg" />
            )}
            <DialogFooter showCloseButton />
          </DialogContent>
        ) : null}
      </Dialog>
    </SettingsSection>
  );
}
