import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Account } from "../api/AuthClient";
import { ApiError } from "../api/http";
import { userExtensionsClient, type UserExtension } from "../api/UserExtensionsClient";
import { useAuthStore } from "../stores/auth";
import UserExtensionModal from "./UserExtensionModal.vue";

vi.mock("../api/UserExtensionsClient", () => ({
  userExtensionsClient: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));

const client = vi.mocked(userExtensionsClient);

const SAVED: UserExtension = {
  id: "notes",
  label: "Notes",
  description: "work",
  url: "https://notes.example.com/mcp",
  header_names: ["X-Key"],
  enabled: true,
  status: "connected",
  error: null,
  tools: ["search"],
};
const ACCOUNT: Account = { id: 1, username: "lex", email: "l@e.com", email_verified: true, roles: [], permissions: ["chat.use"] };

function open(extension: UserExtension | null = null) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().account = ACCOUNT;
  return mount(UserExtensionModal, { props: { open: true, extension }, global: { plugins: [pinia] } });
}

const type = (w: ReturnType<typeof open>, name: string, value: string) => w.get(`input[name=${name}]`).setValue(value);

beforeEach(() => {
  // jsdom has no modal dialogs.
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
  vi.resetAllMocks();
  client.list.mockResolvedValue([]);
});

describe("adding", () => {
  it("sends the label, address and description, and no headers when none were typed", async () => {
    client.create.mockResolvedValue({ ...SAVED, id: "mine" });
    const w = open();
    await type(w, "label", "Mine");
    await type(w, "url", "https://mine.example.com/mcp");

    await w.get("form").trigger("submit");
    await flushPromises();

    expect(client.create).toHaveBeenCalledWith({ label: "Mine", url: "https://mine.example.com/mcp", description: "" });
    expect(w.emitted("saved")![0]![0]).toMatchObject({ id: "mine" });
  });

  it("sends typed headers, with the value masked", async () => {
    client.create.mockResolvedValue(SAVED);
    const w = open();
    await type(w, "label", "Notes");
    await type(w, "url", "https://notes.example.com/mcp");
    await w.get("button.add-header").trigger("click");
    await w.get("input.header-name").setValue("X-Key");
    await w.get("input.header-value").setValue("s3cret");

    expect(w.get("input.header-value").attributes("type")).toBe("password");
    await w.get("form").trigger("submit");
    await flushPromises();

    expect(client.create).toHaveBeenCalledWith({
      label: "Notes",
      url: "https://notes.example.com/mcp",
      description: "",
      headers: { "X-Key": "s3cret" },
    });
  });

  it("ignores a header row left empty and lets a row be removed", async () => {
    client.create.mockResolvedValue(SAVED);
    const w = open();
    await type(w, "label", "Notes");
    await type(w, "url", "https://notes.example.com/mcp");
    await w.get("button.add-header").trigger("click");
    await w.get("button.add-header").trigger("click");
    await w.findAll("input.header-name")[0]!.setValue("A");
    await w.findAll("input.header-value")[0]!.setValue("1");
    await w.findAll("button.remove-header")[1]!.trigger("click");

    await w.get("form").trigger("submit");
    await flushPromises();

    expect(client.create.mock.calls[0]![0]).toMatchObject({ headers: { A: "1" } });
    expect(w.findAll("input.header-name")).toHaveLength(1);
  });

  it("shows the server's message and stays open when it refuses", async () => {
    client.create.mockRejectedValue(new ApiError(422, "Enter an http or https address"));
    const w = open();
    await type(w, "label", "Bad");
    await type(w, "url", "ftp://bad");

    await w.get("form").trigger("submit");
    await flushPromises();

    expect(w.get("[role=alert]").text()).toBe("Enter an http or https address");
    expect(w.emitted("saved")).toBeUndefined();
    expect(w.emitted("close")).toBeUndefined();
  });

  it("disables the button while saving", async () => {
    let finish!: (value: UserExtension) => void;
    client.create.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const w = open();
    await type(w, "label", "Notes");
    await type(w, "url", "https://notes.example.com/mcp");

    await w.get("form").trigger("submit");

    expect(w.get("button[type=submit]").attributes("disabled")).toBeDefined();
    finish(SAVED);
    await flushPromises();
    expect(w.get("button[type=submit]").attributes("disabled")).toBeUndefined();
  });

  it("closes from Cancel", async () => {
    const w = open();

    await w.findAll("button").find((b) => b.text() === "Cancel")!.trigger("click");

    expect(w.emitted("close")).toHaveLength(1);
  });
});

describe("editing", () => {
  it("fills the form, lists the saved header names and shows no value inputs", () => {
    const w = open(SAVED);

    expect((w.get("input[name=label]").element as HTMLInputElement).value).toBe("Notes");
    expect((w.get("input[name=url]").element as HTMLInputElement).value).toBe("https://notes.example.com/mcp");
    expect((w.get("input[name=description]").element as HTMLInputElement).value).toBe("work");
    expect(w.get(".saved-headers").text()).toContain("X-Key");
    expect(w.find("input.header-value").exists()).toBe(false);
  });

  it("keeps the saved headers by not sending any", async () => {
    client.update.mockResolvedValue({ ...SAVED, label: "Renamed" });
    const w = open(SAVED);
    await type(w, "label", "Renamed");

    await w.get("form").trigger("submit");
    await flushPromises();

    expect(client.update).toHaveBeenCalledWith("notes", {
      label: "Renamed",
      url: "https://notes.example.com/mcp",
      description: "work",
    });
    expect(w.emitted("saved")![0]![0]).toMatchObject({ label: "Renamed" });
  });

  it("replaces the headers with what is typed after Replace headers", async () => {
    client.update.mockResolvedValue(SAVED);
    const w = open(SAVED);

    await w.get("button.replace-headers").trigger("click");
    await w.get("button.add-header").trigger("click");
    await w.get("input.header-name").setValue("Authorization");
    await w.get("input.header-value").setValue("Bearer t0ken");
    await w.get("form").trigger("submit");
    await flushPromises();

    expect(client.update.mock.calls[0]![1]).toMatchObject({ headers: { Authorization: "Bearer t0ken" } });
  });

  it("removes every header when the editor is opened and left empty", async () => {
    client.update.mockResolvedValue({ ...SAVED, header_names: [] });
    const w = open(SAVED);

    await w.get("button.replace-headers").trigger("click");
    await w.get("form").trigger("submit");
    await flushPromises();

    expect(client.update.mock.calls[0]![1]).toMatchObject({ headers: {} });
  });

  it("warns that saved headers go when the address moves to another host", async () => {
    const w = open(SAVED);
    expect(w.find(".host-warning").exists()).toBe(false);

    await type(w, "url", "https://other.example.org/mcp");
    expect(w.get(".host-warning").text()).toContain("saved headers");

    await type(w, "url", "https://notes.example.com/other-path");
    expect(w.find(".host-warning").exists()).toBe(false);

    await type(w, "url", "https://other.example.org/mcp");
    await w.get("button.replace-headers").trigger("click");
    expect(w.find(".host-warning").exists()).toBe(false);
  });

  it("does not warn about headers an extension never had", async () => {
    const w = open({ ...SAVED, header_names: [] });

    await type(w, "url", "https://other.example.org/mcp");

    expect(w.find(".host-warning").exists()).toBe(false);
    expect(w.get(".saved-headers").text()).toContain("No headers");
  });
});
