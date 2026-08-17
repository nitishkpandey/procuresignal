import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  getNotifications: vi.fn(),
  markNotificationRead: vi.fn(),
}));

import { NotificationBell } from "@/components/notification-bell";
import * as api from "@/lib/api";
import { useUserStore } from "@/store/user";

import { authUser } from "./helpers";

beforeEach(() => {
  localStorage.clear();
  useUserStore.setState({ user: authUser(), platformLanguage: "en" });
  vi.mocked(api.getNotifications).mockResolvedValue({
    items: [
      {
        public_id: "n-1",
        subject: "Critical sanctions: Siemens AG",
        body: "EU listed a subsidiary.",
        rule_name: "Tier 1",
        risk_type: "sanctions",
        severity: "critical",
        supplier_public_ids: ["s-1"],
        delivered_at: "2026-08-10T08:00:00Z",
        read_at: null,
      },
    ],
    total_count: 1,
    unread_count: 1,
  });
});

describe("NotificationBell", () => {
  it("shows the unread count once loaded", async () => {
    render(<NotificationBell />);

    expect(await screen.findByLabelText(/1 unread/i)).toBeInTheDocument();
  });

  it("shows why an alert was sent, not just that it was", async () => {
    render(<NotificationBell />);

    await userEvent.click(await screen.findByRole("button", { name: /1 unread/i }));

    expect(await screen.findByText(/Critical sanctions: Siemens AG/)).toBeInTheDocument();
    expect(screen.getByText(/Tier 1/)).toBeInTheDocument();
  });

  it("marks an alert read", async () => {
    render(<NotificationBell />);
    await userEvent.click(await screen.findByRole("button", { name: /1 unread/i }));

    await userEvent.click(await screen.findByRole("button", { name: /mark read/i }));

    expect(api.markNotificationRead).toHaveBeenCalledWith("n-1");
  });

  it("says so when there is nothing waiting", async () => {
    vi.mocked(api.getNotifications).mockResolvedValue({
      items: [],
      total_count: 0,
      unread_count: 0,
    });
    render(<NotificationBell />);

    await userEvent.click(await screen.findByRole("button", { name: /notifications/i }));

    expect(await screen.findByText(/nothing new/i)).toBeInTheDocument();
  });
});
