<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { AgentConfig, AgentFile, ProviderCatalog } from "../../api/AgentsAdminClient";
import BaseModal from "../BaseModal.vue";
import ToggleSwitch from "../ToggleSwitch.vue";

/** Create or edit one agent file. The parent keeps `open`, saves on `save`
 * and closes on `close`; `preview` asks the parent for the assembled system
 * prompt of the draft. Fields the form does not show are carried over from
 * `initial` unchanged. */
const props = defineProps<{
  open: boolean;
  initial: AgentFile | null;
  providers: ProviderCatalog;
  suggestedPort: number;
  busy: boolean;
  error: string;
  previewText: string;
  previewing: boolean;
  previewError: string;
}>();
const emit = defineEmits<{ save: [id: string, config: AgentConfig]; preview: [id: string, config: AgentConfig, caveman: boolean]; close: [] }>();

const EFFORTS = ["off", "low", "medium", "high"];
const TIERS = ["light", "standard", "heavy"];

const editing = computed(() => props.initial !== null);
const id = ref("");
const label = ref("");
const port = ref("");
const url = ref("");
const enabled = ref(true);
const entry = ref(false);
const orchestrator = ref(false);
const provider = ref("anthropic");
const gateway = ref("");
const model = ref("");
const effort = ref("off");
const minTier = ref("");
const maxTier = ref("");
const identity = ref("");
const temperature = ref("");
const maxTokens = ref("");
const maxToolRounds = ref("");
const maxEffort = ref("");
const routingLaya = ref(false);
const topK = ref("");
const allowAuto = ref(false);
const minScore = ref("");
const previewCaveman = ref(false);
const persona = ref("");
const instructions = ref("");
const focus = ref("");
const allow = ref("");
const deny = ref("");
const localError = ref("");

const isLaya = computed(() => provider.value === "laya");
const gateways = computed(() => props.providers[provider.value] ?? []);
// What a provider uses when the agent names no gateway (ai_agent: agent_spec._DEFAULT_GATEWAY).
const DEFAULT_GATEWAY: Record<string, string> = { anthropic: "claude", openai: "gpt" };
/** The model each tier resolves to on the chosen gateway, and whether the range allows it. */
const tierPreview = computed(() => {
  const gatewayId = gateway.value || DEFAULT_GATEWAY[provider.value];
  const offered = gateways.value.find((g) => g.id === gatewayId)?.tiers ?? [];
  const low = minTier.value ? TIERS.indexOf(minTier.value) : 0;
  const high = maxTier.value ? TIERS.indexOf(maxTier.value) : TIERS.length - 1;
  return TIERS.map((tier, index) => ({
    tier,
    model: offered.find((t) => t.tier === tier)?.id ?? "",
    allowed: index >= low && index <= high,
  })).filter((row) => row.model);
});
const providerIds = computed(() => Object.keys(props.providers));

function joined(globs: string[] | undefined): string {
  return (globs ?? []).join(", ");
}

watch(
  () => props.open,
  (isOpen) => {
    if (!isOpen) return;
    const a = props.initial;
    localError.value = "";
    id.value = a?.id ?? "";
    label.value = a?.label ?? "";
    port.value = String(a?.port ?? props.suggestedPort);
    url.value = a?.url ?? "";
    enabled.value = a?.enabled ?? true;
    entry.value = a?.entry ?? false;
    orchestrator.value = a?.orchestrator ?? false;
    provider.value = a?.llm?.provider ?? providerIds.value[0] ?? "anthropic";
    gateway.value = a?.llm?.gateway ?? "";
    model.value = a?.llm?.model ?? "";
    effort.value = a?.llm?.reasoning_effort ?? "off";
    minTier.value = a?.llm?.min_tier ?? "";
    maxTier.value = a?.llm?.max_tier ?? "";
    identity.value = a?.identity ?? "";
    temperature.value = a?.llm?.temperature === undefined ? "" : String(a.llm.temperature);
    maxTokens.value = a?.llm?.max_tokens === undefined ? "" : String(a.llm.max_tokens);
    maxToolRounds.value = a?.llm?.max_tool_rounds === undefined ? "" : String(a.llm.max_tool_rounds);
    maxEffort.value = a?.llm?.max_effort ?? "";
    const routing = (a?.routing ?? {}) as Record<string, unknown>;
    routingLaya.value = routing.laya === true;
    topK.value = routing.top_k === undefined ? "" : String(routing.top_k);
    allowAuto.value = routing.allow_auto === true;
    minScore.value = routing.min_score === undefined || routing.min_score === null ? "" : String(routing.min_score);
    previewCaveman.value = false;
    persona.value = a?.persona ?? "";
    instructions.value = a?.instructions ?? "";
    focus.value = a?.focus ?? "";
    allow.value = joined(a?.tools?.allow);
    deny.value = joined(a?.tools?.deny);
  },
  { immediate: true },
);

