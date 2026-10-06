import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import { ApiError } from "../api/http";
import { sharesClient, type SharedChatView as SharedChat } from "../api/SharesClient";
import SharedChatView from "./SharedChatView.vue";

vi.mock("../api/SharesClient", () => ({ sharesClient: { create: vi.fn(), list: vi.fn(), revoke: vi.fn(), read: vi.fn() } }));

const client = vi.mocked(sharesClient);

const SHARED: SharedChat = {
  title: "Quarterly report",
  messages: [
    { role: "user", content: "please summarize <b>this</b>\n\n📎 report.txt" },
    { role: "assistant", content: "Here is **the** summary.\n\n```js\nconst a = 1;\n```" },
  ],
  created_at: "2026-01-01T10:00:00",
  expires_at: "2026-01-08T10:00:00",
};

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/shared/:token", name: "shared", component: SharedChatView, meta: { public: true } }],
  });
}

async function openShared(token = "abc123") {
  const router = makeRouter();
  await router.push(`/shared/${token}`);
  await router.isReady();
  const wrapper = mount(SharedChatView, { global: { plugins: [router] } });
  await flushPromises();
  return { wrapper, router };
}

beforeEach(() => {
  vi.clearAllMocks();
  client.read.mockResolvedValue(SHARED);
  document.title = "Ember";
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("a shared chat", () => {
  it("reads the token from the address and shows the title and the conversation", async () => {
    const { wrapper } = await openShared("the-token");

    expect(client.read).toHaveBeenCalledExactlyOnceWith("the-token");
    expect(wrapper.find("h2").text()).toBe("Quarterly report");
    expect(wrapper.findAll(".user-bubble")).toHaveLength(1);
    expect(wrapper.find(".assistant").exists()).toBe(true);
  });

  it("shows a question as typed and renders only the answer as markdown", async () => {
    const { wrapper } = await openShared();

    const question = wrapper.find(".user-bubble");
    expect(question.text()).toContain("please summarize <b>this</b>");
    expect(question.find("b").exists()).toBe(false); // literal text, not markup
    expect(question.text()).toContain("📎 report.txt");
    const answer = wrapper.find(".assistant");
    expect(answer.find("strong").text()).toBe("the");
    expect(answer.find("pre code").text()).toContain("const a = 1;");
  });

  it("says it is a read-only copy, when it was shared, and when the link stops working", async () => {
    const { wrapper } = await openShared();

    const note = wrapper.find(".note").text();
    expect(note).toContain("read-only copy");
    expect(note).toContain("stops working");
    expect(note).toContain("Tool output and attached files are not included");
  });

  it("says nothing about expiry for a link that never expires", async () => {
    client.read.mockResolvedValue({ ...SHARED, expires_at: null });
    const { wrapper } = await openShared();

    expect(wrapper.find(".note").text()).not.toContain("stops working");
  });

  it("has nothing to click: no send box, no edit, no actions", async () => {
    const { wrapper } = await openShared();

    expect(wrapper.find("textarea").exists()).toBe(false);
    expect(wrapper.find("input").exists()).toBe(false);
    expect(wrapper.find("form").exists()).toBe(false);
  });

  it("puts the chat's title in the browser tab, and puts it back when left", async () => {
    const { wrapper } = await openShared();
    expect(document.title).toBe("Quarterly report - Ember");

    wrapper.unmount();

    expect(document.title).toBe("Ember");
  });
});

describe("a link that does not work", () => {
  it("looks the same whether it never existed, was revoked or expired (the server says 404 for all)", async () => {
    client.read.mockRejectedValue(new ApiError(404, "Shared chat not found"));
    const { wrapper } = await openShared();

    expect(wrapper.find('[role="alert"] h2').text()).toBe("This link doesn't work");
    expect(wrapper.text()).toContain("never existed, or it was turned off, or it has expired");
    expect(wrapper.text()).not.toContain("Shared chat not found");
    expect(wrapper.find(".user-bubble").exists()).toBe(false);
    expect(document.title).toBe("Ember");
  });

  it("asks to wait when rate limited, and can retry", async () => {
    client.read.mockRejectedValueOnce(new ApiError(429, "Too many requests - wait a moment"));
    const { wrapper } = await openShared();
    expect(wrapper.find('[role="alert"] h2').text()).toBe("Too many requests");

    await wrapper.find('[role="alert"] button').trigger("click");
    await flushPromises();

    expect(client.read).toHaveBeenCalledTimes(2);
    expect(wrapper.find("h2").text()).toBe("Quarterly report");
  });

  it("shows other failures with their message and a retry", async () => {
    client.read.mockRejectedValueOnce(new Error("Failed to fetch"));
    const { wrapper } = await openShared();

    expect(wrapper.find('[role="alert"]').text()).toContain("Failed to fetch");

    await wrapper.find('[role="alert"] button').trigger("click");
    await flushPromises();
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    expect(wrapper.find("h2").text()).toBe("Quarterly report");
  });

  it("shows loading first", async () => {
    client.read.mockReturnValue(new Promise(() => {}));
    const router = makeRouter();
    await router.push("/shared/x");
    const wrapper = mount(SharedChatView, { global: { plugins: [router] } });

    expect(wrapper.text()).toContain("Loading");
  });
});

describe("moving from one link to another", () => {
  it("loads the new one and ignores a slow answer for the old one", async () => {
    let finishOld!: (value: SharedChat) => void;
    client.read.mockReturnValueOnce(new Promise((resolve) => (finishOld = resolve)));
    const router = makeRouter();
    await router.push("/shared/old");
    const wrapper = mount(SharedChatView, { global: { plugins: [router] } });
    client.read.mockResolvedValueOnce({ ...SHARED, title: "The new one" });

    await router.push("/shared/new");
    await flushPromises();
    finishOld({ ...SHARED, title: "The old one" });
    await flushPromises();

    expect(client.read.mock.calls.map((c) => c[0])).toEqual(["old", "new"]);
    expect(wrapper.find("h2").text()).toBe("The new one");
  });
});
