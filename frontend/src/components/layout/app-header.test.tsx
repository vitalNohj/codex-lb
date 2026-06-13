import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { AppHeader } from "@/components/layout/app-header";

describe("AppHeader", () => {
  it("opens the OmniRoute link in a new tab", () => {
    render(
      <MemoryRouter>
        <AppHeader onLogout={vi.fn()} />
      </MemoryRouter>,
    );

    const link = screen.getAllByRole("link", { name: /omniroute/i })[0];
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });
});
