<script setup lang="ts">
import { reactive, ref } from "vue";
import { RouterLink, useRouter } from "vue-router";
import AuthCard from "../components/AuthCard.vue";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const router = useRouter();

const form = reactive({ username: "", email: "", password: "", invite_code: "" });
const error = ref("");
const busy = ref(false);

async function submit(): Promise<void> {
  error.value = "";
  busy.value = true;
  try {
    const result = await auth.register({
      username: form.username.trim(),
      email: form.email.trim(),
      password: form.password,
      invite_code: form.invite_code.trim(),
    });
    form.password = "";
    // The verify page offers "resend" when the first email didn't go out.
    await router.replace({ name: "verify-email", query: result.verification_email_sent ? {} : { unsent: "1" } });
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <AuthCard title="Create an account" subtitle="Registration needs an invite code from an admin.">
    <form @submit.prevent="submit">
      <label>
        Invite code
        <input v-model="form.invite_code" autocomplete="off" spellcheck="false" required autofocus />
      </label>
      <label>
        Username
        <input
          v-model="form.username"
          autocomplete="username"
          minlength="3"
          maxlength="80"
          pattern="[A-Za-z0-9_.\-]+"
          title="Letters, digits, dot, dash and underscore"
          required
        />
      </label>
      <label>
        Email
        <input v-model="form.email" type="email" autocomplete="email" required />
      </label>
      <label>
        Password
        <input v-model="form.password" type="password" autocomplete="new-password" minlength="8" required />
      </label>
      <p v-if="error" class="error">{{ error }}</p>
      <button class="primary" :disabled="busy">{{ busy ? "Creating ..." : "Create account" }}</button>
    </form>
    <template #footer>Already registered? <RouterLink to="/login">Log in</RouterLink></template>
  </AuthCard>
</template>
