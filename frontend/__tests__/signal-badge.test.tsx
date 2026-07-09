import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SignalBadge } from "@/components/signal-badge";

describe("SignalBadge", () => {
  it("renders the signal label", () => {
    render(<SignalBadge signal="bankruptcy" />);
    expect(screen.getByText("Bankruptcy")).toBeInTheDocument();
  });

  it("applies priority styling", () => {
    render(<SignalBadge signal="tariff" priority />);
    const el = screen.getByText("Tariff");
    expect(el.className).toContain("bg-red");
  });
});
