<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { authClient, type KnownDevice } from "../api/AuthClient";
import ConfirmModal from "../components/admin/ConfirmModal.vue";
import { useAuthStore } from "../stores/auth";
import { errorMessage, formatUtc } from "../utils/errors";

const auth = useAuthStore();
const router = useRouter();

// The router only opens this page with an account.
const account = computed(() => auth.account!);

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

      <dl class="profile">
        <dt>Username</dt>
        <dd>{{ account.username }}</dd>
        <dt>Email</dt>
        <dd>
          {{ account.email }}
          <span v-if="account.email_verified" class="badge">verified</span>
          <RouterLink v-else to="/verify-email" class="badge warn">{{
            auth.needsVerification ? "unverified - verify now" : "unverified - verify (optional)"
          }}</RouterLink>
        </dd>
        <dt>Roles</dt>
        <dd>{{ account.roles.join(", ") || "None" }}</dd>
        <dt>Permissions</dt>
        <dd>
          <template v-if="account.permissions.length">
            <code v-for="p in account.permissions" :key="p">{{ p }}</code>
          </template>
          <span v-else class="muted">None</span>
          <span v-if="auth.needsVerification && account.permissions.length" class="muted">
            (inactive until your email is verified)
          </span>
        </dd>
      </dl>

      <section class="card" aria-labelledby="account-email">
        <h3 id="account-email">Change email</h3>
        <p v-if="auth.account?.email_verification_required === false" class="muted hint">
          You'll get a code at the new address. Verifying it is optional.
        </p>
        <p v-else class="muted hint">You'll get a code at the new address. Until you enter it, your permissions are paused.</p>
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
          <p v-else-if="emailForm.success" class="notice">{{ emailForm.success }}</p>
          <button class="primary" :disabled="emailForm.busy">Change email</button>
        </form>
      </section>

      <section class="card" aria-labelledby="account-password">
        <h3 id="account-password">Change password</h3>
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
      </section>

      <section class="card" aria-labelledby="account-devices">
        <h3 id="account-devices">Devices</h3>
        <p class="muted hint">
          Where you logged in from, told apart by browser and network. A login from a new one is noted in the activity log.
        </p>
        <p v-if="devicesError" class="error">{{ devicesError }}</p>
        <p v-else-if="devices.length === 0" class="muted">None recorded yet.</p>
        <ul v-else class="devices">
          <li v-for="d in devices" :key="d.id">
            <div class="device">
              <strong>{{ d.label }}</strong>
              <span v-if="d.current" class="badge">this device</span>
              <span class="muted">{{ d.ip_subnet }}</span>
            </div>
            <div class="muted small">
              last used {{ formatUtc(d.last_seen_at) }} · first {{ formatUtc(d.first_seen_at) }}
            </div>
            <div class="muted small ua" :title="d.user_agent">{{ d.user_agent || "(no browser name)" }}</div>
            <button v-if="!d.current" type="button" class="forget" @click="pendingForget = d">Forget</button>
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
  margin: 0 0 4px;
  font-size: 1em;
}
/* One block per task; the profile above is the same kind of card. */
.card {
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
}
.profile {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 8px 16px;
  margin: 0;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
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
  border-radius: var(--radius-sm);
  font-family: var(--mono);
  font-size: 0.9em;
  background: var(--code-bg);
}
.badge {
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
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
.muted {
  color: var(--muted);
}
.devices {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.devices li {
  position: relative;
  padding: 10px 90px 10px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg);
}
.device {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.small {
  font-size: 0.85em;
}
.ua {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.forget {
  position: absolute;
  top: 10px;
  right: 12px;
  padding: 3px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  cursor: pointer;
  color: var(--text);
  background: var(--bg);
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
