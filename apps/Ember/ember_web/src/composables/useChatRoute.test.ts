import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, ref, type Ref } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { chatPath, useChatRoute, type ChatRouteStore } from "./useChatRoute";

const Blank = defineComponent({ render: () => h("div") });

function makeRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", name: "chat", component: Blank },
      { path: "/chat/:id", name: "chat-id", component: Blank },
      { path: "/tools", name: "tools", component: Blank },
    ],
  });
}

/** A chat store that knows `chats`; selecting opens, as the real one does. */
function fakeStore(chats: string[], listReady = true) {
  const known = new Set(chats);
  const activeId = ref<string | null>(null);
  const ready = ref(listReady);
  const store = {
    activeId,
    listReady: ready,
    hasChat: (id: string) => known.has(id),
    selectChat: vi.fn(async (id: string) => {
      activeId.value = id;
    }),
    newChat: vi.fn(() => {
      activeId.value = null;
    }),
    reload: vi.fn(async () => {}),
  } satisfies ChatRouteStore;
  return { store, known, activeId, ready };
}

type Harness = ReturnType<typeof useChatRoute> & { router: Router; shown: Ref<boolean> };

/** Mounts the composable at `start`, as ChatView does: shown, then activated. */
async function setup(
  store: ChatRouteStore,
  start = "/",
  options: { shown?: boolean; before?: (router: Router) => void } = {},
): Promise<Harness> {
  const router = makeRouter();
  options.before?.(router);
  await router.push(start);
  await router.isReady();
  const shown = ref(options.shown ?? true);
  let result!: ReturnType<typeof useChatRoute>;
  mount(
    defineComponent({
      setup() {
        result = useChatRoute(store, shown);
        return () => h("div");
      },
    }),
    { global: { plugins: [router] } },
  );
  if (shown.value) result.activate();
  await flushPromises();
  return { ...result, router, shown };
}

/** Where the back button leads from here (the entry before the current one);
 * the current path itself when there is none. Moves the router, so call it last. */
async function backTarget(router: Router): Promise<string> {
  router.back();
  await flushPromises();
  return router.currentRoute.value.path;
}

afterEach(() => vi.restoreAllMocks());

describe("chatPath", () => {
  it("is / for a fresh chat and /chat/<id> for a saved one", () => {
    expect(chatPath(null)).toBe("/");
    expect(chatPath("c1")).toBe("/chat/c1");
  });

  it("escapes what would break the address", () => {
    expect(chatPath("a b/c?d")).toBe("/chat/a%20b%2Fc%3Fd");
  });
});

describe("opening a chat from the address", () => {
  it("opens /chat/<id> as the page appears", async () => {
    const { store } = fakeStore(["c1", "c2"]);

    await setup(store, "/chat/c2");

    expect(store.selectChat).toHaveBeenCalledExactlyOnceWith("c2");
  });

  it("waits for the chat list, then opens it", async () => {
    const { store, ready } = fakeStore(["c1"], false);
    await setup(store, "/chat/c1");
    expect(store.selectChat).not.toHaveBeenCalled();

    ready.value = true;
    await flushPromises();

    expect(store.selectChat).toHaveBeenCalledExactlyOnceWith("c1");
  });

  it("does nothing when that chat is already open", async () => {
    const { store, activeId } = fakeStore(["c1"]);
    activeId.value = "c1";

    await setup(store, "/chat/c1");

    expect(store.selectChat).not.toHaveBeenCalled();
    expect(store.newChat).not.toHaveBeenCalled();
  });

  it("an unknown id goes back to / with a notice, after one refresh of the list", async () => {
    const { store } = fakeStore(["c1"]);
    const replaced: string[] = [];

    const page = await setup(store, "/chat/ghost", {
      before: (router) => {
        const history = router.options.history;
        const replace = history.replace.bind(history);
        history.replace = (to, data) => {
          replaced.push(to);
          replace(to, data);
        };
      },
    });

    expect(replaced.at(-1)).toBe("/"); // a replacement, not an extra history entry
    expect(store.reload).toHaveBeenCalledOnce();
    expect(store.selectChat).not.toHaveBeenCalled();
    expect(page.router.currentRoute.value.path).toBe("/");
    expect(page.notFound.value).toBe(true);
    // Replaced, so back does not return to the address that failed.
    expect(await backTarget(page.router)).toBe("/");
  });

  it("the notice goes away once a chat that exists is opened by address", async () => {
    const { store } = fakeStore(["c1"]);
    const page = await setup(store, "/chat/ghost");
    expect(page.notFound.value).toBe(true);

    await page.router.push("/chat/c1");
    await flushPromises();

    expect(page.notFound.value).toBe(false);
    expect(store.selectChat).toHaveBeenCalledExactlyOnceWith("c1");
  });

  it("opens a chat that only showed up after the refresh (made in another tab)", async () => {
    const { store, known } = fakeStore([]);
    store.reload.mockImplementation(async () => {
      known.add("new");
    });

    const page = await setup(store, "/chat/new");

    expect(store.selectChat).toHaveBeenCalledExactlyOnceWith("new");
    expect(page.notFound.value).toBe(false);
    expect(page.router.currentRoute.value.path).toBe("/chat/new");
  });

  it("does not report a missing chat when the user already went elsewhere", async () => {
    const { store } = fakeStore(["other"]);
    let finish!: () => void;
    store.reload.mockImplementation(() => new Promise<void>((resolve) => (finish = resolve)));
    const page = await setup(store, "/chat/ghost");

    await page.router.push("/chat/other");
    finish();
    await flushPromises();

    expect(page.notFound.value).toBe(false);
    expect(page.router.currentRoute.value.path).toBe("/chat/other");
  });

  it("reads an escaped id back", async () => {
    const { store } = fakeStore(["a b/c"]);

    await setup(store, chatPath("a b/c"));

    expect(store.selectChat).toHaveBeenCalledExactlyOnceWith("a b/c");
  });
});

