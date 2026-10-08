<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { authClient, type KnownDevice } from "../api/AuthClient";
import ActionButton from "../components/ActionButton.vue";
import ConfirmModal from "../components/admin/ConfirmModal.vue";
import { useTheme } from "../composables/useTheme";
import { useAuthStore } from "../stores/auth";
import { errorMessage, formatUtc } from "../utils/errors";

const auth = useAuthStore();
const router = useRouter();

// Theme and log out live here too: the narrow-screen nav bar has no room for them.
const { theme, cycle } = useTheme();
const THEME_LABELS = { system: "System", light: "Light", dark: "Dark" } as const;

async function logout(): Promise<void> {
  await auth.logout();
  await router.replace({ name: "login" });
}

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
  <!-- Logging out clears the account a moment before the router leaves this page. -->
  <section v-if="auth.account" class="account-view">
    <div class="column page-column">
      <header class="page-head">
        <p class="eyebrow">Your workspace, your account</p>
        <h2 class="page-title">Profile</h2>
        <p class="subtitle page-description">Manage your identity, security, and devices.</p>
      </header>

      <div v-if="!account.email_verified" class="banner" role="status">
        <span>{{ auth.needsVerification
          ? "Your email isn't verified. Permissions are paused until you enter the code."
          : "Your email isn't verified. Verifying it is optional." }}</span>
        <ActionButton icon="verify" class="account-action verify" @click="router.push('/verify-email')">Verify now</ActionButton>
      </div>

      <div class="card profile">
        <div class="identity">
          <div class="avatar" aria-hidden="true">{{ initial }}</div>
          <div class="who">
            <div class="name">{{ account.username }}</div>
            <div class="email">{{ account.email }}</div>
            <span v-if="account.email_verified" class="chip ok">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6" /></svg>Email verified
            </span>
          </div>
        </div>
        <div class="profile-status">
          <p class="eyebrow">Email status</p>
          <p class="state" :class="{ verified: account.email_verified }">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6z" /><path v-if="account.email_verified" d="m8.5 12 2.5 2.5 4.5-5" /><path v-else d="M12 8v5m0 3v.1" /></svg>
            {{ account.email_verified ? 'Verified address' : auth.needsVerification ? 'Verification needed' : 'Verification optional' }}
          </p>
        </div>
      </div>

      <section class="card session" aria-labelledby="account-session">
        <header class="section-header">
          <span class="section-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" /></svg></span>
          <div><h3 id="account-session">Session</h3><p>Appearance on this device, and signing out.</p></div>
        </header>
        <div class="security-body">
          <div class="row">
            <div class="row-copy"><div class="row-title">Theme</div><div class="muted small">{{ THEME_LABELS[theme] }}</div></div>
            <ActionButton icon="theme" class="account-action theme" @click="cycle">Switch theme</ActionButton>
          </div>
          <div class="row">
            <div class="row-copy"><div class="row-title">Log out</div><div class="muted small">End your session on this device.</div></div>
            <ActionButton icon="logout" class="account-action logout" @click="logout">Log out</ActionButton>
          </div>
        </div>
      </section>

      <div class="account-grid">
        <section class="card security" aria-labelledby="account-security">
          <header class="section-header">
            <span class="section-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6zM8.5 12l2.5 2.5 4.5-5" /></svg></span>
            <div><h3 id="account-security">Security</h3><p>Keep your sign-in details up to date.</p></div>
          </header>
          <div class="security-body">
            <div class="row">
              <div class="row-copy"><div class="row-title">Email address</div><div class="muted small">{{ account.email }}</div></div>
              <ActionButton :icon="openForm === 'email' ? 'close' : 'mail'" class="account-action toggle-email" :aria-expanded="openForm === 'email'" aria-controls="account-email-form" @click="toggle('email')">
                {{ openForm === 'email' ? 'Close' : 'Change email' }}
              </ActionButton>
            </div>
            <form v-if="openForm === 'email'" id="account-email-form" class="stack" :aria-busy="emailForm.busy" @submit.prevent="changeEmail">
              <label>New email<input v-model="emailForm.email" type="email" autocomplete="email" required /></label>
              <label>Current password<input v-model="emailForm.password" type="password" autocomplete="current-password" required /></label>
              <p class="muted small">{{ account.email_verification_required === false
                ? "You'll get a code at the new address. Verifying it is optional."
                : "You'll get a code at the new address. Until you enter it, your permissions are paused." }}</p>
              <p v-if="emailForm.error" class="error" role="alert">{{ emailForm.error }}</p>
              <p v-else-if="emailForm.success" class="notice" role="status">{{ emailForm.success }}</p>
              <button class="primary" :disabled="emailForm.busy" :aria-busy="emailForm.busy"><span v-if="emailForm.busy" class="spinner" aria-hidden="true" />{{ emailForm.busy ? 'Changing email…' : 'Change email' }}</button>
            </form>
            <div class="row">
              <div class="row-copy"><div class="row-title">Password</div><div class="muted small">Use a strong, unique password.</div></div>
              <ActionButton :icon="openForm === 'password' ? 'close' : 'lock'" class="account-action toggle-password" :aria-expanded="openForm === 'password'" aria-controls="account-password-form" @click="toggle('password')">
                {{ openForm === 'password' ? 'Close' : 'Change password' }}
              </ActionButton>
            </div>
            <form v-if="openForm === 'password'" id="account-password-form" class="stack" :aria-busy="passwordForm.busy" @submit.prevent="changePassword">
              <label>New password<input v-model="passwordForm.next" type="password" autocomplete="new-password" minlength="8" required /></label>
              <label>Repeat new password<input v-model="passwordForm.confirm" type="password" autocomplete="new-password" required /></label>
              <label>Current password<input v-model="passwordForm.current" type="password" autocomplete="current-password" required /></label>
              <p v-if="passwordMismatch" class="error" role="alert">The new passwords don't match.</p>
              <p v-else-if="passwordForm.error" class="error" role="alert">{{ passwordForm.error }}</p>
              <p v-else-if="passwordForm.done" class="notice" role="status">Password changed.</p>
              <button class="primary" :disabled="passwordForm.busy || passwordMismatch" :aria-busy="passwordForm.busy"><span v-if="passwordForm.busy" class="spinner" aria-hidden="true" />{{ passwordForm.busy ? 'Changing password…' : 'Change password' }}</button>
            </form>
          </div>
          <p class="helper"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 11v6m0-10v.1" /></svg>Password changes sign out your other devices.</p>
        </section>

        <section class="card access" aria-labelledby="account-access">
          <header class="section-header">
            <span class="section-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="8" cy="9" r="4" /><path d="m11 12 9 9m-3-3 3-3m-6 0 3-3" /></svg></span>
            <div><h3 id="account-access">Roles &amp; access</h3><p>Your permissions in this workspace.</p></div>
          </header>
          <div class="access-body">
            <p class="access-label">Assigned roles</p>
            <div class="roles"><span v-for="r in account.roles" :key="r" class="chip role">{{ r }}</span><span v-if="!account.roles.length" class="muted small">No roles</span></div>
            <details class="permissions">
              <summary><span>{{ account.permissions.length }} {{ account.permissions.length === 1 ? 'permission' : 'permissions' }}</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 7 7-7 7" /></svg></summary>
              <p v-if="auth.needsVerification && account.permissions.length" class="muted small">Permissions are inactive until your email is verified.</p>
              <div class="perm-list"><code v-for="p in account.permissions" :key="p">{{ p }}</code></div>
            </details>
            <p class="access-note">Roles are managed by your workspace administrator.</p>
          </div>
        </section>
      </div>

      <section class="card device-card" aria-labelledby="account-devices">
        <header class="section-header device-header">
          <div class="section-heading"><span class="section-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /></svg></span><div><h3 id="account-devices">Remembered devices</h3><p>Devices you've used to sign in to Ember.</p></div></div>
          <span v-if="!devicesError" class="device-count">{{ devices.length }} {{ devices.length === 1 ? 'device' : 'devices' }}</span>
        </header>
        <p v-if="devicesError" class="device-message error" role="alert">{{ devicesError }}</p>
        <p v-else-if="devices.length === 0" class="device-message muted">None recorded yet.</p>
        <ul v-else class="devices">
          <li v-for="d in devices" :key="d.id" :title="d.user_agent || '(no browser name)'">
            <svg class="device-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /></svg>
            <div class="device-main">
              <div class="device-name"><strong>{{ d.label }}</strong><span v-if="d.current" class="chip ok"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6" /></svg>This device</span></div>
              <div class="device-meta"><span>Last used · {{ formatUtc(d.last_seen_at) }}</span><span>{{ d.ip_subnet }}</span><span>First seen · {{ formatUtc(d.first_seen_at) }}</span></div>
            </div>
            <ActionButton v-if="!d.current" icon="close" quiet class="account-action forget" @click="pendingForget = d">Forget</ActionButton>
          </li>
        </ul>
        <p class="device-footer">Forgetting a device makes its next sign-in appear as a new device in your activity log.</p>
      </section>
      <footer class="page-footer">Ember Admin · Profile</footer>
    </div>
    <ConfirmModal v-if="pendingForget" open title="Forget device" :message="`Forget ${pendingForget.label}? Its next login is noted in the activity log as a new device.`" confirm-label="Forget" @confirm="forgetDevice(pendingForget)" @close="pendingForget = null" />
  </section>
