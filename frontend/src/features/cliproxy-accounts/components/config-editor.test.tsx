import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { CLIPROXY_CONFIG_QUERY_KEY } from "@/features/cliproxy-accounts/api";
import { CliproxyConfigEditor } from "@/features/cliproxy-accounts/components/config-editor";
import { server } from "@/test/mocks/server";
import { renderWithProviders } from "@/test/utils";

const VIEW = {
  status: "healthy",
  message: null,
  yaml: "port: 8317\ndebug: false\naccess:\n  api-keys:\n    - \"«codex-lb-redacted»\"\n",
  contentSha256: "abc123",
  sessionAffinity: true,
  forceModelPrefix: false,
  rollbackAvailable: true,
};

describe("CliproxyConfigEditor", () => {
  it("reviews a diff and replaces only after confirmation", async () => {
    const user = userEvent.setup();
    let replaced: { yaml?: string; confirm?: boolean; contentSha256?: string } | undefined;
    server.use(
      http.get("*/api/cliproxy/config", () => HttpResponse.json(VIEW)),
      http.post("*/api/cliproxy/config/preview", async ({ request }) => {
        const body = (await request.json()) as { yaml?: string };
        return HttpResponse.json({
          status: "healthy",
          message: null,
          diff: "--- current\n+++ proposed\n@@\n-debug: false\n+debug: true\n",
          changed: (body.yaml ?? "").includes("debug: true"),
          contentSha256: VIEW.contentSha256,
        });
      }),
      http.put("*/api/cliproxy/config", async ({ request }) => {
        replaced = (await request.json()) as { yaml?: string; confirm?: boolean; contentSha256?: string };
        return HttpResponse.json({ ...VIEW, yaml: replaced.yaml, contentSha256: "def456", rollbackAvailable: true });
      }),
    );
    renderWithProviders(<CliproxyConfigEditor />);

    const editor = await screen.findByRole("textbox", { name: "config.yaml" });
    expect(editor).toHaveValue(VIEW.yaml);
    expect(editor).not.toHaveValue(expect.stringContaining("sk-live"));
    fireEvent.change(editor, { target: { value: "debug: true" } });
    await user.click(screen.getByRole("button", { name: "Review changes" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/debug: true/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Replace config" }));

    await waitFor(() => expect(replaced?.confirm).toBe(true));
    expect(replaced?.yaml).toBe("debug: true");
    expect(replaced?.contentSha256).toBe(VIEW.contentSha256);
    expect(toast.success).toHaveBeenCalledWith("CLIProxyAPI config replaced");
  });

  it("does not confirm a draft typed while the preview is in flight", async () => {
    const user = userEvent.setup();
    let releasePreview: (() => void) | undefined;
    const previewGate = new Promise<void>((resolve) => {
      releasePreview = resolve;
    });
    let replaced = false;
    server.use(
      http.get("*/api/cliproxy/config", () => HttpResponse.json(VIEW)),
      http.post("*/api/cliproxy/config/preview", async ({ request }) => {
        const body = (await request.json()) as { yaml?: string };
        expect(body.yaml).toBe("debug: true");
        await previewGate;
        return HttpResponse.json({
          status: "healthy",
          message: null,
          diff: "--- current\n+++ proposed\n@@\n-debug: false\n+debug: true\n",
          changed: true,
          contentSha256: VIEW.contentSha256,
        });
      }),
      http.put("*/api/cliproxy/config", () => {
        replaced = true;
        return HttpResponse.json(VIEW);
      }),
    );
    renderWithProviders(<CliproxyConfigEditor />);

    const editor = await screen.findByRole("textbox", { name: "config.yaml" });
    fireEvent.change(editor, { target: { value: "debug: true" } });
    await user.click(screen.getByRole("button", { name: "Review changes" }));
    fireEvent.change(editor, { target: { value: "debug: later" } });
    releasePreview?.();

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("The draft changed before the preview finished. Review it again."),
    );
    expect(screen.queryByRole("button", { name: "Replace config" })).not.toBeInTheDocument();
    expect(replaced).toBe(false);
  });

  it("drops a dirty draft when reload sees a newer file", async () => {
    const user = userEvent.setup();
    let current = VIEW;
    server.use(http.get("*/api/cliproxy/config", () => HttpResponse.json(current)));
    renderWithProviders(<CliproxyConfigEditor />);

    const editor = await screen.findByRole("textbox", { name: "config.yaml" });
    fireEvent.change(editor, { target: { value: "debug: true" } });
    current = {
      ...VIEW,
      yaml: "port: 8317\ndebug: false\n",
      contentSha256: "newer-sha",
    };
    await user.click(screen.getByRole("button", { name: "Reload" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("The live config changed, so the draft was dropped."),
    );
    expect(editor).toHaveValue(current.yaml);
    expect(screen.getByRole("button", { name: "Review changes" })).toBeEnabled();
  });

  it("refuses to review a draft after the loaded hash changes", async () => {
    const user = userEvent.setup();
    const newer = { ...VIEW, yaml: "port: 1\n", contentSha256: "newer-sha" };
    let current = VIEW;
    server.use(http.get("*/api/cliproxy/config", () => HttpResponse.json(current)));
    const { queryClient } = renderWithProviders(<CliproxyConfigEditor />);

    const editor = await screen.findByRole("textbox", { name: "config.yaml" });
    fireEvent.change(editor, { target: { value: "debug: true" } });
    current = newer;
    queryClient.setQueryData(CLIPROXY_CONFIG_QUERY_KEY, newer);

    expect(await screen.findByText("The live config changed. Reload to drop this draft before reviewing it.")).toBeInTheDocument();
    expect(editor).toHaveValue("debug: true");
    expect(screen.getByRole("button", { name: "Review changes" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Reload" }));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("The live config changed, so the draft was dropped."),
    );
    expect(editor).toHaveValue(newer.yaml);
    expect(screen.getByRole("button", { name: "Review changes" })).toBeEnabled();
  });

  it("rolls back only after confirmation", async () => {
    const user = userEvent.setup();
    let confirmed = false;
    server.use(
      http.get("*/api/cliproxy/config", () => HttpResponse.json(VIEW)),
      http.post("*/api/cliproxy/config/rollback", async ({ request }) => {
        const body = (await request.json()) as { confirm?: boolean };
        confirmed = body.confirm === true;
        return HttpResponse.json({ ...VIEW, yaml: "port: 8317\n", contentSha256: "restored" });
      }),
    );
    renderWithProviders(<CliproxyConfigEditor />);

    await user.click(await screen.findByRole("button", { name: "Roll back" }));
    expect(confirmed).toBe(false);
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Roll back" }));

    await waitFor(() => expect(confirmed).toBe(true));
    expect(toast.success).toHaveBeenCalledWith("CLIProxyAPI config restored");
  });

  it("patches force model prefix with the loaded document hash", async () => {
    const user = userEvent.setup();
    let body: { enabled?: boolean; contentSha256?: string } | undefined;
    server.use(
      http.get("*/api/cliproxy/config", () => HttpResponse.json(VIEW)),
      http.patch("*/api/cliproxy/config/routing/force-model-prefix", async ({ request }) => {
        body = (await request.json()) as { enabled?: boolean; contentSha256?: string };
        return HttpResponse.json({ ...VIEW, forceModelPrefix: true, contentSha256: "prefixed" });
      }),
    );
    renderWithProviders(<CliproxyConfigEditor />);

    const toggle = await screen.findByRole("switch", { name: "Force model prefix" });
    expect(toggle).not.toBeChecked();
    await user.click(toggle);

    await waitFor(() => expect(body?.enabled).toBe(true));
    expect(body?.contentSha256).toBe(VIEW.contentSha256);
  });

  it("toasts invalid YAML and does not ask to replace", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("*/api/cliproxy/config", () => HttpResponse.json(VIEW)),
      http.post("*/api/cliproxy/config/preview", () =>
        HttpResponse.json(
          { error: { code: "invalid_yaml", message: "Invalid YAML at line 1, column 10" } },
          { status: 400 },
        ),
      ),
    );
    renderWithProviders(<CliproxyConfigEditor />);

    await user.click(await screen.findByRole("button", { name: "Review changes" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Invalid YAML at line 1, column 10"));
    expect(screen.queryByRole("button", { name: "Replace config" })).not.toBeInTheDocument();
  });

  it("hides the editor when the integration is off", async () => {
    server.use(
      http.get("*/api/cliproxy/config", () =>
        HttpResponse.json({
          status: "disabled",
          message: "CLIProxyAPI integration is disabled",
          rollbackAvailable: false,
        }),
      ),
    );
    renderWithProviders(<CliproxyConfigEditor />);

    expect(await screen.findByText("CLIProxyAPI integration is disabled")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "config.yaml" })).not.toBeInTheDocument();
  });
});
