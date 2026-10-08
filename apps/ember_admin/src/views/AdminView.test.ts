import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import { adminClient } from "../api/AdminClient";
import { useAuthStore } from "../stores/auth";
import AdminView from "./AdminView.vue";
import AdminOverviewView from "./AdminOverviewView.vue";

vi.mock("../api/AdminClient", () => ({ adminClient: { summary: vi.fn() } }));
const client = vi.mocked(adminClient);
beforeEach(() => {
  setActivePinia(createPinia());
  useAuthStore().account = { id: 1, username: "admin", email: "a@example.com", email_verified: true, roles: [], permissions: ["accounts.view", "roles.view", "invites.manage", "settings.manage"] };
  client.summary.mockReset();
  client.summary.mockResolvedValue({ accounts: 24, unverified: 3, disabled: 1, open_invites: 5, roles: 2 });
});
async function view(path = '/admin') {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/admin", component: AdminView, children: [
    { path: '', component: AdminOverviewView },
    { path: 'roles', component: { template: '<div>roles page</div>' } },
    { path: 'accounts', component: { template: '<div>accounts page</div>' } },
    { path: 'invites', component: { template: '<div>invites page</div>' } },
    { path: 'settings', component: { template: '<div>settings page</div>' } },
  ] }] });
  await router.push(path);
  const wrapper = mount({ template: '<RouterView />' }, { global: { plugins: [router] } });
  await flushPromises();
  return { wrapper, router };
}
it('shows separate destinations and marks the active child page', async () => {
  const { wrapper, router } = await view('/admin/roles');
  expect(wrapper.get('nav[aria-label="Administration pages"] a[aria-current="page"]').text()).toBe('Roles & permissions');
  expect(wrapper.text()).toContain('roles page');
  expect(client.summary).not.toHaveBeenCalled();
  await router.push('/admin/accounts');
  expect(wrapper.get('nav[aria-label="Administration pages"] a[aria-current="page"]').text()).toBe('Accounts');
});
it('shows counts only on the overview and refreshes when returning', async () => {
  const { wrapper, router } = await view();
  expect(wrapper.findAll('.stats .tile').map(t => t.text())).toEqual(['Accounts24', 'Unverified3', 'Disabled1', 'Open invites5']);
  expect(wrapper.get('.admin-info a').attributes('href')).toBe('/admin/accounts?status=unverified');
  await router.push('/admin/roles');
  expect(wrapper.find('.stats').exists()).toBe(false);
  await router.push('/admin');
  await flushPromises();
  expect(client.summary).toHaveBeenCalledTimes(2);
});
it('keeps navigation and destination links usable when summary fails', async () => {
  client.summary.mockRejectedValue(new Error('boom'));
  const { wrapper } = await view();
  expect(wrapper.get('[role="alert"]').text()).toContain('boom');
  expect(wrapper.findAll('.destination')).toHaveLength(4);
});
it('offers only overview and roles to a role viewer and hides unrelated counts', async () => {
  useAuthStore().account!.permissions = ['roles.view'];
  const { wrapper } = await view();
  expect(wrapper.findAll('nav[aria-label="Administration pages"] a').map(a => a.text())).toEqual(['Overview', 'Roles & permissions']);
  expect(wrapper.findAll('.destination')).toHaveLength(1);
  expect(wrapper.find('.stats').exists()).toBe(false);
  expect(wrapper.find('.admin-page-head .primary').exists()).toBe(false);
});
it('opens invite creation from the overview header', async () => {
  const { wrapper } = await view();
  expect(wrapper.get('.admin-page-head a').attributes('href')).toBe('/admin/invites?create=1');
});
