import axios from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearAccessToken,
  getAccessToken,
  installAuthInterceptors,
  refreshAccessToken,
  restoreSession,
  setAccessToken,
  __resetRefreshState,
} from "@/lib/auth";

import { authUser } from "./helpers";

beforeEach(() => {
  clearAccessToken();
  __resetRefreshState();
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("access token storage", () => {
  it("never writes the token to browser storage", () => {
    setAccessToken("super-secret-token");

    // Anything in localStorage or sessionStorage is readable by any injected script.
    expect(JSON.stringify(localStorage)).not.toContain("super-secret-token");
    expect(JSON.stringify(sessionStorage)).not.toContain("super-secret-token");
    expect(document.cookie).not.toContain("super-secret-token");
    expect(getAccessToken()).toBe("super-secret-token");
  });

  it("forgets the token on clear", () => {
    setAccessToken("t");
    clearAccessToken();
    expect(getAccessToken()).toBeNull();
  });
});

describe("refresh coordination", () => {
  it("shares one refresh across concurrent callers", async () => {
    let resolveRefresh: (value: unknown) => void = () => {};
    const post = vi.spyOn(axios, "post").mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveRefresh = resolve;
        }) as never,
    );

    const flights = [refreshAccessToken(), refreshAccessToken(), refreshAccessToken()];
    resolveRefresh({ data: { access_token: "fresh" } });
    const results = await Promise.all(flights);

    // Three rotations would trip the server's token-reuse detection and revoke the
    // whole family, logging the user out for loading a page with parallel requests.
    expect(post).toHaveBeenCalledTimes(1);
    expect(results).toEqual(["fresh", "fresh", "fresh"]);
    expect(getAccessToken()).toBe("fresh");
  });

  it("allows a new refresh after the previous one settles", async () => {
    const post = vi
      .spyOn(axios, "post")
      .mockResolvedValue({ data: { access_token: "one" } } as never);

    await refreshAccessToken();
    post.mockResolvedValue({ data: { access_token: "two" } } as never);
    await refreshAccessToken();

    expect(post).toHaveBeenCalledTimes(2);
    expect(getAccessToken()).toBe("two");
  });

  it("returns null and clears the token when refresh fails", async () => {
    setAccessToken("stale");
    vi.spyOn(axios, "post").mockRejectedValue(new Error("expired"));

    expect(await refreshAccessToken()).toBeNull();
    expect(getAccessToken()).toBeNull();
  });

  it("does not leave a failed refresh cached", async () => {
    const post = vi.spyOn(axios, "post").mockRejectedValue(new Error("expired"));
    await refreshAccessToken();
    post.mockResolvedValue({ data: { access_token: "recovered" } } as never);

    expect(await refreshAccessToken()).toBe("recovered");
  });
});

describe("session restoration", () => {
  it("restores identity from the refresh response without a second API request", async () => {
    const user = authUser();
    vi.spyOn(axios, "post").mockResolvedValue({
      data: { access_token: "fresh", user },
    } as never);
    const get = vi.spyOn(axios, "get");

    await expect(restoreSession()).resolves.toEqual(user);
    expect(get).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe("fresh");
  });
});

describe("request interceptors", () => {
  function clientWithHandler(handler: (attempt: number) => unknown) {
    const client = axios.create({ baseURL: "http://api.test" });
    let attempt = 0;
    client.defaults.adapter = async (config) => {
      attempt += 1;
      const result = handler(attempt) as { status: number };
      if (result.status >= 400) {
        const error = new Error("request failed") as Error & { response?: unknown };
        error.response = { ...result, config };
        throw error;
      }
      return { ...result, data: { ok: true, seen: config.headers?.Authorization }, config } as never;
    };
    installAuthInterceptors(client);
    return client;
  }

  it("attaches the bearer token when one is held", async () => {
    setAccessToken("held-token");
    const client = clientWithHandler(() => ({ status: 200, headers: {}, statusText: "OK" }));

    const { data } = await client.get("/api/feed");
    expect(data.seen).toBe("Bearer held-token");
  });

  it("sends no Authorization header when signed out", async () => {
    const client = clientWithHandler(() => ({ status: 200, headers: {}, statusText: "OK" }));

    const { data } = await client.get("/api/feed");
    expect(data.seen).toBeUndefined();
  });

  it("refreshes once and retries the original request on 401", async () => {
    setAccessToken("expired-token");
    vi.spyOn(axios, "post").mockResolvedValue({ data: { access_token: "renewed" } } as never);

    const client = clientWithHandler((attempt) =>
      attempt === 1
        ? { status: 401, headers: {}, statusText: "Unauthorized" }
        : { status: 200, headers: {}, statusText: "OK" },
    );

    const { data } = await client.get("/api/feed");
    expect(data.seen).toBe("Bearer renewed");
  });

  it("gives up after one failed retry instead of looping", async () => {
    setAccessToken("expired-token");
    const post = vi
      .spyOn(axios, "post")
      .mockResolvedValue({ data: { access_token: "renewed" } } as never);

    // The server keeps rejecting even with a fresh token.
    const client = clientWithHandler(() => ({
      status: 401,
      headers: {},
      statusText: "Unauthorized",
    }));

    await expect(client.get("/api/feed")).rejects.toThrow();
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("does not try to refresh a failed refresh call", async () => {
    const post = vi.spyOn(axios, "post").mockResolvedValue({ data: {} } as never);
    const client = clientWithHandler(() => ({
      status: 401,
      headers: {},
      statusText: "Unauthorized",
    }));

    await expect(client.post("/api/auth/login", {})).rejects.toThrow();
    expect(post).not.toHaveBeenCalled();
  });
});
