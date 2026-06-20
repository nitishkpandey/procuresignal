import { create } from "zustand";
import { persist } from "zustand/middleware";

interface UserState {
  userId: string;
  setUserId: (id: string) => void;
}

export const useUserStore = create<UserState>()(
  persist(
    (set) => ({
      userId: "demo-user",
      setUserId: (id: string) => set({ userId: id || "demo-user" }),
    }),
    { name: "procuresignal-user" },
  ),
);
