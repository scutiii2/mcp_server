import { afterEach, describe, expect, it, vi } from "vitest";
import { liftDragImage } from "./dragImage";

function setup(reducedMotion = false) {
  window.matchMedia = vi.fn().mockReturnValue({ matches: reducedMotion }) as unknown as typeof window.matchMedia;
  const row = document.createElement("li");
  row.setAttribute("draggable", "true");
  row.getBoundingClientRect = () => ({ left: 10, top: 20, width: 200, height: 40 }) as DOMRect;
  document.body.append(row);
  const setDragImage = vi.fn();
  const event = { clientX: 30, clientY: 35, dataTransfer: { setDragImage } } as unknown as DragEvent;
  return { row, event, setDragImage };
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.useRealTimers();
});

describe("liftDragImage", () => {
  it("hands the browser a lifted clone, grabbed at the same spot as the row", () => {
    const { row, event, setDragImage } = setup();

    liftDragImage(event, row);

    const [frame, x, y] = setDragImage.mock.calls[0]!;
    const ghost = (frame as HTMLElement).firstElementChild as HTMLElement;
    expect(ghost.style.transform).toBe("scale(1.03) rotate(3deg)");
    expect(ghost.style.width).toBe("200px");
    expect(ghost.hasAttribute("draggable")).toBe(false);
    expect([x, y]).toEqual([20 + 14, 15 + 14]);
  });

  it("does not tilt for people who prefer reduced motion", () => {
    const { row, event, setDragImage } = setup(true);

    liftDragImage(event, row);

    const ghost = (setDragImage.mock.calls[0]![0] as HTMLElement).firstElementChild as HTMLElement;
    expect(ghost.style.transform).toBe("scale(1.03) rotate(0deg)");
  });

  it("removes the clone once the browser has taken its snapshot", () => {
    vi.useFakeTimers();
    const { row, event, setDragImage } = setup();

    liftDragImage(event, row);
    const frame = setDragImage.mock.calls[0]![0] as HTMLElement;
    expect(document.body.contains(frame)).toBe(true);

    vi.runAllTimers();
    expect(document.body.contains(frame)).toBe(false);
  });

  it("does nothing where the browser has no setDragImage", () => {
    const { row } = setup();

    expect(() => liftDragImage({ dataTransfer: {} } as unknown as DragEvent, row)).not.toThrow();
    expect(() => liftDragImage({ dataTransfer: null } as unknown as DragEvent, row)).not.toThrow();
    expect(document.body.children).toHaveLength(1);
  });
});
