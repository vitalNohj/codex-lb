import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AliasSettings } from "@/features/settings/components/alias-settings";
import type { DashboardSettings } from "@/features/settings/schemas";
import { createDashboardSettings } from "@/test/mocks/factories";
import { renderWithProviders } from "@/test/utils";

if (!HTMLElement.prototype.hasPointerCapture) {
  HTMLElement.prototype.hasPointerCapture = () => false;
}
if (!HTMLElement.prototype.setPointerCapture) {
  HTMLElement.prototype.setPointerCapture = () => undefined;
}
if (!HTMLElement.prototype.releasePointerCapture) {
  HTMLElement.prototype.releasePointerCapture = () => undefined;
}
if (!HTMLElement.prototype.scrollIntoView) {
  HTMLElement.prototype.scrollIntoView = () => undefined;
}

const ALIAS = "north-mini-code";
const TARGET = "or/cohere/north-mini-code";

function settingsWithAlias(overrides: Partial<DashboardSettings> = {}): DashboardSettings {
  return createDashboardSettings({
    modelAliases: { [ALIAS]: { targets: [TARGET] } },
    customAliasCatalog: {},
    ...overrides,
  });
}

describe("AliasSettings", () => {
  it("renders the editor in its own labelled settings card", () => {
    renderWithProviders(
      <AliasSettings settings={settingsWithAlias()} busy={false} onSave={vi.fn().mockResolvedValue(undefined)} />,
    );

    const card = screen.getByRole("region", { name: "Model aliasing" });
    expect(card).toContainElement(screen.getByTestId(`alias-row-${ALIAS}`));
    expect(card).toContainElement(screen.getByRole("textbox", { name: "Real model" }));
    expect(card).toContainElement(screen.getByRole("textbox", { name: "Alias name" }));
  });

  it("saves custom alias catalog context length overrides", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<AliasSettings settings={settingsWithAlias()} busy={false} onSave={onSave} />);

    await user.click(screen.getByRole("button", { name: "Advanced" }));
    await user.click(screen.getByRole("combobox", { name: `Context length for ${ALIAS}` }));
    await user.click(await screen.findByRole("option", { name: "1,000,000" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        customAliasCatalog: {
          [ALIAS]: { contextLength: 1_000_000 },
        },
      }),
    );
  });

  it("removes custom alias catalog rows when an alias is deleted", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(
      <AliasSettings
        settings={settingsWithAlias({ customAliasCatalog: { [ALIAS]: { contextLength: 1_000_000 } } })}
        busy={false}
        onSave={onSave}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Remove" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        modelAliases: {},
        customAliasCatalog: {},
      }),
    );
  });

  it("blocks adding an alias whose name already exists, ignoring case", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<AliasSettings settings={settingsWithAlias()} busy={false} onSave={onSave} />);

    await user.type(screen.getByRole("textbox", { name: "Real model" }), "gpt-5.4");
    await user.type(screen.getByRole("textbox", { name: "Alias name" }), ALIAS.toUpperCase());

    expect(screen.getByText("An alias with this name already exists.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add alias" })).toBeDisabled();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("sends the settings version with alias saves", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(
      <AliasSettings settings={settingsWithAlias({ version: 7 })} busy={false} onSave={onSave} />,
    );

    await user.type(screen.getByRole("textbox", { name: "Real model" }), " gpt-5.4 ");
    await user.type(screen.getByRole("textbox", { name: "Alias name" }), " fast ");
    await user.click(screen.getByRole("button", { name: "Add alias" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        expectedVersion: 7,
        modelAliases: {
          [ALIAS]: { targets: [TARGET] },
          fast: { targets: ["gpt-5.4"] },
        },
      }),
    );
    expect(screen.getByRole("textbox", { name: "Real model" })).toHaveValue("");
    expect(screen.getByRole("textbox", { name: "Alias name" })).toHaveValue("");
  });

  it("disables editing while busy", () => {
    renderWithProviders(
      <AliasSettings settings={settingsWithAlias()} busy onSave={vi.fn().mockResolvedValue(undefined)} />,
    );

    expect(screen.getByRole("textbox", { name: "Real model" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Alias name" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add alias" })).toBeDisabled();
  });
});
