import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { defineComponent, h, ref, type PropType } from "vue";
import type { WatcherInfo } from "../../api/WatchersClient";
import { groupByCapability } from "../../utils/watchers";
import CapabilityFocus from "./CapabilityFocus.vue";
import WatcherList from "./WatcherList.vue";
import WatcherTimeline from "./WatcherTimeline.vue";

const NOW = Date.parse("2026-10-05T12:00:00Z");
const HOUR = 3_600_000;
const ago = (hours: number) => new Date(NOW - hours * HOUR).toISOString();
const WINDOW = { start: NOW - 24 * HOUR, end: NOW };

const watchers: WatcherInfo[] = [
  { capability: "email", key: "invoice-1", phase: "failed", started_at: ago(12), last_polled_at: ago(11), recipients: ["ops@example.com"] },
  { capability: "email", key: "welcome-2", phase: "completed", started_at: ago(6), last_polled_at: ago(5), detail: { sent: 3 } },
  { capability: "ssh", key: "probe-3", phase: "running", started_at: ago(2) },
  { capability: "ssh", key: "undated", phase: "running" },
];
const groups = groupByCapability(watchers);

function timeline(props: Partial<InstanceType<typeof WatcherTimeline>["$props"]> = {}) {
  return mount(WatcherTimeline, { props: { groups, expanded: new Set<string>(), window: WINDOW, now: NOW, ...props } });
}

describe("WatcherTimeline", () => {
  it("draws a lane per capability, with the axis counted back from now", () => {
    const wrapper = timeline();

    expect(wrapper.findAll(".row:not(.axis):not(.child) .label").map((l) => l.text())).toEqual(["email", "ssh"]);
    expect(wrapper.findAll(".tick").map((t) => t.text())).toEqual(["-24h", "-18h", "-12h", "-6h", "now"]);
    expect(wrapper.findAll(".child")).toHaveLength(0);
  });

  it("places each bar by when the run began and ended, as a share of the window", () => {
    const wrapper = timeline();
    const bars = wrapper.findAll(".row:not(.axis) .bar").map((b) => (b.element as HTMLElement).style);

    // email: failed 12h..11h ago, succeeded 6h..5h ago; ssh: running 2h ago..now (the undated one has no bar)
    expect(bars).toHaveLength(3);
    expect(parseFloat(bars[0]!.left)).toBeCloseTo(50);
    expect(parseFloat(bars[0]!.width)).toBeCloseTo(100 / 24);
    expect(parseFloat(bars[2]!.left)).toBeCloseTo((22 / 24) * 100);
  });

  it("marks running and failed runs by shape as well as colour", () => {
    const wrapper = timeline();

    expect(wrapper.findAll(".bar.failed")).toHaveLength(1);
    expect(wrapper.findAll(".bar.running")).toHaveLength(1);
    expect(wrapper.find(".bar.failed").attributes("title")).toBe("invoice-1 · Failed · 1h 0m 0s");
  });

  it("flags a lane with a failure", () => {
    const wrapper = timeline();

    expect(wrapper.findAll(".alert")).toHaveLength(1);
    expect(wrapper.findAll(".row:not(.axis)")[0]!.find(".alert").exists()).toBe(true);
  });

  it("opens a lane into one lane per watcher and dims the capability's own bars", () => {
    const wrapper = timeline({ expanded: new Set(["email"]) });

    expect(wrapper.findAll(".child .label").map((l) => l.text())).toEqual(["invoice-1", "welcome-2"]);
    expect(wrapper.find(".cap").attributes("aria-expanded")).toBe("true");
    expect(wrapper.find(".track").classes()).toContain("dim");
  });

  it("asks to toggle a lane when its name is clicked", async () => {
    const wrapper = timeline();

    await wrapper.findAll(".cap")[1]!.trigger("click");

    expect(wrapper.emitted("toggle")).toEqual([["ssh"]]);
  });

  it("opens every lane and stops toggling when forced open", () => {
    const wrapper = timeline({ forceOpen: true });

    expect(wrapper.findAll(".child")).toHaveLength(4);
    expect(wrapper.find(".cap").attributes("disabled")).toBeDefined();
  });

  it("clips a run that began before the window", () => {
    const early = groupByCapability([{ capability: "a", key: "k", phase: "running", started_at: ago(40) }]);
    const wrapper = timeline({ groups: early });

    const style = (wrapper.find(".bar").element as HTMLElement).style;
    expect(style.left).toBe("0%");
    expect(style.width).toBe("100%");
  });
});

