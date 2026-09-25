import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { authClient, type Account, type RegisterInput, type RegisterResult } from "../api/AuthClient";
import { onUnauthorized, UnauthorizedError } from "../api/http";

/** Who is logged in. Other stores watch `account` to reset per-user state. */
export const useAuthStore = defineStore("auth", () => {
  const account = ref<Account | null>(null);
  let loaded: Promise<void> | null = null;

  // Any 401 from ember_api means the session is gone.
  onUnauthorized(() => {
    account.value = null;
  });

  const permissions = computed(() => new Set(account.value?.permissions ?? []));

  function hasPermission(name: string): boolean {
    // Mirrors ember_api: an unverified email holds no permissions.
    return account.value?.email_verified === true && permissions.value.has(name);
  }

  /** Asks ember_api once per page load who is logged in (router guards await it). */
  function ensureLoaded(): Promise<void> {
    loaded ??= authClient
      .me()
      .then((me) => {
        account.value = me;
      })
      .catch((err: unknown) => {
        if (!(err instanceof UnauthorizedError)) console.warn("ember_web: /me failed", err);
        account.value = null;
      });
    return loaded;
  }

  async function login(username: string, password: string): Promise<void> {
    account.value = await authClient.login(username, password);
  }

  async function register(input: RegisterInput): Promise<RegisterResult> {
    const result = await authClient.register(input);
    account.value = result.account;
    return result;
  }

  async function verifyEmail(code: string): Promise<void> {
    account.value = await authClient.verifyEmail(code);
  }

  async function resendVerification(): Promise<void> {
    await authClient.resendVerification();
  }

  async function logout(): Promise<void> {
    try {
      await authClient.logout();
    } finally {
      account.value = null;
    }
  }

  return { account, hasPermission, ensureLoaded, login, register, verifyEmail, resendVerification, logout };
});
