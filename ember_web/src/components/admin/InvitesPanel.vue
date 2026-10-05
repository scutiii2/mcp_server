<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { adminClient, type CreatedInvite, type Invite } from "../../api/AdminClient";
import { errorMessage, formatUtc } from "../../utils/errors";
import CopyButton from "../CopyButton.vue";
import ToggleSwitch from "../ToggleSwitch.vue";
import ConfirmModal from "./ConfirmModal.vue";
import "./admin.css";

/** The overview counts (AdminView) change whenever an invite does. */
const emit = defineEmits<{ changed: [] }>();

const invites = ref<Invite[]>([]);
const listError = ref("");

const inviteeEmail = ref("");
const byEmail = ref(false);
const creating = ref(false);
const createError = ref("");
// The code is only ever shown here, right after creation.
const created = ref<CreatedInvite | null>(null);
const pendingRevoke = ref<Invite | null>(null);
const revoking = ref(false);

// Emailing needs an address: clearing it switches the option off.
watch(inviteeEmail, (email) => {
  if (!email.trim()) byEmail.value = false;
});

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
  creating.value = true;
  try {
    const email = inviteeEmail.value.trim() || null;
    created.value = await adminClient.createInvite(email, byEmail.value ? "email" : "manual");
    inviteeEmail.value = "";
    emit("changed");
    await loadInvites();
  } catch (err) {
    createError.value = errorMessage(err);
  } finally {
    creating.value = false;
  }
}

const revokeMessage = computed(() => {
  const invite = pendingRevoke.value;
  if (!invite) return "";
  return `Revoke ${invite.invitee_email ?? "this invite"}? Its code stops working.`;
});

async function confirmRevoke(): Promise<void> {
  const invite = pendingRevoke.value;
  if (!invite) return;
  listError.value = "";
  revoking.value = true;
  try {
    await adminClient.revokeInvite(invite.id);
    invites.value = invites.value.filter((i) => i.id !== invite.id);
    if (created.value?.invite.id === invite.id) created.value = null;
    emit("changed");
  } catch (err) {
    listError.value = errorMessage(err);
  } finally {
    revoking.value = false;
    pendingRevoke.value = null;
  }
}

onMounted(loadInvites);
</script>

<template>
  <div class="admin-panel">
    <form class="row-form" @submit.prevent="createInvite">
      <input v-model="inviteeEmail" type="email" placeholder="Invitee email (optional)" aria-label="Invitee email" />
      <ToggleSwitch
        small
        :checked="byEmail"
        :disabled="!inviteeEmail.trim()"
        @change="byEmail = ($event.target as HTMLInputElement).checked"
      >
        Email the code
      </ToggleSwitch>
      <button class="primary" :disabled="creating">
        {{ creating ? "Creating ..." : "Create invite" }}
      </button>
    </form>
    <p v-if="createError" class="error">{{ createError }}</p>

    <div v-if="created" class="created">
      <p>
        Invite code (shown only now, valid 15 minutes, works once):
        <code class="code">{{ created.code }}</code>
        <CopyButton :text="created.code" label="Copy invite code" />
      </p>
      <p v-if="created.email_sent" class="muted">Emailed to {{ created.invite.invitee_email }}.</p>
      <p v-else-if="created.email_error" class="error">
        Email failed: {{ created.email_error }} - pass the code on by hand.
      </p>
    </div>

    <h3>Open invites</h3>
    <p v-if="listError" class="error">error: {{ listError }}</p>
    <p v-if="invites.length === 0 && !listError" class="muted">No open invites.</p>
    <div class="table-wrap">
      <table v-if="invites.length">
        <thead>
          <tr><th>Invitee</th><th>Delivery</th><th>Created</th><th>Expires</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="i in invites" :key="i.id">
            <td class="invitee">{{ i.invitee_email ?? "-" }}</td>
            <td><span class="badge">{{ i.delivery_method }}</span></td>
            <td>{{ formatUtc(i.created_at) }}</td>
            <td>{{ formatUtc(i.expires_at) }}</td>
            <td>
              <button type="button" class="small danger" @click="pendingRevoke = i">Revoke</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <ConfirmModal
      :open="pendingRevoke !== null"
      title="Revoke invite"
      :message="revokeMessage"
      confirm-label="Revoke"
      danger
      :busy="revoking"
      @confirm="confirmRevoke"
      @close="pendingRevoke = null"
    />
  </div>
</template>

<style scoped>
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
  padding: 8px;
  border-top: 1px solid var(--border);
  text-align: left;
}
th {
  border-top: none;
  font-size: 0.85em;
  font-weight: 500;
  color: var(--muted);
}
.invitee {
  overflow-wrap: anywhere;
}
</style>
