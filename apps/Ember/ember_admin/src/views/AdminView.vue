<script setup lang="ts">
import { computed, watch } from "vue";
import { RouterView, useRoute, useRouter } from "vue-router";
import { ADMIN_SECTIONS } from "../router/pages";
import { useAuthStore } from "../stores/auth";
import "../components/admin/adminPages.css";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const sections = computed(() => ADMIN_SECTIONS.filter((s) => Array.isArray(s.permission) ? s.permission.some(auth.hasPermission) : auth.hasPermission(s.permission)));
// Editing a held role may remove access to the page currently open.
watch(sections, (now) => {
  if (!now.some((s) => s.to === route.path)) void router.replace(now.length ? '/admin' : '/');
});
</script>

<template>
  <section class="admin-workspace" :class="{ 'roles-workspace': route.path === '/admin/roles' }">
    <div class="admin-content">
      <div class="admin-column page-column">
        <RouterView />
      </div>
    </div>
  </section>
</template>

<style scoped>
.admin-workspace { display: flex; flex: 1; min-height: 0; min-width: 0; }
.roles-workspace .admin-content { overflow: hidden; }
.roles-workspace .admin-column { height: 100%; box-sizing: border-box; display: flex; flex-direction: column; }
.admin-content { flex: 1; min-width: 0; min-height: 0; overflow-y: auto; }



</style>
