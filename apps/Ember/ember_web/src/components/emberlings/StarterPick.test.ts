import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { emberlingsClient } from "../../api/EmberlingsClient";
import { CATALOG, PROFILE } from "../../api/EmberlingsClient.fixtures";
import { useEmberlingsStore } from "../../stores/emberlings";
import StarterPick from "./StarterPick.vue";

vi.mock("../../api/EmberlingsClient", () => ({ emberlingsClient: { createProfile: vi.fn() } }));

const client = vi.mocked(emberlingsClient);

beforeEach(() => {
  vi.resetAllMocks();
  setActivePinia(createPinia());
  useEmberlingsStore().catalog = CATALOG;
});

describe("StarterPick", () => {
  it("lists the starters and starts only after one is picked", async () => {
    client.createProfile.mockResolvedValue(PROFILE);
    const wrapper = mount(StarterPick);

    expect(wrapper.findAll(".spark-name").map((n) => n.text())).toEqual(["Guardian", "Striker"]);
    const start = wrapper.find("button.start");
    expect((start.element as HTMLButtonElement).disabled).toBe(true);

    await wrapper.findAll("button.starter-pick")[0]!.trigger("click");
    expect(client.createProfile).not.toHaveBeenCalled();
    expect(start.text()).toBe("Start with Guardian");

    await start.trigger("click");
    await flushPromises();

    expect(client.createProfile).toHaveBeenCalledExactlyOnceWith("guardian");
    expect(wrapper.emitted("started")).toHaveLength(1);
  });

  it("goes back to the menu", async () => {
    const wrapper = mount(StarterPick);
    await wrapper.find("button.back").trigger("click");

    expect(wrapper.emitted("back")).toHaveLength(1);
  });
});
