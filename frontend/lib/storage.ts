import type { StateStorage } from "zustand/middleware";

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

export function getSafeLocalStorage(): StateStorage {
  if (typeof window === "undefined") {
    return memoryStorage;
  }

  try {
    const storage = window.localStorage;
    const probeKey = "__procuresignal_storage_probe__";
    storage.setItem(probeKey, "1");
    storage.removeItem(probeKey);
    return storage;
  } catch {
    return memoryStorage;
  }
}