// A gateway belongs to one provider: changing the provider clears a gateway it does not offer.
watch(provider, () => {
  if (gateway.value && !gateways.value.some((g) => g.id === gateway.value)) gateway.value = "";
  if (isLaya.value) {
    entry.value = false;
    orchestrator.value = false;
  }
});

function globs(text: string): string[] {
  return text.split(/[,\n]/).map((g) => g.trim()).filter(Boolean);
}

/** A blank box is "not set" (undefined); text that is not a number in range is null, with the reason in localError. */
function optionalNumber(text: string, name: string, low: number, high: number, whole: boolean): number | undefined | null {
  if (!text.trim()) return undefined;
  const value = Number(text);
  if (!Number.isFinite(value) || value < low || value > high || (whole && !Number.isInteger(value))) {
    localError.value = `${name} must be ${whole ? "a whole number" : "a number"} from ${low} to ${high}.`;
    return null;
  }
  return value;
}

/** The agent file the form describes, or null (with localError set) when a field is invalid. */
function buildConfig(): AgentConfig | null {
  localError.value = "";
  const portNumber = Number(port.value);
  if (!Number.isInteger(portNumber) || portNumber < 1 || portNumber > 65535) {
    localError.value = "Port must be a whole number from 1 to 65535.";
    return null;
  }
  if (minTier.value && maxTier.value && TIERS.indexOf(minTier.value) > TIERS.indexOf(maxTier.value)) {
    localError.value = "The weakest tier cannot be stronger than the strongest tier.";
    return null;
  }
  const { id: _id, error: _error, ...kept } = props.initial ?? { id: "" };
  const llm: AgentConfig["llm"] = { ...(kept.llm ?? {}), provider: provider.value };
  const setOrDrop = (key: string, value: string): void => {
    if (value) llm[key] = value;
    else delete llm[key];
  };
  setOrDrop("gateway", gateway.value);
  setOrDrop("model", model.value.trim());
  const numbers = {
    temperature: optionalNumber(temperature.value, "Temperature", 0, 2, false),
    max_tokens: optionalNumber(maxTokens.value, "Max tokens", 1, 1_000_000, true),
    max_tool_rounds: optionalNumber(maxToolRounds.value, "Max tool rounds", 1, 100, true),
  };
  const topKNumber = orchestrator.value ? optionalNumber(topK.value, "Top K", 1, 50, true) : undefined;
  const minScoreNumber = orchestrator.value ? optionalNumber(minScore.value, "Min score", -1, 1, false) : undefined;
  if (Object.values(numbers).includes(null as never) || topKNumber === null || minScoreNumber === null) return null;
  if (isLaya.value) {
    // Laya triage runs locally and takes no generation or tier settings.
    for (const key of ["reasoning_effort", "max_tier", "min_tier", "max_effort", "temperature", "max_tokens", "max_tool_rounds"]) delete llm[key];
  } else {
    setOrDrop("reasoning_effort", effort.value === "off" ? "" : effort.value);
    setOrDrop("min_tier", minTier.value);
    setOrDrop("max_tier", maxTier.value);
    setOrDrop("max_effort", maxEffort.value);
    for (const [key, value] of Object.entries(numbers)) {
      if (value === undefined) delete llm[key];
      else llm[key] = value;
    }
  }
  const config: AgentConfig = {
    ...kept,
    label: label.value.trim(),
    port: portNumber,
    url: url.value.trim(),
    enabled: enabled.value,
    entry: entry.value,
    orchestrator: orchestrator.value,
    llm,
    identity: identity.value,
    persona: persona.value,
    instructions: instructions.value,
    focus: focus.value,
    tools: { allow: globs(allow.value), deny: globs(deny.value) },
  };
  if (orchestrator.value) {
    const routing: Record<string, unknown> = { ...((kept.routing ?? {}) as Record<string, unknown>), laya: routingLaya.value, allow_auto: allowAuto.value };
    for (const [key, value] of [["top_k", topKNumber], ["min_score", minScoreNumber]] as const) {
      if (value === undefined) delete routing[key];
      else routing[key] = value;
    }
    config.routing = routing;
  } else {
    delete config.routing; // ai_agent allows routing only on an orchestrator
  }
  for (const key of ["label", "url", "identity", "persona", "instructions", "focus"]) if (!config[key]) delete config[key];
  return config;
}

