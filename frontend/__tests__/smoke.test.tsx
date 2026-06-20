import { describe, expect, it } from "vitest";

import { apiBaseUrl } from "@/lib/api";

describe("smoke", () => {
  it("resolves an API base url", () => {
    expect(typeof apiBaseUrl()).toBe("string");
  });
});
