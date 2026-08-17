import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  updatePlatformLanguage: vi.fn(),
  getNotifications: vi.fn(),
  markNotificationRead: vi.fn(),
}));
import * as api from "@/lib/api";
import { Header } from "@/components/header";
import { useUserStore } from "@/store/user";

import { authUser } from "./helpers";

beforeEach(() => {
  // Call counts leak between cases otherwise, so an assertion that nothing was
  // fetched would pass or fail on test order.
  vi.clearAllMocks();
  localStorage.clear();
  useUserStore.setState({ user: authUser(), platformLanguage: "en" });
  vi.mocked(api.getNotifications).mockResolvedValue({
    items: [],
    total_count: 0,
    unread_count: 0,
  });
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
    expect(screen.getByRole("link", { name: "Watchlists" })).toBeInTheDocument();
  });

  it("hides the notification bell when nobody is signed in", () => {
    useUserStore.setState({ user: null });
    render(<Header />);

    // A bell for an anonymous visitor would fetch another tenant's alerts on a
    // 401 retry loop and show a count that means nothing.
    expect(screen.queryByRole("button", { name: /notifications/i })).not.toBeInTheDocument();
    expect(api.getNotifications).not.toHaveBeenCalled();
  });

  it("shows the signed-in company email and signs out", async () => {
    render(<Header />);
    expect(screen.queryByText("Viewing as")).not.toBeInTheDocument();
    expect(screen.getByText("buyer@example.com")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(useUserStore.getState().user).toBeNull();
  });

  it("uses the selected platform language for shell labels", () => {
    useUserStore.setState({ user: authUser(), platformLanguage: "de" });
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
    expect(api.updatePlatformLanguage).toHaveBeenCalledWith("de");
  });
});
