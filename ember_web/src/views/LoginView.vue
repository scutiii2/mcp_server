<script setup lang="ts">
import { ref } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import AuthCard from "../components/AuthCard.vue";
import { safeRedirect } from "../router/redirect";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const username = ref("");
const password = ref("");
const error = ref("");
const busy = ref(false);

async function submit(): Promise<void> {
  error.value = "";
  busy.value = true;
  try {
    await auth.login(username.value.trim(), password.value);
    password.value = "";
    await router.replace(safeRedirect(route.query.redirect));
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <AuthCard title="Log in" subtitle="Welcome back to Ember.">
    <form @submit.prevent="submit">
      <label>
        Username
        <input v-model="username" autocomplete="username" required autofocus />
      </label>
      <label>
        Password
        <input v-model="password" type="password" autocomplete="current-password" required />
      </label>
      <p v-if="error" class="error">{{ error }}</p>
      <button class="primary" :disabled="busy">{{ busy ? "Logging in ..." : "Log in" }}</button>
    </form>
    <template #footer>
      Have an invite code? <RouterLink to="/register">Create an account</RouterLink>
    </template>
  </AuthCard>
</template>
