<script setup lang="ts">
import { computed } from "vue";
import { RouterLink } from "vue-router";
import { visiblePages } from "../router/pages";
import { useAuthStore } from "../stores/auth";

// Account is always available and is not part of the permission-gated rail.
const ACCOUNT_ICON = ["M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2", "M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0z"];

const auth = useAuthStore();
const pages = computed(() => visiblePages((p) => auth.hasPermission(p)));
const chat = computed(() => pages.value.find((p) => p.to === "/"));
const initial = computed(() => auth.account?.username.charAt(0).toUpperCase() ?? "");
const descriptions: Record<string, string> = {
  "/agents": "Explore your agents and what each one is for.",
  "/capabilities": "Discover tools, resources, and connected extensions.",
  "/watchers": "Browse background watchers across your capabilities.",
  "/usage": "Review your token usage and account limits.",
  "/settings": "Adjust chat and appearance preferences.",
};
const groups = computed(() => {
  const monitor = new Set(["/watchers", "/usage"]);
  const manage = new Set(["/settings"]);
  return [
    {
      id: "work", title: "Build & explore", subtitle: "Meet your agents and their tools",
      pages: pages.value.filter((p) => p.to !== "/" && !monitor.has(p.to) && !manage.has(p.to))
        .sort((a, b) => Number(b.to === "/agents") - Number(a.to === "/agents")),
    },
    {
      id: "monitor", title: "Monitor", subtitle: "Keep an eye on what’s happening",
      pages: pages.value.filter((p) => monitor.has(p.to)),
    },
    {
      id: "manage", title: "Manage", subtitle: "Make Ember work for you",
      pages: [...pages.value.filter((p) => manage.has(p.to)), {
        to: "/account", label: "Account", description: "Your email, password, and signed-in devices.", icon: ACCOUNT_ICON,
      }],
    },
  ].filter((group) => group.pages.length > 0);
});
</script>

<template>
  <section class="overview">
    <div class="column">
      <div class="heading">
        <div><h2>Overview</h2><p>A place to start. Everything you need, close by.</p></div>
        <RouterLink v-if="auth.account" to="/account" class="identity">
          <span class="user" aria-hidden="true">{{ initial }}</span><span>Signed in as <b>{{ auth.account.username }}</b></span>
        </RouterLink>
      </div>
      <section v-if="chat" class="hero" aria-labelledby="chat-heading">
        <div class="hero-copy">
          <div class="eyebrow"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z" /></svg>Your AI workspace</div>
          <h3 id="chat-heading">Turn a thought into a next step.</h3>
          <p>Ask a question, explore an idea, or let an agent help you get something done.</p>
          <RouterLink :to="chat.to" class="primary">Start a chat <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-5-5 5 5-5 5" /></svg></RouterLink>
        </div>
        <div class="hero-art" aria-hidden="true">
          <span class="orbit" /><span class="orbit inner" /><span class="spark" /><span class="spark small" />
          <svg class="flame" viewBox="0 0 64 64"><path d="M35 5c4 15-13 18-10 29 3-2 5-6 6-9 9 6 16 12 14 21-1 10-9 15-18 13C12 56 10 43 17 32c-1 9 3 11 5 12-6-17 17-22 13-39z" /></svg>
        </div>
      </section>
      <p v-if="pages.length === 0" class="empty">Your role gives you no pages yet - ask an administrator.</p>
      <section v-for="group in groups" :key="group.id" :aria-labelledby="`${group.id}-heading`">
        <div class="section-head"><h3 :id="`${group.id}-heading`">{{ group.title }}</h3><span>{{ group.subtitle }}</span></div>
        <div class="grid" :class="{ work: group.id === 'work' }">
          <RouterLink v-for="p in group.pages" :key="p.to" :to="p.to" class="card">
            <span class="icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path v-for="d in p.icon" :key="d" :d="d" /></svg></span>
            <div class="copy"><h4>{{ p.label }}</h4><p>{{ descriptions[p.to] ?? p.description }}</p></div>
            <svg class="arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
          </RouterLink>
        </div>
      </section>
      <footer class="footer"><span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6z" /><path d="m8 12 3 3 5-6" /></svg>Your access determines what appears here.</span><span>ember · Your AI workspace</span></footer>
    </div>
  </section>
</template>

