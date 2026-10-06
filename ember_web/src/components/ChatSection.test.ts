import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import ChatSection from "./ChatSection.vue";

type Props = InstanceType<typeof ChatSection>["$props"];

function mountSection(props: Partial<Props> = {}) {
  return mount(ChatSection, {
    props: { title: "Work", count: 3, collapsible: true, collapsed: false, menu: true, ...props },
    slots: { default: '<li class="row-stub">row</li>' },
  });
}

describe("ChatSection", () => {
  it("shows the title, the count and the rows", () => {
    const wrapper = mountSection();

    expect(wrapper.text()).toContain("Work");
    expect(wrapper.find(".count").text()).toBe("3");
    expect(wrapper.find(".row-stub").exists()).toBe(true);
  });

  it("hides the rows while collapsed, and says so to assistive tech", () => {
    const wrapper = mountSection({ collapsed: true });

    expect(wrapper.find(".row-stub").exists()).toBe(false);
    expect(wrapper.find("button.toggle").attributes("aria-expanded")).toBe("false");
  });

  it("the ... button reports an open menu and stays visible", async () => {
    const wrapper = mountSection();
    const button = () => wrapper.find("button.more");
    expect(button().attributes("aria-expanded")).toBe("false");
    expect(button().classes()).not.toContain("expanded");

    await wrapper.setProps({ expanded: true });

    expect(button().attributes("aria-expanded")).toBe("true");
    expect(button().classes()).toContain("expanded");
  });

  it("toggles from the header", async () => {
    const wrapper = mountSection();

    await wrapper.find("button.toggle").trigger("click");

    expect(wrapper.emitted("toggle")).toHaveLength(1);
  });

  it("is not a button when it cannot collapse", () => {
    const wrapper = mountSection({ collapsible: false, title: "Pinned" });

    expect(wrapper.find("button.toggle").exists()).toBe(false);
    expect(wrapper.text()).toContain("Pinned");
  });

  it("opens its menu from the ... button and by right-click on the header", async () => {
    const wrapper = mountSection();

    await wrapper.find("button.more").trigger("click");
    await wrapper.find("header").trigger("contextmenu", { clientX: 5, clientY: 9 });

    const points = wrapper.emitted("openMenu")!.map((e) => e[0] as { x: number; y: number });
    expect(points).toHaveLength(2);
    expect(points[1]).toMatchObject({ x: 5, y: 9 });
  });

  it("a press on the ... button does not reach the document (an open menu would close on it)", () => {
    const wrapper = mount(ChatSection, {
      props: { title: "Work", count: 3, collapsible: true, collapsed: false, menu: true },
      attachTo: document.body,
    });
    const seen = vi.fn();
    document.addEventListener("pointerdown", seen);

    wrapper.find("button.more").element.dispatchEvent(new Event("pointerdown", { bubbles: true }));

    document.removeEventListener("pointerdown", seen);
    wrapper.unmount();
    expect(seen).not.toHaveBeenCalled();
  });

  it("has no ... button when it has no menu", () => {
    expect(mountSection({ menu: false }).find("button.more").exists()).toBe(false);
  });

  it("renders only the list, with no header, when the title is null", () => {
    const wrapper = mountSection({ title: null });

    expect(wrapper.find("header").exists()).toBe(false);
    expect(wrapper.find(".row-stub").exists()).toBe(true);
  });
});

