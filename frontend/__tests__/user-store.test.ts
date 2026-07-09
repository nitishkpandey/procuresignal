import { beforeEach, describe, expect, it } from "vitest";

import { useUserStore } from "@/store/user";

beforeEach(() => {
  localStorage.clear();
  useUserStore.setState({ userId: "" });
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
    useUserStore.getState().clearUser();
    expect(useUserStore.getState().userId).toBe("");
  });
});
