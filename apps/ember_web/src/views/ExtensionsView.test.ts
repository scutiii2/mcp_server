import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Account } from "../api/AuthClient";
import type { ExtensionInfo } from "../api/ExtensionsClient";
import { useAuthStore } from "../stores/auth";
import ExtensionsView from "./ExtensionsView.vue";

const mocks = vi.hoisted(() => ({ list: vi.fn() }));

vi.mock("../api/ExtensionsClient", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/ExtensionsClient")>()),
  extensionsClient: { list: mocks.list, add: vi.fn(), remove: vi.fn() },
}));

const ext = (id: string, webUrl?: string | null, status = "connected"): ExtensionInfo => ({
  id,
  label: id.toUpperCase(),
  description: "",
  status,
  error: status === "error" ? "down" : null,
  tools: [`${id}__run`],
  web_url: webUrl,
});

const ACCOUNT: Account = {
  id: 1,
  username: "lex",
  email: "lex@example.com",
  email_verified: true,
  roles: [],
  permissions: ["chat.use"],
};

async function show(extensions: ExtensionInfo[]) {
  mocks.list.mockResolvedValue(extensions);
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().account = ACCOUNT;
  const wrapper = mount(ExtensionsView, { global: { plugins: [pinia] } });
  await flushPromises();
  return wrapper;
}

const links = (w: Awaited<ReturnType<typeof show>>) => w.findAll("a").filter((a) => a.text() === "Open app");

beforeEach(() => {
  vi.clearAllMocks();
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
});

describe("ExtensionsView web app link", () => {
  it("links an extension that has a web app, in a new tab, and only that one", async () => {
    const w = await show([ext("pdf", "http://127.0.0.1:5174"), ext("notes", null), ext("plain")]);

    const found = links(w);
    expect(found).toHaveLength(1);
    expect(found[0].attributes("href")).toBe("http://127.0.0.1:5174/");
    expect(found[0].attributes("target")).toBe("_blank");
    expect(found[0].attributes("rel")).toBe("noopener noreferrer");
  });

  it("still links the web app when the extension is not connected", async () => {
    const w = await show([ext("pdf", "https://pdf.example", "error")]);

    expect(links(w)).toHaveLength(1);
  });

  it("never draws a link for a non-http address", async () => {
    const w = await show([ext("a", "javascript:alert(1)"), ext("b", "data:text/html,x"), ext("c", "/relative")]);

    expect(links(w)).toHaveLength(0);
  });

  it("opening the link does not open the details of the tile", async () => {
    const w = await show([ext("pdf", "http://127.0.0.1:5174")]);

    await links(w)[0].trigger("click");

    expect(w.find("dialog[open]").exists()).toBe(false);
  });
});
