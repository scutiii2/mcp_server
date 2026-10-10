<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { useEmberlingsStore } from "../../stores/emberlings";
import { titleCase } from "../../utils/emberlings";
import ConfirmModal from "../ConfirmModal.vue";

/** The Shop tab: EMBLEMs per tier, copies of a regular Spark at a tier, and
 * selling one absorbed copy. EMBLEM buttons are disabled when Insignia would
 * not cover the price. A copy's price depends on numbers only mini_games
 * knows, so it says itself (a 409 with the cost) when Insignia falls short;
 * the page shows that message (the store's `error`). */
const store = useEmberlingsStore();
const MAX_QUANTITY = 99;

const insignia = computed(() => store.profile?.insignia ?? 0);
const tiers = computed(() => store.catalog?.tiers ?? []);
const quantities = reactive<Record<string, number>>({});
const message = ref("");

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
    <p class="muted">You have {{ insignia }} Insignia.</p>
    <p v-if="message" class="notice" role="status">{{ message }}</p>

    <h3>EMBLEMs</h3>
    <ul class="rows">
      <li v-for="t in tiers" :key="t.id" class="row" :data-tier="t.id">
        <span class="row-name">{{ titleCase(t.id) }}</span>
        <span class="muted">{{ t.emblem_price }} Insignia each · you own {{ store.profile?.emblems[t.id] ?? 0 }}</span>
        <input
          type="number"
          min="1"
          :max="MAX_QUANTITY"
          :value="quantityOf(t.id)"
          :aria-label="`${titleCase(t.id)} EMBLEMs to buy`"
          @input="setQuantity(t.id, $event)"
        />
        <button type="button" class="primary" :disabled="!canBuyEmblems(t.id, t.emblem_price)" @click="buyEmblems(t.id)">
          Buy for {{ emblemCost(t.id, t.emblem_price) }}
        </button>
      </li>
    </ul>

    <h3>Copies</h3>
    <p class="muted">
      Copies raise a regular Spark's tier. The price depends on the copies you already have and the Spark's level; the shop
      tells you when your Insignia falls short.
    </p>
    <div class="copies">
      <select v-model="copySpark" name="copy-spark" aria-label="Spark">
        <option value="" disabled>Choose a Spark</option>
        <option v-for="s in regularSparks" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select>
      <select v-model="copyTier" name="copy-tier" aria-label="Tier">
        <option value="" disabled>Choose a tier</option>
        <option v-for="t in regularTiers" :key="t.id" :value="t.id">{{ titleCase(t.id) }}</option>
      </select>
      <button type="button" class="primary" :disabled="store.busy || !copySpark || !copyTier" @click="buyCopies">Buy copies</button>
    </div>

    <h3>Sell</h3>
    <p v-if="sellable.length === 0" class="muted">No absorbed copies to sell.</p>
    <ul v-else class="rows">
      <li v-for="s in sellable" :key="s.spark_id" class="row" :data-sell="s.spark_id">
        <span class="row-name">{{ s.name }}</span>
        <span class="muted">{{ s.copies }} {{ s.copies === 1 ? "copy" : "copies" }} · {{ titleCase(s.tier_id) }}</span>
        <button type="button" class="chip" :disabled="store.busy" @click="selling = s.spark_id">Sell one copy</button>
      </li>
    </ul>

    <ConfirmModal
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
.shop h3 {
  margin: 20px 0 8px;
}
.shop > p {
  margin: 0 0 8px;
}
.notice {
  color: var(--success);
}
.rows {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
}
.row-name {
  min-width: 90px;
  font-weight: 600;
}
.row input {
  width: 72px;
}
.row button {
  margin-left: auto;
}
.copies {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
