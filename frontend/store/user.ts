import { create } from "zustand";
import { createJSONStorage, persist, type StateStorage } from "zustand/middleware";

import { normalizeLanguage, type LanguageCode } from "@/lib/i18n";

interface UserState {
  userId: string;
  platformLanguage: LanguageCode;
  setUserId: (id: string) => void;
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
      userId: "",
      platformLanguage: "en",
      setUserId: (id: string) => set({ userId: id.trim().toLowerCase() }),
      setPlatformLanguage: (language: string) =>
        set({ platformLanguage: normalizeLanguage(language) }),
      clearUser: () => set({ userId: "", platformLanguage: "en" }),
    }),
    {
      name: "procuresignal-user",
      storage: createJSONStorage(getSessionStorage),
    },
  ),
);
