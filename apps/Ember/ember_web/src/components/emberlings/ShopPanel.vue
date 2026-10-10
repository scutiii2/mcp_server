<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { useEmberlingsStore } from "../../stores/emberlings";
import { titleCase } from "../../utils/emberlings";
import EmButton from "./ui/EmButton.vue";
import EmConfirm from "./ui/EmConfirm.vue";
import EmIcon from "./ui/EmIcon.vue";
import EmPanel from "./ui/EmPanel.vue";
import EmTierBadge from "./ui/EmTierBadge.vue";

/** The Shop tab: the wallet, EMBLEMs per tier, copies of a regular Spark at a tier, and
 * selling one absorbed copy. EMBLEM buttons are disabled when Insignia would not cover
 * the price, and a line says which tiers are out of reach. A copy's price depends on
 * numbers only mini_games knows, so it says itself (a 409 with the cost) when Insignia
 * falls short; the page shows that message (the store's `error`). */
const store = useEmberlingsStore();
const MAX_QUANTITY = 99;

const insignia = computed(() => store.profile?.insignia ?? 0);
const tiers = computed(() => store.catalog?.tiers ?? []);
const quantities = reactive<Record<string, number>>({});
const message = ref("");
const outOfReach = computed(() => tiers.value.filter((t) => t.emblem_price > insignia.value).map((t) => titleCase(t.id)));

function quantityOf(tierId: string): number {
  return quantities[tierId] ?? 1;
}

function emblemCost(tierId: string, price: number): number {
  return price * quantityOf(tierId);
}

function canBuyEmblems(tierId: string, price: number): boolean {
  const quantity = quantityOf(tierId);
  const valid = Number.isInteger(quantity) && quantity >= 1 && quantity <= MAX_QUANTITY;
  return !store.busy && valid && emblemCost(tierId, price) <= insignia.value;
}

function setQuantity(tierId: string, event: Event): void {
  quantities[tierId] = Number((event.target as HTMLInputElement).value);
}

async function buyEmblems(tierId: string): Promise<void> {
  message.value = "";
  const bought = await store.buyEmblems(tierId, quantityOf(tierId));
  if (bought) {
    message.value = `Bought ${bought.quantity} ${titleCase(bought.tier_id)} EMBLEM${bought.quantity === 1 ? "" : "s"} for ${bought.price} Insignia.`;
  }
}

const regularSparks = computed(() => (store.catalog?.sparks ?? []).filter((s) => !s.forbidden));
const regularTiers = computed(() => tiers.value.filter((t) => t.copy_threshold !== null));
const copySpark = ref("");
const copyTier = ref("");

async function buyCopies(): Promise<void> {
  message.value = "";
  const bought = await store.buyCopies(copySpark.value, copyTier.value);
  if (bought) {
    const copies = `${bought.copies_granted} ${bought.copies_granted === 1 ? "copy" : "copies"}`;
    message.value = `Bought ${copies} for ${bought.price} Insignia; it is now ${titleCase(bought.resulting_tier_id)}.`;
  }
}

const sellable = computed(() => (store.profile?.sparks ?? []).filter((s) => s.copies > 0));
const selling = ref<string | null>(null);
const sellingName = computed(() => sellable.value.find((s) => s.spark_id === selling.value)?.name ?? "");

async function sell(): Promise<void> {
  const sparkId = selling.value;
  selling.value = null;
  if (sparkId === null) return;
  message.value = "";
  const sale = await store.sellCopy(sparkId);
  if (sale) {
    message.value = `Sold one copy for ${sale.value} Insignia${sale.downgraded ? `; it is now ${titleCase(sale.tier_id)}` : ""}.`;
  }
}
</script>