describe("open and startNew (the user's own choices)", () => {
  it("open selects the chat and adds a history entry", async () => {
    const { store } = fakeStore(["c1"]);
    const page = await setup(store, "/");

    page.open("c1", { messageIndex: 3 });
    await flushPromises();

    expect(store.selectChat).toHaveBeenCalledExactlyOnceWith("c1", { messageIndex: 3 });
    expect(page.router.currentRoute.value.path).toBe("/chat/c1");
    expect(await backTarget(page.router)).toBe("/");
  });

  it("opening the chat that is open again (a search hit) does not pile up entries", async () => {
    const { store } = fakeStore(["c1"]);
    const page = await setup(store, "/");
    page.open("c1");
    await flushPromises();

    page.open("c1", { messageIndex: 2 });
    await flushPromises();

    expect(await backTarget(page.router)).toBe("/");
    expect(store.selectChat).toHaveBeenLastCalledWith("c1", { messageIndex: 2 });
  });

  it("startNew clears the open chat and adds a history entry for /", async () => {
    const { store } = fakeStore(["c1"]);
    const page = await setup(store, "/chat/c1");

    page.startNew();
    await flushPromises();

    expect(store.newChat).toHaveBeenCalledOnce();
    expect(page.router.currentRoute.value.path).toBe("/");
    expect(await backTarget(page.router)).toBe("/chat/c1");
  });

  it("startNew clears the chat even when the address is already /", async () => {
    const { store } = fakeStore(["c1"]);
    const page = await setup(store, "/");

    page.startNew();
    await flushPromises();

    expect(store.newChat).toHaveBeenCalledOnce();
  });

  it("open on the address that is already showing starts no navigation", async () => {
    const { store } = fakeStore(["c1"]);
    const page = await setup(store, "/chat/c1");
    const push = vi.spyOn(page.router, "push");

    page.open("c1", { messageIndex: 1 });
    await flushPromises();

    expect(push).not.toHaveBeenCalled();
    expect(store.selectChat).toHaveBeenLastCalledWith("c1", { messageIndex: 1 });
  });

  it("open clears the not-found notice", async () => {
    const { store } = fakeStore(["c1"]);
    const page = await setup(store, "/chat/ghost");
    expect(page.notFound.value).toBe(true);

    page.open("c1");

    expect(page.notFound.value).toBe(false);
  });

  it("startNew clears the not-found notice", async () => {
    const { store } = fakeStore([]);
    const page = await setup(store, "/chat/ghost");
    expect(page.notFound.value).toBe(true);

    page.startNew();

    expect(page.notFound.value).toBe(false);
  });
});

describe("back and forward", () => {
  it("back returns to the chat opened before", async () => {
    const { store } = fakeStore(["c1", "c2"]);
    const page = await setup(store, "/");
    page.open("c1");
    await flushPromises();
    page.open("c2");
    await flushPromises();
    store.selectChat.mockClear();

    page.router.back();
    await flushPromises();

    expect(store.selectChat).toHaveBeenCalledExactlyOnceWith("c1");
  });

  it("back to / starts a fresh chat", async () => {
    const { store } = fakeStore(["c1"]);
    const page = await setup(store, "/");
    page.open("c1");
    await flushPromises();

    page.router.back();
    await flushPromises();

    expect(store.newChat).toHaveBeenCalledOnce();
  });

  it("forward reopens the chat", async () => {
    const { store } = fakeStore(["c1"]);
    const page = await setup(store, "/");
    page.open("c1");
    await flushPromises();
    page.router.back();
    await flushPromises();
    store.selectChat.mockClear();

    page.router.forward();
    await flushPromises();

    expect(store.selectChat).toHaveBeenCalledExactlyOnceWith("c1");
  });

  it("does not start a second navigation for its own push", async () => {
    const { store } = fakeStore(["c1"]);
    const page = await setup(store, "/");
    const push = vi.spyOn(page.router, "push");
    const replace = vi.spyOn(page.router, "replace");

    page.open("c1");
    await flushPromises();

    expect(push).toHaveBeenCalledOnce();
    expect(replace).not.toHaveBeenCalled();
  });
});

