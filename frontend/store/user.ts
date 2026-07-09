import { create } from "zustand";
import { persist } from "zustand/middleware";

interface UserState {
  userId: string;
  setUserId: (id: string) => void;
  clearUser: () => void;
}

export const useUserStore = create<UserState>()(
  persist(
    (set) => ({
      userId: "",
      setUserId: (id: string) => set({ userId: id.trim().toLowerCase() }),
      clearUser: () => set({ userId: "" }),
    }),
    { name: "procuresignal-user" },
  ),
);
