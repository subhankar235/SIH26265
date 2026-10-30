import { create } from 'zustand';

export const useAuthStore = create((set) => ({
  user: null,
  status: 'loading',
  setUser: (user) => set({ user, status: 'authenticated' }),
  setRestoreUnavailable: () => set({ user: null, status: 'unavailable' }),
  clearSession: () => set({ user: null, status: 'anonymous' }),
}));
