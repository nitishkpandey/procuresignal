import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from "axios";

import type { AuthUser } from "@/lib/types";

export function authBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}

/**
 * The access token lives here and nowhere else.
 *
 * Not in localStorage or sessionStorage: both are readable by any script that manages
 * to run on the page, which turns one XSS into a stolen session. A module variable
 * dies with the tab, and the httpOnly refresh cookie is what survives a reload.
 */
let accessToken: string | null = null;

/** One shared refresh, so parallel 401s do not each rotate the token. */
let inFlightRefresh: Promise<string | null> | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function clearAccessToken(): void {
  accessToken = null;
}

/** Test seam: forget any in-flight refresh between cases. */
export function __resetRefreshState(): void {
  inFlightRefresh = null;
}

function isAuthEndpoint(url: string | undefined): boolean {
  return Boolean(url && url.includes("/api/auth/"));
}

/**
 * Exchange the refresh cookie for a new access token.
 *
 * Concurrent callers share one request. Rotating three times because a page fired
 * three parallel requests would look like a replayed token to the server, which
 * revokes the entire family and signs the user out for behaving normally.
 */
export function refreshAccessToken(): Promise<string | null> {
  if (inFlightRefresh) return inFlightRefresh;

  inFlightRefresh = axios
    .post(`${authBaseUrl()}/api/auth/refresh`, null, { withCredentials: true })
    .then((response) => {
      const token = (response?.data as { access_token?: string })?.access_token ?? null;
      setAccessToken(token);
      return token;
    })
    .catch(() => {
      clearAccessToken();
      return null;
    })
    .finally(() => {
      // Cleared either way: a cached rejection would make every later attempt fail.
      inFlightRefresh = null;
    });

  return inFlightRefresh;
}

type RetriedConfig = InternalAxiosRequestConfig & { _retriedAfterRefresh?: boolean };

export function installAuthInterceptors(client: AxiosInstance): void {
  client.interceptors.request.use((config) => {
    if (accessToken) {
      config.headers.Authorization = `Bearer ${accessToken}`;
    }
    return config;
  });

  client.interceptors.response.use(
    (response) => response,
    async (error) => {
      const config = error?.response?.config as RetriedConfig | undefined;
      const status = error?.response?.status;

      // Retry once. Without the flag a server that keeps returning 401 would drive an
      // endless refresh-and-retry loop. Auth endpoints are skipped so a failed login
      // does not attempt to refresh its way in.
      if (status !== 401 || !config || config._retriedAfterRefresh || isAuthEndpoint(config.url)) {
        return Promise.reject(error);
      }

      config._retriedAfterRefresh = true;
      const token = await refreshAccessToken();
      if (!token) return Promise.reject(error);

      config.headers.Authorization = `Bearer ${token}`;
      return client.request(config);
    },
  );
}

interface SessionResponse {
  access_token: string;
  user: AuthUser;
}

async function startSession(path: string, body: Record<string, unknown>): Promise<AuthUser> {
  const { data } = await axios.post<SessionResponse>(`${authBaseUrl()}${path}`, body, {
    withCredentials: true,
  });
  setAccessToken(data.access_token);
  return data.user;
}

export function login(email: string, password: string): Promise<AuthUser> {
  return startSession("/api/auth/login", { email, password });
}

export function register(
  email: string,
  password: string,
  fullName?: string,
): Promise<AuthUser> {
  return startSession("/api/auth/register", {
    email,
    password,
    full_name: fullName || undefined,
  });
}

export async function logout(): Promise<void> {
  try {
    await axios.post(`${authBaseUrl()}/api/auth/logout`, null, { withCredentials: true });
  } finally {
    // Local state is cleared even if the server call fails, so the UI never shows a
    // signed-in shell for a session the user has asked to end.
    clearAccessToken();
  }
}

/**
 * Restore a session on page load.
 *
 * The access token is gone after a reload, so this refreshes first and then asks who
 * the caller is. Returns null when there is no usable session.
 */
export async function restoreSession(): Promise<AuthUser | null> {
  const token = await refreshAccessToken();
  if (!token) return null;

  try {
    const { data } = await axios.get<AuthUser>(`${authBaseUrl()}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
      withCredentials: true,
    });
    return data;
  } catch {
    clearAccessToken();
    return null;
  }
}
