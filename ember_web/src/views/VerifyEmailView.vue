<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import AuthCard from "../components/AuthCard.vue";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const code = ref("");
const error = ref("");
const notice = ref(
  route.query.unsent ? "The verification email couldn't be sent. Try \"Send a new code\"." : "",
);
const busy = ref(false);

const email = computed(() => auth.account?.email ?? "your address");

async function submit(): Promise<void> {
  error.value = "";
  busy.value = true;
  try {
    await auth.verifyEmail(code.value.trim());
    await router.replace({ name: "chat" });
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    busy.value = false;
  }
}

async function resend(): Promise<void> {
  error.value = "";
  notice.value = "";
  busy.value = true;
  try {
    await auth.resendVerification();
    notice.value = "A new code is on its way.";
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    busy.value = false;
  }
}

async function logout(): Promise<void> {
  await auth.logout();
  await router.replace({ name: "login" });
}
</script>

<template>
  <AuthCard title="Verify your email" :subtitle="`We sent a code to ${email}. It expires in 15 minutes.`">
    <form @submit.prevent="submit">
      <label>
        Verification code
        <input v-model="code" autocomplete="one-time-code" spellcheck="false" required autofocus />
      </label>
      <p v-if="error" class="error">{{ error }}</p>
      <p v-else-if="notice" class="notice">{{ notice }}</p>
      <button class="primary" :disabled="busy">Verify</button>
    </form>
    <template #footer>
      <button type="button" class="link-button" :disabled="busy" @click="resend">Send a new code</button>
      &middot;
      <button type="button" class="link-button" @click="logout">Log out</button>
    </template>
  </AuthCard>
</template>