describe("as a drop zone", () => {
  const dragEvent = (type: string, relatedTarget: EventTarget | null = null) => {
    const event = new Event(type, { bubbles: true, cancelable: true }) as Event & {
      dataTransfer: { dropEffect: string };
      relatedTarget: EventTarget | null;
    };
    event.dataTransfer = { dropEffect: "" };
    event.relatedTarget = relatedTarget;
    return event;
  };

  // The hint depends on the number of rows (`count`), so these mount with no rows in the slot.
  const mountEmpty = (props: Partial<Props> = {}) =>
    mount(ChatSection, {
      props: { title: "Work", count: 0, collapsible: true, collapsed: false, menu: true, ...props },
      slots: { default: "" },
    });

  it("accepts a drop when it is accepting, and says so", async () => {
    const wrapper = mountSection({ accepting: true });
    const over = dragEvent("dragover");

    wrapper.find("section").element.dispatchEvent(over);
    await wrapper.vm.$nextTick();
    expect(over.defaultPrevented).toBe(true); // that is what allows the drop
    expect(over.dataTransfer.dropEffect).toBe("move");
    expect(wrapper.find("section").classes()).toEqual(expect.arrayContaining(["accepting", "over"]));

    const drop = dragEvent("drop");
    wrapper.find("section").element.dispatchEvent(drop);
    await wrapper.vm.$nextTick();
    expect(drop.defaultPrevented).toBe(true);
    expect(wrapper.emitted("drop")).toHaveLength(1);
    expect(wrapper.find("section").classes()).not.toContain("over");
  });

  it("refuses a drop when it is not accepting", async () => {
    const wrapper = mountSection({ accepting: false });
    const over = dragEvent("dragover");

    wrapper.find("section").element.dispatchEvent(over);
    wrapper.find("section").element.dispatchEvent(dragEvent("drop"));
    await wrapper.vm.$nextTick();

    expect(over.defaultPrevented).toBe(false);
    expect(wrapper.emitted("drop")).toBeUndefined();
    expect(wrapper.find("section").classes()).not.toContain("accepting");
  });

  it("is still a drop zone while collapsed", async () => {
    const wrapper = mountSection({ accepting: true, collapsed: true });

    wrapper.find("section").element.dispatchEvent(dragEvent("drop"));
    await wrapper.vm.$nextTick();

    expect(wrapper.find("ul").exists()).toBe(false);
    expect(wrapper.emitted("drop")).toHaveLength(1);
  });

  it("stops highlighting when the pointer leaves the zone, but not when it moves between its children", async () => {
    const wrapper = mountSection({ accepting: true });
    const section = wrapper.find("section").element;
    section.dispatchEvent(dragEvent("dragover"));
    await wrapper.vm.$nextTick();

    section.dispatchEvent(dragEvent("dragleave", wrapper.find("header").element));
    await wrapper.vm.$nextTick();
    expect(wrapper.find("section").classes()).toContain("over");

    section.dispatchEvent(dragEvent("dragleave", document.body));
    await wrapper.vm.$nextTick();
    expect(wrapper.find("section").classes()).not.toContain("over");
  });

  it("clears the highlight when it stops accepting, and does not bring it back", async () => {
    const wrapper = mountSection({ accepting: true });
    wrapper.find("section").element.dispatchEvent(dragEvent("dragover"));
    await wrapper.vm.$nextTick();
    expect(wrapper.find("section").classes()).toContain("over");

    await wrapper.setProps({ accepting: false });
    await wrapper.setProps({ accepting: true });

    expect(wrapper.find("section").classes()).not.toContain("over");
  });

  it("decides by position when dragleave has no relatedTarget", async () => {
    const wrapper = mountSection({ accepting: true });
    const section = wrapper.find("section").element;
    section.getBoundingClientRect = () => ({ left: 0, top: 0, right: 100, bottom: 100, width: 100, height: 100, x: 0, y: 0 }) as DOMRect;
    section.dispatchEvent(dragEvent("dragover"));
    await wrapper.vm.$nextTick();

    const inside = dragEvent("dragleave");
    Object.assign(inside, { clientX: 50, clientY: 50 });
    section.dispatchEvent(inside);
    await wrapper.vm.$nextTick();
    expect(wrapper.find("section").classes()).toContain("over");

    const outside = dragEvent("dragleave");
    Object.assign(outside, { clientX: 150, clientY: 50 });
    section.dispatchEvent(outside);
    await wrapper.vm.$nextTick();
    expect(wrapper.find("section").classes()).not.toContain("over");
  });

  it("shows its hint while accepting and empty", () => {
    expect(mountEmpty({ accepting: true, hint: "Drop here to pin" }).text()).toContain("Drop here to pin");
  });

  it("shows no hint when it has rows or is not accepting", () => {
    expect(mountSection({ accepting: true, hint: "Drop here to pin", count: 2 }).text()).not.toContain("Drop here");
    expect(mountEmpty({ accepting: false, hint: "Drop here to pin" }).text()).not.toContain("Drop here");
  });
});
