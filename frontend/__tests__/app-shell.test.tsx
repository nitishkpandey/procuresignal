import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { AppShell } from "@/components/app-shell";
import { useUserStore } from "@/store/user";

beforeEach(() => {
  localStorage.clear();
  useUserStore.setState({ userId: "", platformLanguage: "en" });
});

describe("AppShell", () => {
  it("requires a company email before showing the app", async () => {
    render(
      <AppShell>
        <p>Private app</p>
      </AppShell>,
    );

    expect(screen.getByLabelText("Company email")).toBeInTheDocument();
    expect(screen.queryByText("Private app")).not.toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Company email"), "buyer@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(useUserStore.getState().userId).toBe("buyer@example.com");
    expect(screen.getByText("Private app")).toBeInTheDocument();
  });
});
