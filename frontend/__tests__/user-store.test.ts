import { beforeEach, describe, expect, it } from "vitest";

import { useUserStore } from "@/store/user";

import { authUser } from "./helpers";

beforeEach(() => {
  localStorage.clear();
  useUserStore.setState({ user: null, platformLanguage: "en" });
});

describe("user store", () => {
  it("starts without a signed-in user", () => {
    expect(useUserStore.getState().user).toBeNull();
  });

  it("stores the identity returned by the server", () => {
    useUserStore.getState().setUser(authUser());
    expect(useUserStore.getState().user?.email).toBe("buyer@example.com");
  });

  it("clears the signed-in user", () => {
    useUserStore.getState().setUser(authUser());
    useUserStore.getState().setPlatformLanguage("de");
    useUserStore.getState().clearUser();
    expect(useUserStore.getState().user).toBeNull();
    expect(useUserStore.getState().platformLanguage).toBe("en");
  });

  it("stores a supported platform language", () => {
    useUserStore.getState().setPlatformLanguage("de");
    expect(useUserStore.getState().platformLanguage).toBe("de");

    useUserStore.getState().setPlatformLanguage("unknown");
    expect(useUserStore.getState().platformLanguage).toBe("en");
  });

  it("never persists the identity to browser storage", () => {
    // A stale local copy could outlive the session or name a disabled account.
    useUserStore.getState().setUser(authUser({ email: "persisted@example.com" }));
    useUserStore.getState().setPlatformLanguage("de");

    const stored = localStorage.getItem("procuresignal-user") ?? "";
    expect(stored).not.toContain("persisted@example.com");
    expect(stored).toContain("de");
  });
});
