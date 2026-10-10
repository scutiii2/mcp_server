import { onBeforeUnmount, onMounted, ref, type Ref } from "vue";

/** Wall-clock epoch seconds (the unit of mini_games' timestamps), updated
 * every second while the component is mounted. */
export function useNowSeconds(): Ref<number> {
  const now = ref(Date.now() / 1000);
  let timer: ReturnType<typeof setInterval> | null = null;
  onMounted(() => {
    timer = setInterval(() => {
      now.value = Date.now() / 1000;
    }, 1000);
  });
  onBeforeUnmount(() => {
    if (timer !== null) clearInterval(timer);
  });
  return now;
}
