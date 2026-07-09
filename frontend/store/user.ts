import { create } from "zustand";
import { createJSONStorage, persist, type StateStorage } from "zustand/middleware";

interface UserState {
  userId: string;
  setUserId: (id: string) => void;
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
      setUserId: (id: string) => set({ userId: id.trim().toLowerCase() }),
      clearUser: () => set({ userId: "" }),
    }),
    {
      name: "procuresignal-user",
      storage: createJSONStorage(getSessionStorage),
    },
  ),
);
