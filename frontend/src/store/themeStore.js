/**
 * Theme store — dark mode toggle with localStorage persistence.
 */
import { create } from 'zustand';

const useThemeStore = create((set) => ({
  isDark: (() => {
    const stored = localStorage.getItem('nepse_theme');
    if (stored) return stored === 'dark';
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  })(),

  toggle: () => {
    set((s) => {
      const next = !s.isDark;
      localStorage.setItem('nepse_theme', next ? 'dark' : 'light');
      if (next) {
        document.documentElement.classList.add('dark');
      } else {
        document.documentElement.classList.remove('dark');
      }
      return { isDark: next };
    });
  },

  // Initialize on mount
  init: () => {
    const stored = localStorage.getItem('nepse_theme');
    const isDark = stored
      ? stored === 'dark'
      : window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (isDark) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  },
}));

export default useThemeStore;
