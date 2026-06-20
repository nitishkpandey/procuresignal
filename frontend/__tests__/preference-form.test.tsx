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
    await waitFor(() => expect(screen.getByLabelText("Add interested_suppliers")).toBeInTheDocument());

    const input = screen.getByLabelText("Add interested_suppliers");
    await userEvent.type(input, "Bosch{enter}");
    expect(screen.getByText("Bosch")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(api.savePreferences).toHaveBeenCalled());
    const saved = vi.mocked(api.savePreferences).mock.calls[0][0];
    expect(saved.interested_suppliers).toContain("Bosch");
    expect(saved.user_id).toBe("u1");
  });
});
