"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  APP_THEME_STORAGE_KEY,
  DEFAULT_APP_THEME,
  isAppTheme,
  type AppTheme,
} from "@/lib/app-theme";

type AppThemeContextValue = {
  theme: AppTheme;
  setTheme: (theme: AppTheme) => void;
};

const AppThemeContext = createContext<AppThemeContextValue | null>(null);

function applyTheme(theme: AppTheme) {
  document.body.dataset.theme = theme;
  document.body.dataset.colorScheme = "dark";
}

export function AppThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<AppTheme>(DEFAULT_APP_THEME);

  const setTheme = useCallback((nextTheme: AppTheme) => {
    setThemeState(nextTheme);
    applyTheme(nextTheme);
    window.localStorage.setItem(APP_THEME_STORAGE_KEY, nextTheme);
  }, []);

  useEffect(() => {
    const storedTheme = window.localStorage.getItem(APP_THEME_STORAGE_KEY);
    const initialTheme = isAppTheme(storedTheme) ? storedTheme : DEFAULT_APP_THEME;
    setThemeState(initialTheme);
    applyTheme(initialTheme);

    function syncTheme(event: StorageEvent) {
      if (event.key !== APP_THEME_STORAGE_KEY || !isAppTheme(event.newValue)) return;
      setThemeState(event.newValue);
      applyTheme(event.newValue);
    }

    window.addEventListener("storage", syncTheme);
    return () => window.removeEventListener("storage", syncTheme);
  }, []);

  const value = useMemo(() => ({ theme, setTheme }), [setTheme, theme]);
  return <AppThemeContext.Provider value={value}>{children}</AppThemeContext.Provider>;
}

export function useAppTheme() {
  const context = useContext(AppThemeContext);
  if (!context) throw new Error("useAppTheme must be used inside AppThemeProvider");
  return context;
}
