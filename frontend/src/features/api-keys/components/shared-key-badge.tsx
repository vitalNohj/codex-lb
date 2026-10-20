import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";

/** Marks a key handed to a friend or client: it sees only its own usage. */
export function SharedKeyBadge() {
  const { t } = useTranslation();
  return (
    <Badge
      variant="outline"
      className="shrink-0 border-sky-500/50 text-sky-700 dark:text-sky-300"
      title={t("apiKeys.form.sharedKeyTooltip")}
    >
      {t("apiKeys.badges.shared")}
    </Badge>
  );
}
