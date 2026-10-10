import { mount } from "@vue/test-utils";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import EmBar from "./EmBar.vue";
import EmButton from "./EmButton.vue";
import EmConfirm from "./EmConfirm.vue";
import EmDialog from "./EmDialog.vue";
import EmIcon from "./EmIcon.vue";
import EmMenuRow from "./EmMenuRow.vue";
import EmNotice from "./EmNotice.vue";
import EmPageHead from "./EmPageHead.vue";
import EmRing from "./EmRing.vue";
import EmSwitch from "./EmSwitch.vue";
import EmTabs from "./EmTabs.vue";
import EmTierBadge from "./EmTierBadge.vue";
import EmToast from "./EmToast.vue";
import { ICONS, type IconName } from "./icons";

// jsdom has no <dialog> methods.
beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

afterEach(() => {
  vi.useRealTimers();
});

describe("EmIcon", () => {
  it("draws every required icon as a decorative svg", () => {
    const required: IconName[] = ["play", "battle", "shop", "book", "reset", "heart", "flame", "feather", "shield", "sword", "arrow", "close"];
    for (const name of required) {
      const svg = mount(EmIcon, { props: { name } }).find("svg");
      expect(svg.attributes("aria-hidden")).toBe("true");
      expect(svg.find("path").attributes("d")).toBe(ICONS[name]);
    }
  });
});

describe("EmButton", () => {
  it("is a real button with a variant class, and does not click when disabled", async () => {
    const wrapper = mount(EmButton, { props: { variant: "primary" }, slots: { default: "Go" } });
    expect(wrapper.element.tagName).toBe("BUTTON");
    expect(wrapper.attributes("type")).toBe("button");
    expect(wrapper.classes()).toContain("primary");

    const off = mount(EmButton, { props: { disabled: true }, slots: { default: "Go" } });
    expect(off.attributes("disabled")).toBeDefined();
  });
});

describe("EmTabs", () => {
  const options = [
    { value: "a", label: "Collection" },
    { value: "b", label: "Battle", disabled: true },
    { value: "c", label: "Shop" },
  ];

  it("marks the selected tab and selects on click", async () => {
    const wrapper = mount(EmTabs, { props: { modelValue: "a", options, ariaLabel: "Sections" } });
    const tabs = wrapper.findAll("[role=tab]");
    expect(tabs.map((t) => t.attributes("aria-selected"))).toEqual(["true", "false", "false"]);

    await tabs[2]!.trigger("click");
    expect(wrapper.emitted("update:modelValue")).toEqual([["c"]]);
  });

  it("moves with the arrow keys, skipping a disabled tab", async () => {
    const wrapper = mount(EmTabs, { props: { modelValue: "a", options, ariaLabel: "Sections" } });
    await wrapper.findAll("[role=tab]")[0]!.trigger("keydown.right");
    expect(wrapper.emitted("update:modelValue")![0]).toEqual(["c"]);
    await wrapper.findAll("[role=tab]")[0]!.trigger("keydown.end");
    expect(wrapper.emitted("update:modelValue")![1]).toEqual(["c"]);
  });
});

describe("EmTierBadge", () => {
  it("writes the tier's name", () => {
    expect(mount(EmTierBadge, { props: { tierId: "unique" } }).text()).toBe("Unique");
  });
});

describe("EmBar", () => {
  it("is a progressbar with its value, and turns red below 30 percent for HP", () => {
    const xp = mount(EmBar, { props: { value: 40, max: 300, label: "XP" } });
    expect(xp.attributes("role")).toBe("progressbar");
    expect(xp.attributes("aria-valuenow")).toBe("40");
    expect(xp.attributes("aria-valuemax")).toBe("300");

    expect(mount(EmBar, { props: { value: 42, max: 180, label: "HP", kind: "hp" } }).classes()).toContain("low");
    expect(mount(EmBar, { props: { value: 100, max: 180, label: "HP", kind: "hp" } }).classes()).not.toContain("low");
  });
});

describe("EmRing", () => {
  it("shows the seconds left, and expires at zero", () => {
    const live = mount(EmRing, { props: { remaining: 3.2, total: 5 } });
    expect(live.text()).toBe("4s");
    expect(live.classes()).not.toContain("expired");

    const done = mount(EmRing, { props: { remaining: 0, total: 5 } });
    expect(done.text()).toBe("0s");
    expect(done.classes()).toContain("expired");
  });
});

describe("EmSwitch", () => {
  it("is a switch input with its label, and reports changes", async () => {
    const wrapper = mount(EmSwitch, { props: { modelValue: false, label: "Steadfast" } });
    const input = wrapper.find("input[role=switch]");
    expect(wrapper.text()).toContain("Steadfast");

    await input.setValue(true);
    expect(wrapper.emitted("update:modelValue")).toEqual([[true]]);
  });

  it("cannot be changed when disabled", () => {
    const wrapper = mount(EmSwitch, { props: { modelValue: false, label: "Patient", disabled: true } });
    expect((wrapper.find("input").element as HTMLInputElement).disabled).toBe(true);
  });
});