describe("WatcherList", () => {
  function list(props: Partial<InstanceType<typeof WatcherList>["$props"]> = {}) {
    return mount(WatcherList, { props: { groups, expanded: new Set(["email"]), now: NOW, ...props } });
  }

  it("heads each capability with its counts and shows rows only for open ones", () => {
    const wrapper = list();

    expect(wrapper.findAll(".head").map((h) => h.text().replace(/\s+/g, " "))).toEqual(["▾email 1 failed 2 watchers", "▸ssh 2 running 2 watchers"]);
    expect(wrapper.findAll(".key").map((k) => k.text())).toEqual(["invoice-1", "welcome-2"]);
  });

  it("puts a failed run first, washes it, and names its status in words and a glyph", () => {
    const wrapper = list();
    const first = wrapper.find(".row");

    expect(first.classes()).toContain("failed");
    expect(first.find(".status").text()).toBe("✕ Failed");
    expect(first.text()).toContain("Recipients: ops@example.com");
    expect(first.find(".duration").text()).toBe("1h 0m 0s");
    expect(first.find(".ago").text()).toBe("11h ago");
  });

  it("offers a succeeded run's detail on request", () => {
    const wrapper = list();
    const second = wrapper.findAll(".row")[1]!;

    expect(second.find(".status").text()).toBe("✓ Succeeded");
    expect(second.find("details pre").text()).toContain('"sent": 3');
  });

  it("measures a running run from its start", () => {
    const wrapper = list({ expanded: new Set(["ssh"]) });
    const running = wrapper.findAll(".row")[0]!;

    expect(running.find(".status").text()).toBe("● Running");
    expect(running.find(".duration").text()).toBe("2h 0m 0s");
    expect(running.find(".ago").text()).toBe("2h ago");
    expect(running.text()).not.toContain("Finished");
  });

  it("copes with a run that never said when it began", () => {
    const wrapper = list({ expanded: new Set(["ssh"]) });
    const undated = wrapper.findAll(".row")[1]!;

    expect(undated.find(".duration").text()).toBe("");
    expect(undated.find(".sub").exists()).toBe(false);
  });

  it("asks to toggle a capability when its head is clicked, unless forced open", async () => {
    const wrapper = list();
    await wrapper.findAll(".head")[1]!.trigger("click");
    expect(wrapper.emitted("toggle")).toEqual([["ssh"]]);

    const forced = list({ forceOpen: true });
    expect(forced.findAll(".row")).toHaveLength(4);
    expect(forced.find(".head").attributes("disabled")).toBeDefined();
  });
});

describe("CapabilityFocus", () => {
  const options = [
    { name: "backup", watchers: 3, failed: true, running: false },
    { name: "email", watchers: 2, failed: false, running: true },
    { name: "ssh", watchers: 1, failed: false, running: false },
  ];

  // CapabilityFocus uses defineModel, so a mount needs a parent that holds the value.
  const FocusHost = defineComponent({
    props: { modelValue: { type: String as PropType<string | null>, default: null } },
    setup(props) {
      const value = ref(props.modelValue);
      return () => h(CapabilityFocus, { modelValue: value.value, "onUpdate:modelValue": (v: string | null) => (value.value = v), options });
    },
  });
  const focus = (modelValue: string | null = null) => mount(FocusHost, { props: { modelValue }, attachTo: document.body });

  it("names the focused capability, or all", () => {
    expect(focus().find(".trigger").text()).toContain("All capabilities");
    expect(focus("ssh").find(".trigger").text()).toContain("ssh");
  });

  it("opens a menu with every capability, its count and a status dot", async () => {
    const wrapper = focus();

    await wrapper.find(".trigger").trigger("click");

    expect(wrapper.findAll(".option").map((o) => o.text())).toEqual(["All capabilities", "backup3", "email2", "ssh1"]);
    expect(wrapper.find(".trigger").attributes("aria-expanded")).toBe("true");
    wrapper.unmount();
  });

  it("filters the menu as you type", async () => {
    const wrapper = focus();
    await wrapper.find(".trigger").trigger("click");

    await wrapper.find(".menu input").setValue("MA");

    expect(wrapper.findAll(".option").map((o) => o.text())).toEqual(["All capabilities", "email2"]);
    await wrapper.find(".menu input").setValue("zzz");
    expect(wrapper.find(".none").text()).toBe("No capability matches.");
    wrapper.unmount();
  });

  it("picks a capability and closes", async () => {
    const wrapper = focus();
    await wrapper.find(".trigger").trigger("click");

    await wrapper.findAll(".option")[3]!.trigger("click");

    expect(wrapper.find(".menu").exists()).toBe(false);
    expect(wrapper.find(".trigger").text()).toContain("ssh");
    wrapper.unmount();
  });

  it("goes back to all capabilities", async () => {
    const wrapper = focus("ssh");
    await wrapper.find(".trigger").trigger("click");

    await wrapper.findAll(".option")[0]!.trigger("click");

    expect(wrapper.find(".trigger").text()).toContain("All capabilities");
    wrapper.unmount();
  });

  it("closes on Escape and on a click outside", async () => {
    const wrapper = focus();
    await wrapper.find(".trigger").trigger("click");
    await wrapper.find(".focus").trigger("keydown", { key: "Escape" });
    expect(wrapper.find(".menu").exists()).toBe(false);

    await wrapper.find(".trigger").trigger("click");
    expect(wrapper.find(".menu").exists()).toBe(true);
    document.body.click();
    await wrapper.vm.$nextTick();
    expect(wrapper.find(".menu").exists()).toBe(false);
    wrapper.unmount();
  });
});