<template>
  <section class="shop">
    <p v-if="message" class="notice" role="status"><EmIcon name="check" /> {{ message }}</p>

    <EmPanel class="wallet">
      <div class="balance">
        <p class="em-eyebrow">Your wallet</p>
        <h3 class="em-pixel em-num amount">{{ insignia }} Insignia</h3>
      </div>
      <div v-for="t in tiers" :key="t.id" class="count" :style="{ '--tier': `var(--em-tier-${t.id}, var(--em-tier-common))` }">
        <strong class="em-pixel em-num">{{ store.profile?.emblems[t.id] ?? 0 }}</strong>
        <span>{{ titleCase(t.id) }} EMBLEMs</span>
      </div>
    </EmPanel>

    <EmPanel>
      <div class="section-head">
        <h3 class="em-pixel">Buy EMBLEMs</h3>
        <small>Choose how many, then buy</small>
      </div>
      <ul class="rows">
        <li v-for="t in tiers" :key="t.id" class="row" :data-tier="t.id">
          <div class="what">
            <EmTierBadge :tier-id="t.id" />
            <span>{{ titleCase(t.id) }} EMBLEM</span>
          </div>
          <span class="price em-num"><strong>{{ t.emblem_price }}</strong> Insignia</span>
          <span class="owned em-num">{{ store.profile?.emblems[t.id] ?? 0 }} owned</span>
          <input
            type="number"
            min="1"
            :max="MAX_QUANTITY"
            :value="quantityOf(t.id)"
            :aria-label="`${titleCase(t.id)} EMBLEMs to buy`"
            @input="setQuantity(t.id, $event)"
          />
          <EmButton variant="primary" :disabled="!canBuyEmblems(t.id, t.emblem_price)" @click="buyEmblems(t.id)">
            Buy for {{ emblemCost(t.id, t.emblem_price) }}
          </EmButton>
        </li>
      </ul>
      <p v-if="outOfReach.length" class="hint">Not enough Insignia for: {{ outOfReach.join(", ") }}.</p>
    </EmPanel>

    <div class="lower">
      <EmPanel>
        <h3 class="em-pixel">Buy Spark copies</h3>
        <label class="field">
          <span>Spark</span>
          <select v-model="copySpark" name="copy-spark" aria-label="Spark">
            <option value="" disabled>Choose a Spark</option>
            <option v-for="s in regularSparks" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
        </label>
        <label class="field">
          <span>Tier</span>
          <select v-model="copyTier" name="copy-tier" aria-label="Tier">
            <option value="" disabled>Choose a tier</option>
            <option v-for="t in regularTiers" :key="t.id" :value="t.id">{{ titleCase(t.id) }}</option>
          </select>
        </label>
        <p class="hint">
          Absorbed copies raise a Spark's tier. The price depends on the copies you already have and the Spark's level; the shop
          tells you when your Insignia falls short.
        </p>
        <EmButton variant="primary" class="block" :disabled="store.busy || !copySpark || !copyTier" @click="buyCopies">
          <EmIcon name="shop" /> Buy copies
        </EmButton>
      </EmPanel>

      <EmPanel>
        <h3 class="em-pixel">Sell an absorbed copy</h3>
        <p v-if="sellable.length === 0" class="empty">No absorbed copies to sell.</p>
        <template v-else>
          <p class="hint">Sell one absorbed copy. Your collected Spark stays with you.</p>
          <ul class="rows sell">
            <li v-for="s in sellable" :key="s.spark_id" class="row" :data-sell="s.spark_id">
              <div class="what">
                <strong>{{ s.name }}</strong>
                <span class="em-num">{{ s.copies }} {{ s.copies === 1 ? "copy" : "copies" }} · {{ titleCase(s.tier_id) }}</span>
              </div>
              <EmButton :disabled="store.busy" @click="selling = s.spark_id"><EmIcon name="coin" /> Sell one copy</EmButton>
            </li>
          </ul>
        </template>
      </EmPanel>
    </div>

    <EmConfirm
      :open="selling !== null"
      title="Sell one copy?"
      :message="`One absorbed copy of ${sellingName} goes back to the shop for Insignia. Its tier can drop.`"
      confirm-label="Sell"
      :busy="store.busy"
      @confirm="sell"
      @close="selling = null"
    />
  </section>
</template>

<style scoped>
.shop {
  display: flex;
  flex-direction: column;
  gap: var(--em-space-5);
}
.notice {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border: 1px solid var(--em-success);
  border-radius: var(--em-radius);
  color: var(--em-success);
  background: var(--em-success-surface);
}
.wallet {
  display: grid;
  grid-template-columns: 1.5fr repeat(6, 1fr);
  gap: var(--em-space-3);
  align-items: center;
}
.amount {
  margin: 6px 0 0;
  font-size: 18px;
}
.count {
  text-align: center;
  font-size: 12px;
  color: var(--tier);
}
.count strong {
  display: block;
  margin-bottom: 4px;
  font-size: 22px;
  font-weight: 400;
}
.section-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--em-space-3);
  margin-bottom: var(--em-space-3);
}
h3 {
  margin: 0 0 var(--em-space-3);
  font-size: 18px;
  line-height: 1.4;
}
.section-head h3 {
  margin: 0;
}
.section-head small {
  color: var(--em-muted);
}
.rows {
  margin: 0;
  padding: 0;
  list-style: none;
}
.row {
  display: grid;
  grid-template-columns: 1fr 120px 90px 70px 120px;
  align-items: center;
  gap: var(--em-space-4);
  padding: 14px 0;
  border-bottom: 1px solid var(--em-divider);
}
.row:last-child {
  border-bottom: 0;
}
.sell .row {
  grid-template-columns: 1fr auto;
}
.what {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}
.what > span:last-child {
  font-size: 12px;
  color: var(--em-muted);
}
.price {
  text-align: right;
}
.price strong {
  font-size: 16px;
}
.owned {
  text-align: right;
  font-size: 13px;
  color: var(--em-muted);
}
.row input {
  min-height: var(--em-target);
  padding: 8px;
  border: 1px solid var(--em-border);
  border-radius: var(--em-radius);
  color: var(--em-text);
  background: var(--em-bg);
  font: inherit;
  text-align: center;
}
.hint {
  margin: var(--em-space-3) 0;
  font-size: 12px;
  color: var(--em-muted);
}
.lower {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--em-space-5);
  align-items: start;
}
.field {
  display: flex;
  flex-direction: column;
  gap: var(--em-space-2);
  margin-bottom: var(--em-space-3);
  font-size: 12px;
  font-weight: 600;
  color: var(--em-muted);
}
.field select {
  min-height: var(--em-target);
  padding: 10px 12px;
  border: 1px solid var(--em-border);
  border-radius: var(--em-radius);
  color: var(--em-text);
  background: var(--em-bg);
  font: inherit;
  font-size: 14px;
}
.block {
  width: 100%;
}
.empty {
  padding: 14px;
  border: 1px dashed var(--em-border);
  font-size: 13px;
  color: var(--em-muted);
}
@media (max-width: 700px) {
  .wallet {
    grid-template-columns: repeat(3, 1fr);
    gap: 20px 10px;
  }
  .balance {
    grid-column: 1 / -1;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--em-divider);
    text-align: center;
  }
  .row {
    grid-template-columns: 1fr 70px 76px;
    gap: var(--em-space-2);
  }
  .row .price,
  .row .owned {
    display: none;
  }
  .lower {
    grid-template-columns: minmax(0, 1fr);
  }
  .sell .row {
    grid-template-columns: 1fr auto;
  }
}
</style>
