import { create } from 'zustand';

const readTheme = () => {
  try {
    const dark = localStorage.getItem('fdr-theme') === 'dark';
    if (dark) document.documentElement.classList.add('dark');
    return dark;
  } catch { return false; }
};

export const useUiStore = create(set => ({
  sidebarOpen: true,
  darkMode: readTheme(),
  filters: {},
  toggleSidebar: () => set(state => ({ sidebarOpen: !state.sidebarOpen })),
  setFilters: filters => set({ filters }),
  toggleDarkMode: () => set(state => {
    const darkMode = !state.darkMode;
    try { localStorage.setItem('fdr-theme', darkMode ? 'dark' : 'light'); } catch { /* storage may be disabled */ }
    document.documentElement.classList.toggle('dark', darkMode);
    return { darkMode };
  }),
}));
