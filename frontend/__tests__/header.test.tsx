import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ updatePlatformLanguage: vi.fn() }));
import * as api from "@/lib/api";
import { Header } from "@/components/header";
import { useUserStore } from "@/store/user";

beforeEach(() => {
  localStorage.clear();
  useUserStore.setState({ userId: "buyer@example.com", platformLanguage: "en" });
  vi.mocked(api.updatePlatformLanguage).mockResolvedValue({
    user_id: "buyer@example.com",
    interested_categories: [],
    interested_suppliers: [],
    interested_regions: [],
    interested_signals: [],
    excluded_categories: [],
    excluded_suppliers: [],
    excluded_regions: [],
    excluded_signals: [],
    platform_language: "de",
  });
});

describe("Header", () => {
  it("shows nav links", () => {
    render(<Header />);
    expect(screen.getByRole("link", { name: "Feed" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Currency" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Risks" })).toBeInTheDocument();
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

  it("uses the selected platform language for shell labels", () => {
    useUserStore.setState({ userId: "buyer@example.com", platformLanguage: "de" });
    render(<Header />);

    expect(screen.getByRole("link", { name: "Signale" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Einstellungen" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Abmelden" })).toBeInTheDocument();
  });

  it("keeps the language selector beside the signed-in email and persists changes", async () => {
    render(<Header />);

    const email = screen.getByText("buyer@example.com");
    const language = screen.getByLabelText("Platform language");
    expect(email.parentElement).toContainElement(language);
    expect(language).toHaveDisplayValue("EN");

    await userEvent.selectOptions(language, "de");

    expect(useUserStore.getState().platformLanguage).toBe("de");
    expect(api.updatePlatformLanguage).toHaveBeenCalledWith("buyer@example.com", "de");
  });
});
