<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { authClient, type KnownDevice } from "../api/AuthClient";
import ActionButton from "../components/ActionButton.vue";
import ConfirmModal from "../components/admin/ConfirmModal.vue";
import { useAuthStore } from "../stores/auth";
import { errorMessage, formatUtc } from "../utils/errors";

const auth = useAuthStore();
const router = useRouter();

// The router only opens this page with an account.
const account = computed(() => auth.account!);
const initial = computed(() => account.value.username.charAt(0).toUpperCase());

// Which security form is open; one at a time keeps the page short.
const openForm = ref<"email" | "password" | null>(null);

function toggle(form: "email" | "password"): void {
  openForm.value = openForm.value === form ? null : form;
}

const emailForm = reactive({ email: "", password: "", busy: false, error: "", success: "" });
const passwordForm = reactive({ next: "", confirm: "", current: "", busy: false, error: "", done: false });

const passwordMismatch = computed(() => passwordForm.confirm !== "" && passwordForm.next !== passwordForm.confirm);

async function changeEmail(): Promise<void> {
  emailForm.error = "";
  emailForm.success = "";
  emailForm.busy = true;
  try {
    const result = await auth.changeEmail(emailForm.password, emailForm.email.trim());
    emailForm.email = "";
    emailForm.password = "";
    if (result.account.email_verified) {
      emailForm.error = "That is already your email.";
    } else if (result.account.email_verification_required === false) {
      emailForm.success = "Email changed. You can verify it any time from this page.";
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

// Devices this account logged in from; a login from a new one is noted in
// the activity log. Forgetting one makes its next login "new" again.
const devices = ref<KnownDevice[]>([]);
const devicesError = ref("");

async function loadDevices(): Promise<void> {
  try {
    devices.value = await authClient.devices();
    devicesError.value = "";
  } catch (err) {
    devicesError.value = errorMessage(err);
  }
}

// Forgetting a device asks first, in the confirmation dialog.
const pendingForget = ref<KnownDevice | null>(null);

async function forgetDevice(device: KnownDevice): Promise<void> {
  pendingForget.value = null;
  try {
    await authClient.forgetDevice(device.id);
    devices.value = devices.value.filter((d) => d.id !== device.id);
  } catch (err) {
    devicesError.value = errorMessage(err);
  }
}

onMounted(loadDevices);

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

      <div v-if="!account.email_verified" class="banner" role="status">
        <span>
          {{
            auth.needsVerification
              ? "Your email isn't verified. Permissions are paused until you enter the code."
              : "Your email isn't verified. Verifying it is optional."
          }}
        </span>
        <ActionButton icon="verify" class="verify" @click="router.push('/verify-email')">Verify now</ActionButton>
      </div>

      <div class="card profile">
        <div class="identity">
          <div class="avatar" aria-hidden="true">{{ initial }}</div>
          <div class="who">
            <div class="name">{{ account.username }}</div>
            <div class="email">
              {{ account.email }}
              <span v-if="account.email_verified" class="chip ok">verified</span>
            </div>
            <div class="roles">
              <span v-for="r in account.roles" :key="r" class="chip">{{ r }}</span>
              <span v-if="!account.roles.length" class="muted small">No roles</span>
            </div>
          </div>
        </div>
        <details class="permissions">
          <summary>
            {{ account.permissions.length }} {{ account.permissions.length === 1 ? "permission" : "permissions" }}
            <span v-if="auth.needsVerification && account.permissions.length" class="muted">(inactive until your email is verified)</span>
          </summary>
          <div class="perm-list">
            <code v-for="p in account.permissions" :key="p">{{ p }}</code>
          </div>
        </details>
      </div>

      <section class="card" aria-labelledby="account-security">
        <h3 id="account-security">Security</h3>

        <div class="row">
          <div>
            <div>Email</div>
            <div class="muted small">
              {{
                auth.account?.email_verification_required === false
                  ? "You'll get a code at the new address. Verifying it is optional."
                  : "You'll get a code at the new address. Until you enter it, your permissions are paused."
              }}
            </div>
          </div>
          <ActionButton :icon="openForm === 'email' ? 'close' : 'mail'" class="toggle-email" :aria-expanded="openForm === 'email'" @click="toggle('email')">
            {{ openForm === "email" ? "Close" : "Change" }}
          </ActionButton>
        </div>
        <form v-if="openForm === 'email'" class="stack" @submit.prevent="changeEmail">
          <label>
            New email
            <input v-model="emailForm.email" type="email" autocomplete="email" required />
          </label>
          <label>
            Current password
            <input v-model="emailForm.password" type="password" autocomplete="current-password" required />
          </label>
          <p v-if="emailForm.error" class="error">{{ emailForm.error }}</p>
          <p v-else-if="emailForm.success" class="notice">{{ emailForm.success }}</p>
          <button class="primary" :disabled="emailForm.busy">Change email</button>
        </form>

        <div class="row">
          <div>
            <div>Password</div>
            <div class="muted small">Other devices where you're logged in will be logged out.</div>
          </div>
          <ActionButton
            :icon="openForm === 'password' ? 'close' : 'lock'"
            class="toggle-password"
            :aria-expanded="openForm === 'password'"
            @click="toggle('password')"
          >
            {{ openForm === "password" ? "Close" : "Change" }}
          </ActionButton>
        </div>
        <form v-if="openForm === 'password'" class="stack" @submit.prevent="changePassword">
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
      </section>

      <section class="card" aria-labelledby="account-devices">
        <div class="head">
          <h3 id="account-devices">Devices</h3>
          <span class="muted small">A login from a new one is noted in the activity log</span>
        </div>
        <p v-if="devicesError" class="error">{{ devicesError }}</p>
        <p v-else-if="devices.length === 0" class="muted">None recorded yet.</p>
        <ul v-else class="devices">
          <li v-for="d in devices" :key="d.id" :title="d.user_agent || '(no browser name)'">
            <svg class="device-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M2 3h12v8H2zM5 14h6M8 11v3" /></svg>
            <div class="device-main">
              <div class="device-name">
                <strong>{{ d.label }}</strong>
                <span v-if="d.current" class="chip ok">this device</span>
              </div>
              <div class="muted small">
                {{ d.ip_subnet }} · last used {{ formatUtc(d.last_seen_at) }} · first {{ formatUtc(d.first_seen_at) }}
              </div>
            </div>
            <ActionButton v-if="!d.current" icon="close" quiet class="forget" @click="pendingForget = d">Forget</ActionButton>
          </li>
        </ul>
      </section>
    </div>

    <ConfirmModal
      v-if="pendingForget"
      open
      title="Forget device"
      :message="`Forget ${pendingForget.label}? Its next login is noted in the activity log as a new device.`"
      confirm-label="Forget"
      @confirm="forgetDevice(pendingForget)"
      @close="pendingForget = null"
    />
  </section>
</template>

<style scoped>
.account-view {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.column {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 820px;
  margin: 0 auto;
  padding: 24px 16px;
}
h2 {
  margin: 0;
  font-size: 1.2em;
}
h3 {
  margin: 0;
  font-size: 1em;
}
.card {
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
}
.card > h3 {
  margin-bottom: 4px;
}
.head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 4px 12px;
  margin-bottom: 8px;
}
.banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 12px;
  padding: 10px 14px;
  border: 1px solid var(--danger);
  border-radius: var(--radius-md);
  font-size: 0.9em;
  color: var(--danger);
}
.identity {
  display: flex;
  align-items: center;
  gap: 16px;
}
.avatar {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  border-radius: var(--radius-full);
  font-size: 1.4em;
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
.who {
  min-width: 0;
}
.name {
  font-size: 1.2em;
  font-weight: 600;
}
.email {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin: 2px 0 6px;
  overflow-wrap: anywhere;
  color: var(--muted);
  font-size: 0.9em;
}
.roles {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip {
  padding: 1px 8px;
  border-radius: var(--radius-full);
  font-size: 0.75em;
  color: var(--muted);
  background: var(--code-bg);
}
.chip.ok {
  color: var(--accent);
}
.permissions {
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
  font-size: 0.9em;
}
.permissions summary {
  cursor: pointer;
  color: var(--muted);
}
.perm-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}
.perm-list code {
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  font-family: var(--mono);
  font-size: 0.9em;
  background: var(--code-bg);
}
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 0;
  border-top: 1px solid var(--border);
}
.row:first-of-type {
  border-top: none;
}
.small {
  font-size: 0.85em;
}
.muted {
  color: var(--muted);
}
.stack {
  display: grid;
  gap: 10px;
  max-width: 380px;
  margin: 0 0 12px;
  padding: 12px 14px;
  border-radius: var(--radius-md);
  background: var(--code-bg);
}
.stack label {
  display: grid;
  gap: 4px;
  font-size: 0.9em;
}
.stack input {
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
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
  border-radius: var(--radius-full);
  cursor: pointer;
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
.primary:disabled {
  cursor: default;
  opacity: 0.5;
}
.devices {
  margin: 0;
  padding: 0;
  list-style: none;
}
.devices li {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-top: 1px solid var(--border);
}
.devices li:first-child {
  padding-top: 0;
  border-top: none;
}
.device-icon {
  flex: none;
  box-sizing: content-box;
  width: 16px;
  height: 16px;
  padding: 8px;
  border-radius: var(--radius-md);
  fill: none;
  stroke: var(--muted);
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
  background: var(--code-bg);
}
.device-main {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}
.device-name {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.error {
  color: var(--danger);
}
.notice {
  color: var(--muted);
}
@media (max-width: 480px) {
  .identity {
    gap: 12px;
  }
  .devices li {
    align-items: flex-start;
  }
}
</style>
