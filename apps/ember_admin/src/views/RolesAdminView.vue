<script setup lang="ts">
import { onBeforeRouteLeave } from "vue-router";
import { ref } from "vue";
import RolesPanel from "../components/admin/RolesPanel.vue";
import { useAuthStore } from "../stores/auth";
const auth = useAuthStore();
const panel = ref<InstanceType<typeof RolesPanel> | null>(null);
onBeforeRouteLeave(() => panel.value?.confirmDiscard() ?? true);
</script>
<template>
  <div class="admin-panel"><header class="admin-page-head"><div><h2 class="page-title">Roles &amp; permissions</h2><p class="page-description">Make access easy to understand and maintain.</p></div><button v-if="auth.hasPermission('roles.manage')" type="button" class="primary" @click="panel?.openCreate()">＋ New role</button></header><RolesPanel ref="panel" :show-heading="false" /></div>
</template>