describe("changes nobody asked the address for", () => {
  it("a new chat getting its id replaces / instead of adding an entry", async () => {
    const { store, activeId } = fakeStore([]);
    const page = await setup(store, "/");

    activeId.value = "made"; // the first question created the chat
    await flushPromises();

    expect(page.router.currentRoute.value.path).toBe("/chat/made");
    expect(await backTarget(page.router)).toBe("/chat/made"); // no earlier entry to go back to
    expect(store.selectChat).not.toHaveBeenCalled();
  });

  it("deleting the open chat replaces its address with /", async () => {
    const { store, activeId } = fakeStore(["c1"]);
    const page = await setup(store, "/chat/c1");
    expect(activeId.value).toBe("c1");

    activeId.value = null;
    await flushPromises();

    expect(page.router.currentRoute.value.path).toBe("/");
    expect(await backTarget(page.router)).toBe("/"); // replaced: nothing earlier
    expect(store.newChat).not.toHaveBeenCalled();
  });

  it("leaves the address alone while the chat list is still loading", async () => {
    const { store, activeId } = fakeStore(["c1"], false);
    const page = await setup(store, "/chat/c1");

    activeId.value = "other";
    await flushPromises();

    expect(page.router.currentRoute.value.path).toBe("/chat/c1");
  });
});

describe("while the page is cached behind another one", () => {
  it("ignores the address", async () => {
    const { store } = fakeStore(["c1"]);
    const page = await setup(store, "/", { shown: false });

    await page.router.push("/chat/c1");
    await flushPromises();

    expect(store.selectChat).not.toHaveBeenCalled();
  });

  it("does not rewrite a chat address while the page is cached", async () => {
    const { store, activeId } = fakeStore(["c1"]);
    const page = await setup(store, "/", { shown: false });

    activeId.value = "c1";
    await flushPromises();

    expect(page.router.currentRoute.value.path).toBe("/");
  });

  it("does not drag the address away from another page when the chat changes", async () => {
    const { store, activeId } = fakeStore(["c1"]);
    const page = await setup(store, "/");
    await page.router.push("/tools");
    await flushPromises();

    activeId.value = "c1";
    await flushPromises();

    expect(page.router.currentRoute.value.path).toBe("/tools");
  });

  it("leaving for another page does not start a fresh chat", async () => {
    const { store, activeId } = fakeStore(["c1"]);
    const page = await setup(store, "/chat/c1");
    expect(activeId.value).toBe("c1");

    page.shown.value = false; // ChatView's onDeactivated
    await page.router.push("/tools");
    await flushPromises();

    expect(store.newChat).not.toHaveBeenCalled();
    expect(activeId.value).toBe("c1");
  });

  it("coming back to a bare / keeps the chat that was open", async () => {
    const { store, activeId } = fakeStore(["c1"]);
    const page = await setup(store, "/chat/c1");
    page.shown.value = false;
    await page.router.push("/tools");
    await page.router.push("/"); // the Chat tab
    await flushPromises();

    page.shown.value = true; // onActivated
    page.activate();
    await flushPromises();

    expect(store.newChat).not.toHaveBeenCalled();
    expect(activeId.value).toBe("c1");
    expect(page.router.currentRoute.value.path).toBe("/chat/c1");
    // The bare / was replaced, so back goes to the page before it.
    expect(await backTarget(page.router)).toBe("/tools");
  });

  it("coming back to a bare / with no chat open stays on /", async () => {
    const { store } = fakeStore(["c1"]);
    const page = await setup(store, "/");
    page.shown.value = false;
    await page.router.push("/tools");
    await page.router.push("/");

    page.shown.value = true;
    page.activate();
    await flushPromises();

    expect(page.router.currentRoute.value.path).toBe("/");
    expect(store.newChat).not.toHaveBeenCalled();
  });

  it("coming back to a chat address opens that chat", async () => {
    const { store } = fakeStore(["c1", "c2"]);
    const page = await setup(store, "/chat/c1");
    page.shown.value = false;
    await page.router.push("/tools");
    await page.router.push("/chat/c2");
    await flushPromises();
    store.selectChat.mockClear();

    page.shown.value = true;
    page.activate();
    await flushPromises();

    expect(store.selectChat).toHaveBeenCalledExactlyOnceWith("c2");
  });
});
