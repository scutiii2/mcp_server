<script setup lang="ts">
import { computed, reactive } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";
import { errorMessage } from "../utils/errors";

const auth = useAuthStore();
const router = useRouter();

// The router only opens this page with an account.
const account = computed(() => auth.account!);

const emailForm = reactive({ email: "", password: "", busy: false, error: "" });
const passwordForm = reactive({ next: "", confirm: "", current: "", busy: false, error: "", done: false });

const passwordMismatch = computed(() => passwordForm.confirm !== "" && passwordForm.next !== passwordForm.confirm);

async function changeEmail(): Promise<void> {
  emailForm.error = "";
  emailForm.busy = true;
  try {
    const result = await auth.changeEmail(emailForm.password, emailForm.email.trim());
    emailForm.email = "";
    emailForm.password = "";
    if (result.account.email_verified) {
      emailForm.error = "That is already your email.";
    } else {
      // Permissions are off until the new address is verified.
      await router.replace({ name: "verify-email", query: result.verification_email_sent ? {} : { unsent: "1" } });
    }
  } catch (err) {
    emailForm.error = errorMessage(err);
  } finally {
    emailForm.busy = false;
  }
}

async function changePassword(): Promise<void> {
  passwordForm.error = "";
  passwordForm.done = false;
  if (passwordMismatch.value) return;
  passwordForm.busy = true;
  try {
    await auth.changePassword(passwordForm.current, passwordForm.next);
    passwordForm.next = "";
    passwordForm.confirm = "";
    passwordForm.current = "";
    passwordForm.done = true;
  } catch (err) {
    passwordForm.error = errorMessage(err);
  } finally {
    passwordForm.busy = false;
  }
}
</script>

<template>
  <section class="account-view">
    <div class="column">
      <h2>Account</h2>

      <dl class="profile">
        <dt>Username</dt>
        <dd>{{ account.username }}</dd>
        <dt>Email</dt>
        <dd>
          {{ account.email }}
          <span v-if="account.email_verified" class="badge">verified</span>
          <RouterLink v-else to="/verify-email" class="badge warn">unverified - verify now</RouterLink>
        </dd>
        <dt>Roles</dt>
        <dd>{{ account.roles.join(", ") || "None" }}</dd>
        <dt>Permissions</dt>
        <dd>
          <template v-if="account.permissions.length">
            <code v-for="p in account.permissions" :key="p">{{ p }}</code>
          </template>
          <span v-else class="muted">None</span>
          <span v-if="!account.email_verified && account.permissions.length" class="muted">
            (inactive until your email is verified)
          </span>
        </dd>
      </dl>

      <h3>Change email</h3>
      <p class="muted hint">You'll get a code at the new address. Until you enter it, your permissions are paused.</p>
      <form class="stack" @submit.prevent="changeEmail">
        <label>
          New email
          <input v-model="emailForm.email" type="email" autocomplete="email" required />
        </label>
        <label>
          Current password
          <input v-model="emailForm.password" type="password" autocomplete="current-password" required />
        </label>
        <p v-if="emailForm.error" class="error">{{ emailForm.error }}</p>
        <button class="primary" :disabled="emailForm.busy">Change email</button>
      </form>

      <h3>Change password</h3>
      <p class="muted hint">Other devices where you're logged in will be logged out.</p>
      <form class="stack" @submit.prevent="changePassword">
        <label>
          New password
          <input v-model="passwordForm.next" type="password" autocomplete="new-password" minlength="8" required />
        </label>
        <label>
          Repeat new password
          <input v-model="passwordForm.confirm" type="password" autocomplete="new-password" required />
        </label>
        <label>
          Current password
          <input v-model="passwordForm.current" type="password" autocomplete="current-password" required />
        </label>
        <p v-if="passwordMismatch" class="error">The new passwords don't match.</p>
        <p v-else-if="passwordForm.error" class="error">{{ passwordForm.error }}</p>
        <p v-else-if="passwordForm.done" class="notice">Password changed.</p>
        <button class="primary" :disabled="passwordForm.busy || passwordMismatch">Change password</button>
      </form>
    </div>
  </section>
</template>

<style scoped>
.account-view {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.column {
  max-width: 820px;
  margin: 0 auto;
  padding: 24px 16px;
}
h2 {
  margin: 0 0 16px;
  font-size: 1.2em;
}
h3 {
  margin: 28px 0 4px;
  font-size: 1em;
}
.profile {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 8px 16px;
  margin: 0;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
}
.profile dt {
  color: var(--muted);
}
.profile dd {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin: 0;
  overflow-wrap: anywhere;
}
.profile code {
  padding: 1px 6px;
  border-radius: 6px;
  font-family: var(--mono);
  font-size: 0.9em;
  background: var(--code-bg);
}
.badge {
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 0.75em;
  color: var(--muted);
  text-decoration: none;
}
.badge.warn {
  color: var(--danger);
  border-color: var(--danger);
}
.hint {
  margin: 0 0 10px;
  font-size: 0.9em;
}
.stack {
  display: grid;
  gap: 10px;
  max-width: 380px;
}
.stack label {
  display: grid;
  gap: 4px;
  font-size: 0.9em;
}
.stack input {
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  background: var(--bg);
  font: inherit;
}
.stack p {
  margin: 0;
}
.primary {
  justify-self: start;
  padding: 7px 18px;
  border: none;
  border-radius: 999px;
  cursor: pointer;
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
.primary:disabled {
  cursor: default;
  opacity: 0.5;
}
.muted {
  color: var(--muted);
}
.error {
  color: var(--danger);
}
.notice {
  color: var(--muted);
}
@media (max-width: 480px) {
  .profile {
    grid-template-columns: 1fr;
    gap: 2px;
  }
  .profile dd {
    margin-bottom: 8px;
  }
}
</style>
