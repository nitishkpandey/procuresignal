import { beforeEach, describe, expect, it } from "vitest";

import { useUserStore } from "@/store/user";

beforeEach(() => {
  localStorage.clear();
  useUserStore.setState({ userId: "", platformLanguage: "en" });
});

describe("user store", () => {
  it("starts without a signed-in user", () => {
    expect(useUserStore.getState().userId).toBe("");
  });

  it("stores a normalized company email", () => {
    useUserStore.getState().setUserId(" Buyer@Example.COM ");
    expect(useUserStore.getState().userId).toBe("buyer@example.com");
  });

  it("clears the signed-in user", () => {
    useUserStore.getState().setUserId("buyer@example.com");
    useUserStore.getState().setPlatformLanguage("de");
    useUserStore.getState().clearUser();
    expect(useUserStore.getState().userId).toBe("");
    expect(useUserStore.getState().platformLanguage).toBe("en");
  });

  it("stores a supported platform language", () => {
    useUserStore.getState().setPlatformLanguage("de");
    expect(useUserStore.getState().platformLanguage).toBe("de");

    useUserStore.getState().setPlatformLanguage("unknown");
    expect(useUserStore.getState().platformLanguage).toBe("en");
  });
});
