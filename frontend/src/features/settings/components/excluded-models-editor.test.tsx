import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  ExcludedModelsEditor,
  MAX_PATTERN_LENGTH,
  MAX_PATTERNS,
} from "@/features/settings/components/excluded-models-editor";

function renderEditor(excludedModels: string[], onChange = vi.fn()) {
  render(
    <ExcludedModelsEditor
      name="claude-a@example.com.json"
      emailLabel="a@example.com"
      excludedModels={excludedModels}
      onChange={onChange}
    />,
  );
  return onChange;
}

describe("ExcludedModelsEditor", () => {
  it("shows a family switch as on when its pattern is excluded", () => {
    renderEditor(["claude-fable-*"]);

    expect(screen.getByRole("switch", { name: "Exclude Fable on a@example.com" })).toBeChecked();
    expect(
      screen.getByRole("switch", { name: "Exclude Opus 5 on a@example.com" }),
    ).not.toBeChecked();
  });

  it("turning a family switch on saves its pattern", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor([]);

    await user.click(screen.getByRole("switch", { name: "Exclude Fable on a@example.com" }));

    expect(onChange).toHaveBeenCalledWith(["claude-fable-*"]);
  });

  it("turning a family switch off clears its pattern", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor(["claude-fable-*"]);

    await user.click(screen.getByRole("switch", { name: "Exclude Fable on a@example.com" }));

    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("turning a family switch off keeps unrelated custom patterns", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor(["claude-fable-*", "claude-opus-4-*"]);

    await user.click(screen.getByRole("switch", { name: "Exclude Fable on a@example.com" }));

    expect(onChange).toHaveBeenCalledWith(["claude-opus-4-*"]);
  });

  it("renders a custom pattern as a removable chip", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor(["claude-opus-4-*"]);

    expect(screen.getByText("claude-opus-4-*")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Remove claude-opus-4-* from a@example.com" }),
    );

    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("does not render a chip for a pattern owned by a family switch", () => {
    renderEditor(["claude-fable-*"]);

    expect(
      screen.queryByRole("button", { name: "Remove claude-fable-* from a@example.com" }),
    ).not.toBeInTheDocument();
  });

  it("adds a typed pattern on Enter", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor([]);

    await user.type(
      screen.getByLabelText("Add excluded model pattern for a@example.com"),
      "claude-opus-4-*{Enter}",
    );

    expect(onChange).toHaveBeenCalledWith(["claude-opus-4-*"]);
  });

  it("adds a typed pattern with the Add button", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor(["claude-fable-*"]);

    await user.type(
      screen.getByLabelText("Add excluded model pattern for a@example.com"),
      "  claude-opus-4-*  ",
    );
    await user.click(
      screen.getByRole("button", { name: "Add excluded model pattern to claude-a@example.com.json" }),
    );

    expect(onChange).toHaveBeenCalledWith(["claude-fable-*", "claude-opus-4-*"]);
  });

  it("ignores a blank pattern", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor([]);

    await user.type(screen.getByLabelText("Add excluded model pattern for a@example.com"), "   {Enter}");

    expect(onChange).not.toHaveBeenCalled();
  });

  it("ignores a duplicate pattern regardless of case", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor(["claude-opus-4-*"]);

    await user.type(
      screen.getByLabelText("Add excluded model pattern for a@example.com"),
      "CLAUDE-OPUS-4-*{Enter}",
    );

    expect(onChange).not.toHaveBeenCalled();
  });

  it("refuses a cc/-prefixed alias id and explains why", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor([]);
    const input = screen.getByLabelText("Add excluded model pattern for a@example.com");

    await user.type(input, "cc/claude-fable-5{Enter}");

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Use the CLIProxyAPI wire id (claude-...), not the cc/ prefix",
    );
    expect(input).toHaveValue("cc/claude-fable-5");
  });

  it("clears the cc/ hint once the pattern is corrected", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor([]);
    const input = screen.getByLabelText("Add excluded model pattern for a@example.com");

    await user.type(input, "cc/claude-fable-5{Enter}");
    await user.clear(input);
    await user.type(input, "claude-fable-5{Enter}");

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(onChange).toHaveBeenCalledWith(["claude-fable-5"]);
  });

  it("treats a narrower pattern in a family's namespace as a custom pattern", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor(["claude-fable-5"]);

    expect(screen.getByRole("switch", { name: "Exclude Fable on a@example.com" })).not.toBeChecked();
    await user.click(
      screen.getByRole("button", { name: "Remove claude-fable-5 from a@example.com" }),
    );

    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("broadens a narrower pattern to the family pattern when the switch is turned on", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor(["claude-haiku-4-5"]);

    await user.click(screen.getByRole("switch", { name: "Exclude Haiku on a@example.com" }));

    expect(onChange).toHaveBeenCalledWith(["claude-haiku-4-5", "claude-haiku-*"]);
  });

  it("refuses a pattern containing a comma", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor([]);

    await user.type(
      screen.getByLabelText("Add excluded model pattern for a@example.com"),
      "claude-a-*,claude-b-*{Enter}",
    );

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("a comma is not allowed");
  });

  it("refuses an overlong pattern", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor([]);

    await user.type(
      screen.getByLabelText("Add excluded model pattern for a@example.com"),
      `${"x".repeat(MAX_PATTERN_LENGTH + 1)}{Enter}`,
    );

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      `Keep the pattern under ${MAX_PATTERN_LENGTH} characters`,
    );
  });

  it("refuses to add beyond the maximum number of patterns", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor(
      Array.from({ length: MAX_PATTERNS }, (_, index) => `claude-full-${index}`),
    );

    await user.type(
      screen.getByLabelText("Add excluded model pattern for a@example.com"),
      "claude-one-too-many{Enter}",
    );

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(`At most ${MAX_PATTERNS} patterns`);
  });

  it("refuses to toggle a family on beyond the maximum number of patterns", async () => {
    const user = userEvent.setup();
    const onChange = renderEditor(
      Array.from({ length: MAX_PATTERNS }, (_, index) => `claude-full-${index}`),
    );

    await user.click(screen.getByRole("switch", { name: "Exclude Fable on a@example.com" }));

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(`At most ${MAX_PATTERNS} patterns`);
  });

  it("still turns a family off when the list is at the maximum", async () => {
    const user = userEvent.setup();
    const full = Array.from({ length: MAX_PATTERNS - 1 }, (_, index) => `claude-full-${index}`);
    const onChange = renderEditor([...full, "claude-fable-*"]);

    await user.click(screen.getByRole("switch", { name: "Exclude Fable on a@example.com" }));

    expect(onChange).toHaveBeenCalledWith(full);
  });

  it("locks every control and explains when the stored list could not be read", () => {
    render(
      <ExcludedModelsEditor
        name="claude-a@example.com.json"
        emailLabel="a@example.com"
        excludedModels={[]}
        state="unreadable"
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Could not read this account's excluded models",
    );
    expect(screen.getByRole("switch", { name: "Exclude Fable on a@example.com" })).toBeDisabled();
    expect(screen.getByLabelText("Add excluded model pattern for a@example.com")).toBeDisabled();
    expect(
      screen.getByRole("button", {
        name: "Add excluded model pattern to claude-a@example.com.json",
      }),
    ).toBeDisabled();
  });

  it("locks an unsupported row without claiming a read failed", () => {
    render(
      <ExcludedModelsEditor
        name="a@example.com"
        emailLabel="a@example.com"
        excludedModels={[]}
        state="unsupported"
        onChange={vi.fn()}
      />,
    );

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/Could not read/)).not.toBeInTheDocument();
    expect(
      screen.getByText("Excluded models are not available for this row."),
    ).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Exclude Fable on a@example.com" })).toBeDisabled();
  });

  it("stays editable when the list is readable but empty", () => {
    renderEditor([]);

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      screen.getByRole("switch", { name: "Exclude Fable on a@example.com" }),
    ).not.toBeDisabled();
    expect(
      screen.getByLabelText("Add excluded model pattern for a@example.com"),
    ).not.toBeDisabled();
  });

  it("disables every control when disabled", () => {
    render(
      <ExcludedModelsEditor
        name="claude-a@example.com.json"
        emailLabel="a@example.com"
        excludedModels={["claude-opus-4-*"]}
        disabled
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("switch", { name: "Exclude Fable on a@example.com" })).toBeDisabled();
    expect(screen.getByLabelText("Add excluded model pattern for a@example.com")).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Remove claude-opus-4-* from a@example.com" }),
    ).toBeDisabled();
  });
});
