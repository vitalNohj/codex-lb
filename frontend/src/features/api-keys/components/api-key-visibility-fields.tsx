import { CircleHelp } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Checkbox } from "@/components/ui/checkbox";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { UsageSectionsMultiSelect } from "@/features/api-keys/components/usage-sections-multi-select";

export type ApiKeyVisibilityFieldsProps = {
  /** Prefix for element ids, unique per dialog. */
  idPrefix: string;
  isShared: boolean;
  usageSections: string;
  onIsSharedChange: (isShared: boolean) => void;
  onUsageSectionsChange: (usageSections: string) => void;
};

/**
 * The "Shared key" toggle and the usage sections it overrides.
 *
 * A shared key sees only its own usage, limits and expiry, so the sections
 * picker is disabled while the toggle is on. Its value is kept untouched and
 * still submitted, so turning the toggle off restores what the key saw.
 */
export function ApiKeyVisibilityFields({
  idPrefix,
  isShared,
  usageSections,
  onIsSharedChange,
  onUsageSectionsChange,
}: ApiKeyVisibilityFieldsProps) {
  const { t } = useTranslation();
  const sharedId = `${idPrefix}-shared`;
  const sharedHintId = `${idPrefix}-shared-hint`;
  const sectionsHintId = `${idPrefix}-usage-sections-hint`;
  const sectionsOverrideId = `${idPrefix}-usage-sections-overridden`;

  return (
    <>
      <div className="space-y-1 rounded-md border p-2 text-sm">
        <div className="flex items-center gap-2">
          <Checkbox
            id={sharedId}
            checked={isShared}
            aria-describedby={sharedHintId}
            onCheckedChange={(checked) => onIsSharedChange(checked === true)}
          />
          <label htmlFor={sharedId} className="cursor-pointer">
            {t("apiKeys.form.sharedKey")}
          </label>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className="text-muted-foreground hover:text-foreground"
                  aria-label={t("apiKeys.form.sharedKeyHelpLabel")}
                >
                  <CircleHelp className="size-3.5" aria-hidden="true" />
                </button>
              </TooltipTrigger>
              <TooltipContent className="max-w-xs">{t("apiKeys.form.sharedKeyTooltip")}</TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
        <p id={sharedHintId} className="text-xs text-muted-foreground">
          {t("apiKeys.form.sharedKeyHint")}
        </p>
      </div>

      <div className="space-y-1">
        <div className="text-sm font-medium">{t("apiKeys.form.usageSections")}</div>
        <UsageSectionsMultiSelect
          value={usageSections}
          onChange={onUsageSectionsChange}
          disabled={isShared}
          aria-describedby={isShared ? `${sectionsOverrideId} ${sectionsHintId}` : sectionsHintId}
        />
        {isShared ? (
          <p id={sectionsOverrideId} className="text-xs font-medium text-amber-600 dark:text-amber-400">
            {t("apiKeys.form.usageSectionsOverriddenByShared")}
          </p>
        ) : null}
        <p id={sectionsHintId} className="text-xs text-muted-foreground">
          {t("apiKeys.form.usageSectionsHint")}
        </p>
      </div>
    </>
  );
}
