import { create } from "zustand";
import { createJSONStorage, persist, type StateStorage } from "zustand/middleware";

import { normalizeLanguage, type LanguageCode } from "@/lib/i18n";
import type { AuthUser } from "@/lib/types";

interface UserState {
  user: AuthUser | null;
  platformLanguage: LanguageCode;
  setUser: (user: AuthUser | null) => void;
  setPlatformLanguage: (language: string) => void;
  clearUser: () => void;
}

const memoryValues = new Map<string, string>();

const memoryStorage: StateStorage = {
  getItem: (name) => memoryValues.get(name) ?? null,
  setItem: (name, value) => {
    memoryValues.set(name, value);
  },
  removeItem: (name) => {
    memoryValues.delete(name);
  },
};

function getSessionStorage(): StateStorage {
  if (typeof window === "undefined") {
    return memoryStorage;
  }

  try {
    if (!window.localStorage) {
      return memoryStorage;
    }

    const probeKey = "__procuresignal_storage_probe__";
    window.localStorage.setItem(probeKey, "1");
    window.localStorage.removeItem(probeKey);
    return window.localStorage;
  } catch {
    return memoryStorage;
  }
}

export const useUserStore = create<UserState>()(
  persist(
    (set) => ({
      user: null,
      platformLanguage: "en",
      setUser: (user: AuthUser | null) => set({ user }),
      setPlatformLanguage: (language: string) =>
        set({ platformLanguage: normalizeLanguage(language) }),
      clearUser: () => set({ user: null, platformLanguage: "en" }),
    }),
    {
      name: "procuresignal-user",
      storage: createJSONStorage(getSessionStorage),
      // Only the language preference is persisted. Identity is not: it comes from
      // /api/auth/me on load, so a stale local copy can never outlive the session
      // or claim an account the server has since disabled.
      partialize: (state) => ({ platformLanguage: state.platformLanguage }),
    },
  ),
);
