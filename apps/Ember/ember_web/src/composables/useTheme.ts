import { ref } from "vue";

export type Theme = "system" | "light" | "dark";

const STORAGE_KEY = "ember_web.theme";
// Order the toggle cycles through.
const CYCLE: readonly Theme[] = ["system", "light", "dark"];

function isTheme(value: unknown): value is Theme {
  return typeof value === "string" && (CYCLE as readonly string[]).includes(value);
}

// Per-browser convenience (the login page is themed too): blocked storage
// just means "system".
function readStored(): Theme {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return isTheme(value) ? value : "system";
  } catch {
    return "system";
  }
}

function writeStored(theme: Theme): void {
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // ignore - see readStored
  }
}

/** The colors are `light-dark()` tokens (style.css), so the theme is only the
 * page's `color-scheme`: "light dark" follows the system setting. */
function apply(theme: Theme): void {
  document.documentElement.style.colorScheme = theme === "system" ? "light dark" : theme;
}

const theme = ref<Theme>("system");

/** Applies the saved theme; call once before the app mounts. */
export function initTheme(): void {
  theme.value = readStored();
  apply(theme.value);
}

/** The theme every new visitor gets: follow the system. */
export const DEFAULT_THEME: Theme = "system";

/** The current theme, a way to step to the next (system, light, dark) and one to pick it. */
export function useTheme(): {
  theme: typeof theme;
  next: () => Theme;
  cycle: () => void;
  setTheme: (value: Theme) => void;
} {
  const next = (): Theme => CYCLE[(CYCLE.indexOf(theme.value) + 1) % CYCLE.length]!;
  function setTheme(value: Theme): void {
    theme.value = value;
    apply(value);
    writeStored(value);
  }
  function cycle(): void {
    setTheme(next());
  }
  return { theme, next, cycle, setTheme };
}
