import { afterEach, describe, expect, it, vi } from "vitest";
import { copyText } from "./clipboard";

function setClipboard(value: unknown): void {
  Object.defineProperty(navigator, "clipboard", { value, configurable: true });
}

// jsdom has no execCommand of its own.
function setExecCommand(fn: (command: string) => boolean): void {
  Object.defineProperty(document, "execCommand", { value: fn, configurable: true, writable: true });
}

afterEach(() => {
  setClipboard(undefined);
});

describe("copyText", () => {
  it("uses the async clipboard API when it is there", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard({ writeText });

    await expect(copyText("hello")).resolves.toBe(true);

    expect(writeText).toHaveBeenCalledWith("hello");
  });

  it("falls back to execCommand when the API is missing", async () => {
    setClipboard(undefined);
    let copied = "";
    setExecCommand((command) => {
      copied = (document.activeElement as HTMLTextAreaElement).value;
      return command === "copy";
    });

    await expect(copyText("legacy")).resolves.toBe(true);

    expect(copied).toBe("legacy");
    expect(document.querySelector("textarea")).toBeNull(); // the helper element is removed
  });

  it("gives focus back to what had it after the legacy copy", async () => {
    setClipboard(undefined);
    setExecCommand(() => true);
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();

    await copyText("x");

    expect(document.activeElement).toBe(input);
    input.remove();
  });

  it("falls back when the API refuses (blocked permission)", async () => {
    setClipboard({ writeText: vi.fn().mockRejectedValue(new Error("denied")) });
    setExecCommand(() => true);

    await expect(copyText("x")).resolves.toBe(true);
  });

  it("resolves false when both paths fail", async () => {
    setClipboard({ writeText: vi.fn().mockRejectedValue(new Error("denied")) });
    setExecCommand(() => {
      throw new Error("not allowed");
    });

    await expect(copyText("x")).resolves.toBe(false);
    expect(document.querySelector("textarea")).toBeNull();
  });
});
