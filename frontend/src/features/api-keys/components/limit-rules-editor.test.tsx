import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { LimitRuleCreate } from "@/features/api-keys/schemas";
import { renderWithProviders } from "@/test/utils";

import { LimitRulesEditor } from "./limit-rules-editor";

describe("LimitRulesEditor", () => {
  it("renders basic mode when rules are empty", () => {
    renderWithProviders(<LimitRulesEditor rules={[]} onChange={vi.fn()} />);

    expect(screen.getByText("Weekly token limit")).toBeInTheDocument();
    expect(screen.getByText("Weekly cost limit ($)")).toBeInTheDocument();
  });

  it("renders basic mode for standard weekly rules", () => {
    const rules: LimitRuleCreate[] = [
      { limitType: "total_tokens", limitWindow: "weekly", maxValue: 500_000, modelFilter: null },
    ];
    renderWithProviders(<LimitRulesEditor rules={rules} onChange={vi.fn()} />);

    expect(screen.getByText("Weekly token limit")).toBeInTheDocument();
    expect(screen.getByDisplayValue("500000")).toBeInTheDocument();
  });

  it("starts in advanced mode when rules have non-standard types", () => {
    const rules: LimitRuleCreate[] = [
      { limitType: "input_tokens", limitWindow: "weekly", maxValue: 100, modelFilter: null },
    ];
    renderWithProviders(<LimitRulesEditor rules={rules} onChange={vi.fn()} />);

    expect(screen.getByText("Add limit rule")).toBeInTheDocument();
  });

  it("loads an all-models limit into the top boxes for its window", () => {
    const rules: LimitRuleCreate[] = [
      { limitType: "total_tokens", limitWindow: "daily", maxValue: 100, modelFilter: null },
    ];
    renderWithProviders(<LimitRulesEditor rules={rules} onChange={vi.fn()} />);

    expect(screen.getByText("Daily token limit")).toBeInTheDocument();
    expect(screen.getByDisplayValue("100")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Window" })).toHaveTextContent("Daily");
    expect(screen.queryByText("Add limit rule")).not.toBeInTheDocument();
  });

  it("keeps a reasoning effort on an overall limit without an effort control", () => {
    const onChange = vi.fn();
    const rules: LimitRuleCreate[] = [
      {
        limitType: "total_tokens",
        limitWindow: "weekly",
        maxValue: 100,
        modelFilter: null,
        reasoningEffort: "high",
      },
    ];
    renderWithProviders(<LimitRulesEditor rules={rules} onChange={onChange} />);

    expect(screen.queryByText("Add limit rule")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Reasoning effort" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Weekly token limit")).toHaveDisplayValue("100");

    fireEvent.change(screen.getByLabelText("Weekly token limit"), { target: { value: "250" } });

    expect(onChange).toHaveBeenCalledWith([
      expect.objectContaining({
        limitType: "total_tokens",
        limitWindow: "weekly",
        maxValue: 250,
        modelFilter: null,
        reasoningEffort: "high",
      }),
    ]);
  });

  it("starts in advanced mode when rules have model filters", () => {
    const rules: LimitRuleCreate[] = [
      { limitType: "total_tokens", limitWindow: "weekly", maxValue: 100, modelFilter: "gpt-5.1" },
    ];
    renderWithProviders(<LimitRulesEditor rules={rules} onChange={vi.fn()} />);

    expect(screen.getByText("Add limit rule")).toBeInTheDocument();
  });

  it("adds a new rule in advanced mode", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const rules: LimitRuleCreate[] = [
      { limitType: "input_tokens", limitWindow: "daily", maxValue: 100, modelFilter: null },
    ];
    renderWithProviders(<LimitRulesEditor rules={rules} onChange={onChange} />);

    await user.click(screen.getByText("Add limit rule"));

    expect(onChange).toHaveBeenCalledWith([
      rules[0],
      { limitType: "total_tokens", limitWindow: "weekly", maxValue: 0, modelFilter: null },
    ]);
  });

  it("shows multi-rule warning when more than one rule exists", () => {
    const rules: LimitRuleCreate[] = [
      { limitType: "input_tokens", limitWindow: "daily", maxValue: 100, modelFilter: null },
      { limitType: "output_tokens", limitWindow: "daily", maxValue: 200, modelFilter: null },
    ];
    renderWithProviders(<LimitRulesEditor rules={rules} onChange={vi.fn()} />);

    expect(screen.getByText(/All rules are applied together/)).toBeInTheDocument();
  });

  it("does not show multi-rule warning with single rule", () => {
    const rules: LimitRuleCreate[] = [
      { limitType: "input_tokens", limitWindow: "daily", maxValue: 100, modelFilter: null },
    ];
    renderWithProviders(<LimitRulesEditor rules={rules} onChange={vi.fn()} />);

    expect(screen.queryByText(/All rules are applied together/)).not.toBeInTheDocument();
  });

  it("handles basic token input change via fireEvent", () => {
    const onChange = vi.fn();
    renderWithProviders(<LimitRulesEditor rules={[]} onChange={onChange} />);

    const inputs = screen.getAllByRole("spinbutton");
    fireEvent.change(inputs[0], { target: { value: "1000" } });

    const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    const tokenRule = lastCall.find(
      (r: LimitRuleCreate) => r.limitType === "total_tokens",
    );
    expect(tokenRule).toBeDefined();
    expect(tokenRule.maxValue).toBe(1000);
  });

  it("handles basic cost input change via fireEvent", () => {
    const onChange = vi.fn();
    renderWithProviders(<LimitRulesEditor rules={[]} onChange={onChange} />);

    const inputs = screen.getAllByRole("spinbutton");
    fireEvent.change(inputs[1], { target: { value: "5" } });

    const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    const costRule = lastCall.find(
      (r: LimitRuleCreate) => r.limitType === "cost_usd",
    );
    expect(costRule).toBeDefined();
    expect(costRule.maxValue).toBe(5_000_000);
  });

  it("removes token rule when cleared in basic mode", () => {
    const onChange = vi.fn();
    const rules: LimitRuleCreate[] = [
      { limitType: "total_tokens", limitWindow: "weekly", maxValue: 1000, modelFilter: null },
    ];
    renderWithProviders(<LimitRulesEditor rules={rules} onChange={onChange} />);

    const inputs = screen.getAllByRole("spinbutton");
    fireEvent.change(inputs[0], { target: { value: "" } });

    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("displays cost value converted from micro-USD in basic mode", () => {
    const rules: LimitRuleCreate[] = [
      { limitType: "cost_usd", limitWindow: "weekly", maxValue: 3_500_000, modelFilter: null },
    ];
    renderWithProviders(<LimitRulesEditor rules={rules} onChange={vi.fn()} />);

    expect(screen.getByDisplayValue("3.5")).toBeInTheDocument();
  });

  it("can switch to advanced mode without hiding the overall limits", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LimitRulesEditor rules={[]} onChange={vi.fn()} />);

    expect(screen.getByText("Weekly token limit")).toBeInTheDocument();
    expect(screen.getByText("Weekly cost limit ($)")).toBeInTheDocument();

    await user.click(screen.getByRole("switch"));

    expect(screen.getByText("Add limit rule")).toBeInTheDocument();
    expect(screen.getByText("Weekly token limit")).toBeInTheDocument();
    expect(screen.getByText("Weekly cost limit ($)")).toBeInTheDocument();
  });

  it("keeps advanced rule inputs focused while max value edits rerender", async () => {
    const user = userEvent.setup();
    function StatefulLimitRulesEditor() {
      const [rules, setRules] = useState<LimitRuleCreate[]>([
        { limitType: "input_tokens", limitWindow: "daily", maxValue: 1, modelFilter: null },
      ]);
      return <LimitRulesEditor rules={rules} onChange={setRules} />;
    }

    renderWithProviders(<StatefulLimitRulesEditor />);

    const maxValueInput = screen.getByLabelText("Max value (tokens)");
    await user.clear(maxValueInput);
    await user.type(maxValueInput, "1234");

    expect(maxValueInput).toHaveFocus();
    expect(maxValueInput).toHaveValue(1234);
  });

  it("keeps weekly token and cost caps beside a group rule while advanced is on", () => {
    const rules: LimitRuleCreate[] = [
      { limitType: "total_tokens", limitWindow: "weekly", maxValue: 1000, modelFilter: null },
      { limitType: "cost_usd", limitWindow: "weekly", maxValue: 500_000_000, modelFilter: null },
      {
        limitType: "total_tokens",
        limitWindow: "daily",
        maxValue: 50,
        modelFilter: "gpt-5.4",
        modelFilters: ["gpt-5.4"],
      },
    ];
    renderWithProviders(<LimitRulesEditor rules={rules} onChange={vi.fn()} />);

    expect(screen.queryByText("Overall limit (all models)")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Weekly token limit")).toHaveDisplayValue("1000");
    expect(screen.getByLabelText("Weekly cost limit ($)")).toHaveDisplayValue("500");

    const groupCard = screen.getByText("Limit rule").closest(".rounded-lg");
    expect(groupCard).not.toBeNull();
    expect(within(groupCard as HTMLElement).getByDisplayValue("50")).toBeInTheDocument();
    expect(within(groupCard as HTMLElement).getByText("Model Filter")).toBeInTheDocument();
    expect(screen.getAllByRole("combobox", { name: "Reasoning effort" })).toHaveLength(1);
    expect(within(groupCard as HTMLElement).getByRole("combobox", { name: "Reasoning effort" })).toBeInTheDocument();
  });

  it("keeps the overall limit editable when advanced mode is toggled", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const rules: LimitRuleCreate[] = [
      { limitType: "cost_usd", limitWindow: "weekly", maxValue: 500_000_000, modelFilter: null },
    ];
    renderWithProviders(<LimitRulesEditor rules={rules} onChange={onChange} />);

    expect(screen.getByLabelText("Weekly cost limit ($)")).toHaveDisplayValue("500");

    await user.click(screen.getByRole("switch", { name: "Advanced" }));

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText("Add limit rule")).toBeInTheDocument();
    expect(screen.getByLabelText("Weekly cost limit ($)")).toHaveDisplayValue("500");
    expect(screen.queryByText("Overall limit (all models)")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Weekly cost limit ($)"), { target: { value: "600" } });
    expect(onChange).toHaveBeenCalledWith([
      expect.objectContaining({
        limitType: "cost_usd",
        limitWindow: "weekly",
        maxValue: 600_000_000,
        modelFilter: null,
      }),
    ]);

    await user.click(screen.getByRole("switch", { name: "Advanced" }));

    expect(screen.queryByText("Add limit rule")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Weekly cost limit ($)")).toHaveDisplayValue("500");
  });

  it("round-trips the overall window for token and cost limits", async () => {
    const user = userEvent.setup();
    const seen: LimitRuleCreate[][] = [];

    function StatefulLimitRulesEditor() {
      const [rules, setRules] = useState<LimitRuleCreate[]>([
        { limitType: "total_tokens", limitWindow: "weekly", maxValue: 1000, modelFilter: null },
        { limitType: "cost_usd", limitWindow: "weekly", maxValue: 5_000_000, modelFilter: null },
      ]);
      return (
        <LimitRulesEditor
          rules={rules}
          onChange={(next) => {
            seen.push(next);
            setRules(next);
          }}
        />
      );
    }

    renderWithProviders(<StatefulLimitRulesEditor />);

    expect(screen.getByLabelText("Weekly token limit")).toHaveDisplayValue("1000");
    expect(screen.getByLabelText("Weekly cost limit ($)")).toHaveDisplayValue("5");

    await user.click(screen.getByRole("combobox", { name: "Window" }));
    await user.click(await screen.findByRole("option", { name: "Monthly" }));

    expect(screen.getByLabelText("Monthly token limit")).toHaveDisplayValue("1000");
    expect(screen.getByLabelText("Monthly cost limit ($)")).toHaveDisplayValue("5");
    expect(seen.at(-1)).toEqual([
      expect.objectContaining({ limitType: "total_tokens", limitWindow: "monthly", maxValue: 1000 }),
      expect.objectContaining({ limitType: "cost_usd", limitWindow: "monthly", maxValue: 5_000_000 }),
    ]);

    await user.click(screen.getByRole("combobox", { name: "Window" }));
    await user.click(await screen.findByRole("option", { name: "Weekly" }));

    expect(screen.getByLabelText("Weekly token limit")).toHaveDisplayValue("1000");
    expect(screen.getByLabelText("Weekly cost limit ($)")).toHaveDisplayValue("5");
    expect(seen.at(-1)).toEqual([
      expect.objectContaining({ limitType: "total_tokens", limitWindow: "weekly", maxValue: 1000 }),
      expect.objectContaining({ limitType: "cost_usd", limitWindow: "weekly", maxValue: 5_000_000 }),
    ]);
  });

  it("defaults a new rule to the overall window", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const rules: LimitRuleCreate[] = [
      { limitType: "cost_usd", limitWindow: "monthly", maxValue: 5_000_000, modelFilter: null },
    ];
    renderWithProviders(<LimitRulesEditor rules={rules} onChange={onChange} />);

    await user.click(screen.getByRole("switch", { name: "Advanced" }));
    await user.click(screen.getByText("Add limit rule"));

    expect(onChange).toHaveBeenCalledWith([
      rules[0],
      { limitType: "total_tokens", limitWindow: "monthly", maxValue: 0, modelFilter: null },
    ]);
  });

  it("saves an overall limit together with a group rule", () => {
    function StatefulLimitRulesEditor() {
      const [rules, setRules] = useState<LimitRuleCreate[]>([
        {
          limitType: "total_tokens",
          limitWindow: "weekly",
          maxValue: 1000,
          modelFilter: "gpt-5.4",
          modelFilters: ["gpt-5.4"],
          reasoningEffort: "high",
        },
      ]);
      return <LimitRulesEditor rules={rules} onChange={setRules} />;
    }

    renderWithProviders(<StatefulLimitRulesEditor />);

    expect(screen.queryByText("Overall limit (all models)")).not.toBeInTheDocument();
    expect(screen.getAllByRole("combobox", { name: "Reasoning effort" })).toHaveLength(1);
    const groupCard = screen.getByText("Limit rule").closest(".rounded-lg");
    expect(groupCard).not.toBeNull();
    expect(within(groupCard as HTMLElement).getByRole("combobox", { name: "Reasoning effort" })).toHaveTextContent("High");

    fireEvent.change(screen.getByLabelText("Weekly cost limit ($)"), { target: { value: "500" } });

    expect(screen.getByLabelText("Weekly cost limit ($)")).toHaveDisplayValue("500");
    expect(screen.getByDisplayValue("1000")).toBeInTheDocument();
    expect(within(groupCard as HTMLElement).getByRole("combobox", { name: "Reasoning effort" })).toHaveTextContent("High");
    expect(screen.getByText(/All rules are applied together/)).toBeInTheDocument();
  });

  it("clears an overall cap without restoring it when the window changes", async () => {
    const user = userEvent.setup();
    const seen: LimitRuleCreate[][] = [];

    function StatefulLimitRulesEditor() {
      const [rules, setRules] = useState<LimitRuleCreate[]>([
        {
          limitType: "total_tokens",
          limitWindow: "weekly",
          maxValue: 1000,
          modelFilter: "gpt-5.4",
          modelFilters: ["gpt-5.4"],
        },
      ]);
      return (
        <LimitRulesEditor
          rules={rules}
          onChange={(next) => {
            seen.push(next);
            setRules(next);
          }}
        />
      );
    }

    renderWithProviders(<StatefulLimitRulesEditor />);

    fireEvent.change(screen.getByLabelText("Weekly cost limit ($)"), { target: { value: "500" } });
    expect(screen.getByLabelText("Weekly cost limit ($)")).toHaveDisplayValue("500");

    fireEvent.change(screen.getByLabelText("Weekly cost limit ($)"), { target: { value: "" } });

    expect(screen.getByLabelText("Weekly cost limit ($)")).toHaveValue(null);
    expect(seen.at(-1)?.some((rule) => rule.limitType === "cost_usd" && (rule.maxValue ?? 0) > 0)).toBe(false);

    const [overallWindow] = screen.getAllByRole("combobox", { name: "Window" });
    await user.click(overallWindow);
    await user.click(await screen.findByRole("option", { name: "Daily" }));

    expect(screen.getByLabelText("Daily cost limit ($)")).toHaveValue(null);
    expect(seen.at(-1)?.some((rule) => rule.limitType === "cost_usd" && (rule.maxValue ?? 0) > 0)).toBe(false);
  });

  it("does not restore a removed overall cap when advanced mode is toggled", async () => {
    const user = userEvent.setup();

    function StatefulLimitRulesEditor() {
      const [rules, setRules] = useState<LimitRuleCreate[]>([
        {
          limitType: "total_tokens",
          limitWindow: "weekly",
          maxValue: 1000,
          modelFilter: "gpt-5.4",
          modelFilters: ["gpt-5.4"],
        },
      ]);
      return <LimitRulesEditor rules={rules} onChange={setRules} />;
    }

    renderWithProviders(<StatefulLimitRulesEditor />);

    fireEvent.change(screen.getByLabelText("Weekly cost limit ($)"), { target: { value: "500" } });
    fireEvent.change(screen.getByLabelText("Weekly cost limit ($)"), { target: { value: "" } });

    await user.click(screen.getByRole("switch", { name: "Advanced" }));
    await user.click(screen.getByRole("switch", { name: "Advanced" }));

    expect(screen.getByLabelText("Weekly cost limit ($)")).toHaveValue(null);
    expect(screen.getByDisplayValue("1000")).toBeInTheDocument();
  });
});
