<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { MenuItem } from "../utils/chatMenu";

// A small popup menu at a point of the page, with an optional flyout for items
// that have `children`. It is teleported to <body>, so no scrolling or clipping
// parent (the sidebar) can cut it off. It reports what was chosen (`select`) or
// that it should go away (`close`: Esc, a press outside, Tab, a resize); the
// owner removes it, and puts focus back where it came from after a `close`.
const MENU_WIDTH = 210;
const FLYOUT_WIDTH = 220;
const MARGIN = 8;

const props = defineProps<{ items: MenuItem[]; x: number; y: number; label: string }>();
const emit = defineEmits<{ select: [id: string]; close: [] }>();

const root = ref<HTMLElement | null>(null);
const left = ref(props.x);
const top = ref(props.y);
// The item whose flyout is open.
const openId = ref<string | null>(null);
// A flyout needs room to the right; without it (or on touch screens, which have
// no hover) it opens over the main menu instead.
const overlay = ref(false);

// Inline placement of the open flyout, set once it is on the page and measured:
// it hangs from its entry's top, which for a row near the bottom of the window
// would put the folders below the edge. `top` moves it up (negative, from its
// entry), `maxHeight` pins the measured height so a long list scrolls inside the flyout.
const flyoutStyle = ref<Record<string, string>>({});

function placeFlyout(): void {
  const box = root.value?.querySelector<HTMLElement>(".flyout")?.getBoundingClientRect();
  if (!box) return;
  const room = window.innerHeight - 2 * MARGIN;
  const height = Math.min(box.height, room);
  // Bottom edge inside the window, but the top never above the top margin.
  const wanted = Math.max(MARGIN, Math.min(box.top, window.innerHeight - MARGIN - height));
  const shift = Math.round(wanted - box.top);
  // The cap is the height just measured (already limited by the stylesheet's 60vh and by the
  // window), not the window: a looser cap would let the list grow after the shift was worked out.
  flyoutStyle.value = { maxHeight: `${height}px`, ...(shift !== 0 ? { top: `${shift}px` } : {}) };
}

// Post flush: the flyout is in the DOM by then, however it was opened (hover,
// click, key).
watch(
  openId,
  async (id) => {
    flyoutStyle.value = {};
    if (id === null) return;
    await nextTick();
    placeFlyout();
  },
  { flush: "post" },
);

function touchOnly(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(hover: none)").matches;
}

function place(): void {
  const box = root.value?.getBoundingClientRect();
  const width = box?.width || MENU_WIDTH;
  const height = box?.height || 0;
  left.value = Math.max(MARGIN, Math.min(props.x, window.innerWidth - width - MARGIN));
  top.value = Math.max(MARGIN, Math.min(props.y, window.innerHeight - height - MARGIN));
  overlay.value = touchOnly() || left.value + width + FLYOUT_WIDTH > window.innerWidth;
}

/** The enabled buttons of the level (main menu or flyout) that holds `from`. */
function levelButtons(from: Element | null): HTMLButtonElement[] {
  const flyout = from?.closest(".flyout");
  const scope = flyout ?? root.value;
  if (!scope) return [];
  const all = [...scope.querySelectorAll<HTMLButtonElement>("button[role^='menuitem']:not([aria-disabled='true'])")];
  return flyout ? all : all.filter((b) => !b.closest(".flyout"));
}

function focusFirst(): void {
  levelButtons(root.value?.querySelector("button") ?? null)[0]?.focus();
}

function move(step: 1 | -1 | "first" | "last"): void {
  const buttons = levelButtons(document.activeElement);
  if (buttons.length === 0) return;
  const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
  let next: number;
  if (step === "first") next = 0;
  else if (step === "last") next = buttons.length - 1;
  // Focus not on an item yet (on the menu box): Down starts at the top, Up at
  // the bottom, instead of stepping from index -1.
  else if (at < 0) next = step === 1 ? 0 : buttons.length - 1;
  else next = (at + step + buttons.length) % buttons.length;
  buttons[next]!.focus();
  // Moving within the main menu leaves the item whose flyout was open (opened
  // by hover), so that flyout closes and its aria-expanded goes back to false.
  if (!buttons[next]!.closest(".flyout")) openId.value = null;
}

async function openFlyout(item: MenuItem, focusChild: boolean): Promise<void> {
  if (item.disabled || !item.children) return;
  openId.value = item.id;
  if (!focusChild) return;
  await nextTick();
  root.value?.querySelector<HTMLButtonElement>(".flyout button:not([aria-disabled='true'])")?.focus();
}

async function closeFlyout(): Promise<void> {
  const id = openId.value;
  if (id === null) return;
  openId.value = null;
  await nextTick();
  focusMainItem(id);
}

/** Focus the main-menu button of item `id`, or the menu box if it has none.
 * Ids are compared directly: an id is free text and could break a selector. */
function focusMainItem(id: string): void {
  const button = levelButtons(root.value?.querySelector("button") ?? null).find((b) => b.dataset.id === id);
  (button ?? root.value)?.focus();
}

function activate(item: MenuItem): void {
  if (item.disabled) return;
  if (item.children) void openFlyout(item, true);
  else emit("select", item.id);
}