describe("EmToast", () => {
  it("announces politely and asks to close after the duration", async () => {
    vi.useFakeTimers();
    const wrapper = mount(EmToast, { props: { open: true, message: "Preset 1 saved.", duration: 4000 } });
    expect(wrapper.attributes("role")).toBe("status");
    expect(wrapper.text()).toContain("Preset 1 saved.");

    await vi.advanceTimersByTimeAsync(3999);
    expect(wrapper.emitted("close")).toBeUndefined();
    await vi.advanceTimersByTimeAsync(2);
    expect(wrapper.emitted("close")).toHaveLength(1);
  });

  it("waits while the pointer is on it", async () => {
    vi.useFakeTimers();
    const wrapper = mount(EmToast, { props: { open: true, message: "Saved", duration: 1000 } });
    await wrapper.find(".em-toast").trigger("mouseenter");
    await vi.advanceTimersByTimeAsync(5000);
    expect(wrapper.emitted("close")).toBeUndefined();

    await wrapper.find(".em-toast").trigger("mouseleave");
    await vi.advanceTimersByTimeAsync(1001);
    expect(wrapper.emitted("close")).toHaveLength(1);
  });
});

describe("EmDialog", () => {
  it("opens modally, and asks to close from the button and on Escape", async () => {
    const wrapper = mount(EmDialog, { props: { open: false, title: "How to play" }, slots: { default: "<p>Rules</p>" } });
    const dialog = wrapper.find("dialog").element as HTMLDialogElement;
    expect(dialog.open).toBe(false);

    await wrapper.setProps({ open: true });
    await nextTick();
    await nextTick();
    expect(dialog.open).toBe(true);
    expect(wrapper.find("dialog").attributes("aria-label")).toBe("How to play");

    await wrapper.find("button.close").trigger("click");
    await wrapper.find("dialog").trigger("cancel");
    expect(wrapper.emitted("close")).toHaveLength(2);
  });

  it("gives a danger dialog the red rule class", () => {
    expect(mount(EmDialog, { props: { open: false, title: "Reset", danger: true } }).find("dialog").classes()).toContain("danger");
  });
});

describe("EmConfirm", () => {
  it("keeps confirm disabled until the exact word is typed, then confirms", async () => {
    const wrapper = mount(EmConfirm, {
      props: { open: true, title: "Reset all Emberlings progress?", message: "This cannot be undone.", confirmLabel: "Reset progress", requireText: "RESET", danger: true },
    });
    const confirm = () => wrapper.find("button.confirm");
    expect((confirm().element as HTMLButtonElement).disabled).toBe(true);

    await wrapper.find("input").setValue("reset");
    expect((confirm().element as HTMLButtonElement).disabled).toBe(true);
    await wrapper.find("input").setValue("RESET");
    expect((confirm().element as HTMLButtonElement).disabled).toBe(false);

    await confirm().trigger("click");
    expect(wrapper.emitted("confirm")).toHaveLength(1);
  });

  it("confirms at once without a required word, and names its cancel button", async () => {
    const wrapper = mount(EmConfirm, {
      props: { open: true, title: "Forfeit?", message: "You lose the battle.", confirmLabel: "Forfeit battle", cancelLabel: "Keep battling" },
    });

    expect((wrapper.find("button.confirm").element as HTMLButtonElement).disabled).toBe(false);
    expect(wrapper.text()).toContain("Keep battling");
  });
});

describe("EmMenuRow", () => {
  it("is a button with its label and an arrow, with a variant and a disabled state", () => {
    const wrapper = mount(EmMenuRow, { props: { icon: "play", variant: "primary" }, slots: { default: "Continue" } });
    expect(wrapper.element.tagName).toBe("BUTTON");
    expect(wrapper.find(".label").text()).toBe("Continue");
    expect(wrapper.classes()).toContain("primary");
    expect(wrapper.findAll("svg")).toHaveLength(2);

    expect(mount(EmMenuRow, { props: { icon: "reset", variant: "danger", disabled: true } }).attributes("disabled")).toBeDefined();
  });
});

describe("EmNotice", () => {
  it("uses alert for errors and status for warnings", () => {
    expect(mount(EmNotice, { props: { tone: "error" }, slots: { default: "Failed" } }).attributes("role")).toBe("alert");
    const warning = mount(EmNotice, { slots: { default: "Reconnecting" } });
    expect(warning.attributes("role")).toBe("status");
    expect(warning.text()).toBe("Reconnecting");
  });
});

describe("EmPageHead", () => {
  it("shows the eyebrow, the title, the subtitle and the side slot", () => {
    const wrapper = mount(EmPageHead, { props: { title: "Your collection", subtitle: "6 Sparks." }, slots: { default: "<a>Main menu</a>" } });
    expect(wrapper.find(".em-eyebrow").text()).toBe("The forge is yours");
    expect(wrapper.find("h2").text()).toBe("Your collection");
    expect(wrapper.find(".subtitle").text()).toBe("6 Sparks.");
    expect(wrapper.find(".side").text()).toBe("Main menu");
  });
});
