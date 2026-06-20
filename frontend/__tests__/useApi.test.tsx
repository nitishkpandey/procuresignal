import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useApi } from "@/lib/useApi";

describe("useApi", () => {
  it("resolves data", async () => {
    const { result } = renderHook(() => useApi(async () => 42, []));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toBe(42);
    expect(result.current.error).toBeNull();
  });

  it("captures errors", async () => {
    const { result } = renderHook(() =>
      useApi(async () => {
        throw new Error("boom");
      }, []),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe("boom");
    expect(result.current.data).toBeNull();
  });
});