function hover(item: MenuItem, event: MouseEvent): void {
  // An overlay flyout would cover the menu the pointer is on, so it opens by
  // click or keyboard only.
  if (touchOnly() || overlay.value) return;
  // Focus follows the pointer, so focus is never left on a flyout item that
  // this hover removes (keys would then go to <body>, not the menu).
  if (!item.disabled) (event.currentTarget as HTMLButtonElement).focus();
  // A disabled item is skipped by the arrow keys and not focused by hover; if focus is in the flyout this hover
  // closes, put it on that flyout's parent before the flyout goes.
  else if (openId.value !== null && document.activeElement?.closest(".flyout")) focusMainItem(openId.value);
  // One `openId`: a hover replaces the open flyout, never adds a second one.
  openId.value = item.children && !item.disabled ? item.id : null;
}

function focusedItem(): MenuItem | undefined {
  const id = (document.activeElement as HTMLElement | null)?.dataset.id;
  return props.items.find((i) => i.id === id);
}

function onKey(event: KeyboardEvent): void {
  switch (event.key) {
    case "Escape":
      event.preventDefault();
      event.stopPropagation();
      if (openId.value !== null) void closeFlyout();
      else emit("close");
      break;
    case "ArrowDown":
      event.preventDefault();
      move(1);
      break;
    case "ArrowUp":
      event.preventDefault();
      move(-1);
      break;
    case "Home":
      event.preventDefault();
      move("first");
      break;
    case "End":
      event.preventDefault();
      move("last");
      break;
    case "ArrowRight": {
      const item = focusedItem();
      if (item?.children) {
        event.preventDefault();
        void openFlyout(item, true);
      }
      break;
    }
    case "ArrowLeft":
      if (openId.value !== null) {
        event.preventDefault();
        void closeFlyout();
      }
      break;
    case "Tab":
      emit("close");
      break;
  }
}

function onPointerDown(event: Event): void {
  if (root.value && !root.value.contains(event.target as Node)) emit("close");
}

const onResize = () => emit("close");

onMounted(async () => {
  document.addEventListener("pointerdown", onPointerDown);
  window.addEventListener("resize", onResize);
  await nextTick();
  place();
  focusFirst();
});
onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", onPointerDown);
  window.removeEventListener("resize", onResize);
});
</script>

<template>
  <Teleport to="body">
    <div
      ref="root"
      class="popup"
      role="menu"
      tabindex="-1"
      :aria-label="label"
      :style="{ left: `${left}px`, top: `${top}px` }"
      @keydown="onKey"
    >
      <template v-for="item in items" :key="item.id">
        <hr v-if="item.separator" role="separator" />
        <div v-else class="entry">
          <button
            type="button"
            role="menuitem"
            :data-id="item.id"
            :class="['item', { danger: item.danger }]"
            :aria-disabled="item.disabled ? 'true' : undefined"
            :aria-haspopup="item.children ? 'menu' : undefined"
            :aria-expanded="item.children ? openId === item.id : undefined"
            @click="activate(item)"
            @mouseenter="hover(item, $event)"
          >
            <span>{{ item.label }}</span>
            <span v-if="item.children" class="chevron" aria-hidden="true">›</span>
          </button>
          <div
            v-if="item.children && openId === item.id"
            :class="['flyout', { overlay }]"
            :style="flyoutStyle"
            role="menu"
            :aria-label="item.label"
          >
            <template v-for="child in item.children" :key="child.id">
              <hr v-if="child.separator" role="separator" />
              <button
                v-else
                type="button"
                role="menuitemradio"
                :aria-checked="child.checked ?? false"
                :data-id="child.id"
                :class="['item', { danger: child.danger }]"
                :aria-disabled="child.disabled ? 'true' : undefined"
                @click="activate(child)"
              >
                <span class="check" aria-hidden="true">{{ child.checked ? "✓" : "" }}</span>
                <span>{{ child.label }}</span>
              </button>
            </template>
          </div>
        </div>
      </template>
    </div>
  </Teleport>
</template>

<style scoped>
.popup:focus {
  outline: none;
}
.popup {
  position: fixed;
  z-index: 50;
  min-width: 170px;
  max-width: 260px;
  padding: 4px;
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--text);
  background: var(--surface);
  box-shadow: 0 6px 24px rgb(0 0 0 / 22%);
}
.entry {
  position: relative;
}
.item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 7px 10px;
  border: none;
  border-radius: 7px;
  cursor: pointer;
  text-align: left;
  font: inherit;
  font-size: 0.9em;
  color: var(--text);
  background: transparent;
}
.item:hover:not([aria-disabled='true']),
.item:focus-visible {
  outline: none;
  background: var(--bg);
}
.item[aria-disabled='true'] {
  cursor: default;
  opacity: 0.45;
}
.danger {
  color: var(--danger);
}
.chevron {
  color: var(--muted);
}
.check {
  width: 1em;
  flex-shrink: 0;
  color: var(--accent);
}
hr {
  margin: 4px 6px;
  border: none;
  border-top: 1px solid var(--border);
}
.flyout {
  position: absolute;
  z-index: 1;
  top: 0;
  left: 100%;
  min-width: 170px;
  max-width: 260px;
  max-height: 60vh;
  padding: 4px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
  box-shadow: 0 6px 24px rgb(0 0 0 / 22%);
}
/* No room to the right (or no hover): cover the main menu instead. */
.flyout.overlay {
  top: 0;
  left: 0;
  right: 0;
  min-width: 100%;
  max-width: none;
}
.flyout .item {
  justify-content: flex-start;
}
</style>
