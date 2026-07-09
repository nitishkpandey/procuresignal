import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ getPreferences: vi.fn(), savePreferences: vi.fn() }));
import * as api from "@/lib/api";
import { PreferenceForm } from "@/components/preference-form";
import { useUserStore } from "@/store/user";

beforeEach(() => {
  localStorage.clear();
  useUserStore.setState({ userId: "u1" });
  vi.mocked(api.getPreferences).mockResolvedValue(null);
  vi.mocked(api.savePreferences).mockImplementation(async (p) => p);
});

describe("PreferenceForm", () => {
  it("adds a supplier and saves", async () => {
    render(<PreferenceForm />);
    await waitFor(() => expect(screen.getByText("Supplier")).toBeInTheDocument());

    const input = screen.getByLabelText("Add suppliers");
    await userEvent.type(input, "Bosch{enter}");
    expect(screen.getByText("Bosch")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(api.savePreferences).toHaveBeenCalled());
    const saved = vi.mocked(api.savePreferences).mock.calls[0][0];
    expect(saved.interested_suppliers).toContain("Bosch");
    expect(saved.user_id).toBe("u1");
  });

  it("shows the four preference groups and platform language", async () => {
    render(<PreferenceForm />);

    await waitFor(() => expect(screen.getByText("Supplier")).toBeInTheDocument());
    expect(screen.getByText("Location")).toBeInTheDocument();
    expect(screen.getByText("Categories")).toBeInTheDocument();
    expect(screen.getByText("Misc")).toBeInTheDocument();
    expect(screen.getByLabelText("Platform language")).toBeInTheDocument();
  });

  it("shows a retry state when preferences cannot load", async () => {
    vi.mocked(api.getPreferences).mockRejectedValueOnce(new Error("Network Error"));
    render(<PreferenceForm />);
    await waitFor(() => expect(screen.getByText("Preferences unavailable")).toBeInTheDocument());
    expect(screen.getByText(/The preference service did not respond/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
