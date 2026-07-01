import { create } from "zustand";
import { persist } from "zustand/middleware";

interface ReadState {
  ids: number[];
  markRead: (id: number) => void;
}

// Tracks which article ids the user has opened, persisted to localStorage so
// read/unread survives reloads. Purely client-side presentation state.
export const useReadStore = create<ReadState>()(
  persist(
    (set, get) => ({
      ids: [],
      markRead: (id: number) =>
        set(get().ids.includes(id) ? {} : { ids: [...get().ids, id] }),
    }),
    { name: "procuresignal-read" },
  ),
);
