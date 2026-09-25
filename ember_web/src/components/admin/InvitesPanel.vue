<script setup lang="ts">
import { onMounted, ref } from "vue";
import { adminClient, type CreatedInvite, type Invite } from "../../api/AdminClient";
import { errorMessage, formatUtc } from "../../utils/errors";
import "./admin.css";

const invites = ref<Invite[]>([]);
const listError = ref("");

const inviteeEmail = ref("");
const byEmail = ref(false);
const creating = ref(false);
const createError = ref("");
// The code is only ever shown here, right after creation.
const created = ref<CreatedInvite | null>(null);
const copied = ref(false);
const revokingId = ref<number | null>(null);

async function loadInvites(): Promise<void> {
  listError.value = "";
  try {
    invites.value = await adminClient.listInvites();
  } catch (err) {
    listError.value = errorMessage(err);
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
    createError.value = errorMessage(err);
  } finally {
    creating.value = false;
  }
}

async function revoke(invite: Invite): Promise<void> {
  const who = invite.invitee_email ?? "this invite";
  if (!confirm(`Revoke ${who}? Its code stops working.`)) return;
  listError.value = "";
  revokingId.value = invite.id;
  try {
    await adminClient.revokeInvite(invite.id);
    invites.value = invites.value.filter((i) => i.id !== invite.id);
    if (created.value?.invite.id === invite.id) created.value = null;
  } catch (err) {
    listError.value = errorMessage(err);
  } finally {
    revokingId.value = null;
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

onMounted(loadInvites);
</script>

<template>
  <div class="admin-panel">
    <form class="row-form" @submit.prevent="createInvite">
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
    <p v-if="invites.length === 0 && !listError" class="muted">None.</p>
    <div class="table-wrap">
      <table v-if="invites.length">
        <thead>
          <tr><th>Invitee</th><th>Delivery</th><th>Created</th><th>Expires</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="i in invites" :key="i.id">
            <td>{{ i.invitee_email ?? "-" }}</td>
            <td>{{ i.delivery_method }}</td>
            <td>{{ formatUtc(i.created_at) }}</td>
            <td>{{ formatUtc(i.expires_at) }}</td>
            <td>
              <button type="button" class="small danger" :disabled="revokingId === i.id" @click="revoke(i)">
                Revoke
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.9em;
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
.table-wrap {
  overflow-x: auto;
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
</style>
