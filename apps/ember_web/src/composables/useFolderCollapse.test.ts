import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import { useAuthStore } from "../stores/auth";
import { useFolderCollapse } from "./useFolderCollapse";

const account = (id: number) => ({ id, username: "u", email: "u@example.com", email_verified: true, roles: [], permissions: ["chat.use"] });

beforeEach(() => {
  localStorage.clear();
  setActivePinia(createPinia());
  useAuthStore().account = account(1);
});

describe("useFolderCollapse", () => {
  it("starts with every folder open", () => {
    const { isCollapsed } = useFolderCollapse();

    expect(isCollapsed(5)).toBe(false);
  });

  it("toggles a folder and remembers it for the next visit", () => {
    const first = useFolderCollapse();
    first.toggle(5);
    expect(first.isCollapsed(5)).toBe(true);

    expect(useFolderCollapse().isCollapsed(5)).toBe(true);
    first.toggle(5);
    expect(useFolderCollapse().isCollapsed(5)).toBe(false);
  });

  it("keeps each account's choices apart", () => {
    useFolderCollapse().toggle(5);

    useAuthStore().account = account(2);

    expect(useFolderCollapse().isCollapsed(5)).toBe(false);
  });

  it("ignores damaged storage", () => {
    localStorage.setItem("ember_web.collapsedFolders.1", "not json");

    expect(useFolderCollapse().isCollapsed(5)).toBe(false);
  });

  it("still works in memory when storage is blocked", () => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = () => {
      throw new Error("blocked");
    };
    try {
      const { toggle, isCollapsed } = useFolderCollapse();
      toggle(5);
      expect(isCollapsed(5)).toBe(true);
    } finally {
      Storage.prototype.setItem = original;
    }
  });
});
