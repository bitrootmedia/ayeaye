import { useCallback, useEffect, useState } from "react";

// Deliberately brand-free: putting the product name in a storage key means
// every saved preference silently resets the day the brand changes.
const KEY = "ui-theme";

type Theme = "light" | "dark";

/**
 * Apply the saved theme before anything renders.
 *
 * `useTheme` only runs inside the signed-in shell, so without this the auth
 * screens are always light — someone who works in dark mode signs out and gets
 * a full-brightness page in the face. Called once from main.tsx, before React
 * mounts, so there is no flash of the wrong theme either.
 */
export function applyStoredTheme(): void {
  try {
    document.documentElement.classList.toggle("dark", preferred() === "dark");
  } catch {
    // Storage unavailable (private browsing). Light is a fine fallback.
  }
}

function preferred(): Theme {
  const saved = localStorage.getItem(KEY);
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Toggles the `.dark` class the theme tokens key off. Persisted, because an
 *  operator who dims the console once shouldn't have to do it again. */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(preferred);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem(KEY, theme);
  }, [theme]);

  const toggle = useCallback(
    () => setTheme((t) => (t === "dark" ? "light" : "dark")),
    [],
  );

  return { theme, toggle };
}
