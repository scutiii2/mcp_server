import { mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import type { MenuItem } from "../utils/chatMenu";
import PopupMenu from "./PopupMenu.vue";

const ITEMS: MenuItem[] = [
  { id: "pin", label: "Pin" },
  {
    id: "move",
    label: "Move to...",
    children: [
      { id: "move:none", label: "No folder", checked: false },
      { id: "move:1", label: "Work", checked: true },
    ],
  },
  { id: "sep", label: "", separator: true },
  { id: "off", label: "Off", disabled: true },
  { id: "delete", label: "Delete", danger: true },
];

let wrapper: VueWrapper | null = null;

function open(items: MenuItem[] = ITEMS) {
  wrapper = mount(PopupMenu, { props: { items, x: 40, y: 60, label: "Chat actions" }, attachTo: document.body });
  return wrapper;
}

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
});

const q = (selector: string) => document.body.querySelector<HTMLElement>(selector);
const all = (selector: string) => [...document.body.querySelectorAll<HTMLElement>(selector)];
// The text of the focused menu item, or "" when focus is not on one. Reading
// `document.activeElement.textContent` directly would pass by accident when
// focus falls to <body>, whose text holds every label.
const focused = () => {
  const el = document.activeElement;
  return el instanceof HTMLElement && el.matches("[role^='menuitem']") ? (el.textContent ?? "") : "";
};
const key = (el: Element | null, name: string) => {
  el?.dispatchEvent(new KeyboardEvent("keydown", { key: name, bubbles: true }));
  return nextTick();
};

