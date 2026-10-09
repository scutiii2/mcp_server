import { flushPromises, mount } from "@vue/test-utils";
import { ref } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PwaStatus from "./PwaStatus.vue";

const update = vi.fn(async () => {});
const needRefresh = ref(false);
vi.mock("virtual:pwa-register/vue", () => ({ useRegisterSW: () => ({ needRefresh, updateServiceWorker: update }) }));
const props = { appName: "Ember", offlineMessage: "Reconnect to send messages." };
let wrappers: ReturnType<typeof mount>[] = [];
function view() { const w = mount(PwaStatus, { props }); wrappers.push(w); return w; }
function installEvent() {
  const event = new Event("beforeinstallprompt", { cancelable: true });
  const prompt = vi.fn(async () => {});
  Object.assign(event, { prompt, userChoice: Promise.resolve({ outcome: "dismissed" }) });
  window.dispatchEvent(event);
  return { event, prompt };
}
beforeEach(() => {
  needRefresh.value = false;
  vi.clearAllMocks();
  Object.defineProperty(navigator, "onLine", { configurable: true, value: true });
});
afterEach(() => { wrappers.forEach(w => w.unmount()); wrappers = []; });
describe("PWA status", () => {
  it("stays hidden when there is nothing to announce", () => { expect(view().find('aside').exists()).toBe(false); });
  it("explains going offline and offers a reload on reconnect", async () => {
    const w = view();
    Object.defineProperty(navigator, "onLine", { configurable: true, value: false });
    window.dispatchEvent(new Event("offline"));
    await flushPromises();
    expect(w.get('[role="status"]').text()).toContain("Reconnect to send messages");
    Object.defineProperty(navigator, "onLine", { configurable: true, value: true });
    window.dispatchEvent(new Event("online"));
    await flushPromises();
    expect(w.text()).toContain("Back online");
    expect(w.text()).toContain("Retry");
  });
  it("waits for the install button before prompting, and handles dismissal", async () => {
    const w = view();
    const { event, prompt } = installEvent();
    await flushPromises();
    expect(event.defaultPrevented).toBe(true);
    expect(prompt).not.toHaveBeenCalled();
    await w.findAll('button').find(b => b.text() === 'Install app')!.trigger('click');
    await flushPromises();
    expect(prompt).toHaveBeenCalledOnce();
    expect(w.find('aside').exists()).toBe(false);
  });
  it("removes the install offer when installed through the browser", async () => {
    const w = view();
    installEvent();
    window.dispatchEvent(new Event('appinstalled'));
    await flushPromises();
    expect(w.find('aside').exists()).toBe(false);
  });
  it("never updates automatically and lets the user postpone", async () => {
    const w = view();
    needRefresh.value = true;
    await flushPromises();
    expect(w.text()).toContain('Save your work');
    expect(update).not.toHaveBeenCalled();
    await w.findAll('button').find(b => b.text() === 'Later')!.trigger('click');
    expect(update).not.toHaveBeenCalled();
    expect(needRefresh.value).toBe(false);
    needRefresh.value = true;
    await flushPromises();
    await w.findAll('button').find(b => b.text() === 'Reload to update')!.trigger('click');
    expect(update).toHaveBeenCalledOnce();
  });
  it("shows an update failure so it can be retried", async () => {
    update.mockRejectedValueOnce(new Error('offline'));
    const w = view();
    needRefresh.value = true;
    await flushPromises();
    await w.findAll('button').find(b => b.text() === 'Reload to update')!.trigger('click');
    await flushPromises();
    expect(w.get('[role="alert"]').text()).toContain('try again');
  });
});
