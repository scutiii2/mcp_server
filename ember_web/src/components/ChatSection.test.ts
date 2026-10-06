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
