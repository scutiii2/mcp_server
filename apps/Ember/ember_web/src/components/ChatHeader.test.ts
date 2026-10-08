import { useAuthStore } from "../stores/auth";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ChatHeader from "./ChatHeader.vue";

// The agent tag talks to ember_api; the header only needs it to be there.
vi.mock("./EntryAgentTag.vue", () => ({ default: { template: '<div class="agent-tag">Talking to Test Agent</div>' } }));

type Props = InstanceType<typeof ChatHeader>["$props"];

function mountHeader(props: Partial<Props> = {}) {
  return mount(ChatHeader, {
    props: { title: "Usage page", hasMessages: true, contextPercent: 38, locked: false, ...props },
    attachTo: document.body,
  });
}

const iconButton = (w: ReturnType<typeof mountHeader>, label: string) =>
  w.findAll("button.action").find((b) => b.text() === label)!;
const menuItem = (label: string) =>
  [...document.querySelectorAll<HTMLButtonElement>("[role='menuitem']")].find((b) => b.textContent?.trim() === label)!;

beforeEach(() => {
  setActivePinia(createPinia());
  useAuthStore().account = { id: 1, username: "admin", email: "a@example.com", email_verified: true, roles: [], permissions: ["chat.share"] };
  document.body.innerHTML = "";
});

describe("ChatHeader", () => {
  it("shows the title and the agent it talks to", () => {
    const w = mountHeader();

    expect(w.get("h2.title").text()).toBe("Usage page");
    expect(w.text()).toContain("Talking to Test Agent");
  });

  it("shows the context meter, and marks it high from 50%", () => {
    const w = mountHeader({ contextPercent: 38 });
    expect(w.get(".context").text()).toContain("38%");
    expect(w.get(".meter").attributes("aria-valuenow")).toBe("38");
    expect(w.get(".context").classes()).not.toContain("high");

    const high = mountHeader({ contextPercent: 62 });
    expect(high.get(".context").classes()).toContain("high");
  });

  it("leaves out the meter before any answer", () => {
    expect(mountHeader({ contextPercent: null }).find(".context").exists()).toBe(false);
  });

  it("leaves out the actions while the chat has no messages", () => {
    const w = mountHeader({ hasMessages: false });

    expect(w.findAll("button.action")).toHaveLength(0);
  });

  it("emits export and share from its icon buttons", async () => {
    const w = mountHeader();

    await iconButton(w, "Export").trigger("click");
    await iconButton(w, "Share").trigger("click");

    expect(w.emitted("export")).toHaveLength(1);
    expect(w.emitted("share")).toHaveLength(1);
  });

  it("opens a menu with Summarize and Clear, and emits the one chosen", async () => {
    const w = mountHeader();
    expect(iconButton(w, "More").attributes("aria-expanded")).toBe("false");

    await iconButton(w, "More").trigger("click");
    expect(iconButton(w, "More").attributes("aria-expanded")).toBe("true");
    expect(menuItem("Summarize")).toBeTruthy();

    menuItem("Clear").click();
    await w.vm.$nextTick();

    expect(w.emitted("clear")).toHaveLength(1);
    expect(w.emitted("summarize")).toBeUndefined();
    expect(document.querySelector("[role='menu']")).toBeNull();
  });

  it("closes the menu with a second press on the button", async () => {
    const w = mountHeader();

    await iconButton(w, "More").trigger("click");
    await iconButton(w, "More").trigger("click");

    expect(document.querySelector("[role='menu']")).toBeNull();
  });

  it("switches Summarize and Clear off while an answer is being written", async () => {
    const w = mountHeader({ locked: true });

    await iconButton(w, "More").trigger("click");

    expect(menuItem("Summarize").getAttribute("aria-disabled")).toBe("true");
    expect(menuItem("Clear").getAttribute("aria-disabled")).toBe("true");
    menuItem("Clear").click();
    expect(w.emitted("clear")).toBeUndefined();
  });
});

it("does not offer public sharing without chat.share", () => {
  useAuthStore().account!.permissions = [];
  expect(iconButton(mountHeader(), "Share")).toBeUndefined();
});
