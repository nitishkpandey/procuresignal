import { beforeEach, describe, expect, it } from "vitest";

import { useUserStore } from "@/store/user";

beforeEach(() => {
  localStorage.clear();
  useUserStore.setState({ userId: "demo-user" });
});

describe("user store", () => {
  it("defaults to demo-user", () => {
    expect(useUserStore.getState().userId).toBe("demo-user");
  });

  it("updates the user id", () => {
    useUserStore.getState().setUserId("alice");
    expect(useUserStore.getState().userId).toBe("alice");
  });
});
