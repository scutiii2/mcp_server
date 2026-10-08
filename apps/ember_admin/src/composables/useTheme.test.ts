import { beforeEach, describe, expect, it, vi } from "vitest";

const KEY = "ember_admin.theme";

// The theme lives in module state, so each test loads a fresh copy.
async function load() {
  vi.resetModules();
  return import("./useTheme");
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.style.colorScheme = "";
});

describe("useTheme", () => {
  it("follows the system when nothing was saved", async () => {
    const { initTheme, useTheme } = await load();

    initTheme();

    expect(useTheme().theme.value).toBe("system");
    expect(document.documentElement.style.colorScheme).toBe("light dark");
  });

  it("applies a saved theme before the app mounts", async () => {
    localStorage.setItem(KEY, "dark");
    const { initTheme, useTheme } = await load();

    initTheme();

    expect(useTheme().theme.value).toBe("dark");
    expect(document.documentElement.style.colorScheme).toBe("dark");
  });

  it("ignores a saved value that is not a theme", async () => {
    localStorage.setItem(KEY, "purple");
    const { initTheme, useTheme } = await load();

    initTheme();

    expect(useTheme().theme.value).toBe("system");
  });

  it("cycles system, light, dark and back, saving each step", async () => {
    const { initTheme, useTheme } = await load();
    initTheme();
    const { theme, next, cycle } = useTheme();

    const seen: string[] = [];
    for (let i = 0; i < 4; i += 1) {
      expect(next()).toBe(["light", "dark", "system", "light"][i]);
      cycle();
      seen.push(`${theme.value}:${document.documentElement.style.colorScheme}:${localStorage.getItem(KEY)}`);
    }

    expect(seen).toEqual(["light:light:light", "dark:dark:dark", "system:light dark:system", "light:light:light"]);
  });

  it("sets a chosen theme directly, saving it, and DEFAULT_THEME is the system", async () => {
    const { initTheme, useTheme, DEFAULT_THEME } = await load();
    initTheme();
    const { theme, setTheme } = useTheme();

    setTheme("dark");

    expect(theme.value).toBe("dark");
    expect(document.documentElement.style.colorScheme).toBe("dark");
    expect(localStorage.getItem(KEY)).toBe("dark");
    setTheme(DEFAULT_THEME);
    expect(theme.value).toBe("system");
    expect(document.documentElement.style.colorScheme).toBe("light dark");
  });

  it("still works when storage is blocked", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const { initTheme, useTheme } = await load();

    expect(() => initTheme()).not.toThrow();
    const { theme, cycle } = useTheme();
    expect(() => cycle()).not.toThrow();

    expect(theme.value).toBe("light");
    expect(document.documentElement.style.colorScheme).toBe("light");
  });
});
