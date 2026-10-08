import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";
import type { PromptTemplate } from "../api/TemplatesClient";
import TemplatePicker from "./TemplatePicker.vue";

const tpl = (id: number, name: string, body = `${name} body`): PromptTemplate => ({
  id,
  name,
  body,
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00",
});

const LIST = [tpl(1, "Summarize"), tpl(2, "Code review"), tpl(3, "Review notes")];

type Props = InstanceType<typeof TemplatePicker>["$props"];

function mountPicker(props: Partial<Props> = {}) {
  return mount(TemplatePicker, {
    props: { templates: LIST, loading: false, error: "", canSave: true, ...props },
    attachTo: document.body,
  });
}

async function openIt(wrapper: ReturnType<typeof mountPicker>) {
  await wrapper.find("button.trigger").trigger("click");
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("TemplatePicker", () => {
  it("is closed until the button is clicked, and asks for the list when it opens", async () => {
    const wrapper = mountPicker();
    expect(wrapper.find(".popover").exists()).toBe(false);

    await openIt(wrapper);

    expect(wrapper.find(".popover").exists()).toBe(true);
    expect(wrapper.emitted("open")).toHaveLength(1);
    expect(wrapper.find("button.trigger").attributes("aria-expanded")).toBe("true");
  });

  it("puts the caret in the filter box", async () => {
    const wrapper = mountPicker();

    await openIt(wrapper);

    expect(document.activeElement).toBe(wrapper.find("input").element);
  });

  it("lists names with a preview of each text", async () => {
    const wrapper = mountPicker({ templates: [tpl(1, "Summarize", "\nSummarize the text below.\nMore")] });
    await openIt(wrapper);

    expect(wrapper.find(".item .name").text()).toBe("Summarize");
    expect(wrapper.find(".item .body").text()).toBe("Summarize the text below.");
  });

  it("filters by name as you type, best matches first", async () => {
    const wrapper = mountPicker();
    await openIt(wrapper);

    await wrapper.find("input").setValue("review");

    expect(wrapper.findAll(".item .name").map((n) => n.text())).toEqual(["Review notes", "Code review"]);
  });

  it("says when nothing matches, and when there is nothing saved", async () => {
    const wrapper = mountPicker();
    await openIt(wrapper);
    await wrapper.find("input").setValue("zzz");
    expect(wrapper.find(".note").text()).toBe("No prompt matches.");

    const empty = mountPicker({ templates: [] });
    await openIt(empty);
    expect(empty.find(".note").text()).toBe("No saved prompts yet.");
  });

  it("shows loading, and an error with a retry that asks again", async () => {
    const loading = mountPicker({ templates: [], loading: true });
    await openIt(loading);
    expect(loading.find(".note").text()).toBe("Loading …");

    const failed = mountPicker({ templates: [], error: "down" });
    await openIt(failed);
    expect(failed.find('[role="alert"]').text()).toContain("down");
    await failed.find('[role="alert"] button').trigger("click");
    expect(failed.emitted("open")).toHaveLength(2);
  });

  it("keeps showing the list while a refresh is loading", async () => {
    const wrapper = mountPicker({ loading: true });
    await openIt(wrapper);

    expect(wrapper.findAll(".item")).toHaveLength(3);
  });

  it("picking a prompt emits it and closes", async () => {
    const wrapper = mountPicker();
    await openIt(wrapper);

    await wrapper.findAll(".item")[1]!.trigger("click");

    expect(wrapper.emitted("pick")).toEqual([[LIST[1]]]);
    expect(wrapper.find(".popover").exists()).toBe(false);
  });

  it("Manage and Save current text emit and close", async () => {
    const wrapper = mountPicker();
    await openIt(wrapper);
    const [save, manage] = wrapper.findAll(".foot button");

    await save!.trigger("click");
    expect(wrapper.emitted("save")).toHaveLength(1);
    expect(wrapper.find(".popover").exists()).toBe(false);

    await openIt(wrapper);
    await manage!.trigger("click");
    expect(wrapper.emitted("manage")).toHaveLength(1);
  });

  it("cannot save an empty input", async () => {
    const wrapper = mountPicker({ canSave: false });
    await openIt(wrapper);

    const save = wrapper.findAll(".foot button")[0]!;
    expect(save.attributes("disabled")).toBeDefined();
    await save.trigger("click");
    expect(wrapper.emitted("save")).toBeUndefined();
  });

  it("closes on Esc, and swallows it so the page's Esc (stop) does not fire", async () => {
    const wrapper = mountPicker();
    await openIt(wrapper);
    const event = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });

    wrapper.find("input").element.dispatchEvent(event);
    await wrapper.vm.$nextTick();

    expect(wrapper.find(".popover").exists()).toBe(false);
    expect(event.defaultPrevented).toBe(true);
  });

  it("closes when the pointer goes down elsewhere, but not inside", async () => {
    const wrapper = mountPicker();
    await openIt(wrapper);

    wrapper.find("input").element.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    await wrapper.vm.$nextTick();
    expect(wrapper.find(".popover").exists()).toBe(true);

    document.body.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    await wrapper.vm.$nextTick();
    expect(wrapper.find(".popover").exists()).toBe(false);
  });

  it("clears the filter each time it opens", async () => {
    const wrapper = mountPicker();
    await openIt(wrapper);
    await wrapper.find("input").setValue("sum");
    await openIt(wrapper); // closes
    await openIt(wrapper); // opens again

    expect((wrapper.find("input").element as HTMLInputElement).value).toBe("");
    expect(wrapper.findAll(".item")).toHaveLength(3);
  });
});