</template>

<style scoped>
.account-view  {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.column  {
  display: flex;
  flex-direction: column;
  gap: 22px;



}



p, h3  {
  margin: 0;
}

h3  {
  font-size: 1em;
  font-weight: 600;
}

.eyebrow  {
  color: var(--muted);
  font-size: .75em;
  letter-spacing: .13em;
  text-transform: uppercase;
  font-weight: 600;
}

.subtitle  {

  color: var(--muted);
}

.card  {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  min-width: 0;
}

.profile  {
  position: relative;
  overflow: hidden;
  padding: 26px 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}

.profile::before  {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: var(--accent);
}

.identity  {
  display: flex;
  align-items: center;
  gap: 18px;
  min-width: 0;
}

.avatar  {
  display: grid;
  place-items: center;
  width: 64px;
  height: 64px;
  flex: none;
  border: 1px solid color-mix(in srgb, var(--accent) 35%, var(--border));
  border-radius: var(--radius-full);
  background: color-mix(in srgb, var(--accent) 12%, var(--surface));
  color: var(--accent);
  font-size: 1.6em;
  font-weight: 600;
}

.who  {
  min-width: 0;
}

.name  {
  font-size: 1.2em;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.email  {
  font-size: .9em;
  color: var(--muted);
  overflow-wrap: anywhere;
  margin: 2px 0 10px;
}

.chip  {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: var(--radius-full);
  font-size: .75em;
  background: var(--code-bg);
  border: 1px solid var(--border);
  color: var(--muted);
  overflow-wrap: anywhere;
}

.chip svg  {
  width: 12px;
  height: 12px;
}

.chip.ok  {
  color: var(--success);
  border-color: color-mix(in srgb, var(--success) 25%, var(--border));
  background: color-mix(in srgb, var(--success) 7%, var(--surface));
}

.profile-status  {
  border-left: 1px solid var(--border);
  padding-left: 24px;
  flex: none;
}

.profile-status .eyebrow  {
  font-size: .7em;
  text-align: right;
}

.state  {
  font-size: .9em;
  margin-top: 7px;
  display: flex;
  align-items: center;
  gap: 7px;
}

.state svg  {
  width: 15px;
  height: 15px;
  color: var(--warning);
}

.state.verified svg  {
  color: var(--success);
}

.account-grid  {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 18px;
}

.section-header  {
  padding: 21px 24px 17px;
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.section-header p  {
  font-size: .85em;
  color: var(--muted);
  margin-top: 3px;
}

.section-icon  {
  width: 36px;
  height: 36px;
  flex: none;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  display: grid;
  place-items: center;
  color: var(--muted);
}

.section-icon svg  {
  width: 18px;
  height: 18px;
}

svg  {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
  flex: none;
}

.security  {
  display: flex;
  flex-direction: column;
}

.security-body  {
  padding: 0 24px 8px;
}

.row  {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 0;
  border-top: 1px solid var(--border);
}

.row-copy  {
  min-width: 0;
  overflow-wrap: anywhere;
}

.row-title  {
  font-size: .9em;
  font-weight: 550;
}

.row .small  {
  margin-top: 3px;
  font-size: .8em;
}

button.account-action  {
  border-radius: var(--radius-full);
  padding: 6px 13px;
  font-size: .8em;
  font-weight: 550;
  flex: none;
}

.account-action :deep(.label)  {
  position: static;
  width: auto;
  height: auto;
  overflow: visible;
  clip-path: none;
}

.helper  {
  border-top: 1px solid var(--border);
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 12px 24px;
  color: var(--muted);
  font-size: .75em;
  margin-top: auto;
}

.helper svg  {
  width: 14px;
  height: 14px;
}

.access-body  {
  padding: 0 24px 20px;
}

.access-label  {
  font-size: .75em;
  color: var(--muted);
  margin-bottom: 9px;
}

.roles  {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 20px;
}

.chip.role  {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 7%, var(--surface));
  border-color: color-mix(in srgb, var(--accent) 20%, var(--border));
}

.permissions  {
  border-top: 1px solid var(--border);
  padding-top: 15px;
}

.permissions summary  {
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: .85em;
  list-style: none;
}

.permissions summary::-webkit-details-marker  {
  display: none;
}

.permissions summary svg  {
  width: 15px;
  height: 15px;
  color: var(--muted);
}

.permissions[open] summary svg  {
  transform: rotate(90deg);
}

.permissions > p  {
  margin-top: 10px;
}

.perm-list  {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;
}

.perm-list code  {
  font: .7em var(--mono);
  padding: 4px 6px;
  border-radius: var(--radius-sm);
  background: var(--code-bg);
  color: var(--muted);
  overflow-wrap: anywhere;
  max-width: 100%;
}

.access-note  {
  font-size: .75em;
  color: var(--muted);
  margin-top: 12px;
}

.device-header  {
  align-items: center;
  justify-content: space-between;
  padding-bottom: 20px;
}

.section-heading  {
  display: flex;
  gap: 12px;
  min-width: 0;
}

.device-count  {
  font-size: .75em;
  color: var(--muted);
  border: 1px solid var(--border);
  padding: 3px 9px;
  border-radius: var(--radius-full);
  flex: none;
  white-space: nowrap;
}

.devices  {
  margin: 0;
  padding: 0 24px;
  list-style: none;
}

.devices li  {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 0;
  border-top: 1px solid var(--border);
}

.device-icon  {
  box-sizing: border-box;
  width: 40px;
  height: 40px;
  padding: 10px;
  border-radius: var(--radius-md);
  background: var(--code-bg);
  color: var(--muted);
}

.device-main  {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}

.device-name  {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: .9em;
}

.device-name strong  {
  font-weight: 550;
}

.device-name .chip  {
  font-size: .8em;
}

.device-meta  {
  display: flex;
  gap: 4px 12px;
  flex-wrap: wrap;
  font-size: .75em;
  color: var(--muted);
  margin-top: 5px;
}

button.forget  {
  background: transparent;
  border-color: transparent;
  padding: 6px 10px;
}

.device-footer  {
  padding: 13px 24px;
  border-top: 1px solid var(--border);
  font-size: .75em;
  color: var(--muted);
}

.device-message  {
  padding: 0 24px 20px;
  font-size: .9em;
}

.page-footer  {
  font-size: .7em;
  color: var(--muted);
}

.banner  {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 12px;
  padding: 12px 18px;
  border: 1px solid color-mix(in srgb, var(--warning) 35%, var(--border));
  border-radius: var(--radius-lg);
  font-size: .9em;
  color: var(--warning);
  background: color-mix(in srgb, var(--warning) 5%, var(--surface));
}

.small  {
  font-size: .85em;
}

.muted  {
  color: var(--muted);
}

.stack  {
  display: grid;
  gap: 10px;
  margin: 0 0 12px;
  padding: 14px;
  border-radius: var(--radius-md);
  background: var(--code-bg);
}

.stack label  {
  display: grid;
  gap: 5px;
  font-size: .85em;
}

.stack input  {
  width: 100%;
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  background: var(--bg);
  font: inherit;
}

.primary  {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  justify-self: start;
  padding: 7px 18px;
  border: none;
  border-radius: var(--radius-full);
  cursor: pointer;
  font-weight: 600;
  font-size: .85em;
  color: var(--accent-contrast);
  background: var(--accent);
}

.primary:disabled  {
  cursor: default;
  opacity: .5;
}

.error  {
  color: var(--danger);
}

.notice  {
  color: var(--success);
}

:focus-visible  {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.spinner  {
  width: 14px;
  height: 14px;
  border: 2px solid currentColor;
  border-right-color: transparent;
  border-radius: var(--radius-full);
  animation: account-spin .8s linear infinite;
}

@keyframes account-spin  {
  to  {
    transform: rotate(360deg);
  }
}

@media (max-width: 767px)  {
.column  {

    gap: 16px;
  }
  .page-head  {
    margin-bottom: 4px;
  }
  .account-grid  {
    grid-template-columns: 1fr;
    gap: 16px;
  }
  .profile  {
    padding: 22px 18px;
    flex-wrap: wrap;
    gap: 20px;
  }
  .identity  {
    gap: 12px;
  }
  .avatar  {
    width: 52px;
    height: 52px;
    font-size: 1.4em;
  }
  .profile-status  {
    border-left: 0;
    border-top: 1px solid var(--border);
    padding: 14px 0 0;
    width: 100%;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    justify-content: space-between;
  }
  .state  {
    margin: 0;
  }
  .section-header, .device-header  {
    padding: 18px;
  }
  .security-body  {
    padding: 0 18px 5px;
  }
  .access-body  {
    padding: 0 18px 18px;
  }
  .helper  {
    padding: 12px 18px;
  }
  .devices  {
    padding: 0 18px;
  }
  .devices li  {
    gap: 10px;
    align-items: flex-start;
  }
  .device-icon  {
    width: 32px;
    height: 32px;
    padding: 7px;
  }
  button.forget  {
    padding: 5px 0;
  }
  .device-footer  {
    padding: 12px 18px;
  }
  .device-message  {
    padding: 0 18px 18px;
  }
}

@media (prefers-reduced-motion: reduce)  {
  .spinner  {
    animation: none;
  }
}
</style>
