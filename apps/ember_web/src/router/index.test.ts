import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { authClient, type Account } from "../api/AuthClient";
import { UnauthorizedError } from "../api/http";
import { router } from "./index";

vi.mock("../api/AuthClient", () => ({ authClient: { me: vi.fn() } }));

const me = vi.mocked(authClient.me);

const ACCOUNT: Account = {
  id: 1,
  username: "root",
  email: "root@example.com",
  email_verified: true,
  roles: [],
  permissions: ["chat.use"],
};

beforeEach(async () => {
  // Park the shared router on the login page as a visitor, then start the
  // test with a fresh auth store (the guard loads the account once per store)
  // and clean mocks.
  setActivePinia(createPinia());
  me.mockRejectedValue(new UnauthorizedError(401, "Not logged in"));
  await router.replace("/login");
  setActivePinia(createPinia());
  vi.clearAllMocks();
});

describe("shared chat route", () => {
  it("opens for someone who is not logged in, without asking who they are", async () => {
    me.mockRejectedValue(new UnauthorizedError(401, "Not logged in"));

    await router.push("/shared/abc123");

    expect(router.currentRoute.value.name).toBe("shared");
    expect(router.currentRoute.value.params.token).toBe("abc123");
    expect(me).not.toHaveBeenCalled();
  });

  it("stays put for a logged-in user, instead of redirecting them home", async () => {
    me.mockResolvedValue(ACCOUNT);

    await router.push("/shared/abc123");

    expect(router.currentRoute.value.name).toBe("shared");
  });

  it("stays put for an account whose email is not verified yet", async () => {
    me.mockResolvedValue({ ...ACCOUNT, email_verified: false });

    await router.push("/shared/abc123");

    expect(router.currentRoute.value.name).toBe("shared");
  });

  it("stays put for an account with no permissions", async () => {
    me.mockResolvedValue({ ...ACCOUNT, permissions: [] });

    await router.push("/shared/abc123");

    expect(router.currentRoute.value.name).toBe("shared");
  });
});

describe("the rest of the app stays behind the login", () => {
  it("sends a visitor who is not logged in to the login page", async () => {
    me.mockRejectedValue(new UnauthorizedError(401, "Not logged in"));

    await router.push("/usage");

    expect(router.currentRoute.value.name).toBe("login");
    expect(router.currentRoute.value.query.redirect).toBe("/usage");
  });

  it("does not turn other unknown paths into public pages", async () => {
    me.mockRejectedValue(new UnauthorizedError(401, "Not logged in"));

    await router.push("/shared");
    expect(router.currentRoute.value.name).toBe("login");

    await router.push("/sharedx/abc");
    expect(router.currentRoute.value.name).toBe("login");
  });

  it("only the shared route is marked public", () => {
    const publicRoutes = router.getRoutes().filter((r) => r.meta.public).map((r) => r.name);

    expect(publicRoutes).toEqual(["shared"]);
  });
});

describe("email verification", () => {
  const UNVERIFIED = { ...ACCOUNT, email_verified: false };

  it("sends an unverified account to the verify page when verification is required", async () => {
    me.mockResolvedValue({ ...UNVERIFIED, email_verification_required: true });

    await router.push("/");

    expect(router.currentRoute.value.name).toBe("verify-email");
  });

  it("treats a missing flag as required", async () => {
    me.mockResolvedValue(UNVERIFIED);

    await router.push("/");

    expect(router.currentRoute.value.name).toBe("verify-email");
  });

  it("lets an unverified account use the app when verification is not required", async () => {
    me.mockResolvedValue({ ...UNVERIFIED, email_verification_required: false });

    await router.push("/");

    expect(router.currentRoute.value.name).toBe("chat");
  });

  it("still opens the verify page for an unverified account when it is optional", async () => {
    me.mockResolvedValue({ ...UNVERIFIED, email_verification_required: false });

    await router.push("/verify-email");

    expect(router.currentRoute.value.name).toBe("verify-email");
  });

  it("sends a verified account away from the verify page", async () => {
    me.mockResolvedValue({ ...ACCOUNT, email_verification_required: false });

    await router.push("/verify-email");

    expect(router.currentRoute.value.name).toBe("chat");
  });
});

const ACCOUNT_WITH_TOOLS = { ...ACCOUNT, permissions: ["chat.use", "tools.use"] };

describe("the merged Capabilities page", () => {
  it("sends the old Tools address to Capabilities, keeping the filter", async () => {
    me.mockResolvedValue(ACCOUNT_WITH_TOOLS);

    await router.push("/tools?q=merge");

    expect(router.currentRoute.value.name).toBe("capabilities");
    expect(router.currentRoute.value.path).toBe("/capabilities");
    expect(router.currentRoute.value.query.q).toBe("merge");
  });

  it("sends the old Extensions address to Capabilities", async () => {
    me.mockResolvedValue(ACCOUNT_WITH_TOOLS);

    await router.push("/extensions");

    expect(router.currentRoute.value.name).toBe("capabilities");
  });

  it("sends the old page of one extension to Capabilities", async () => {
    me.mockResolvedValue(ACCOUNT_WITH_TOOLS);

    await router.push("/extensions/pdf");

    expect(router.currentRoute.value.name).toBe("capabilities");
  });

  it("opens for chat.use alone, to switch extensions", async () => {
    me.mockResolvedValue({ ...ACCOUNT, permissions: ["chat.use"] });

    await router.push("/capabilities");

    expect(router.currentRoute.value.name).toBe("capabilities");
  });

  it("opens the Supermarket for chat.use alone", async () => {
    me.mockResolvedValue({ ...ACCOUNT, permissions: ["chat.use"] });

    await router.push("/capabilities/supermarket");

    expect(router.currentRoute.value.name).toBe("supermarket");
  });

  it("keeps the Supermarket from being taken for a capability page", () => {
    expect(router.resolve("/capabilities/supermarket").name).toBe("supermarket");
    expect(router.resolve("/capabilities/pdf").name).toBe("capability-page");
  });


  it("stays closed to an account with neither tools.use nor chat.use", async () => {
    me.mockResolvedValue({ ...ACCOUNT, permissions: ["watchers.view"] });

    await router.push("/capabilities");

    expect(router.currentRoute.value.name).not.toBe("capabilities");
  });
});

describe("pages moved to Ember Admin", () => {
  it.each(["/admin", "/analytics", "/logs"])("opens the Web home for an old %s link", async (path) => {
    me.mockResolvedValue({ ...ACCOUNT, permissions: ["chat.use", "admin.manage", "logs.view"] });
    await router.push(path);
    expect(router.currentRoute.value.name).toBe("chat");
  });
  it("does not use Admin as a Web landing page", async () => {
    me.mockResolvedValue({ ...ACCOUNT, permissions: ["admin.manage"] });
    await router.push("/");
    expect(router.currentRoute.value.name).toBe("no-access");
  });
});
