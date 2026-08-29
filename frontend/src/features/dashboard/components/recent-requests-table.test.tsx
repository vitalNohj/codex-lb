import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RecentRequestsTable } from "@/features/dashboard/components/recent-requests-table";
import type { RequestLog } from "@/features/dashboard/schemas";

const ISO = "2026-01-01T12:00:00+00:00";
const NULL_FAILURE_METADATA = {
  failurePhase: null,
  failureDetail: null,
  failureExceptionType: null,
  upstreamStatusCode: null,
  upstreamErrorCode: null,
  bridgeStage: null,
  conversationId: null,
  requestedReasoningEffort: null,
};
const NULL_USERAGENT_METADATA = {
  useragent: null,
  useragentGroup: null,
  clientIp: null,
};

const { toastSuccess, toastError } = vi.hoisted(() => ({
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));
const originalClipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");
const originalIsSecureContext = Object.getOwnPropertyDescriptor(window, "isSecureContext");

vi.mock("sonner", () => ({
  toast: {
    success: toastSuccess,
    error: toastError,
  },
}));

vi.mock("@/features/conversation-archive/components/request-archive-panel", () => ({
  RequestArchivePanel: ({ requestId }: { requestId: string }) => (
    <div data-testid="request-archive-panel">Archive for {requestId}</div>
  ),
}));

const PAGINATION_PROPS = {
  total: 1,
  limit: 25,
  offset: 0,
  hasMore: false,
  viewMode: "expanded" as const,
  onLimitChange: vi.fn(),
  onOffsetChange: vi.fn(),
};

const VIEW_MODE_REQUEST: RequestLog = {
  requestedAt: ISO,
  accountId: "acc-view",
  planType: "plus",
  apiKeyName: "View Key",
  apiKeyId: "key-view",
  requestId: "req-view",
  requestKind: "normal",
  model: "gpt-5.1",
  source: null,
  serviceTier: null,
  requestedServiceTier: null,
  actualServiceTier: null,
  transport: "http",
  upstreamTransport: "auto",
  status: "ok",
  errorCode: null,
  errorMessage: null,
  ...NULL_FAILURE_METADATA,
  ...NULL_USERAGENT_METADATA,
  tokens: 1200,
  inputTokens: 1000,
  outputTokens: 200,
  outputTokensRaw: 200,
  cachedInputTokens: 0,
  reasoningEffort: null,
  requestedReasoningEffort: null,
  costUsd: 0.01,
  costBreakdown: null,
  latencyMs: 1000,
  latencyFirstTokenMs: 200,
  latencyQueueMs: 50,
};

function openRequestDetails(index = 0) {
  fireEvent.click(screen.getAllByRole("button", { name: "View Details" })[index]);
  return screen.getByRole("dialog");
}

describe("RecentRequestsTable", () => {
  beforeEach(() => {
    toastSuccess.mockReset();
    toastError.mockReset();
  });

  afterEach(() => {
    if (originalClipboard) {
      Object.defineProperty(navigator, "clipboard", originalClipboard);
    }

    if (originalIsSecureContext) {
      Object.defineProperty(window, "isSecureContext", originalIsSecureContext);
    }
  });

  it("renders the exact simplified column set with plan inside Account", () => {
    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        viewMode="simplified"
        accounts={[]}
        requests={[VIEW_MODE_REQUEST]}
      />,
    );

    const table = screen.getByRole("table");
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((header) => header.textContent);
    const row = within(table).getByText("gpt-5.1").closest("tr");

    expect(headers).toEqual([
      "Time",
      "Account",
      "API Key",
      "Model",
      "Tokens",
      "Cost",
      "Status",
      "Details",
    ]);
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getAllByRole("cell")).toHaveLength(8);
    expect(within(row as HTMLElement).getAllByRole("cell")[1]).toHaveTextContent("Plus");
    expect(within(table).queryByText("HTTP")).not.toBeInTheDocument();
    expect(within(table).queryByText("200ms")).not.toBeInTheDocument();

    const dialog = openRequestDetails();
    expect(within(dialog).getByText("Transport").closest("div.space-y-1")).toHaveTextContent("HTTP");
    expect(within(dialog).getByText("TTFT").closest("div.space-y-1")).toHaveTextContent("200 ms");
    expect(within(dialog).getByText("Queue").closest("div.space-y-1")).toHaveTextContent("50 ms");
    expect(within(dialog).getByText("TPS").closest("div.space-y-1")).toHaveTextContent("250.0");
  });

  it("renders the complete expanded column set", () => {
    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        viewMode="expanded"
        accounts={[]}
        requests={[VIEW_MODE_REQUEST]}
      />,
    );

    const table = screen.getByRole("table");
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((header) => header.textContent);
    const row = within(table).getByText("gpt-5.1").closest("tr");

    expect(headers).toEqual([
      "Time",
      "Account",
      "Plan",
      "API Key",
      "Model",
      "Transport",
      "Status",
      "TTFT",
      "TPS",
      "Tokens",
      "Cost",
      "Details",
    ]);
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getAllByRole("cell")).toHaveLength(12);
    expect(within(row as HTMLElement).getAllByRole("cell")[2]).toHaveTextContent("Plus");
    expect(within(table).getByText("HTTP")).toBeInTheDocument();
    expect(within(table).getByText("200ms")).toBeInTheDocument();
    expect(within(table).getByText("250.0")).toBeInTheDocument();
  });

  it("renders rows with status badges and supports request details and copy actions", async () => {
    const longError = "Rate limit reached while processing this request ".repeat(3);
    const writeText = vi.fn().mockResolvedValue(undefined);

    Object.defineProperty(window, "isSecureContext", {
      configurable: true,
      value: true,
    });
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
         accounts={[
           {
             accountId: "acc-primary",
             email: "primary@example.com",
             displayName: "Primary Account",
             planType: "plus",
             status: "active",
             limitWarmupEnabled: false,
             additionalQuotas: [],
             sidecarAuths: [],
           },
         ]}
        requests={[
          {
            requestedAt: ISO,
            accountId: "acc-primary",
            planType: "plus",
            apiKeyName: "Key Alpha",
            apiKeyId: "key-alpha",
            requestId: "req-1",
            archiveRequestId: "archive-req-1",
            requestKind: "normal",
            model: "gpt-5.1",
            source: null,
            serviceTier: "default",
            requestedServiceTier: "priority",
            actualServiceTier: "default",
            transport: "websocket",
             status: "rate_limit",
             errorCode: "rate_limit_exceeded",
             errorMessage: longError,
            ...NULL_FAILURE_METADATA,
            ...NULL_USERAGENT_METADATA,
            upstreamTransport: "auto",
             tokens: 1200,
             inputTokens: 1000,
             outputTokens: 200,
             outputTokensRaw: null,
             latencyFirstTokenMs: null,
            latencyQueueMs: null,
             cachedInputTokens: 200,
             reasoningEffort: "high",
             requestedReasoningEffort: "medium",
             costUsd: 0.01,
             costBreakdown: {
               inputUsd: 0.004,
               cachedInputUsd: 0.001,
               outputUsd: 0.005,
               totalUsd: 0.01,
             },
             latencyMs: 1000,
           },
         ]}
       />,
    );

    expect(screen.getByText("Primary Account")).toBeInTheDocument();
    expect(screen.getByText("Plus")).toBeInTheDocument();
    expect(screen.getByText("Key Alpha")).toBeInTheDocument();
    expect(screen.getByText("gpt-5.1 (high, default)")).toBeInTheDocument();
    expect(screen.getByText("Requested priority")).toBeInTheDocument();
    expect(screen.getByText("Requested effort medium")).toBeInTheDocument();
    expect(screen.getByText("WS")).toBeInTheDocument();
    expect(screen.getByText("Up Auto")).toBeInTheDocument();
    expect(screen.getByText("Rate limit")).toBeInTheDocument();
    expect(screen.getByText("rate_limit_exceeded")).toBeInTheDocument();

    const dialog = openRequestDetails();
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText("Request Details")).toBeInTheDocument();
    expect(within(dialog).getByText("req-1")).toBeInTheDocument();
    expect(within(dialog).getByTestId("request-archive-panel")).toHaveTextContent("Archive for archive-req-1");
    expect(within(dialog).getByText("rate_limit_exceeded")).toBeInTheDocument();
    expect(dialog.textContent).toContain("Rate limit reached while processing this request");
    expect(within(dialog).getByText("1.0 s")).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy Request ID" }));
      await Promise.resolve();
    });

    expect(writeText).toHaveBeenCalledWith("req-1");
    expect(toastSuccess).toHaveBeenCalledWith("Copied to clipboard");
    expect(screen.getByRole("button", { name: "Copy Request ID Copied" })).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy Error" }));
      await Promise.resolve();
    });

    expect(writeText).toHaveBeenCalledWith(longError);
  });

  it("neutralizes errors from disabled capability request rows", () => {
    const request = {
      ...VIEW_MODE_REQUEST,
      accountId: null,
      requestId: "req-disabled-provider",
      model: "omniroute/test-chat",
      source: "omniroute_sidecar",
      status: "error",
      errorCode: "omniroute_sidecar_unavailable",
      errorMessage: "OmniRoute sidecar unavailable",
    } satisfies RequestLog;

    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        accounts={[]}
        requests={[request]}
      />,
    );

    const row = screen.getByText("omniroute/test-chat").closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("Error")).toBeInTheDocument();
    expect(within(row as HTMLElement).queryByText("omniroute_sidecar_unavailable")).not.toBeInTheDocument();
    expect(within(row as HTMLElement).queryByText("OmniRoute sidecar unavailable")).not.toBeInTheDocument();

    const dialog = openRequestDetails();
    expect(within(dialog).getByText("omniroute/test-chat")).toBeInTheDocument();
    expect(within(dialog).queryByRole("heading", { name: "Full error" })).not.toBeInTheDocument();
    expect(within(dialog).queryByText("omniroute_sidecar_unavailable")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("OmniRoute sidecar unavailable")).not.toBeInTheDocument();
    expect(dialog).not.toHaveTextContent("OmniRoute");
    expect(within(dialog).queryByRole("button", { name: /Copy Error/ })).not.toBeInTheDocument();
  });

  it("preserves errors from enabled capability request rows", () => {
    const request = {
      ...VIEW_MODE_REQUEST,
      accountId: null,
      requestId: "req-enabled-provider",
      model: "orcarouter/test-chat",
      source: "orcarouter_sidecar",
      status: "error",
      errorCode: "orcarouter_upstream_unavailable",
      errorMessage: "OrcaRouter upstream unavailable",
    } satisfies RequestLog;

    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        accounts={[]}
        requests={[request]}
      />,
    );

    const row = screen.getByText("orcarouter/test-chat").closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("orcarouter_upstream_unavailable")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("OrcaRouter upstream unavailable")).toBeInTheDocument();

    const dialog = openRequestDetails();
    expect(within(dialog).getByRole("heading", { name: "Full Error" })).toBeInTheDocument();
    expect(within(dialog).getByText("orcarouter_upstream_unavailable")).toBeInTheDocument();
    expect(within(dialog).getByText("OrcaRouter upstream unavailable")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Copy Error" })).toBeInTheDocument();
  });

  it("renders sidecar rows with standard model and transport labels", () => {
    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        total={3}
        accounts={[]}
        requests={[
          {
            requestedAt: ISO,
            accountId: null,
            planType: null,
            apiKeyName: "Claude Key",
            apiKeyId: "key-claude",
            requestId: "req-sidecar",
            requestKind: "normal",
            model: "claude-sonnet",
            source: "claude_sidecar",
            sidecarAccountLabel: "claude@example.com",
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            ...NULL_USERAGENT_METADATA,
            status: "ok",
            errorCode: null,
            errorMessage: null,
            ...NULL_FAILURE_METADATA,
            tokens: 15,
            inputTokens: 10,
            outputTokens: 5,
            cachedInputTokens: 0,
            reasoningEffort: null,
            requestedReasoningEffort: null,
            costUsd: 0,
            costBreakdown: null,
            latencyMs: 50,
            outputTokensRaw: null,
            latencyFirstTokenMs: null,
            latencyQueueMs: null,
          },
          {
            requestedAt: ISO,
            accountId: null,
            planType: null,
            apiKeyName: "OpenRouter Key",
            apiKeyId: "key-openrouter",
            requestId: "req-openrouter",
            requestKind: "normal",
            model: "openrouter/test-chat",
            source: "openrouter_sidecar",
            sidecarAccountLabel: null,
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            ...NULL_USERAGENT_METADATA,
            status: "ok",
            errorCode: null,
            errorMessage: null,
            ...NULL_FAILURE_METADATA,
            tokens: 15,
            inputTokens: 10,
            outputTokens: 5,
            cachedInputTokens: 0,
            reasoningEffort: null,
            requestedReasoningEffort: null,
            costUsd: 0,
            costBreakdown: null,
            latencyMs: 50,
            outputTokensRaw: null,
            latencyFirstTokenMs: null,
            latencyQueueMs: null,
          },
          {
            requestedAt: ISO,
            accountId: null,
            planType: null,
            apiKeyName: "OmniRoute Key",
            apiKeyId: "key-omniroute",
            requestId: "req-omniroute",
            requestKind: "normal",
            model: "omniroute/test-chat",
            source: "omniroute_sidecar",
            sidecarAccountLabel: null,
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            ...NULL_USERAGENT_METADATA,
            status: "ok",
            errorCode: null,
            errorMessage: null,
            ...NULL_FAILURE_METADATA,
            tokens: 15,
            inputTokens: 10,
            outputTokens: 5,
            cachedInputTokens: 0,
            reasoningEffort: null,
            requestedReasoningEffort: null,
            costUsd: 0,
            costBreakdown: null,
            latencyMs: 50,
            outputTokensRaw: null,
            latencyFirstTokenMs: null,
            latencyQueueMs: null,
          },
          {
            requestedAt: ISO,
            accountId: null,
            planType: null,
            apiKeyName: "Ollama Key",
            apiKeyId: "key-ollama",
            requestId: "req-ollama",
            requestKind: "normal",
            model: "gpt-oss:120b-cloud",
            source: "ollama_sidecar",
            sidecarAccountLabel: null,
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            ...NULL_USERAGENT_METADATA,
            status: "ok",
            errorCode: null,
            errorMessage: null,
            ...NULL_FAILURE_METADATA,
            tokens: 15,
            inputTokens: 10,
            outputTokens: 5,
            cachedInputTokens: 0,
            reasoningEffort: null,
            requestedReasoningEffort: null,
            costUsd: 0,
            costBreakdown: null,
            latencyMs: 50,
            outputTokensRaw: null,
            latencyFirstTokenMs: null,
            latencyQueueMs: null,
          },
        ]}
      />,
    );

    const claudeRow = screen.getByText("claude-sonnet").closest("tr");
    expect(claudeRow).not.toBeNull();
    const claudeCells = within(claudeRow as HTMLElement).getAllByRole("cell");
    expect(claudeCells[1]).toHaveTextContent("CLIProxyAPI: claude@example.com");
    expect(claudeCells[1]).not.toHaveTextContent("Claude sidecar");
    expect(claudeCells[4]).toHaveTextContent("claude-sonnet");
    expect(claudeCells[4]).not.toHaveTextContent("Claude sidecar");

    const openRouterRow = screen.getByText("openrouter/test-chat").closest("tr");
    expect(openRouterRow).not.toBeNull();
    const openRouterCells = within(openRouterRow as HTMLElement).getAllByRole("cell");
    expect(openRouterCells[1]).toHaveTextContent("OpenRouter");
    expect(openRouterCells[1]).not.toHaveTextContent("OpenRouter sidecar");

    // Historical OmniRoute rows are retained (never deleted or rewritten) but
    // render without the disabled integration's branding.
    const omniRouteRow = screen.getByText("omniroute/test-chat").closest("tr");
    expect(omniRouteRow).not.toBeNull();
    const omniRouteCells = within(omniRouteRow as HTMLElement).getAllByRole("cell");
    expect(omniRouteCells[1]).not.toHaveTextContent("OmniRoute");
    expect(omniRouteCells[4]).toHaveTextContent("omniroute/test-chat");

    const ollamaRow = screen.getByText("gpt-oss:120b-cloud").closest("tr");
    expect(ollamaRow).not.toBeNull();
    const ollamaCells = within(ollamaRow as HTMLElement).getAllByRole("cell");
    expect(ollamaCells[1]).toHaveTextContent("Ollama");
    expect(ollamaCells[1]).not.toHaveTextContent("Ollama sidecar");
    expect(ollamaCells[4]).toHaveTextContent("gpt-oss:120b-cloud");
    expect(ollamaCells[4]).not.toHaveTextContent("Ollama sidecar");
    expect(screen.queryByText("Sidecar HTTP")).not.toBeInTheDocument();

    const dialog = openRequestDetails();
    expect(within(dialog).getByText("Source")).toBeInTheDocument();
    expect(within(dialog).getAllByText("CLIProxyAPI").length).toBeGreaterThan(0);
    expect(within(dialog).getByText("Transport").closest("div.space-y-1")).toHaveTextContent("HTTP");
    expect(within(dialog).queryByText("Sidecar HTTP")).not.toBeInTheDocument();
  });

  it("shows TTFT and output-token TPS beside tokens", () => {
    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        accounts={[]}
        requests={[
          {
            requestedAt: ISO,
            accountId: "acc-speed",
            planType: "plus",
            apiKeyName: "Key Speed",
            apiKeyId: "key-speed",
            requestId: "req-speed",
            requestKind: "normal",
            model: "gpt-5.1",
            source: null,
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            ...NULL_USERAGENT_METADATA,
            status: "ok",
            errorCode: null,
            errorMessage: null,
            ...NULL_FAILURE_METADATA,
            tokens: 1200,
            inputTokens: 1000,
            outputTokens: 200,
            outputTokensRaw: 200,
            reasoningTokens: 40,
            cachedInputTokens: 0,
            reasoningEffort: null,
            requestedReasoningEffort: null,
            costUsd: 0,
            costBreakdown: null,
            latencyMs: 1000,
            latencyFirstTokenMs: 200,
            latencyQueueMs: null,
          },
        ]}
      />,
    );

    const row = screen.getByText("gpt-5.1").closest("tr");

    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("200ms")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("200.0")).toBeInTheDocument();
  });

  it("does not calculate TPS from fallback output tokens", () => {
    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        accounts={[]}
        requests={[
          {
            requestedAt: ISO,
            accountId: "acc-reasoning",
            planType: "plus",
            apiKeyName: "Key Reasoning",
            apiKeyId: "key-reasoning",
            requestId: "req-reasoning",
            requestKind: "normal",
            model: "gpt-5.1",
            source: null,
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            ...NULL_USERAGENT_METADATA,
            status: "ok",
            errorCode: null,
            errorMessage: null,
            ...NULL_FAILURE_METADATA,
            tokens: 1200,
            inputTokens: 1000,
            outputTokens: 200,
            outputTokensRaw: null,
            cachedInputTokens: 0,
            reasoningEffort: null,
            requestedReasoningEffort: null,
            costUsd: 0,
            costBreakdown: null,
            latencyMs: 1000,
            latencyFirstTokenMs: 200,
            latencyQueueMs: null,
          },
        ]}
      />,
    );

    const row = screen.getByText("gpt-5.1").closest("tr");

    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("200ms")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("--")).toBeInTheDocument();
    expect(within(row as HTMLElement).queryByText("250.0")).not.toBeInTheDocument();
  });

  it("renders empty state", () => {
    render(<RecentRequestsTable {...PAGINATION_PROPS} total={0} accounts={[]} requests={[]} />);
    expect(screen.getByText("No request logs match the current filters.")).toBeInTheDocument();
  });

  it("shows warmup marker only for warmup rows", () => {
    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        total={2}
        hasMore
        accounts={[]}
        requests={[
          {
            requestedAt: ISO,
            accountId: "acc-normal",
            planType: null,
            apiKeyName: null,
            apiKeyId: null,
            requestId: "req-normal",
            requestKind: "normal",
            source: null,
            ...NULL_FAILURE_METADATA,
            model: "gpt-5.1",
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            ...NULL_USERAGENT_METADATA,
            status: "ok",
            errorCode: null,
            errorMessage: null,
            tokens: 1,
            inputTokens: 1,
            outputTokens: 0,
            outputTokensRaw: null,
            latencyFirstTokenMs: null,
            latencyQueueMs: null,
            cachedInputTokens: null,
            reasoningEffort: null,
            requestedReasoningEffort: null,
            costUsd: 0,
            costBreakdown: null,
            latencyMs: 1,
          },
          {
            requestedAt: ISO,
            accountId: "acc-warmup",
            planType: null,
            apiKeyName: null,
            apiKeyId: null,
            requestId: "req-warmup",
            requestKind: "warmup",
            source: null,
            ...NULL_FAILURE_METADATA,
            model: "gpt-5.1",
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            ...NULL_USERAGENT_METADATA,
             status: "ok",
             errorCode: null,
             errorMessage: null,
            tokens: 1,
            inputTokens: 1,
            outputTokens: 0,
            outputTokensRaw: null,
            latencyFirstTokenMs: null,
            latencyQueueMs: null,
            cachedInputTokens: null,
            reasoningEffort: null,
            requestedReasoningEffort: null,
            costUsd: 0,
            costBreakdown: null,
            latencyMs: 1,
          },
        ]}
      />,
    );

    expect(screen.getByText("Warmup")).toBeInTheDocument();
    expect(screen.queryByText("Normal")).not.toBeInTheDocument();
  });

  it("renders placeholder transport for legacy rows", () => {
    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        accounts={[]}
        requests={[
          {
            requestedAt: ISO,
            accountId: "acc-legacy",
            planType: null,
            apiKeyName: null,
            apiKeyId: null,
            requestId: "req-legacy",
            requestKind: "normal",
            model: "gpt-5.1",
            source: null,
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: null,
            ...NULL_USERAGENT_METADATA,
             status: "ok",
             errorCode: null,
             errorMessage: null,
            ...NULL_FAILURE_METADATA,
             tokens: 1,
             inputTokens: 1,
             outputTokens: 0,
             outputTokensRaw: null,
             latencyFirstTokenMs: null,
            latencyQueueMs: null,
             cachedInputTokens: null,
             reasoningEffort: null,
             requestedReasoningEffort: null,
             costUsd: 0,
             costBreakdown: null,
             latencyMs: 1,
           },
         ]}
       />,
    );

    const row = screen.getByText("gpt-5.1").closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getAllByText("--").length).toBeGreaterThan(0);
  });

  it("shows details action for error-code-only rows", async () => {
    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        accounts={[]}
        requests={[
          {
            requestedAt: ISO,
            accountId: "acc-legacy",
            planType: null,
            apiKeyName: null,
            apiKeyId: null,
            requestId: "req-error-code",
            requestKind: "normal",
            model: "gpt-5.1",
            source: null,
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            ...NULL_USERAGENT_METADATA,
             status: "error",
             errorCode: "upstream_error",
             errorMessage: null,
            ...NULL_FAILURE_METADATA,
             tokens: 1,
             inputTokens: 1,
             outputTokens: 0,
             outputTokensRaw: null,
             latencyFirstTokenMs: null,
            latencyQueueMs: null,
             cachedInputTokens: null,
             reasoningEffort: null,
             requestedReasoningEffort: null,
             costUsd: 0,
             costBreakdown: null,
             latencyMs: 1,
           },
         ]}
       />,
    );

    const dialog = openRequestDetails();

    expect(dialog).toHaveTextContent("upstream_error");
    expect(dialog).toHaveTextContent("Full Error");
  });

  it("shows a cost section for ok rows", () => {
    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        accounts={[]}
        requests={[
          {
            requestedAt: ISO,
            accountId: "acc-cost",
            planType: "plus",
            apiKeyName: "Key Cost",
            apiKeyId: "key-cost",
            requestId: "req-cost",
            requestKind: "normal",
            model: "gpt-5.1",
            source: null,
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            ...NULL_USERAGENT_METADATA,
            status: "ok",
            errorCode: null,
            errorMessage: null,
            ...NULL_FAILURE_METADATA,
            tokens: 1400,
            inputTokens: 1000,
            outputTokens: 400,
            outputTokensRaw: null,
            latencyFirstTokenMs: null,
            latencyQueueMs: null,
            cachedInputTokens: 200,
            reasoningEffort: null,
            requestedReasoningEffort: null,
            costUsd: 0.01,
            costBreakdown: {
              inputUsd: 0.004,
              cachedInputUsd: 0.002,
              outputUsd: 0.004,
              totalUsd: 0.01,
            },
            latencyMs: 100,
          },
        ]}
      />,
    );

    const dialog = openRequestDetails();
    const costSection = within(dialog).getByText("Cost").closest("div.space-y-2");

    expect(within(dialog).getByText("Cost")).toBeInTheDocument();
    expect(costSection).toHaveTextContent("$0.01 =");
    // Sub-cent segments render at extra precision so a real cost is not rounded
    // away to "$0.00" (formatCurrency's precise branch).
    expect(costSection).toHaveTextContent("800 Input ($0.004)");
    expect(costSection).toHaveTextContent("200 Cached ($0.002)");
    expect(costSection).toHaveTextContent("400 Output ($0.004)");
  });

  it("shows the full user agent in request details when present", () => {
    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        accounts={[]}
        requests={[
          {
            requestedAt: ISO,
            accountId: "acc-useragent",
            planType: "plus",
            apiKeyName: "Key Agent",
            apiKeyId: "key-agent",
            requestId: "req-useragent",
            requestKind: "normal",
            model: "gpt-5.1",
            source: null,
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            useragent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36",
            useragentGroup: "Mozilla",
            clientIp: "203.0.113.7",
            status: "ok",
            errorCode: null,
            errorMessage: null,
            ...NULL_FAILURE_METADATA,
            tokens: 1,
            inputTokens: 1,
            outputTokens: 0,
            outputTokensRaw: null,
            latencyFirstTokenMs: null,
            latencyQueueMs: null,
            cachedInputTokens: null,
            reasoningEffort: null,
            requestedReasoningEffort: null,
            costUsd: 0,
            costBreakdown: null,
            latencyMs: 1,
          },
        ]}
      />,
    );

    const dialog = openRequestDetails();
    const dialogText = dialog.textContent ?? "";
    const errorCodeIndex = dialogText.indexOf("Error Code");
    const userAgentIndex = dialogText.indexOf("User Agent");
    const clientIpIndex = dialogText.indexOf("Client IP");

    expect(within(dialog).getByText("User Agent")).toBeInTheDocument();
    expect(
      within(dialog).getByText("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36"),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Client IP")).toBeInTheDocument();
    expect(within(dialog).getByText("203.0.113.7")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Copy User Agent" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Copy Client IP" })).toBeInTheDocument();
    expect(errorCodeIndex).toBeGreaterThanOrEqual(0);
    expect(userAgentIndex).toBeGreaterThan(errorCodeIndex);
    expect(clientIpIndex).toBeGreaterThan(userAgentIndex);
  });

  it("shows an em dash for missing user agent in request details", () => {
    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        accounts={[]}
        requests={[
          {
            requestedAt: ISO,
            accountId: "acc-no-useragent",
            planType: null,
            apiKeyName: null,
            apiKeyId: null,
            requestId: "req-no-useragent",
            requestKind: "normal",
            model: "gpt-5.1",
            source: null,
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            useragent: null,
            useragentGroup: null,
            clientIp: null,
            status: "ok",
            errorCode: null,
            errorMessage: null,
            ...NULL_FAILURE_METADATA,
            tokens: 1,
            inputTokens: 1,
            outputTokens: 0,
            outputTokensRaw: null,
            latencyFirstTokenMs: null,
            latencyQueueMs: null,
            cachedInputTokens: null,
            reasoningEffort: null,
            requestedReasoningEffort: null,
            costUsd: 0,
            costBreakdown: null,
            latencyMs: 1,
          },
        ]}
      />,
    );

    const dialog = openRequestDetails();
    const userAgentField = within(dialog).getByText("User Agent").closest("div.space-y-1");
    const clientIpField = within(dialog).getByText("Client IP").closest("div.space-y-1");

    expect(userAgentField).not.toBeNull();
    expect(userAgentField).toHaveTextContent("User Agent");
    expect(userAgentField).toHaveTextContent("—");
    expect(clientIpField).not.toBeNull();
    expect(clientIpField).toHaveTextContent("Client IP");
    expect(clientIpField).toHaveTextContent("—");
    expect(within(dialog).queryByRole("button", { name: "Copy" })).not.toBeInTheDocument();
  });

  it("hides the cost section for non-ok rows", () => {
    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        accounts={[]}
        requests={[
          {
            requestedAt: ISO,
            accountId: "acc-no-cost",
            planType: null,
            apiKeyName: null,
            apiKeyId: null,
            requestId: "req-no-cost",
            requestKind: "normal",
            model: "gpt-5.1",
            source: null,
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            ...NULL_USERAGENT_METADATA,
            status: "error",
            errorCode: "upstream_error",
            errorMessage: "boom",
            ...NULL_FAILURE_METADATA,
            tokens: 1,
            inputTokens: 1,
            outputTokens: 0,
            outputTokensRaw: null,
            latencyFirstTokenMs: null,
            latencyQueueMs: null,
            cachedInputTokens: 0,
            reasoningEffort: null,
            requestedReasoningEffort: null,
            costUsd: 0.01,
            costBreakdown: {
              inputUsd: 0.01,
              cachedInputUsd: null,
              outputUsd: null,
              totalUsd: 0.01,
            },
            latencyMs: 1,
          },
        ]}
      />,
    );

    const dialog = openRequestDetails();

    expect(within(dialog).queryByText("Cost")).not.toBeInTheDocument();
  });

  it("renders only available cost segments for partial data", () => {
    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        accounts={[]}
        requests={[
          {
            requestedAt: ISO,
            accountId: "acc-partial-cost",
            planType: "plus",
            apiKeyName: "Key Partial",
            apiKeyId: "key-partial",
            requestId: "req-partial-cost",
            requestKind: "normal",
            model: "gpt-5.1",
            source: null,
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            ...NULL_USERAGENT_METADATA,
            status: "ok",
            errorCode: null,
            errorMessage: null,
            ...NULL_FAILURE_METADATA,
            tokens: 700,
            inputTokens: 700,
            outputTokens: null,
            outputTokensRaw: null,
            latencyFirstTokenMs: null,
            latencyQueueMs: null,
            cachedInputTokens: 200,
            reasoningEffort: null,
            requestedReasoningEffort: null,
            costUsd: 0.01,
            costBreakdown: {
              inputUsd: 0.006,
              cachedInputUsd: 0.004,
              outputUsd: null,
              totalUsd: 0.01,
            },
            latencyMs: 1,
          },
        ]}
      />,
    );

    const dialog = openRequestDetails();
    const costSection = within(dialog).getByText("Cost").closest("div.space-y-2");

    expect(within(dialog).getByText("Cost")).toBeInTheDocument();
    expect(costSection).toHaveTextContent("$0.01 =");
    expect(costSection).toHaveTextContent("500 Input ($0.006)");
    expect(costSection).toHaveTextContent("200 Cached ($0.004)");
    expect(costSection).not.toHaveTextContent("Output");
  });

  it("renders available cost segments when total cost is unavailable", () => {
    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        accounts={[]}
        requests={[
          {
            requestedAt: ISO,
            accountId: "acc-partial-no-total",
            planType: "plus",
            apiKeyName: "Key Partial No Total",
            apiKeyId: "key-partial-no-total",
            requestId: "req-partial-no-total",
            requestKind: "normal",
            model: "gpt-5.1",
            source: null,
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            ...NULL_USERAGENT_METADATA,
            status: "ok",
            errorCode: null,
            errorMessage: null,
            ...NULL_FAILURE_METADATA,
            tokens: null,
            inputTokens: 1000,
            outputTokens: null,
            outputTokensRaw: null,
            latencyFirstTokenMs: null,
            latencyQueueMs: null,
            cachedInputTokens: 200,
            reasoningEffort: null,
            requestedReasoningEffort: null,
            costUsd: null,
            costBreakdown: {
              inputUsd: 0.006,
              cachedInputUsd: 0.004,
              outputUsd: null,
              totalUsd: null,
            },
            latencyMs: 1,
          },
        ]}
      />,
    );

    const dialog = openRequestDetails();
    const costSection = within(dialog).getByText("Cost").closest("div.space-y-2");

    expect(within(dialog).getByText("Cost")).toBeInTheDocument();
    expect(costSection).not.toHaveTextContent("=");
    expect(costSection).toHaveTextContent("800 Input ($0.006)");
    expect(costSection).toHaveTextContent("200 Cached ($0.004)");
    expect(costSection).not.toHaveTextContent("Output");
  });

  it("shows the full user agent in request details when present", () => {
    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        accounts={[]}
        requests={[
          {
            requestedAt: ISO,
            accountId: "acc-useragent",
            planType: "plus",
            apiKeyName: "Key Agent",
            apiKeyId: "key-agent",
            requestId: "req-useragent",
            requestKind: "normal",
            model: "gpt-5.1",
            source: null,
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            useragent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36",
            useragentGroup: "Mozilla",
            clientIp: "203.0.113.7",
            status: "ok",
            errorCode: null,
            errorMessage: null,
            ...NULL_FAILURE_METADATA,
            tokens: 1,
            inputTokens: 1,
            outputTokens: 0,
            outputTokensRaw: null,
            latencyFirstTokenMs: null,
            latencyQueueMs: null,
            cachedInputTokens: null,
            reasoningEffort: null,
            requestedReasoningEffort: null,
            costUsd: 0,
            costBreakdown: null,
            latencyMs: 1,
          },
        ]}
      />,
    );

    const dialog = openRequestDetails();
    const dialogText = dialog.textContent ?? "";
    const errorCodeIndex = dialogText.indexOf("Error Code");
    const userAgentIndex = dialogText.indexOf("User Agent");
    const clientIpIndex = dialogText.indexOf("Client IP");

    expect(within(dialog).getByText("User Agent")).toBeInTheDocument();
    expect(
      within(dialog).getByText("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36"),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Client IP")).toBeInTheDocument();
    expect(within(dialog).getByText("203.0.113.7")).toBeInTheDocument();
    expect(errorCodeIndex).toBeGreaterThanOrEqual(0);
    expect(userAgentIndex).toBeGreaterThan(errorCodeIndex);
    expect(clientIpIndex).toBeGreaterThan(userAgentIndex);
  });

  it("shows an em dash for missing user agent in request details", () => {
    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        accounts={[]}
        requests={[
          {
            requestedAt: ISO,
            accountId: "acc-no-useragent",
            planType: null,
            apiKeyName: null,
            apiKeyId: null,
            requestId: "req-no-useragent",
            requestKind: "normal",
            model: "gpt-5.1",
            source: null,
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            useragent: null,
            useragentGroup: null,
            clientIp: null,
            status: "ok",
            errorCode: null,
            errorMessage: null,
            ...NULL_FAILURE_METADATA,
            tokens: 1,
            inputTokens: 1,
            outputTokens: 0,
            outputTokensRaw: null,
            latencyFirstTokenMs: null,
            latencyQueueMs: null,
            cachedInputTokens: null,
            reasoningEffort: null,
            requestedReasoningEffort: null,
            costUsd: 0,
            costBreakdown: null,
            latencyMs: 1,
          },
        ]}
      />,
    );

    const dialog = openRequestDetails();
    const userAgentField = within(dialog).getByText("User Agent").closest("div.space-y-1");
    const clientIpField = within(dialog).getByText("Client IP").closest("div.space-y-1");

    expect(userAgentField).not.toBeNull();
    expect(userAgentField).toHaveTextContent("User Agent");
    expect(userAgentField).toHaveTextContent("—");
    expect(clientIpField).not.toBeNull();
    expect(clientIpField).toHaveTextContent("Client IP");
    expect(clientIpField).toHaveTextContent("—");
    expect(within(dialog).getByText("1 ms")).toBeInTheDocument();
  });

  it("hides the cost section for total-only cost breakdown rows", () => {
    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        accounts={[]}
        requests={[
          {
            requestedAt: ISO,
            accountId: "acc-total-only-cost",
            planType: "plus",
            apiKeyName: "Key Total Only",
            apiKeyId: "key-total-only",
            requestId: "req-total-only-cost",
            requestKind: "normal",
            model: "gpt-5.1",
            source: null,
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            useragent: null,
            useragentGroup: null,
            clientIp: null,
            status: "ok",
            errorCode: null,
            errorMessage: null,
            ...NULL_FAILURE_METADATA,
            tokens: 1500,
            inputTokens: 1000,
            outputTokens: 500,
            outputTokensRaw: null,
            latencyFirstTokenMs: null,
            latencyQueueMs: null,
            cachedInputTokens: null,
            reasoningEffort: null,
            requestedReasoningEffort: null,
            costUsd: 4.321234,
            costBreakdown: {
              inputUsd: null,
              cachedInputUsd: null,
              outputUsd: null,
              totalUsd: 4.321234,
            },
            latencyMs: 1,
          },
        ]}
      />,
    );

    const dialog = openRequestDetails();

    expect(within(dialog).queryByText("Cost")).not.toBeInTheDocument();
  });

  it("closes the dialog when conversation ID button is clicked and fires handler", () => {
    const onConversationClick = vi.fn();
    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        accounts={[]}
        onConversationClick={onConversationClick}
        requests={[
          {
            requestedAt: ISO,
            accountId: "acc-conv-click",
            planType: "plus",
            apiKeyName: "Key Conv",
            apiKeyId: "key-conv",
            requestId: "req-conv-click",
            requestKind: "normal",
            model: "gpt-5.1",
            source: null,
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            useragent: null,
            useragentGroup: null,
            clientIp: "10.0.0.1",
            status: "ok",
            errorCode: null,
            errorMessage: null,
            ...NULL_FAILURE_METADATA,
            conversationId: "conv_dialog_close_test",
            tokens: 1,
            inputTokens: 1,
            outputTokens: 0,
            outputTokensRaw: null,
            latencyFirstTokenMs: null,
            latencyQueueMs: null,
            cachedInputTokens: null,
            reasoningEffort: null,
            costUsd: 0,
            costBreakdown: null,
            latencyMs: 1,
          },
        ]}
      />,
    );

    const dialog = openRequestDetails();
    expect(within(dialog).getByText("conv_dialog_close_test")).toBeInTheDocument();

    const convButton = within(dialog).getByRole("button", { name: /Filter by conversation/i });
    fireEvent.click(convButton);

    expect(onConversationClick).toHaveBeenCalledWith("conv_dialog_close_test");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders conversation ID as plain text when no handler is provided", () => {
    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        accounts={[]}
        requests={[
          {
            requestedAt: ISO,
            accountId: "acc-conv-text",
            planType: "plus",
            apiKeyName: "Key Text",
            apiKeyId: "key-text",
            requestId: "req-conv-text",
            requestKind: "normal",
            model: "gpt-5.1",
            source: null,
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            useragent: null,
            useragentGroup: null,
            clientIp: null,
            status: "ok",
            errorCode: null,
            errorMessage: null,
            ...NULL_FAILURE_METADATA,
            conversationId: "conv_plain_text_render",
            tokens: 1,
            inputTokens: 1,
            outputTokens: 0,
            outputTokensRaw: null,
            latencyFirstTokenMs: null,
            latencyQueueMs: null,
            cachedInputTokens: null,
            reasoningEffort: null,
            costUsd: 0,
            costBreakdown: null,
            latencyMs: 1,
          },
        ]}
      />,
    );

    const dialog = openRequestDetails();
    const textEl = within(dialog).getByText("conv_plain_text_render");
    expect(textEl).toBeInTheDocument();
    // Must be a <p>, not a button
    expect(textEl.tagName).toBe("P");
    expect(textEl).toHaveClass("truncate");
    expect(
      within(dialog).queryByRole("button", { name: /Filter by conversation/i }),
    ).not.toBeInTheDocument();
  });

  it("truncates long conversation IDs with title attribute in dialog", () => {
    const longId = "conv_this_is_a_very_very_very_very_long_conversation_id_that_would_overflow_a_half_width_column";
    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        accounts={[]}
        onConversationClick={vi.fn()}
        requests={[
          {
            requestedAt: ISO,
            accountId: "acc-long-cid",
            planType: "plus",
            apiKeyName: "Key Long",
            apiKeyId: "key-long",
            requestId: "req-long-cid",
            requestKind: "normal",
            model: "gpt-5.1",
            source: null,
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            useragent: null,
            useragentGroup: null,
            clientIp: null,
            status: "ok",
            errorCode: null,
            errorMessage: null,
            ...NULL_FAILURE_METADATA,
            conversationId: longId,
            tokens: 1,
            inputTokens: 1,
            outputTokens: 0,
            outputTokensRaw: null,
            latencyFirstTokenMs: null,
            latencyQueueMs: null,
            cachedInputTokens: null,
            reasoningEffort: null,
            costUsd: 0,
            costBreakdown: null,
            latencyMs: 1,
          },
        ]}
      />,
    );

    const dialog = openRequestDetails();
    const convButton = within(dialog).getByRole("button", { name: /Filter by conversation/i });
    expect(convButton).toHaveAttribute("title", longId);
    expect(convButton).toHaveClass("truncate");
    expect(convButton.className).toMatch(/max-w-\[200px\]/);
  });

  it("truncates long no-handler conversation IDs with title attribute", () => {
    const longId = "conv_this_is_a_very_very_long_id_with_no_handler_that_would_overflow";
    render(
      <RecentRequestsTable
        {...PAGINATION_PROPS}
        accounts={[]}
        requests={[
          {
            requestedAt: ISO,
            accountId: "acc-long-cid-nh",
            planType: "plus",
            apiKeyName: "Key Long NH",
            apiKeyId: "key-long-nh",
            requestId: "req-long-cid-nh",
            requestKind: "normal",
            model: "gpt-5.1",
            source: null,
            serviceTier: null,
            requestedServiceTier: null,
            actualServiceTier: null,
            transport: "http",
            useragent: null,
            useragentGroup: null,
            clientIp: null,
            status: "ok",
            errorCode: null,
            errorMessage: null,
            ...NULL_FAILURE_METADATA,
            conversationId: longId,
            tokens: 1,
            inputTokens: 1,
            outputTokens: 0,
            outputTokensRaw: null,
            latencyFirstTokenMs: null,
            latencyQueueMs: null,
            cachedInputTokens: null,
            reasoningEffort: null,
            costUsd: 0,
            costBreakdown: null,
            latencyMs: 1,
          },
        ]}
      />,
    );

    const dialog = openRequestDetails();
    const textEl = within(dialog).getByText(longId);
    expect(textEl.tagName).toBe("P");
    expect(textEl).toHaveClass("truncate");
    expect(textEl).toHaveAttribute("title", longId);
  });

  describe("cost column price markers", () => {
    const renderCost = (overrides: Partial<RequestLog>) => {
      render(
        <RecentRequestsTable
          {...PAGINATION_PROPS}
          accounts={[]}
          requests={[{ ...VIEW_MODE_REQUEST, ...overrides }]}
        />,
      );
    };

    it("marks an eligible model that stayed unresolved with !! and explains why", () => {
      renderCost({ costUsd: null, costSource: null, priceStatus: "unresolved" });

      const marker = screen.getByText("!!");
      expect(marker).toBeInTheDocument();
      expect(marker).toHaveAttribute("title", expect.stringContaining("No published price"));
    });

    it("marks an ambiguous model with !! and names the ambiguity", () => {
      renderCost({ costUsd: null, costSource: null, priceStatus: "ambiguous" });

      const marker = screen.getByText("!!");
      expect(marker).toHaveAttribute("title", expect.stringContaining("more than one catalog entry"));
    });

    it("keeps -- for an integration that is not externally priced", () => {
      // Ollama and OmniRoute rows carry no price status at all. A marker here
      // would report a defect where none exists.
      renderCost({ costUsd: null, costSource: null, priceStatus: null });

      expect(screen.queryByText("!!")).not.toBeInTheDocument();
      expect(screen.getAllByText("--").length).toBeGreaterThan(0);
    });

    it("keeps -- for a model the catalog lists without a per-token price", () => {
      renderCost({ costUsd: null, costSource: null, priceStatus: "not_token_priced" });

      expect(screen.queryByText("!!")).not.toBeInTheDocument();
    });

    it("keeps -- for a first sighting whose lookup had not finished", () => {
      // The very first request for a newly routed model is written before any
      // lookup concludes. Marking it !! would flag every new model permanently,
      // even when the background lookup priced it moments later.
      renderCost({ costUsd: null, costSource: null, priceStatus: "pending" });

      expect(screen.queryByText("!!")).not.toBeInTheDocument();
      expect(screen.getAllByText("--").length).toBeGreaterThan(0);
    });

    it("keeps -- when a priced model reported no token usage", () => {
      renderCost({
        costUsd: null,
        costSource: null,
        priceStatus: "resolved",
        tokens: null,
        inputTokens: null,
        outputTokens: null,
      });

      expect(screen.queryByText("!!")).not.toBeInTheDocument();
    });

    it("labels a catalog-calculated cost as list price without hiding the number", () => {
      renderCost({ costUsd: 0.25, costSource: "catalog_calculated", priceStatus: "resolved" });

      const cell = screen.getByTitle(/list price/i);
      expect(cell).toHaveTextContent("$0.25");
    });

    it("shows an upstream-billed cost with no list-price caveat", () => {
      renderCost({ costUsd: 0.25, costSource: "upstream_billed", priceStatus: "resolved" });

      expect(screen.queryByTitle(/list price/i)).not.toBeInTheDocument();
      expect(screen.getAllByText("$0.25").length).toBeGreaterThan(0);
    });
  });
});
