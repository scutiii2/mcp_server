import { mount } from "@vue/test-utils";
import { expect, it } from "vitest";
import PlanPanel from "./PlanPanel.vue";

it("shows checklist text safely with a label for every state", () => {
  const panel = mount(PlanPanel, { props: { plans: [{ agent_id: "main", agent_label: "Ember", items: [
    { text: "<img src=x onerror=alert(1)>", status: "pending" },
    { text: "Inspect", status: "in_progress" },
    { text: "Finish", status: "done" },
  ] }] } });
  expect(panel.text()).toContain("Ember");
  expect(panel.text()).toContain("Pending");
  expect(panel.text()).toContain("In progress");
  expect(panel.text()).toContain("Done");
  expect(panel.find("img").exists()).toBe(false);
});