function submit(): void {
  const config = buildConfig();
  if (config) emit("save", id.value.trim(), config);
}

function previewPrompt(): void {
  const config = buildConfig();
  if (config) emit("preview", id.value.trim() || "draft", config, previewCaveman.value);
}
</script>

<template>
  <BaseModal :open="open" :title="editing ? `Edit ${initial?.label || initial?.id}` : 'New agent'" @close="emit('close')">
    <form class="agent-form" @submit.prevent="submit">
      <label class="field">
        <span>Id</span>
        <input v-model="id" data-test="id" type="text" required maxlength="63" pattern="[a-z0-9][a-z0-9\-]*" autocomplete="off" :disabled="editing" placeholder="data-analyst" />
        <small>Lowercase letters, digits and dashes. It names the file and cannot change later.</small>
      </label>
      <div class="row">
        <label class="field grow"><span>Name</span><input v-model="label" data-test="label" type="text" maxlength="80" autocomplete="off" placeholder="Data analyst" /></label>
        <label class="field port"><span>Port</span><input v-model="port" data-test="port" type="number" min="1" max="65535" required /></label>
      </div>

      <label class="field">
        <span>URL</span>
        <input v-model="url" data-test="url" type="text" autocomplete="off" placeholder="http://127.0.0.1:9104/mcp" />
        <small>Where ember and the other agents reach this agent. Leave empty to use this machine and the port above; set it for an agent behind another host or a proxy.</small>
      </label>

      <fieldset>
        <legend>Model</legend>
        <div class="row">
          <label class="field grow"><span>Provider</span>
            <select v-model="provider" data-test="provider"><option v-for="p in providerIds" :key="p" :value="p">{{ p }}</option></select>
          </label>
          <label class="field grow"><span>Gateway</span>
            <select v-model="gateway" data-test="gateway" :disabled="isLaya">
              <option value="">Provider default</option>
              <option v-for="g in gateways" :key="g.id" :value="g.id">{{ g.label }}</option>
            </select>
          </label>
        </div>
        <label class="field"><span>Model</span><input v-model="model" data-test="model" type="text" autocomplete="off" :disabled="isLaya" placeholder="Gateway default" /></label>
        <div v-if="!isLaya" class="row">
          <label class="field grow"><span>Reasoning effort</span>
            <select v-model="effort" data-test="effort"><option v-for="e in EFFORTS" :key="e" :value="e">{{ e }}</option></select>
          </label>
          <label class="field grow"><span>Weakest tier it may use</span>
            <select v-model="minTier" data-test="min-tier"><option value="">No limit</option><option v-for="t in TIERS" :key="t" :value="t">{{ t }}</option></select>
          </label>
          <label class="field grow"><span>Strongest tier it may use</span>
            <select v-model="maxTier" data-test="max-tier"><option value="">No limit</option><option v-for="t in TIERS" :key="t" :value="t">{{ t }}</option></select>
          </label>
        </div>
        <ul v-if="tierPreview.length" class="tier-preview" aria-label="Model tiers on this gateway" data-test="tier-preview">
          <li v-for="row in tierPreview" :key="row.tier" :class="{ off: !row.allowed }" :data-tier="row.tier">
            <span>{{ row.tier }}</span><code>{{ row.model }}</code><span class="where">{{ row.allowed ? "available" : "not available" }}</span>
          </li>
        </ul>
        <div v-if="!isLaya" class="row">
          <label class="field grow"><span>Temperature</span><input v-model="temperature" data-test="temperature" type="text" inputmode="decimal" autocomplete="off" placeholder="Model default" /></label>
          <label class="field grow"><span>Max tokens</span><input v-model="maxTokens" data-test="max-tokens" type="text" inputmode="numeric" autocomplete="off" placeholder="Gateway limit" /></label>
          <label class="field grow"><span>Max tool rounds</span><input v-model="maxToolRounds" data-test="max-tool-rounds" type="text" inputmode="numeric" autocomplete="off" placeholder="Default" /></label>
        </div>
        <label v-if="!isLaya" class="field"><span>Highest effort a delegating agent may request</span>
          <select v-model="maxEffort" data-test="max-effort"><option value="">No limit</option><option v-for="e in EFFORTS" :key="e" :value="e">{{ e }}</option></select>
        </label>
        <small v-if="!isLaya">The orchestrator picks the lightest tier in this range that fits each task. Tier models are set per gateway in ai_agent's config_gateways.json.</small>
      </fieldset>

      <fieldset>
        <legend>Behaviour</legend>
        <label class="field"><span>Identity (replaces the shared identity line)</span><textarea v-model="identity" data-test="identity" rows="2" placeholder="Empty = the shared identity from Shared prompts" /></label>
        <label class="field"><span>Persona</span><textarea v-model="persona" data-test="persona" rows="3" /></label>
        <label class="field"><span>Instructions</span><textarea v-model="instructions" data-test="instructions" rows="8" placeholder="Empty = the shared default instructions" /></label>
        <label class="field"><span>Focus</span><input v-model="focus" data-test="focus" type="text" autocomplete="off" placeholder="One line the entry agent uses to pick this specialist" /></label>
        <div class="row">
          <label class="field grow"><span>Allowed tools</span><input v-model="allow" data-test="allow" type="text" autocomplete="off" placeholder="All tools, or e.g. calc_*, convert_*" /></label>
          <label class="field grow"><span>Denied tools</span><input v-model="deny" data-test="deny" type="text" autocomplete="off" placeholder="None" /></label>
        </div>
      </fieldset>

      <fieldset v-if="orchestrator">
        <legend>Routing (how an orchestrator picks specialists)</legend>
        <div class="row">
          <label class="field grow"><span>Shortlist size (top K)</span><input v-model="topK" data-test="top-k" type="text" inputmode="numeric" autocomplete="off" placeholder="3" /></label>
          <label class="field grow"><span>Minimum score (-1 to 1)</span><input v-model="minScore" data-test="min-score" type="text" inputmode="decimal" autocomplete="off" placeholder="None" /></label>
        </div>
        <ToggleSwitch :checked="routingLaya" data-test="routing-laya" @change="routingLaya = ($event.target as HTMLInputElement).checked">Use Laya triage to shortlist specialists</ToggleSwitch>
        <ToggleSwitch :checked="allowAuto" data-test="routing-auto" @change="allowAuto = ($event.target as HTMLInputElement).checked">Let triage pick the specialist automatically</ToggleSwitch>
      </fieldset>

      <div class="switches">
        <ToggleSwitch :checked="enabled" data-test="enabled" @change="enabled = ($event.target as HTMLInputElement).checked">Enabled</ToggleSwitch>
        <ToggleSwitch :checked="orchestrator" :disabled="isLaya" data-test="orchestrator" @change="orchestrator = ($event.target as HTMLInputElement).checked">Orchestrator (can hand work to other agents)</ToggleSwitch>
        <ToggleSwitch :checked="entry" :disabled="isLaya" data-test="entry" @change="entry = ($event.target as HTMLInputElement).checked">Entry agent (receives every new question)</ToggleSwitch>
      </div>
      <p v-if="entry" class="hint">Only one enabled agent can be the entry agent. To move it, unset it on the current one first.</p>

      <fieldset class="preview">
        <legend>Prompt preview</legend>
        <p class="hint">The system prompt the model receives, built from this form and the shared prompts.</p>
        <div class="row preview-bar">
          <ToggleSwitch :checked="previewCaveman" data-test="preview-caveman" @change="previewCaveman = ($event.target as HTMLInputElement).checked">Caveman mode on</ToggleSwitch>
          <button type="button" class="cancel" data-test="preview" :disabled="previewing" @click="previewPrompt">{{ previewing ? "Building…" : "Show prompt" }}</button>
        </div>
        <p v-if="previewError" class="error" role="alert" data-test="preview-error">{{ previewError }}</p>
        <pre v-if="previewText" class="prompt-text" data-test="preview-text">{{ previewText }}</pre>
      </fieldset>

      <p v-if="localError || error" class="error" role="alert" data-test="form-error">{{ localError || error }}</p>
      <div class="actions">
        <button type="button" class="cancel" :disabled="busy" @click="emit('close')">Cancel</button>
        <button type="submit" class="primary" :disabled="busy" data-test="save">{{ busy ? "Saving…" : editing ? "Save" : "Create" }}</button>
      </div>
    </form>
  </BaseModal>
