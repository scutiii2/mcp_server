import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { defineComponent, h, KeepAlive, nextTick, ref } from "vue";
import { useChatShortcuts, type ChatShortcutActions } from "./useChatShortcuts";

interface Spies extends ChatShortcutActions {
  canStop: Mock<() => boolean>;
  stop: Mock<() => void>;
  focusInput: Mock<() => void>;
  newChat: Mock<() => void>;
}

function actions(canStop = true): Spies {
  return {
    canStop: vi.fn<() => boolean>(() => canStop),
    stop: vi.fn<() => void>(),
    focusInput: vi.fn<() => void>(),
    newChat: vi.fn<() => void>(),
  };
}

function host(a: ChatShortcutActions) {
  return mount(
    defineComponent({
      setup() {
        useChatShortcuts(a);
        return () => h("div");
      },
    }),
  );
}

function press(init: KeyboardEventInit): KeyboardEvent {
  const event = new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init });
  window.dispatchEvent(event);
  return event;
}

let mounted: ReturnType<typeof host> | null = null;
afterEach(() => {
  mounted?.unmount();
  mounted = null;
  document.body.innerHTML = "";
});

describe("useChatShortcuts", () => {
  it("Esc stops a running answer", () => {
    const a = actions(true);
    mounted = host(a);

    const event = press({ key: "Escape" });

    expect(a.stop).toHaveBeenCalledOnce();
    expect(event.defaultPrevented).toBe(true);
  });

  it("Esc does nothing when no answer is running", () => {
    const a = actions(false);
    mounted = host(a);

    const event = press({ key: "Escape" });

    expect(a.stop).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
  });

  it("Esc with a modifier is left alone", () => {
    const a = actions(true);
    mounted = host(a);

    press({ key: "Escape", shiftKey: true });
    press({ key: "Escape", ctrlKey: true });

    expect(a.stop).not.toHaveBeenCalled();
  });

  it("Ctrl+K and Cmd+K focus the input, in either case", () => {
    const a = actions();
    mounted = host(a);

    const first = press({ key: "k", ctrlKey: true });
    press({ key: "K", metaKey: true });

    expect(a.focusInput).toHaveBeenCalledTimes(2);
    expect(first.defaultPrevented).toBe(true);
  });

  it("Ctrl+Shift+K is not Ctrl+K", () => {
    const a = actions();
    mounted = host(a);

    press({ key: "K", ctrlKey: true, shiftKey: true });

    expect(a.focusInput).not.toHaveBeenCalled();
  });

  it("Ctrl+Shift+O starts a new chat (by physical key, so Shift's letter case is moot)", () => {
    const a = actions();
    mounted = host(a);

    press({ key: "O", code: "KeyO", ctrlKey: true, shiftKey: true });
    press({ key: "o", code: "KeyO", ctrlKey: true }); // without Shift: not the shortcut

    expect(a.newChat).toHaveBeenCalledOnce();
  });

  it("skips a key something else already handled (a rename box's Esc)", () => {
    const a = actions(true);
    mounted = host(a);
    const input = document.createElement("input");
    input.addEventListener("keydown", (e) => e.preventDefault());
    document.body.appendChild(input);

    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));

    expect(a.stop).not.toHaveBeenCalled();
  });

  it("skips everything while a dialog is open", () => {
    const a = actions(true);
    mounted = host(a);
    const dialog = document.createElement("dialog");
    dialog.setAttribute("open", "");
    document.body.appendChild(dialog);

    press({ key: "Escape" });
    press({ key: "k", ctrlKey: true });

    expect(a.stop).not.toHaveBeenCalled();
    expect(a.focusInput).not.toHaveBeenCalled();
  });

  it("skips IME composition", () => {
    const a = actions(true);
    mounted = host(a);

    press({ key: "Escape", isComposing: true });

    expect(a.stop).not.toHaveBeenCalled();
  });

  it("stops listening once the page is unmounted", () => {
    const a = actions(true);
    const wrapper = host(a);

    wrapper.unmount();
    press({ key: "Escape" });

    expect(a.stop).not.toHaveBeenCalled();
  });

  it("listens only while the kept-alive page is active", async () => {
    const a = actions(true);
    const page = defineComponent({
      name: "Page",
      setup() {
        useChatShortcuts(a);
        return () => h("div");
      },
    });
    const shown = ref(true);
    mounted = mount(
      defineComponent({
        setup: () => () => h(KeepAlive, null, shown.value ? [h(page)] : [h("span")]),
      }),
    ) as unknown as ReturnType<typeof host>;

    press({ key: "Escape" });
    expect(a.stop).toHaveBeenCalledTimes(1);

    shown.value = false; // deactivated, not destroyed
    await nextTick();
    press({ key: "Escape" });
    expect(a.stop).toHaveBeenCalledTimes(1);

    shown.value = true; // activated again
    await nextTick();
    press({ key: "Escape" });
    expect(a.stop).toHaveBeenCalledTimes(2);
  });
});
