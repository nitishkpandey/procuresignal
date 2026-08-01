import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/components/app-shell";
import { useUserStore } from "@/store/user";

import { authUser } from "./helpers";

const restoreSession = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth", () => ({
  restoreSession,
  getAccessToken: () => null,
  login: vi.fn(),
  register: vi.fn(),
  logout: vi.fn(),
  installAuthInterceptors: vi.fn(),
}));

beforeEach(() => {
  localStorage.clear();
  useUserStore.setState({ user: null, platformLanguage: "en" });
  restoreSession.mockReset();
});

describe("AppShell", () => {
  it("hides the app until a session is restored", async () => {
    restoreSession.mockResolvedValue(authUser());

    render(
      <AppShell>
        <p>Private app</p>
      </AppShell>,
    );

    // No sign-in form flashes while the refresh cookie is still being checked.
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Private app")).toBeInTheDocument());
  });

  it("asks for credentials when there is no session", async () => {
    restoreSession.mockResolvedValue(null);

    render(
      <AppShell>
        <p>Private app</p>
      </AppShell>,
    );

    await waitFor(() => expect(screen.getByLabelText("Password")).toBeInTheDocument());
    expect(screen.queryByText("Private app")).not.toBeInTheDocument();
  });

  it("does not strand the user on the loading state when restore fails", async () => {
    restoreSession.mockRejectedValue(new Error("network down"));

    render(
      <AppShell>
        <p>Private app</p>
      </AppShell>,
    );

    await waitFor(() => expect(screen.getByLabelText("Password")).toBeInTheDocument());
  });
});
