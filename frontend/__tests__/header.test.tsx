import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { Header } from "@/components/header";
import { useUserStore } from "@/store/user";

beforeEach(() => {
  localStorage.clear();
  useUserStore.setState({ userId: "demo-user" });
});

describe("Header", () => {
  it("shows nav links", () => {
    render(<Header />);
    expect(screen.getByRole("link", { name: "Feed" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Preferences" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Chat" })).toBeInTheDocument();
  });

  it("edits the user id", async () => {
    render(<Header />);
    const input = screen.getByLabelText("User ID") as HTMLInputElement;
    await userEvent.clear(input);
    await userEvent.type(input, "alice");
    expect(useUserStore.getState().userId).toBe("alice");
  });
});
