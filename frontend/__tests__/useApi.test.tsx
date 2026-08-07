import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useApi } from "@/lib/useApi";

describe("useApi", () => {
  it("resolves data", async () => {
    const { result } = renderHook(() => useApi(async () => 42, "answer"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toBe(42);
    expect(result.current.error).toBeNull();
  });

  it("captures errors", async () => {
    const { result } = renderHook(() =>
      useApi(async () => {
        throw new Error("boom");
      }, "error"),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe("boom");
    expect(result.current.data).toBeNull();
  });

  it("hides stale data while a changed request is loading", async () => {
    let resolveSecond: (value: number) => void = () => undefined;
    const second = new Promise<number>((resolve) => {
      resolveSecond = resolve;
    });
    const { result, rerender } = renderHook(
      ({ requestKey }) =>
        useApi(() => (requestKey === "first" ? Promise.resolve(1) : second), requestKey),
      { initialProps: { requestKey: "first" } },
    );
    await waitFor(() => expect(result.current.data).toBe(1));

    rerender({ requestKey: "second" });

    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBeNull();
    act(() => resolveSecond(2));
    await waitFor(() => expect(result.current.data).toBe(2));
  });

  it("returns to a loading state when reloaded", async () => {
    let calls = 0;
    const { result } = renderHook(() => useApi(async () => ++calls, "counter"));
    await waitFor(() => expect(result.current.data).toBe(1));

    act(() => result.current.reload());

    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBeNull();
    await waitFor(() => expect(result.current.data).toBe(2));
  });
});
