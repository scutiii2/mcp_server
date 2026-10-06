import { describe, expect, it } from "vitest";
import { safeWebUrl } from "./webUrl";

describe("safeWebUrl", () => {
  it("accepts http and https addresses", () => {
    expect(safeWebUrl("http://127.0.0.1:5174")).toBe("http://127.0.0.1:5174/");
    expect(safeWebUrl(" https://tools.example/app?x=1 ")).toBe("https://tools.example/app?x=1");
  });

  it.each(["javascript:alert(1)", "data:text/html,<b>x</b>", "ftp://host/app", "//host/app", "/relative", "not a url", "", "   "])(
    "rejects %s",
    (value) => {
      expect(safeWebUrl(value)).toBeNull();
    },
  );

  it("treats a missing value as no link", () => {
    expect(safeWebUrl(null)).toBeNull();
    expect(safeWebUrl(undefined)).toBeNull();
  });
});
