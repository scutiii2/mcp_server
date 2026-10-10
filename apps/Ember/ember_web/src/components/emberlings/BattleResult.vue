<script setup lang="ts">
import { computed } from "vue";
import type { BattleView, ResultKind } from "../../api/EmberlingsClient";
import { useNowSeconds } from "../../composables/useNowSeconds";
import { useEmberlingsStore } from "../../stores/emberlings";
import { RESULT_LABELS, formatCountdown, titleCase } from "../../utils/emberlings";
import EmButton from "./ui/EmButton.vue";
import EmIcon from "./ui/EmIcon.vue";
import EmPanel from "./ui/EmPanel.vue";
import type { IconName } from "./ui/icons";

/** A finished battle: one banner per outcome (the outcome is always written), what it
 * paid (only what was awarded), the personalities a capture revealed, and Back to the
 * encounter screen. */
const props = defineProps<{ battle: BattleView }>();
const store = useEmberlingsStore();
const now = useNowSeconds();
const result = computed(() => props.battle.result);

const TONES: Record<ResultKind, { tone: "success" | "danger" | "accent" | "warning"; icon: IconName }> = {
  won: { tone: "success", icon: "shield" },
  knocked_out: { tone: "danger", icon: "heart" },
  captured: { tone: "accent", icon: "spark" },
  escaped: { tone: "warning", icon: "arrow" },
  wild_escaped: { tone: "warning", icon: "arrow" },
  forfeited: { tone: "danger", icon: "battle" },
};

const style = computed(() => (result.value ? TONES[result.value.kind] : TONES.won));
const restLeft = computed(() => {
  const until = result.value?.faint_until;
  return until === undefined ? 0 : Math.max(0, until - now.value);
});
const levelledUp = computed(() => {
  const r = result.value;
  return r?.level_before !== undefined && r.level_after !== undefined && r.level_after > r.level_before;
});
const awarded = computed(() => {
  const r = result.value;
  return r !== null && (r.xp !== undefined || r.insignia !== undefined || r.copies_granted !== undefined);
});
const story = computed(() => {
  const r = result.value;
  if (r === null) return "";
  const rest = restLeft.value > 0 ? ` Ready again in ${formatCountdown(restLeft.value)}.` : "";
  const mine = props.battle.player.name;
  const theirs = props.battle.wild.name;
  switch (r.kind) {
    case "won":
      return `${mine} stood its ground. A well-earned victory.`;
    case "knocked_out":
      return `${mine} fainted and needs rest before its next battle.${rest}`;
    case "captured":
      return `A wild ${theirs} joins your collection.`;
    case "escaped":
      return `You slipped away safely. ${mine} lives to fight again.`;
    case "wild_escaped":
      return `The wild ${theirs} got away this time.`;
    case "forfeited":
      return `${mine} fainted and needs rest before its next battle.${rest}`;
  }
});
</script>

<template>
  <EmPanel v-if="result" class="battle-result" role="status">
    <div class="mark" :class="style.tone" aria-hidden="true"><EmIcon :name="style.icon" :size="40" /></div>
    <h2 class="em-pixel title">{{ RESULT_LABELS[result.kind] }}</h2>
    <p class="story">{{ story }}</p>

    <div v-if="awarded" class="rewards">
      <div v-if="result.xp !== undefined" class="reward">
        <strong class="em-pixel em-num">+{{ result.xp }} XP</strong>
        <span>for {{ battle.player.name }}<template v-if="levelledUp">, now level {{ result.level_after }}</template></span>
      </div>
      <div v-if="result.insignia !== undefined" class="reward">
        <strong class="em-pixel em-num">+{{ result.insignia }} Insignia</strong>
        <span>added to your wallet</span>
      </div>
      <div v-if="result.copies_granted !== undefined" class="reward">
        <strong class="em-pixel em-num">+{{ result.copies_granted }} {{ result.copies_granted === 1 ? "copy" : "copies" }}</strong>
        <span>of {{ battle.wild.name }}<template v-if="result.tier_id">, now {{ titleCase(result.tier_id) }}</template></span>
      </div>
    </div>
    <p v-else class="none">No rewards from this battle.</p>

    <template v-if="result.revealed_personalities?.length">
      <h3 class="revealed-title">Personalities revealed</h3>
      <ul class="revealed">
        <li v-for="p in result.revealed_personalities" :key="p.id">
          {{ titleCase(p.type) }} · tier {{ p.tier }}<strong v-if="p.id === result.awarded_personality?.id"> (now yours)</strong>
        </li>
      </ul>
    </template>

    <EmButton variant="primary" @click="store.closeBattle()">Back</EmButton>
  </EmPanel>
</template>

<style scoped>
.battle-result {
  display: flex;
  flex-direction: column;
  align-items: center;
  max-width: 760px;
  margin: 0 auto var(--em-space-5);
  text-align: center;
  background:
    radial-gradient(ellipse at top, #3c352c, transparent 70%),
    var(--em-panel);
}
.mark {
  display: grid;
  width: 80px;
  height: 80px;
  place-items: center;
  margin-bottom: var(--em-space-4);
  border: 1px solid currentColor;
  background: #15202b;
  clip-path: polygon(12% 0, 88% 0, 100% 12%, 100% 88%, 88% 100%, 12% 100%, 0 88%, 0 12%);
}
.mark.success {
  color: var(--em-success);
}
.mark.danger {
  color: var(--em-danger);
}
.mark.accent {
  color: var(--em-accent);
}
.mark.warning {
  color: var(--em-warning);
}
.title {
  margin: 0 0 var(--em-space-2);
  font-size: 28px;
  line-height: 1.3;
}
.story {
  max-width: 480px;
  color: var(--em-muted);
}
.rewards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--em-space-4);
  width: 100%;
  margin: var(--em-space-5) 0;
}
.reward {
  padding: var(--em-space-4);
  border: 1px solid var(--em-border);
  background: #15202b;
}
.reward strong {
  display: block;
  margin-bottom: 5px;
  font-size: 22px;
  font-weight: 400;
  color: var(--em-accent);
}
.reward span {
  font-size: 13px;
  color: var(--em-muted);
}
.none {
  margin: var(--em-space-5) 0;
  padding: 14px;
  border: 1px dashed var(--em-border);
  color: var(--em-muted);
  font-size: 13px;
}
.revealed-title {
  margin: 0 0 var(--em-space-2);
  font-size: 16px;
}
.revealed {
  margin: 0 0 var(--em-space-5);
  padding: 0;
  list-style: none;
  color: var(--em-muted);
}
@media (max-width: 700px) {
  .title {
    font-size: 23px;
  }
  .reward strong {
    font-size: 20px;
  }
}
</style>
