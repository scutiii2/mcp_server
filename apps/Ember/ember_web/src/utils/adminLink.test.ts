import { describe, expect, it } from "vitest";
import { emberAdminUrl } from "./adminLink";
describe("emberAdminUrl", () => {
  it("uses the same host and default admin port", () => {
    expect(emberAdminUrl("http://127.0.0.1:5173/chat?q=1#message", "")).toBe("http://127.0.0.1:5176/");
  });
  it("supports a configured deployment URL or proxy path", () => {
    expect(emberAdminUrl("https://ember.example/chat", "https://admin.example/")).toBe("https://admin.example/");
    expect(emberAdminUrl("https://ember.example/chat", "/admin/")).toBe("https://ember.example/admin/");
  });
});

it("falls back safely for invalid or non-HTTP deployment addresses", () => {
  expect(emberAdminUrl("http://localhost:5173/", "http://[")).toBe("http://localhost:5176/");
  expect(emberAdminUrl("http://localhost:5173/", "javascript:alert(1)")).toBe("http://localhost:5176/");
});