describe("PopupMenu", () => {
  it("renders the items in the page body, at the given place, with a label", () => {
    open();

    expect(q('[role="menu"]')!.parentElement).toBe(document.body); // teleported, not inside the mount container
    expect(q('[role="menu"]')?.getAttribute("aria-label")).toBe("Chat actions");
    expect(all('[role="menuitem"]').map((b) => b.textContent?.replace("›", "").trim())).toEqual([
      "Pin",
      "Move to...",
      "Off",
      "Delete",
    ]);
    expect(q('[role="menu"]')?.style.left).toBe("40px");
    expect(q('[role="menu"]')?.style.top).toBe("60px");
  });

  it("selects an item by click and reports its id", async () => {
    const w = open();

    q('[role="menuitem"]')!.click();

    expect(w.emitted("select")).toEqual([["pin"]]);
  });

  it("does not select a disabled item", () => {
    const w = open();

    all('[role="menuitem"]').find((b) => b.textContent?.includes("Off"))!.click();

    expect(w.emitted("select")).toBeUndefined();
  });

  it("marks a dangerous item", () => {
    open();

    expect(all('[role="menuitem"]').find((b) => b.textContent?.includes("Delete"))?.classList.contains("danger")).toBe(true);
  });

  it("focuses the first enabled item when it opens", async () => {
    open();
    await nextTick();

    expect(focused()).toContain("Pin");
  });

  it("moves focus with the arrow keys, skipping disabled items, and wraps", async () => {
    open();
    await nextTick();
    const menu = q('[role="menu"]');

    await key(menu, "ArrowDown");
    expect(focused()).toContain("Move to...");
    await key(menu, "ArrowDown");
    expect(focused()).toContain("Delete"); // "Off" is skipped
    await key(menu, "ArrowDown");
    expect(focused()).toContain("Pin");
    await key(menu, "ArrowUp");
    expect(focused()).toContain("Delete");
  });

  it("Home and End jump to the first and last item", async () => {
    open();
    await nextTick();
    const menu = q('[role="menu"]');

    await key(menu, "End");
    expect(focused()).toContain("Delete");
    await key(menu, "Home");
    expect(focused()).toContain("Pin");
  });

  it("Enter activates the focused item", async () => {
    const w = open();
    await nextTick();

    (document.activeElement as HTMLElement).click(); // Enter on a button is a click

    expect(w.emitted("select")).toEqual([["pin"]]);
  });

  it("opens the flyout on click, shows the current choice, and selects a child", async () => {
    const w = open();

    all('[role="menuitem"]').find((b) => b.textContent?.includes("Move to..."))!.click();
    await nextTick();
    const radios = all('[role="menuitemradio"]');

    expect(radios.map((r) => [r.textContent?.replace("✓", "").trim(), r.getAttribute("aria-checked")])).toEqual([
      ["No folder", "false"],
      ["Work", "true"],
    ]);
    radios[1]!.click();
    expect(w.emitted("select")).toEqual([["move:1"]]);
  });

  describe("flyout placement", () => {
    const mockRects = (flyoutTop: number, flyoutHeight: number, innerHeight: number) => {
      vi.stubGlobal("innerHeight", innerHeight);
      vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
        const isFlyout = this.classList.contains("flyout");
        const top = isFlyout ? flyoutTop : 0;
        const height = isFlyout ? flyoutHeight : 100;
        return { top, bottom: top + height, left: 0, right: 200, width: 200, height, x: 0, y: top, toJSON() {} } as DOMRect;
      });
    };
    afterEach(() => {
      vi.unstubAllGlobals();
      vi.restoreAllMocks();
    });
    const openMove = async () => {
      all('[role="menuitem"]').find((b) => b.textContent?.includes("Move to..."))!.click();
      await nextTick();
      await nextTick();
    };

    it("shifts a flyout that would leave the window up, and caps its height", async () => {
      mockRects(700, 300, 800);
      open();
      await openMove();

      // bottom 1000 must land at 800 - 8: shifted up by 208
      expect(q(".flyout")!.style.top).toBe("-208px");
      // the cap is the height it was measured at, so it cannot grow after the shift
      expect(q(".flyout")!.style.maxHeight).toBe("300px");
    });

    it("keeps the height the browser gave it (the 60vh CSS cap), never the whole window", async () => {
      // 30 folders: taller than the window, but the stylesheet caps the flyout at 60vh = 480px.
      // The shift is worked out from those 480px, so the inline cap must stay 480px: lifting it
      // to the window height would let the list grow past the bottom edge again.
      mockRects(700, 480, 800);
      open();
      await openMove();

      expect(q(".flyout")!.style.maxHeight).toBe("480px");
      expect(q(".flyout")!.style.top).toBe("-388px"); // bottom 1180 lands at 792
    });

    it("never lifts a tall flyout above the top margin", async () => {
      mockRects(500, 900, 800);
      open();
      await openMove();

      // capped to 784px, its top is placed 8px from the window top: 8 - 500
      expect(q(".flyout")!.style.top).toBe("-492px");
    });

    it("leaves a flyout that fits where it is", async () => {
      mockRects(100, 120, 800);
      open();
      await openMove();

      expect(q(".flyout")!.style.top).toBe("");
    });
  });

  it("ArrowRight opens the flyout and focuses its first item; ArrowLeft closes it", async () => {
    open();
    await nextTick();
    const menu = q('[role="menu"]');
    await key(menu, "ArrowDown"); // on Move to...

    await key(document.activeElement, "ArrowRight");
    await nextTick();
    expect(focused()).toContain("No folder");

    await key(document.activeElement, "ArrowLeft");
    await nextTick();
    expect(all('[role="menuitemradio"]')).toHaveLength(0);
    expect(focused()).toContain("Move to...");
  });

  it("Esc closes the flyout first, then the menu", async () => {
    const w = open();
    await nextTick();
    all('[role="menuitem"]').find((b) => b.textContent?.includes("Move to..."))!.click();
    await nextTick();

    await key(document.activeElement, "Escape");
    await nextTick();
    expect(all('[role="menuitemradio"]')).toHaveLength(0);
    expect(w.emitted("close")).toBeUndefined();
    expect(focused()).toContain("Move to...");

    await key(document.activeElement, "Escape");
    expect(w.emitted("close")).toHaveLength(1);
  });

  it("closes on a press outside, but not on a press inside", () => {
    const w = open();

    q('[role="menu"]')!.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    expect(w.emitted("close")).toBeUndefined();

    document.body.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    expect(w.emitted("close")).toHaveLength(1);
  });

  it("closes on Tab", async () => {
    const w = open();
    await nextTick();

    await key(q('[role="menu"]'), "Tab");

    expect(w.emitted("close")).toHaveLength(1);
  });

  it("hover opens one flyout at a time and moves focus with the pointer", async () => {
    open([
      { id: "a", label: "A", children: [{ id: "a:1", label: "A1" }] },
      { id: "b", label: "B", children: [{ id: "b:1", label: "B1" }] },
      { id: "c", label: "C" },
    ]);
    await nextTick();
    const hover = (label: string) => {
      all('[role="menuitem"]').find((b) => b.textContent?.includes(label))!.dispatchEvent(new MouseEvent("mouseenter"));
      return nextTick();
    };

    await hover("A");
    expect(all('[role="menuitemradio"]').map((r) => r.textContent?.trim())).toEqual(["A1"]);
    await hover("B");
    expect(all('[role="menuitemradio"]').map((r) => r.textContent?.trim())).toEqual(["B1"]);
    expect(all(".flyout")).toHaveLength(1);
    expect(focused()).toContain("B");
    await hover("C");
    expect(all(".flyout")).toHaveLength(0);
    expect(focused()).toContain("C");
  });

  it("hovering a disabled item while focus is in the flyout closes it and keeps focus in the menu", async () => {
    open();
    await nextTick();
    await key(q('[role="menu"]'), "ArrowDown"); // on Move to...
    await key(document.activeElement, "ArrowRight");
    await nextTick();
    expect(focused()).toContain("No folder");

    all('[role="menuitem"]').find((b) => b.textContent?.includes("Off"))!.dispatchEvent(new MouseEvent("mouseenter"));
    await nextTick();

    expect(all(".flyout")).toHaveLength(0);
    expect(focused()).toContain("Move to...");
    await key(document.activeElement, "ArrowDown");
    expect(focused()).toContain("Delete");
  });

  it("ArrowUp from the menu itself (no item focused) lands on the last enabled item", async () => {
    open();
    await nextTick();
    const menu = q('[role="menu"]')!;
    menu.focus(); // the menu box is focusable (tabindex -1), e.g. after a press on its padding
    expect(document.activeElement).toBe(menu);

    await key(menu, "ArrowUp");

    expect(focused()).toContain("Delete");
  });

  it("a hover-opened flyout closes when the arrow keys move to another main item", async () => {
    open();
    await nextTick();
    all('[role="menuitem"]').find((b) => b.textContent?.includes("Move to..."))!.dispatchEvent(new MouseEvent("mouseenter"));
    await nextTick();
    expect(all(".flyout")).toHaveLength(1);

    await key(document.activeElement, "ArrowDown");

    expect(focused()).toContain("Delete");
    expect(all(".flyout")).toHaveLength(0);
    expect(q('[data-id="move"]')?.getAttribute("aria-expanded")).toBe("false");
  });

  it("removes its document and window listeners when it goes away", () => {
    // Spies, not events: Vue drops an emit from an unmounted component, so a
    // leaked listener would not show up as a `close`.
    const docAdd = vi.spyOn(document, "addEventListener");
    const docRemove = vi.spyOn(document, "removeEventListener");
    const winAdd = vi.spyOn(window, "addEventListener");
    const winRemove = vi.spyOn(window, "removeEventListener");
    try {
      const w = open();
      const pointer = docAdd.mock.calls.find(([type]) => type === "pointerdown")?.[1];
      const resize = winAdd.mock.calls.find(([type]) => type === "resize")?.[1];
      expect(pointer).toBeTypeOf("function");
      expect(resize).toBeTypeOf("function");

      w.unmount();
      wrapper = null;

      expect(docRemove).toHaveBeenCalledWith("pointerdown", pointer);
      expect(winRemove).toHaveBeenCalledWith("resize", resize);
    } finally {
      vi.restoreAllMocks();
    }
  });

  it("closes on a window resize", () => {
    const w = open();

    window.dispatchEvent(new Event("resize"));

    expect(w.emitted("close")).toHaveLength(1);
  });

  it("does not open the flyout of a disabled parent", () => {
    open([{ id: "move", label: "Move to...", disabled: true, children: [{ id: "x", label: "X" }] }]);

    q('[role="menuitem"]')!.click();

    expect(all('[role="menuitemradio"]')).toHaveLength(0);
  });
});
