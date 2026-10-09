import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCompletionNotifications, notifyCompletion, requestCompletionPermission } from "./useCompletionNotify";

const created: FakeNotification[] = [];
class FakeNotification {
  static permission: NotificationPermission = "granted";
  static requestPermission = vi.fn(async (): Promise<NotificationPermission> => "granted");
  onclick: (() => void) | null = null;
  onclose: (() => void) | null = null;
  close = vi.fn();
  title: string;
  options: NotificationOptions;
  constructor(title: string, options: NotificationOptions) {
    this.title = title;
    this.options = options;
    created.push(this);
  }
}
function away(hidden = true, focused = false) {
  Object.defineProperty(document, "hidden", { configurable: true, value: hidden });
  vi.spyOn(document, "hasFocus").mockReturnValue(focused);
}
beforeEach(() => {
  document.title = "Ember";
  created.length = 0;
  vi.clearAllMocks();
  FakeNotification.permission = "granted";
  vi.stubGlobal("Notification", FakeNotification);
  away();
});
afterEach(() => {
  clearCompletionNotifications();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  Object.defineProperty(document, "hidden", { configurable: true, value: false });
});
describe("completion alerts", () => {
  it("counts answers in the tab title and restores it on returning", () => {
    notifyCompletion("c1", false, vi.fn());
    notifyCompletion("c2", false, vi.fn());
    expect(document.title).toBe("(2) Answer ready · Ember");
    expect(created).toHaveLength(0);
    away(false, true);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(document.title).toBe("Ember");
  });
  it("stays quiet when the page is visible and focused", () => {
    away(false, true);
    notifyCompletion("c1", true, vi.fn());
    expect(document.title).toBe("Ember");
    expect(created).toHaveLength(0);
  });
  it("opens the chat on click with generic notification text and no extra sound", () => {
    away(false, false);
    const open = vi.fn();
    const focus = vi.spyOn(window, "focus").mockImplementation(() => {});
    notifyCompletion("c1", true, open);
    expect(created[0]!.title).toBe("Ember: answer ready");
    expect(created[0]!.options).toEqual({ body: "Your answer is ready. Click to open the chat.", tag: "ember-answer-c1", silent: true });
    created[0]!.onclick!();
    expect(open).toHaveBeenCalledOnce();
    expect(focus).toHaveBeenCalledOnce();
    expect(created[0]!.close).toHaveBeenCalledOnce();
  });
  it.each(["denied", "default"] as const)("keeps the tab indicator when permission is %s without asking", permission => {
    FakeNotification.permission = permission;
    notifyCompletion("c1", true, vi.fn());
    expect(document.title).toContain("Answer ready");
    expect(created).toHaveLength(0);
    expect(FakeNotification.requestPermission).not.toHaveBeenCalled();
  });
  it("handles unsupported browsers and mobile constructors without losing the indicator", () => {
    vi.stubGlobal("Notification", undefined);
    expect(() => notifyCompletion("c1", true, vi.fn())).not.toThrow();
    vi.stubGlobal("Notification", class { static permission = "granted"; constructor() { throw new Error("unsupported"); } });
    expect(() => notifyCompletion("c2", true, vi.fn())).not.toThrow();
    expect(document.title).toBe("(2) Answer ready · Ember");
  });
  it("closes alerts and resets the count when the account changes", () => {
    notifyCompletion("c1", true, vi.fn());
    clearCompletionNotifications();
    expect(created[0]!.close).toHaveBeenCalledOnce();
    expect(document.title).toBe("Ember");
    notifyCompletion("c2", false, vi.fn());
    expect(document.title).toBe("(1) Answer ready · Ember");
  });
});
describe("permission from the settings interaction", () => {
  it("requests undecided permission", async () => {
    FakeNotification.permission = "default";
    expect(await requestCompletionPermission()).toBe("");
    expect(FakeNotification.requestPermission).toHaveBeenCalledOnce();
  });
  it("explains a denial without requesting again", async () => {
    FakeNotification.permission = "denied";
    expect(await requestCompletionPermission()).toContain("site settings");
    expect(FakeNotification.requestPermission).not.toHaveBeenCalled();
  });
  it("explains unsupported browsers", async () => {
    vi.stubGlobal("Notification", undefined);
    expect(await requestCompletionPermission()).toContain("does not support");
  });
  it("handles dismissed prompts and permission errors", async () => {
    FakeNotification.permission = "default";
    FakeNotification.requestPermission.mockResolvedValueOnce("default");
    expect(await requestCompletionPermission()).toContain("not granted");
    FakeNotification.requestPermission.mockRejectedValueOnce(new Error("blocked"));
    expect(await requestCompletionPermission()).toContain("HTTPS");
  });
});
