<script setup lang="ts">
import { storeToRefs } from "pinia";
import { watch } from "vue";
import { RouterView, useRoute, useRouter } from "vue-router";
import NavRail from "./components/NavRail.vue";
import { useAuthStore } from "./stores/auth";

const auth = useAuthStore();
const { account } = storeToRefs(auth);
const route = useRoute();
const router = useRouter();

// The session can end mid-page (expired, or logged out elsewhere): any 401
// clears the account, and this sends the user back to the login page.
watch(account, (now) => {
  if (!now && !route.meta.guestOnly && !route.meta.public) void router.replace({ name: "login" });
});
</script>

<template>
  <div class="shell">
    <NavRail />
    <main class="page">
      <!-- KeepAlive: switching to Tools and back keeps the chat (and a turn in
           flight) intact. Keyed by account so a different user never gets the
           previous user's cached pages. -->
      <RouterView v-slot="{ Component }">
        <KeepAlive :key="account?.id ?? 'guest'" include="ChatView,CapabilitiesView">
          <component :is="Component" />
        </KeepAlive>
      </RouterView>
    </main>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  flex: 1;
  min-height: 0;
}
/* Fills what the rail leaves; each view manages its own scrolling. */
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
