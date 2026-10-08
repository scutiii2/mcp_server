import { useAuthStore } from "../stores/auth";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it } from "vitest";
import DownloadCards from "./DownloadCards.vue";

const card = (extra = {}) => ({ filename: "report.csv", bytes: 2048, href: "/api/server/download?path=x", label: "EXPORT", ...extra });

describe("DownloadCards", () => {
  it("shows nothing without downloads", () => {
    expect(mount(DownloadCards, { props: { downloads: [] } }).find(".downloads").exists()).toBe(false);
  });

  it("shows a link with the file name and size", () => {
    const wrapper = mount(DownloadCards, { props: { downloads: [card()] } });

    const link = wrapper.find("a.file");
    expect(link.text()).toBe("⬇ Download report.csv (2 KB)");
    expect(link.attributes("href")).toBe("/api/server/download?path=x");
    expect(link.attributes("download")).toBeDefined();
    expect(wrapper.find(".tag").text()).toBe("EXPORT");
  });

  it("leaves the size out when it is not known", () => {
    const wrapper = mount(DownloadCards, { props: { downloads: [card({ bytes: 0 })] } });

    expect(wrapper.find("a.file").text()).toBe("⬇ Download report.csv");
  });

  it("shows a file without a usable link as unavailable, not as a link", () => {
    const wrapper = mount(DownloadCards, { props: { downloads: [card({ href: null })] } });

    expect(wrapper.find("a").exists()).toBe(false);
    expect(wrapper.find(".file.unavailable").text()).toBe("report.csv (2 KB) (unavailable)");
  });

  it("shows one card for each download", () => {
    const wrapper = mount(DownloadCards, { props: { downloads: [card(), card({ filename: "b.txt", label: "DOWNLOAD" })] } });

    expect(wrapper.findAll(".card")).toHaveLength(2);
    expect(wrapper.findAll(".tag").map((t) => t.text())).toEqual(["EXPORT", "DOWNLOAD"]);
  });

  it("shows a file name as text, never as markup", () => {
    const wrapper = mount(DownloadCards, { props: { downloads: [card({ filename: "<img src=x onerror=alert(1)>" })] } });

    expect(wrapper.find("img").exists()).toBe(false);
    expect(wrapper.find("a.file").text()).toContain("<img src=x onerror=alert(1)>");
  });
});


beforeEach(() => {
  setActivePinia(createPinia());
  useAuthStore().account = { id: 1, username: "admin", email: "a@example.com", email_verified: true, roles: [], permissions: ["files.download"] };
});

it("does not offer server downloads without files.download", () => {
  useAuthStore().account!.permissions = [];
  const wrapper = mount(DownloadCards, { props: { downloads: [card()] } });
  expect(wrapper.find("a.file").exists()).toBe(false);
});
