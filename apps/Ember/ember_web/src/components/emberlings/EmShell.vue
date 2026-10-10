<script setup lang="ts">
import EmIcon from "./ui/EmIcon.vue";

/** The page's frame: the masthead (logo, tagline, Insignia wallet) over the content.
 * The wallet shows only once there is a profile. */
defineProps<{ insignia: number | null }>();
</script>

<template>
  <div class="shell">
    <header class="mast">
      <h1 class="brand em-pixel"><EmIcon name="flame" :size="22" /> EMBERLINGS</h1>
      <p class="tagline">Collect. Forge. Battle.</p>
      <div v-if="insignia !== null" class="wallet" aria-label="Your Insignia">
        <EmIcon name="coin" />
        <span class="em-num amount">{{ insignia }}</span>
        Insignia
      </div>
      <span v-else class="wallet-gap" aria-hidden="true" />
    </header>
    <main class="main"><slot /></main>
  </div>
</template>

<style scoped>
.shell {
  min-height: 100%;
}
.mast {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: var(--em-space-4);
  height: 88px;
  padding: 0 var(--em-space-7);
  border-bottom: 1px solid var(--em-divider);
  background: var(--em-header);
}
.brand {
  display: flex;
  align-items: center;
  gap: var(--em-space-3);
  margin: 0;
  font-size: 20px;
  line-height: 1.2;
  color: var(--em-accent);
}
.tagline {
  margin: 0;
  font-size: 12px;
  letter-spacing: 1px;
  text-transform: uppercase;
  color: var(--em-muted);
}
.wallet {
  display: flex;
  align-items: center;
  justify-self: end;
  gap: 9px;
  padding: 8px 14px;
  border: 1px solid var(--em-border);
  background: var(--em-panel);
  font-weight: 600;
}
.wallet svg {
  color: var(--em-accent);
}
.amount {
  font-size: 16px;
}
.main {
  max-width: calc(1184px + 2 * var(--em-space-7));
  margin: 0 auto;
  padding: var(--em-space-6) var(--em-space-7) var(--em-space-7);
}
@media (max-width: 700px) {
  .mast {
    grid-template-columns: 1fr auto;
    height: 72px;
    padding: 0 var(--em-space-4);
  }
  .brand {
    gap: 8px;
    font-size: 16px;
  }
  .tagline {
    display: none;
  }
  .wallet {
    padding: 6px 9px;
    font-size: 12px;
  }
  .main {
    padding: var(--em-space-5) var(--em-space-4) var(--em-space-6);
  }
}
</style>
