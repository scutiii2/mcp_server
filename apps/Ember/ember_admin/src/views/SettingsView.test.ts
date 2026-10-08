import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, expect, it } from "vitest";
import { createMemoryHistory, createRouter, RouterView } from "vue-router";
import { initTheme, useTheme } from "../composables/useTheme";
import { useAuthStore } from "../stores/auth";
import { useNavPrefsStore } from "../stores/navPrefs";
import SettingsView from "./SettingsView.vue";

beforeEach(() => {
  HTMLDialogElement.prototype.showModal ??= function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close ??= function () { this.removeAttribute("open"); };
  localStorage.clear();
  initTheme();
  setActivePinia(createPinia());
  useAuthStore().account = { id: 1, username: "admin", email: "a@example.com", email_verified: true, roles: [], permissions: ["capabilities.manage", "extensions.manage"] };
});

async function show() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: "/settings", component: SettingsView },
    { path: "/profile", component: { template: "<div />" } },
  ] });
  await router.push("/settings");
  const wrapper = mount({ components: { RouterView }, template: "<RouterView />" }, { global: { plugins: [router] } });
  return { wrapper, router };
}

it("keeps theme and sidebar changes as drafts until Save", async () => {
  const { wrapper } = await show();
  expect(wrapper.find(".settings-save-bar").exists()).toBe(false);
  await wrapper.get('button[data-value="dark"]').trigger("click");
  await wrapper.get('input[aria-label="Show Capabilities in the sidebar"]').setValue(false);
  expect(useTheme().theme.value).toBe("system");
  expect(useNavPrefsStore().prefs.hidden).toEqual([]);
  expect(localStorage.getItem("ember_admin.nav.1")).toBeNull();
  await wrapper.get("button.save").trigger("click");
  expect(useTheme().theme.value).toBe("dark");
  expect(useNavPrefsStore().prefs.hidden).toEqual(["/capabilities"]);
  expect(JSON.parse(localStorage.getItem("ember_admin.nav.1")!).hidden).toEqual(["/capabilities"]);
  expect(wrapper.find(".settings-save-bar").exists()).toBe(false);
  wrapper.unmount();
});

it("Revert restores saved preferences and clears the unsaved bar", async () => {
  const { wrapper } = await show();
  await wrapper.get('button[data-value="dark"]').trigger("click");
  await wrapper.get('input[aria-label="Show Capabilities in the sidebar"]').setValue(false);
  await wrapper.get("button.revert").trigger("click");
  expect(wrapper.get('button[data-value="system"]').attributes("aria-pressed")).toBe("true");
  expect((wrapper.get('input[aria-label="Show Capabilities in the sidebar"]').element as HTMLInputElement).checked).toBe(true);
  expect(wrapper.find(".settings-save-bar").exists()).toBe(false);
  wrapper.unmount();
});

it("asks before leaving with drafts and protects reload", async () => {
  const { wrapper, router } = await show();
  await wrapper.get('button[data-value="dark"]').trigger("click");
  const unload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(unload);
  expect(unload.defaultPrevented).toBe(true);
  const navigation = router.push("/profile");
  await flushPromises();
  expect(wrapper.text()).toContain("Discard unsaved settings?");
  await wrapper.get("button.cancel").trigger("click");
  await navigation;
  expect(router.currentRoute.value.path).toBe("/settings");
  expect(wrapper.find(".settings-save-bar").exists()).toBe(true);
  const leave = router.push("/profile");
  await flushPromises();
  await wrapper.get("button.confirm").trigger("click");
  await leave;
  expect(router.currentRoute.value.path).toBe("/profile");
  expect(useTheme().theme.value).toBe("system");
  wrapper.unmount();
});
