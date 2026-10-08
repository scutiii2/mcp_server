import { onScopeDispose, ref } from "vue";

/** A whole-second countdown that calls `onZero` once at zero. It does not tick
 * while the tab is hidden (nobody sees it) and carries on when the tab returns;
 * it stops when its owner is disposed. */
export function useCountdown(onZero: () => void) {
  const remaining = ref(0);
  const running = ref(false);
  let timer: ReturnType<typeof setInterval> | null = null;

  function clear(): void {
    if (timer !== null) clearInterval(timer);
    timer = null;
    running.value = false;
  }

  function tick(): void {
    if (document.hidden) return;
    remaining.value -= 1;
    if (remaining.value <= 0) {
      remaining.value = 0;
      clear();
      onZero();
    }
  }

  function start(seconds: number): void {
    clear();
    remaining.value = Math.max(1, Math.ceil(seconds));
    running.value = true;
    timer = setInterval(tick, 1000);
  }

  onScopeDispose(clear);
  return { remaining, running, start, stop: clear };
}
