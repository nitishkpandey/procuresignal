import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import { normalizeLanguage, type LanguageCode } from "@/lib/i18n";
import { getSafeLocalStorage } from "@/lib/storage";
import type { AuthUser } from "@/lib/types";

interface UserState {
  user: AuthUser | null;
  platformLanguage: LanguageCode;
  setUser: (user: AuthUser | null) => void;
  setPlatformLanguage: (language: string) => void;
  clearUser: () => void;
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
      storage: createJSONStorage(getSafeLocalStorage),
      // Only the language preference is persisted. Identity is not: it comes from
      // /api/auth/me on load, so a stale local copy can never outlive the session
      // or claim an account the server has since disabled.
      partialize: (state) => ({ platformLanguage: state.platformLanguage }),
    },
  ),
);
