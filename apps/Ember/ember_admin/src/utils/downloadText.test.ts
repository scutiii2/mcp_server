import { afterEach, expect, it, vi } from "vitest";
import { downloadText, exportFileName } from "./downloadText";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });
it("uses Windows-safe nonempty export filenames", () => {
  expect(exportFileName('usage-alice/bob:*', 'md')).toBe('usage-alice_bob_.md');
  expect(exportFileName(' . ', 'md')).toBe('chat.md');
});
it("downloads locally and releases the blob after the click", () => {
  vi.useFakeTimers();
  const create = vi.fn(() => "blob:usage");
  const revoke = vi.fn();
  vi.stubGlobal("URL", { createObjectURL: create, revokeObjectURL: revoke });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  downloadText("usage.md", "# Usage", "text/markdown");
  expect(create).toHaveBeenCalledOnce(); expect(click).toHaveBeenCalledOnce();
  expect(revoke).not.toHaveBeenCalled(); vi.runAllTimers();
  expect(revoke).toHaveBeenCalledWith("blob:usage");
});
