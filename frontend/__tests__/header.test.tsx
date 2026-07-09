import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { Header } from "@/components/header";
import { useUserStore } from "@/store/user";

beforeEach(() => {
  localStorage.clear();
  useUserStore.setState({ userId: "buyer@example.com" });
});

describe("Header", () => {
  it("shows nav links", () => {
    render(<Header />);
    expect(screen.getByRole("link", { name: "Feed" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Preferences" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Chat" })).toBeInTheDocument();
  });

  it("shows the signed-in company email and signs out", async () => {
    render(<Header />);
    expect(screen.queryByText("Viewing as")).not.toBeInTheDocument();
    expect(screen.getByText("buyer@example.com")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(useUserStore.getState().userId).toBe("");
  });
});