</template>

<style scoped>
.agent-form { display: grid; gap: 12px; }
.row { display: flex; flex-wrap: wrap; gap: 10px; }
.grow { flex: 1 1 160px; }
.port { flex: 0 0 110px; }
.field { display: grid; gap: 4px; min-width: 0; font-size: 0.9em; }
.field > span { color: var(--muted); }
.field small, .hint { color: var(--muted); font-size: 0.8em; }
.hint { margin: 0; }
input:not([type="checkbox"]), select, textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  background: var(--bg);
  font: inherit;
}
textarea { resize: vertical; }
input:disabled, select:disabled { opacity: 0.6; }
fieldset { display: grid; gap: 10px; margin: 0; padding: 10px 12px 12px; border: 1px solid var(--border); border-radius: var(--radius-lg); }
legend { padding: 0 6px; color: var(--muted); font-size: 0.85em; }
.tier-preview { display: grid; gap: 4px; margin: 0; padding: 0; list-style: none; font-size: 0.85em; }
.tier-preview li { display: grid; grid-template-columns: 70px minmax(0, 1fr) auto; gap: 10px; }
.tier-preview li.off { color: var(--muted); text-decoration: line-through; }
.tier-preview code { font-family: var(--mono); overflow-wrap: anywhere; }
.tier-preview .where { color: var(--muted); text-decoration: none; }
.switches { display: grid; gap: 8px; }
.preview-bar { align-items: center; justify-content: space-between; }
.prompt-text { max-height: 280px; margin: 0; padding: 10px 12px; overflow: auto; border-radius: var(--radius-md); background: var(--code-bg); color: var(--text); font-family: var(--mono); font-size: 0.8em; white-space: pre-wrap; overflow-wrap: anywhere; }
.actions { display: flex; justify-content: flex-end; gap: 8px; }
.cancel { padding: 6px 16px; border: 1px solid var(--border); border-radius: var(--radius-full); background: transparent; color: var(--text); font: inherit; cursor: pointer; }
.primary { padding: 6px 16px; border: none; border-radius: var(--radius-full); cursor: pointer; font: inherit; font-weight: 600; color: var(--accent-contrast); background: var(--accent); }
.primary:disabled, .cancel:disabled { opacity: 0.6; cursor: default; }
.error { margin: 0; color: var(--danger); }
:is(button, input, select, textarea):focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
</style>
