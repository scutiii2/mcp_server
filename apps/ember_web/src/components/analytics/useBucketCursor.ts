import { computed, ref, toValue, type MaybeRefOrGetter, type Ref } from "vue";

/** One thing a chart draws: a stacked segment or a line. */
export interface ChartPart {
  id: string;
  label: string;
  /** A CSS colour, normally a theme token such as `var(--kind-action)`. */
  color: string;
}

const MAX_TICKS = 6;

/** The "which bucket am I reading" state the time charts share: the bucket under
 * the pointer (or reached with the arrow keys), where its tooltip sits, and how
 * sparse the time axis labels are. `plot` is the element the pointer is read against
 * (a template ref), `count` the number of buckets. */
export function useBucketCursor(plot: Ref<HTMLElement | null>, count: MaybeRefOrGetter<number>) {
  const active = ref<number | null>(null);

  const labelEvery = computed(() => Math.ceil(toValue(count) / MAX_TICKS));

  const tooltipStyle = computed(() => {
    if (active.value === null) return {};
    const share = (active.value + 0.5) / toValue(count);
    const anchor = share < 0.2 ? "0" : share > 0.8 ? "-100%" : "-50%";
    // The plot is the area minus its side padding (see .area in chart.css).
    return { left: `calc(18px + (100% - 36px) * ${share})`, transform: `translateX(${anchor})` };
  });

  function select(event: PointerEvent): void {
    const box = plot.value?.getBoundingClientRect();
    if (!box || box.width === 0) return;
    const share = (event.clientX - box.left) / box.width;
    active.value = Math.min(toValue(count) - 1, Math.max(0, Math.floor(share * toValue(count))));
  }

  function onKey(event: KeyboardEvent): void {
    const last = toValue(count) - 1;
    const move: Record<string, number | null> = {
      ArrowLeft: Math.max(0, (active.value ?? last + 1) - 1),
      ArrowRight: Math.min(last, (active.value ?? -1) + 1),
      Home: 0,
      End: last,
      Escape: null,
    };
    if (!(event.key in move)) return;
    event.preventDefault();
    active.value = move[event.key] ?? null;
  }

  return { active, labelEvery, tooltipStyle, select, onKey };
}
