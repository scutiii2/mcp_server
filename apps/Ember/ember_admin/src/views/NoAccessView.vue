<script setup lang="ts">
import AuthCard from "../components/AuthCard.vue";
import { RouterLink } from "vue-router";
</script>

<template>
  <AuthCard
    title="No access"
    subtitle="Your account doesn't have permission for an administration page yet. Ask an admin to give your account a role."
  ><RouterLink to="/profile">Manage your profile</RouterLink></AuthCard>
</template>
