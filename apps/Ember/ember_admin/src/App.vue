<script setup lang="ts">
import { storeToRefs } from "pinia";
import { watch } from "vue";
import { RouterView, useRoute, useRouter } from "vue-router";
import AdminNav from "./components/AdminNav.vue";
import PwaStatus from "../../ember_web/src/components/PwaStatus.vue";
import { useAuthStore } from "./stores/auth";

const auth = useAuthStore();
const { account } = storeToRefs(auth);
const route = useRoute();
const router = useRouter();

// The session can end mid-page (expired, or logged out elsewhere): any 401
// clears the account, and this sends the user back to the login page.
watch(account, (now) => {
  if (!now && !route.meta.guestOnly) void router.replace({ name: "login" });
});
</script>

<template>
  <PwaStatus app-name="Ember Admin" offline-message="Reconnect to load workspace data and make administration changes." />
  <div class="shell">
    <AdminNav />
    <main class="page"><RouterView :key="account?.id ?? 'guest'" /></main>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  flex: 1;
  min-height: 0;
}
.page {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
@media (max-width: 767px) {
  .shell {
    flex-direction: column-reverse;
  }
}
</style>
