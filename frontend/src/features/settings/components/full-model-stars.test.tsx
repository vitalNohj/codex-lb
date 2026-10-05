import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OrcaRouterSidecarSettings } from "@/features/settings/components/orcarouter-sidecar-settings";
import type { DashboardSettings, SettingsUpdateRequest } from "@/features/settings/schemas";
import { createDashboardSettings } from "@/test/mocks/factories";

const SHARED_MODEL = "z-ai/glm-5.3";

function baseSettings(overrides: Partial<DashboardSettings> = {}): DashboardSettings {
  return {
    ...createDashboardSettings({}),
    orcarouterSidecarEnabled: true,
    orcarouterSidecarBaseUrl: "https://api.orcarouter.ai/v1",
    orcarouterSidecarApiKeyConfigured: true,
    orcarouterSidecarModelPrefixes: [{ prefix: "orcarouter/", strip: false }],
    ...overrides,
  } as DashboardSettings;
}

function renderCard(settings: DashboardSettings, onSave: (patch: Partial<SettingsUpdateRequest>) => Promise<unknown>) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <OrcaRouterSidecarSettings settings={settings} busy={false} onSave={onSave} />
    </QueryClientProvider>,
  );
}

function modelsRegion() {
  return within(screen.getByLabelText("Configured full models for OrcaRouter Integration"));
}

describe("full-model stars on integration cards", () => {
  it("allows adding a full model another card already carries, unstarred", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    const settings = baseSettings({
      openrouterSidecarFullModels: [SHARED_MODEL],
      sidecarFullModelStars: { [SHARED_MODEL]: "openrouter" },
    });
    renderCard(settings, onSave);

    await user.type(screen.getByLabelText("New full model for OrcaRouter Integration"), SHARED_MODEL);
    await user.click(screen.getByRole("button", { name: "Add full model" }));

    expect(modelsRegion().getByText(SHARED_MODEL)).toBeInTheDocument();
    // No conflict error: duplicates across cards are the point.
    expect(screen.queryByText(/already used by/)).not.toBeInTheDocument();
    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith(
        expect.objectContaining({
          orcarouterSidecarFullModels: [SHARED_MODEL],
          // OpenRouter's star survives; OrcaRouter's copy stays unstarred.
          sidecarFullModelStars: { [SHARED_MODEL]: "openrouter" },
        }),
      ),
    );
  });

  it("stars a model no other card carries when it is added", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderCard(baseSettings(), onSave);

    await user.type(screen.getByLabelText("New full model for OrcaRouter Integration"), "fresh/model-1");
    await user.click(screen.getByRole("button", { name: "Add full model" }));

    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith(
        expect.objectContaining({
          orcarouterSidecarFullModels: ["fresh/model-1"],
          sidecarFullModelStars: { "fresh/model-1": "orcarouter" },
        }),
      ),
    );
  });

  it("toggles the star and moves it off other cards", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    const settings = baseSettings({
      orcarouterSidecarFullModels: [SHARED_MODEL],
      openrouterSidecarFullModels: [SHARED_MODEL],
      sidecarFullModelStars: { [SHARED_MODEL]: "openrouter" },
    });
    renderCard(settings, onSave);

    const star = screen.getByRole("button", { name: `Star ${SHARED_MODEL}: make this integration its default route` });
    await user.click(star);

    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith(
        expect.objectContaining({ sidecarFullModelStars: { [SHARED_MODEL]: "orcarouter" } }),
      ),
    );
  });

  it("unstars through the star button, leaving the model unrouted-by-default", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    const settings = baseSettings({
      orcarouterSidecarFullModels: [SHARED_MODEL],
      sidecarFullModelStars: { [SHARED_MODEL]: "orcarouter" },
    });
    renderCard(settings, onSave);

    await user.click(
      screen.getByRole("button", {
        name: `Unstar ${SHARED_MODEL}: it stops being this integration's default route`,
      }),
    );

    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ sidecarFullModelStars: {} })),
    );
  });

  it("renders the model id as selectable text with a separate remove control", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    const settings = baseSettings({ orcarouterSidecarFullModels: [SHARED_MODEL] });
    renderCard(settings, onSave);

    const region = modelsRegion();
    // The model id is plain selectable text, not the remove button.
    const text = region.getByText(SHARED_MODEL);
    expect(text.closest("button")).toBeNull();
    expect(text).toHaveClass("select-all");
    await user.click(region.getByRole("button", { name: `Remove ${SHARED_MODEL}` }));

    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith(
        expect.objectContaining({ orcarouterSidecarFullModels: [] }),
      ),
    );
  });

  it("drops this card's star when the starred entry is removed", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    const settings = baseSettings({
      orcarouterSidecarFullModels: [SHARED_MODEL, "other/model"],
      sidecarFullModelStars: { [SHARED_MODEL]: "orcarouter", "other/model": "openrouter" },
    });
    renderCard(settings, onSave);

    await user.click(modelsRegion().getByRole("button", { name: `Remove ${SHARED_MODEL}` }));

    await waitFor(() =>
      expect(onSave).toHaveBeenLastCalledWith(
        expect.objectContaining({
          orcarouterSidecarFullModels: ["other/model"],
          // The star this card held decays; the star another card holds stays.
          sidecarFullModelStars: { "other/model": "openrouter" },
        }),
      ),
    );
  });
});