<style scoped>
.overview { flex: 1; min-height: 0; overflow-y: auto; }
a { color: inherit; text-decoration: none; }
svg { width: 24px; height: 24px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; flex-shrink: 0; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
.column { max-width: 980px; padding: 32px 16px 26px; margin: auto; }
.heading { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 24px; }
h2 { font-size: 1.2em; font-weight: 600; margin: 0 0 4px; }
.heading p { color: var(--muted); margin: 0; font-size: 0.9em; }
.identity { display: flex; gap: 9px; align-items: center; font-size: 0.85em; color: var(--muted); min-width: 0; max-width: 40%; overflow-wrap: anywhere; }
.identity b { color: var(--text); font-weight: 500; }
.user { display: grid; place-items: center; width: 32px; height: 32px; flex-shrink: 0; border: 1px solid var(--border); border-radius: var(--radius-full); background: var(--surface); }
.hero { display: flex; justify-content: space-between; position: relative; overflow: hidden; border: 1px solid color-mix(in srgb, var(--accent) 25%, var(--border)); border-radius: var(--radius-lg); background: linear-gradient(110deg, color-mix(in srgb, var(--accent) 8%, var(--surface)), var(--surface)); padding: 27px 28px; margin-bottom: 30px; }
.hero-copy { min-width: 0; }
.eyebrow { font-size: 0.75em; letter-spacing: 0.1em; text-transform: uppercase; color: var(--accent); font-weight: 600; display: flex; gap: 7px; align-items: center; }
.eyebrow svg { width: 15px; height: 15px; }
.hero h3 { font-size: 1.6em; letter-spacing: -0.025em; font-weight: 600; margin: 9px 0 6px; }
.hero p { color: var(--muted); font-size: 0.9em; margin: 0 0 21px; max-width: 430px; }
.primary { display: inline-flex; align-items: center; gap: 24px; padding: 9px 17px; border-radius: var(--radius-full); background: var(--accent); color: var(--accent-contrast); font-weight: 600; font-size: 0.85em; }
.primary:hover { background: color-mix(in srgb, var(--accent) 90%, var(--text)); }
.primary svg { width: 16px; height: 16px; }
.hero-art { position: relative; width: 210px; flex-shrink: 0; display: grid; place-items: center; color: var(--accent); margin-right: 14px; }
.orbit { position: absolute; width: 168px; height: 168px; border: 1px solid color-mix(in srgb, var(--accent) 16%, transparent); border-radius: var(--radius-full); }
.orbit.inner { width: 128px; height: 128px; background: color-mix(in srgb, var(--accent) 4%, transparent); animation: ember-breathe 4s ease-in-out infinite; }
.flame { width: 63px; height: 63px; stroke-width: 1.1; fill: color-mix(in srgb, var(--accent) 9%, transparent); z-index: 1; transform-origin: 50% 90%; animation: ember-flicker 2.6s ease-in-out infinite; }
.spark { position: absolute; left: 50%; top: 50%; width: 8px; height: 8px; margin: -4px; background: var(--accent); border-radius: var(--radius-full); animation: ember-orbit 9s linear infinite; }
.spark.small { width: 5px; height: 5px; margin: -2.5px; opacity: 0.45; animation: ember-orbit 14s linear infinite reverse; animation-delay: -5s; }
@keyframes ember-orbit { from { transform: rotate(0) translateX(84px) rotate(0); } to { transform: rotate(360deg) translateX(84px) rotate(-360deg); } }
@keyframes ember-flicker {
  0%, 100% { transform: scale(1) skewX(0); filter: drop-shadow(0 0 3px color-mix(in srgb, var(--accent) 30%, transparent)); }
  30% { transform: scale(1.04, 1.07) skewX(-2deg); filter: drop-shadow(0 0 7px color-mix(in srgb, var(--accent) 55%, transparent)); }
  60% { transform: scale(0.98, 1.02) skewX(1.5deg); filter: drop-shadow(0 0 4px color-mix(in srgb, var(--accent) 35%, transparent)); }
}
@keyframes ember-breathe { 0%, 100% { opacity: 0.6; transform: scale(1); } 50% { opacity: 1; transform: scale(1.04); } }
@media (prefers-reduced-motion: reduce) {
  .orbit.inner, .flame, .spark { animation: none; }
  .spark { transform: rotate(-40deg) translateX(84px); }
  .spark.small { transform: rotate(140deg) translateX(84px); }
}
.section-head { display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 10px; margin-bottom: 11px; }
h3 { font-size: 1em; font-weight: 600; margin: 0; }
.section-head span { color: var(--muted); font-size: 0.8em; }
.grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 23px; }
.grid.work { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.card { display: flex; gap: 12px; padding: 18px 16px; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface); transition: border-color 0.15s ease, transform 0.15s ease; }
.card:hover { border-color: var(--accent); transform: translateY(-2px); }
.icon { display: grid; place-items: center; width: 36px; height: 36px; border-radius: var(--radius-md); background: color-mix(in srgb, var(--accent) 8%, var(--bg)); color: var(--accent); flex-shrink: 0; }
.icon svg { width: 20px; height: 20px; }
.card h4 { font-size: 0.95em; font-weight: 600; margin: 0 0 5px; }
.card p { font-size: 0.85em; color: var(--muted); margin: 0; line-height: 1.55; }
.arrow { width: 15px; height: 15px; color: var(--muted); margin-left: auto; margin-top: 8px; }
.copy { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.empty { color: var(--muted); margin: 0 0 24px; }
.footer { border-top: 1px solid var(--border); padding-top: 15px; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px 16px; color: var(--muted); font-size: 0.75em; }
.footer span:first-child { display: flex; align-items: center; gap: 6px; }
.footer svg { width: 13px; height: 13px; }
@media (max-width: 767px) {
  .column { padding: 24px 16px; }
  .identity, .hero-art { display: none; }
  .hero { padding: 22px; }
  .hero h3 { font-size: 1.4em; }
  .hero p { font-size: 0.85em; }
  .grid, .grid.work { grid-template-columns: 1fr; gap: 8px; }
  .card { padding: 15px; }
}
@media (prefers-reduced-motion: reduce) { .card { transition: none; } }
</style>
