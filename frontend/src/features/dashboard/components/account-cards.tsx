import { Users } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { AccountCard, ClaudeAuthCard, type AccountCardProps } from "@/features/dashboard/components/account-card";
import type { AccountSummary } from "@/features/dashboard/schemas";
import { isClaudeSidecar, isXaiCliproxyAccount } from "@/features/dashboard/utils";
import { RESIZABLE_PANEL_TARGET_ATTR } from "@/components/resizable-panel";
import { cn } from "@/lib/utils";

const ACCOUNT_CARD_VISIBLE_ROWS = 2;
// Account cards can grow when the optional email row is rendered.
const ACCOUNT_CARD_ROW_HEIGHT_REM = 16;
const ACCOUNT_CARD_ROW_GAP_REM = 1;

export type AccountCardsProps = {
  accounts: AccountSummary[];
  readOnly?: boolean;
  onAction?: AccountCardProps["onAction"];
  /**
   * Size columns from the panel's own width instead of the viewport. Used by
   * the dashboard split view, where the panel is a fraction of a wide screen.
   */
  fluidColumns?: boolean;
};

export function AccountCards({ accounts, readOnly = false, onAction, fluidColumns = false }: AccountCardsProps) {
  const { t } = useTranslation();

  if (accounts.length === 0) {
    return (
      <EmptyState
        icon={Users}
        title={t("dashboard.accounts.emptyTitle")}
        description={t("dashboard.accounts.emptyDescription")}
        action={
          <Button asChild size="sm">
            <Link to="/accounts">{t("dashboard.accounts.emptyAction")}</Link>
          </Button>
        }
      />
    );
  }

  return (
    <div
      data-testid="dashboard-account-cards"
      {...{ [RESIZABLE_PANEL_TARGET_ATTR]: "" }}
      className={cn(
        "grid gap-4 overflow-y-auto pr-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
        fluidColumns ? "grid-cols-[repeat(auto-fill,minmax(min(100%,20rem),1fr))]" : "sm:grid-cols-2 lg:grid-cols-3",
      )}
      // `--panel-height` is set by the surrounding ResizablePanel once the
      // operator has dragged the grip; until then the two-row default applies.
      style={{
        maxHeight: `var(--panel-height, calc(${ACCOUNT_CARD_VISIBLE_ROWS} * ${ACCOUNT_CARD_ROW_HEIGHT_REM}rem + ${(ACCOUNT_CARD_VISIBLE_ROWS - 1) * ACCOUNT_CARD_ROW_GAP_REM}rem))`,
      }}
    >
      {accounts.flatMap((account, index) => {
        const xaiLogin = isXaiCliproxyAccount(account);
        if (isClaudeSidecar(account) || xaiLogin) {
          return (account.sidecarAuths ?? []).map((auth, authIndex) => (
            <div
              key={`${account.accountId}-${auth.name}`}
              className="flex animate-fade-in-up"
              style={{ animationDelay: `${(index + authIndex) * 75}ms` }}
            >
              <ClaudeAuthCard
                account={account}
                auth={auth}
                onAction={onAction}
                variant={xaiLogin ? "xai" : "claude"}
              />
            </div>
          ));
        }
        return (
          <div key={account.accountId} className="animate-fade-in-up" style={{ animationDelay: `${index * 75}ms` }}>
            <AccountCard
              account={account}
              showAccountId={account.isEmailDuplicate === true}
              readOnly={readOnly}
              onAction={onAction}
            />
          </div>
        );
      })}
    </div>
  );
}
