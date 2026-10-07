import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
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
const WITH_TOOLS = ["chat.use", "tools.use"];

async function show(extensions: ExtensionInfo[], permissions = ACCOUNT.permissions) {
  mocks.list.mockResolvedValue(extensions);
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().account = { ...ACCOUNT, permissions };
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/extensions", component: ExtensionsView },
      { path: "/extensions/:id", component: { template: "<div />" } },
    ],
  });
  await router.push("/extensions");
  const wrapper = mount(ExtensionsView, { global: { plugins: [pinia, router] } });
  await flushPromises();
  return wrapper;
}

type Wrapper = Awaited<ReturnType<typeof show>>;
const pageLinks = (w: Wrapper) => w.findAll("a").filter((a) => a.text() === "Open page");
const hrefs = (w: Wrapper) => pageLinks(w).map((a) => a.attributes("href"));

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

describe("ExtensionsView Open page", () => {
  it("opens the web UI of an extension that has one, in a new tab", async () => {
    const w = await show([ext("pdf", "http://127.0.0.1:5174")], WITH_TOOLS);

    const [link] = pageLinks(w);
    expect(link.attributes("href")).toBe("http://127.0.0.1:5174/");
    expect(link.attributes("target")).toBe("_blank");
    expect(link.attributes("rel")).toBe("noopener noreferrer");
  });

  it("opens the tools page of an extension without a web UI", async () => {
    const w = await show([ext("notes"), ext("odd id/x", null)], WITH_TOOLS);

    expect(hrefs(w)).toEqual(["/extensions/notes", "/extensions/odd%20id%2Fx"]);
    expect(pageLinks(w).some((a) => a.attributes("target") === "_blank")).toBe(false);
  });

  it("has one Open page button per tile and no separate Open app link", async () => {
    const w = await show([ext("pdf", "http://127.0.0.1:5174"), ext("notes")], WITH_TOOLS);

    expect(pageLinks(w)).toHaveLength(2);
    expect(w.findAll("a").some((a) => a.text() === "Open app")).toBe(false);
  });

  it("still opens the web UI when the extension is not connected", async () => {
    const w = await show([ext("pdf", "https://pdf.example", "error")], WITH_TOOLS);

    expect(hrefs(w)).toEqual(["https://pdf.example/"]);
  });

  it("without tools.use only an extension with a web UI has a button", async () => {
    const w = await show([ext("pdf", "http://127.0.0.1:5174"), ext("notes"), ext("plain", null)]);

    expect(hrefs(w)).toEqual(["http://127.0.0.1:5174/"]);
  });

  it("never links a non-http address as a web UI; the tools page is used instead", async () => {
    const w = await show([ext("a", "javascript:alert(1)"), ext("b", "data:text/html,x"), ext("c", "/relative")], WITH_TOOLS);

    expect(hrefs(w)).toEqual(["/extensions/a", "/extensions/b", "/extensions/c"]);
  });

  it("without tools.use a non-http address gives no button at all", async () => {
    const w = await show([ext("a", "javascript:alert(1)")]);

    expect(pageLinks(w)).toHaveLength(0);
  });

  it("opening the link does not open the details of the tile", async () => {
    const w = await show([ext("pdf", "http://127.0.0.1:5174")], WITH_TOOLS);

    await pageLinks(w)[0].trigger("click");

    expect(w.find("dialog[open]").exists()).toBe(false);
  });
});

describe("ExtensionsView details", () => {
  const open = async (w: Wrapper) => {
    await w.find(".tile-main").trigger("click");
    return w.find("dialog[open]");
  };

  it("lists each tool on its own row under a count", async () => {
    const info = { ...ext("pdf"), description: "Merge PDFs.", tools: ["pdf__merge", "pdf__split"] };
    const dialog = await open(await show([info], WITH_TOOLS));

    expect(dialog.text()).toContain("Connected");
    expect(dialog.text()).toContain("Merge PDFs.");
    expect(dialog.findAll(".tools li").map((li) => li.text())).toEqual(["merge", "split"]);
    expect(dialog.find(".tools-head").text()).toContain("2");
  });

  it("shows the error and no tool list when it is not connected", async () => {
    const dialog = await open(await show([{ ...ext("pdf", null, "error"), tools: [] }], WITH_TOOLS));

    expect(dialog.text()).toContain("Not connected");
    expect(dialog.find(".error").text()).toBe("down");
    expect(dialog.find(".tools").exists()).toBe(false);
  });

  it("says so when a connected extension has no tools", async () => {
    const dialog = await open(await show([{ ...ext("pdf"), tools: [] }], WITH_TOOLS));

    expect(dialog.text()).toContain("No tools.");
  });

  it("offers Open page in the details, and not without a page to open", async () => {
    const withPage = await open(await show([ext("pdf", "http://127.0.0.1:5174")], WITH_TOOLS));
    expect(withPage.find(".detail-actions a").attributes("href")).toBe("http://127.0.0.1:5174/");

    const without = await open(await show([ext("pdf")]));
    expect(without.find(".detail-actions").exists()).toBe(false);
  });
});
