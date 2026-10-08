import { onActivated, onDeactivated, onScopeDispose, ref, watch, type Ref } from "vue";

const TICK_MS = 200;

/**
 * Milliseconds since `since` (a `Date.now()` value), kept up to date while
 * `since` is set; 0 while it is null. Ticks about five times a second, and
 * not at all while the page holding it is cached behind another one.
 */
export function useElapsed(since: Ref<number | null>, tickMs: number = TICK_MS): Ref<number> {
  const elapsed = ref(0);
  let timer: ReturnType<typeof setInterval> | null = null;

  function update(): void {
    elapsed.value = since.value === null ? 0 : Math.max(0, Date.now() - since.value);
  }

  function stop(): void {
    if (timer !== null) clearInterval(timer);
    timer = null;
  }

  function start(): void {
    stop();
    update();
    if (since.value !== null) timer = setInterval(update, tickMs);
  }

  watch(since, start, { immediate: true });
  onActivated(start);
  onDeactivated(stop);
  onScopeDispose(stop);
  return elapsed;
}
