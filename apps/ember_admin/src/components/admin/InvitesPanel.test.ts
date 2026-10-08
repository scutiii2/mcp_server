import { flushPromises, mount } from "@vue/test-utils";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { adminClient, type CreatedInvite, type Invite } from "../../api/AdminClient";
import { ApiError } from "../../api/http";
import ConfirmModal from "./ConfirmModal.vue";
import InvitesPanel from "./InvitesPanel.vue";

vi.mock("../../api/AdminClient", () => ({
  adminClient: { listInvites: vi.fn(), createInvite: vi.fn(), revokeInvite: vi.fn() },
}));

const client = vi.mocked(adminClient);

// jsdom has no <dialog> methods.
beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

const INVITE: Invite = {
  id: 5,
  invitee_email: "new@mail.com",
  delivery_method: "email",
  created_at: "2026-10-05T09:00:00",
  expires_at: "2026-10-05T09:15:00",
};

const CREATED: CreatedInvite = {
  invite: { ...INVITE, id: 6, invitee_email: null, delivery_method: "manual" },
  code: "ABCD-1234",
  email_sent: false,
  email_error: null,
};

async function panel() {
  const wrapper = mount(InvitesPanel);
  await flushPromises();
  return wrapper;
}

type Panel = Awaited<ReturnType<typeof panel>>;

const confirmDialog = (wrapper: Panel) => wrapper.getComponent(ConfirmModal);
const emailBox = (wrapper: Panel) => wrapper.get('input[role="switch"]');

beforeEach(() => {
  vi.clearAllMocks();
  client.listInvites.mockResolvedValue([INVITE]);
});

describe("InvitesPanel", () => {
  it("lists the open invites", async () => {
    const wrapper = await panel();

    expect(wrapper.findAll("tbody tr")).toHaveLength(1);
    expect(wrapper.get("tbody").text()).toContain("new@mail.com");
    expect(wrapper.get("tbody").text()).toContain("email");
  });

  it("says when there are none", async () => {
    client.listInvites.mockResolvedValue([]);

    expect((await panel()).text()).toContain("No open invites.");
  });

  it("shows an error when the list cannot be read", async () => {
    client.listInvites.mockRejectedValue(new ApiError(500, "boom"));

    expect((await panel()).text()).toContain("boom");
  });

  it("creates an invite, shows its code once, and reloads the list", async () => {
    client.createInvite.mockResolvedValue(CREATED);
    const wrapper = await panel();

    await wrapper.get('input[type="email"]').setValue("  ");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(client.createInvite).toHaveBeenCalledWith(null, "manual");
    expect(wrapper.get(".created").text()).toContain("ABCD-1234");
    expect(client.listInvites).toHaveBeenCalledTimes(2);
    expect(wrapper.emitted("changed")).toHaveLength(1);
  });

  it("emails the code only when asked and an address is given", async () => {
    client.createInvite.mockResolvedValue({ ...CREATED, email_sent: true });
    const wrapper = await panel();
    expect(emailBox(wrapper).attributes("disabled")).toBeDefined();

    await wrapper.get('input[type="email"]').setValue("a@b.co");
    expect(emailBox(wrapper).attributes("disabled")).toBeUndefined();
    await emailBox(wrapper).setValue(true);
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(client.createInvite).toHaveBeenCalledWith("a@b.co", "email");
  });

  it("switches emailing off when the address is cleared", async () => {
    const wrapper = await panel();
    await wrapper.get('input[type="email"]').setValue("a@b.co");
    await emailBox(wrapper).setValue(true);

    await wrapper.get('input[type="email"]').setValue("");

    expect((emailBox(wrapper).element as HTMLInputElement).checked).toBe(false);
  });

  it("shows when the email could not be sent", async () => {
    client.createInvite.mockResolvedValue({ ...CREATED, email_error: "SMTP down" });
    const wrapper = await panel();

    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(wrapper.get(".created").text()).toContain("Email failed: SMTP down");
  });

  it("shows why creating failed", async () => {
    client.createInvite.mockRejectedValue(new ApiError(422, "invitee_email is required for email delivery"));
    const wrapper = await panel();

    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(wrapper.text()).toContain("invitee_email is required");
    expect(wrapper.find(".created").exists()).toBe(false);
  });

  it("asks before revoking, and does nothing when cancelled", async () => {
    const wrapper = await panel();

    await wrapper.get("tbody button.danger").trigger("click");
    expect(confirmDialog(wrapper).props("open")).toBe(true);
    expect(confirmDialog(wrapper).props("message")).toBe("Revoke new@mail.com? Its code stops working.");

    await confirmDialog(wrapper).get(".cancel").trigger("click");

    expect(confirmDialog(wrapper).props("open")).toBe(false);
    expect(client.revokeInvite).not.toHaveBeenCalled();
  });

  it("revokes once confirmed and removes the row", async () => {
    client.revokeInvite.mockResolvedValue(undefined);
    const wrapper = await panel();

    await wrapper.get("tbody button.danger").trigger("click");
    await confirmDialog(wrapper).get(".confirm").trigger("click");
    await flushPromises();

    expect(client.revokeInvite).toHaveBeenCalledWith(5);
    expect(wrapper.find("tbody").exists()).toBe(false);
    expect(confirmDialog(wrapper).props("open")).toBe(false);
    expect(wrapper.emitted("changed")).toHaveLength(1);
  });

  it("hides the shown code when its invite is revoked", async () => {
    client.createInvite.mockResolvedValue(CREATED);
    client.listInvites.mockResolvedValueOnce([INVITE]).mockResolvedValue([INVITE, CREATED.invite]);
    client.revokeInvite.mockResolvedValue(undefined);
    const wrapper = await panel();
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.find(".created").exists()).toBe(true);

    await wrapper.findAll("tbody button.danger")[1]!.trigger("click");
    await confirmDialog(wrapper).get(".confirm").trigger("click");
    await flushPromises();

    expect(wrapper.find(".created").exists()).toBe(false);
  });

  it("shows why a revoke failed and keeps the row", async () => {
    client.revokeInvite.mockRejectedValue(new ApiError(409, "That invite was already used"));
    const wrapper = await panel();

    await wrapper.get("tbody button.danger").trigger("click");
    await confirmDialog(wrapper).get(".confirm").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("already used");
    expect(wrapper.findAll("tbody tr")).toHaveLength(1);
    expect(wrapper.emitted("changed")).toBeUndefined();
  });
});
