import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ExcludedModelsEditor } from "@/features/settings/components/excluded-models-editor";

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
