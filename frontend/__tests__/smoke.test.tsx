import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "@/app/page";

describe("smoke", () => {
  it("renders the home placeholder", () => {
    render(<Home />);
    expect(screen.getByText("ProcureSignal")).toBeInTheDocument();
  });
});
