/**
 * Which dashboard cards and sections the operator has chosen to show.
 *
 * These defaults match `app/modules/settings/dashboard_layout.py`. Active
 * conversations stays hidden until an operator turns it on. Every other card
 * and section stays visible.
 */
export type DashboardLayoutVisibility = {
  requests: boolean;
  tokens: boolean;
  estimatedCost: boolean;
  conversations: boolean;
  errorRate: boolean;
  usage: boolean;
  accounts: boolean;
  requestLogs: boolean;
};

export const DEFAULT_DASHBOARD_LAYOUT: DashboardLayoutVisibility = {
  requests: true,
  tokens: true,
  estimatedCost: true,
  conversations: false,
  errorRate: true,
  usage: true,
  accounts: true,
  requestLogs: true,
};

export const DASHBOARD_LAYOUT_CARD_KEYS = [
  "requests",
  "tokens",
  "estimatedCost",
  "conversations",
  "errorRate",
] as const satisfies readonly (keyof DashboardLayoutVisibility)[];

export const DASHBOARD_LAYOUT_SECTION_KEYS = [
  "usage",
  "accounts",
  "requestLogs",
] as const satisfies readonly (keyof DashboardLayoutVisibility)[];
