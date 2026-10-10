import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { emberlingsClient } from "../../api/EmberlingsClient";
import { CATALOG, PROFILE, ownedSpark } from "../../api/EmberlingsClient.fixtures";
import { ApiError } from "../../api/http";
import { useEmberlingsStore } from "../../stores/emberlings";
import ShopPanel from "./ShopPanel.vue";

vi.mock("../../api/EmberlingsClient", () => ({
  emberlingsClient: { buyEmblems: vi.fn(), buyCopies: vi.fn(), sellCopy: vi.fn(), profile: vi.fn() },
}));

const client = vi.mocked(emberlingsClient);

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

beforeEach(() => {
  vi.resetAllMocks();
  setActivePinia(createPinia());
  client.profile.mockResolvedValue(PROFILE);
});

function mountShop(insignia = 25) {
  const store = useEmberlingsStore();
  store.catalog = CATALOG;
  store.profile = { ...PROFILE, insignia, sparks: [ownedSpark("guardian", { copies: 2 })] };
  return { store, wrapper: mount(ShopPanel) };
}

const buyIn = (wrapper: ReturnType<typeof mountShop>["wrapper"], tier: string) => wrapper.find(`[data-tier="${tier}"] button`);

describe("ShopPanel", () => {
  it("disables EMBLEMs the Insignia does not cover", async () => {
    const { wrapper } = mountShop(25);

    expect(buyIn(wrapper, "normal").attributes("disabled")).toBeUndefined();
    expect(buyIn(wrapper, "rare").attributes("disabled")).toBeDefined();

    await wrapper.find('[data-tier="normal"] input').setValue("3");

    expect(buyIn(wrapper, "normal").text()).toBe("Buy for 30");
    expect(buyIn(wrapper, "normal").attributes("disabled")).toBeDefined();
  });

  it("buys EMBLEMs and says what it bought", async () => {
    client.buyEmblems.mockResolvedValue({ kind: "emblems", tier_id: "normal", quantity: 2, price: 20 });
    const { wrapper } = mountShop(25);

    await wrapper.find('[data-tier="normal"] input').setValue("2");
    await buyIn(wrapper, "normal").trigger("click");
    await flushPromises();

    expect(client.buyEmblems).toHaveBeenCalledExactlyOnceWith("normal", 2);
    expect(wrapper.find(".notice").text()).toBe("Bought 2 Normal EMBLEMs for 20 Insignia.");
  });

  it("leaves the copy price to the server and keeps its refusal", async () => {
    client.buyCopies.mockRejectedValue(new ApiError(409, "that costs 400 Insignia and you have 25"));
    const { store, wrapper } = mountShop(25);
    const buy = () => wrapper.findAll("button").find((b) => b.text() === "Buy copies")!;
    expect(buy().attributes("disabled")).toBeDefined();

    await wrapper.find("select[name='copy-spark']").setValue("bruiser");
    await wrapper.find("select[name='copy-tier']").setValue("rare");
    expect(buy().attributes("disabled")).toBeUndefined();
    await buy().trigger("click");
    await flushPromises();

    expect(client.buyCopies).toHaveBeenCalledExactlyOnceWith("bruiser", "rare");
    expect(store.error).toBe("that costs 400 Insignia and you have 25");
  });

  it("sells one copy after confirming", async () => {
    client.sellCopy.mockResolvedValue({ kind: "sale", spark_id: "guardian", value: 12, copies: 1, tier_id: "normal", downgraded: false });
    const { wrapper } = mountShop();

    await wrapper.find('[data-sell="guardian"] button').trigger("click");
    expect(client.sellCopy).not.toHaveBeenCalled();
    await wrapper.find("button.confirm").trigger("click");
    await flushPromises();

    expect(client.sellCopy).toHaveBeenCalledExactlyOnceWith("guardian");
    expect(wrapper.find(".notice").text()).toBe("Sold one copy for 12 Insignia.");
  });
});
