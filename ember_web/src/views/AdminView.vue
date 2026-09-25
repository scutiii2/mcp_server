<script setup lang="ts">
import { onMounted, ref } from "vue";
import { adminClient, type CreatedInvite, type Invite } from "../api/AdminClient";

const invites = ref<Invite[]>([]);
const listError = ref("");

const inviteeEmail = ref("");
const byEmail = ref(false);
const creating = ref(false);
const createError = ref("");
// The code is only ever shown here, right after creation.
const created = ref<CreatedInvite | null>(null);
const copied = ref(false);

async function loadInvites(): Promise<void> {
  listError.value = "";
  try {
    invites.value = await adminClient.listInvites();
  } catch (err) {
    listError.value = err instanceof Error ? err.message : String(err);
  }
}

async function createInvite(): Promise<void> {
  createError.value = "";
  created.value = null;
  copied.value = false;
  creating.value = true;
  try {
    const email = inviteeEmail.value.trim() || null;
    created.value = await adminClient.createInvite(email, byEmail.value ? "email" : "manual");
    inviteeEmail.value = "";
    await loadInvites();
  } catch (err) {
    createError.value = err instanceof Error ? err.message : String(err);
  } finally {
    creating.value = false;
  }
}

async function copyCode(): Promise<void> {
  if (!created.value) return;
  try {
    await navigator.clipboard.writeText(created.value.code);
    copied.value = true;
  } catch {
    // clipboard blocked; the code is still on screen
  }
}

function formatTime(iso: string): string {
  // ember_api sends naive UTC times.
  return new Date(`${iso}Z`).toLocaleString();
}

onMounted(loadInvites);
</script>

<template>
  <section class="admin-view">
    <div class="column">
      <h2>Invites</h2>

      <form class="create" @submit.prevent="createInvite">
        <input v-model="inviteeEmail" type="email" placeholder="Invitee email (optional)" />
        <label class="check">
          <input v-model="byEmail" type="checkbox" :disabled="!inviteeEmail.trim()" />
          Email the code
        </label>
        <button class="primary" :disabled="creating || (byEmail && !inviteeEmail.trim())">
          {{ creating ? "Creating ..." : "Create invite" }}
        </button>
      </form>
      <p v-if="createError" class="error">{{ createError }}</p>

      <div v-if="created" class="created">
        <p>
          Invite code (shown only now, valid 15 minutes, works once):
          <code class="code">{{ created.code }}</code>
          <button type="button" class="small" @click="copyCode">{{ copied ? "Copied" : "Copy" }}</button>
        </p>
        <p v-if="created.email_sent" class="muted">Emailed to {{ created.invite.invitee_email }}.</p>
        <p v-else-if="created.email_error" class="error">
          Email failed: {{ created.email_error }} - pass the code on by hand.
        </p>
      </div>

      <h3>Open invites</h3>
      <p v-if="listError" class="error">error: {{ listError }}</p>
      <p v-else-if="invites.length === 0" class="muted">None.</p>
      <table v-else>
        <thead>
          <tr><th>Invitee</th><th>Delivery</th><th>Created</th><th>Expires</th></tr>
        </thead>
        <tbody>
          <tr v-for="i in invites" :key="i.id">
            <td>{{ i.invitee_email ?? "-" }}</td>
            <td>{{ i.delivery_method }}</td>
            <td>{{ formatTime(i.created_at) }}</td>
            <td>{{ formatTime(i.expires_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.admin-view {
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
  margin: 28px 0 10px;
  font-size: 1em;
}
.create {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.create input[type="email"] {
  flex: 1 1 240px;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg);
}
.check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.9em;
}
.primary {
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
.created {
  margin-top: 14px;
  padding: 12px 14px;
  border: 1px solid var(--accent);
  border-radius: 10px;
  background: var(--surface);
}
.created p {
  margin: 0.3em 0;
}
.code {
  margin: 0 6px;
  padding: 2px 8px;
  border-radius: 6px;
  font-family: var(--mono);
  font-size: 1.05em;
  background: var(--code-bg);
}
.small {
  padding: 2px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  cursor: pointer;
  font-size: 0.85em;
  background: transparent;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9em;
}
th,
td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  text-align: left;
}
th {
  color: var(--muted);
  font-weight: 600;
}
.muted {
  color: var(--muted);
}
.error {
  color: var(--danger);
}
</style>
