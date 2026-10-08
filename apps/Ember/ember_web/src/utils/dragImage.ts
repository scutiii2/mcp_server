/** Padding around the lifted clone, so its tilt and shadow are not clipped by the snapshot. */
const PAD = 14;

/**
 * Gives a drag the "lifted" look: the browser snapshots a styled clone of the
 * row (a touch bigger, shadowed, tilted 3° and outlined in the accent) in place
 * of its own flat ghost. The clone is only ever read by the browser, so it is
 * removed again right after `dragstart` returns. The tilt is skipped for people
 * who prefer reduced motion. Does nothing where `setDragImage` is missing.
 */
export function liftDragImage(event: DragEvent, row: HTMLElement): void {
  const transfer = event.dataTransfer;
  if (!transfer || typeof transfer.setDragImage !== "function") return;

  const rect = row.getBoundingClientRect();
  const tilt = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? 0 : 3;

  const ghost = row.cloneNode(true) as HTMLElement;
  ghost.removeAttribute("draggable");
  ghost.removeAttribute("id");
  Object.assign(ghost.style, {
    boxSizing: "border-box",
    width: `${rect.width}px`,
    height: `${rect.height}px`,
    opacity: "1",
    background: "var(--surface)",
    border: "1px solid var(--accent)",
    borderRadius: "var(--radius-md)",
    boxShadow: "0 8px 20px rgba(0, 0, 0, 0.28)",
    transform: `scale(1.03) rotate(${tilt}deg)`,
  } satisfies Partial<CSSStyleDeclaration>);

  const frame = document.createElement("div");
  Object.assign(frame.style, {
    position: "fixed",
    top: "-10000px",
    left: "0",
    padding: `${PAD}px`,
    pointerEvents: "none",
  } satisfies Partial<CSSStyleDeclaration>);
  frame.append(ghost);
  document.body.append(frame);

  transfer.setDragImage(frame, event.clientX - rect.left + PAD, event.clientY - rect.top + PAD);
  setTimeout(() => frame.remove(), 0);
}
