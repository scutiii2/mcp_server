import { beforeEach, describe, expect, it, vi } from "vitest";
import { useSidebarCollapse } from "./useSidebarCollapse";

const KEY = "ember_web.chatSidebarCollapsed";

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("useSidebarCollapse", () => {
  it("starts expanded when nothing was saved", () => {
    expect(useSidebarCollapse().collapsed.value).toBe(false);
  });

  it("starts collapsed when that was saved", () => {
    localStorage.setItem(KEY, "1");

    expect(useSidebarCollapse().collapsed.value).toBe(true);
  });

  it("ignores a saved value it does not know", () => {
    localStorage.setItem(KEY, "maybe");

    expect(useSidebarCollapse().collapsed.value).toBe(false);
  });

  it("toggles and remembers the choice for the next visit", () => {
    const first = useSidebarCollapse();

    first.toggle();
    expect(first.collapsed.value).toBe(true);
    expect(useSidebarCollapse().collapsed.value).toBe(true);

    first.toggle();
    expect(first.collapsed.value).toBe(false);
    expect(useSidebarCollapse().collapsed.value).toBe(false);
  });

  it("still works when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    const sidebar = useSidebarCollapse();
    expect(sidebar.collapsed.value).toBe(false);
    sidebar.toggle();

    expect(sidebar.collapsed.value).toBe(true);
  });
});
