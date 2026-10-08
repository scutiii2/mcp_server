import { createPinia, setActivePinia } from "pinia";
import { nextTick } from "vue";
import { beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "./auth";
import { useNavPrefsStore } from "./navPrefs";

beforeEach(() => { localStorage.clear(); setActivePinia(createPinia()); });
const account = (id: number) => ({ id, username: `user${id}`, email: "u@example.com", email_verified: true, roles: [], permissions: [] });

it("keeps each account's Admin layout separate and restores it on return", async () => {
  const auth = useAuthStore();
  auth.account = account(1);
  const nav = useNavPrefsStore();
  nav.update({ order: ["/agents"], pinned: ["/agents"], hidden: [] });
  auth.account = account(2);
  await nextTick();
  expect(nav.prefs.order).toEqual([]);
  auth.account = account(1);
  await nextTick();
  expect(nav.prefs.pinned).toEqual(["/agents"]);
  auth.account = null;
  await nextTick();
  expect(nav.prefs.order).toEqual([]);
});

it("uses defaults for malformed storage and reports failed persistence", () => {
  localStorage.setItem("ember_admin.nav.1", '{"order":[1],"pinned":[],"hidden":[]}');
  useAuthStore().account = account(1);
  const nav = useNavPrefsStore();
  expect(nav.prefs.order).toEqual([]);
  const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
  nav.update({ order: ["/agents"], pinned: [], hidden: [] });
  expect(nav.prefs.order).toEqual(["/agents"]);
  expect(nav.error).toContain("could not save");
  spy.mockRestore();
});
