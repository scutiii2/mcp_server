import { flushPromises, mount, type DOMWrapper } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatMessage } from "../api/types";
import { useChatStore } from "../stores/chat";
import { useEntryAgentStore } from "../stores/entryAgent";
import { withAttachments } from "../utils/attachments";
import ConfirmModal from "./admin/ConfirmModal.vue";
import MessageList from "./MessageList.vue";

// <AgentActivity> reads the chat store, which loads chats when it starts.
vi.mock("../api/ChatsClient", () => ({ chatsClient: { list: vi.fn().mockResolvedValue([]) } }));
vi.mock("../services/turnStream", () => ({ watchTurn: vi.fn(() => Promise.resolve("aborted")) }));

const user = (content: string): ChatMessage => ({ role: "user", content });
const assistant = (content: string, extra: Partial<ChatMessage> = {}): ChatMessage => ({
  role: "assistant",
  content,
  ...extra,
});

const FOUR = [user("q1"), assistant("a1"), user("q2"), assistant("a2")];
const FILE = { filename: "f.txt", chars: 3, truncated: false, text: "abc" };

type Props = InstanceType<typeof MessageList>["$props"];

function mountList(props: Partial<Props> = {}) {
  return mount(MessageList, {
    props: { messages: FOUR, streaming: "", activity: "", steps: [], busy: false, canChange: true, regenerateIndex: 2, ...props },
    global: { plugins: [createPinia()] },
    attachTo: document.body,
  });
}

// jsdom doesn't lay anything out and has no scrollIntoView or <dialog> methods.
let scrollIntoView: ReturnType<typeof vi.fn>;
beforeEach(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
  scrollIntoView = vi.fn();
  Element.prototype.scrollIntoView = scrollIntoView as unknown as Element["scrollIntoView"];
});

afterEach(() => {
  document.body.innerHTML = "";
  vi.useRealTimers();
});

describe("jumping to a message (a search result)", () => {
  it("scrolls the message to the centre, flashes it, then says it is done", async () => {
    vi.useFakeTimers();
    const wrapper = mountList({ jumpIndex: 2 });
    await vi.advanceTimersByTimeAsync(0);

    expect(scrollIntoView).toHaveBeenCalledExactlyOnceWith({ block: "center" });
    const target = scrollIntoView.mock.contexts[0] as HTMLElement;
    expect(target.dataset.index).toBe("2");
    expect(wrapper.findAll(".msg")[2]!.classes()).toContain("flash");
    expect(wrapper.emitted("jumped")).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(1600);
    expect(wrapper.find(".flash").exists()).toBe(false);
  });

  it("follows a target set after the list is already showing", async () => {
    const wrapper = mountList();
    await flushPromises();
    expect(scrollIntoView).not.toHaveBeenCalled();

    await wrapper.setProps({ jumpIndex: 0 });
    await flushPromises();

    expect((scrollIntoView.mock.contexts[0] as HTMLElement).dataset.index).toBe("0");
  });

  it("drops a target past the end of the chat without scrolling", async () => {
    const wrapper = mountList({ jumpIndex: 9 });
    await flushPromises();

    expect(scrollIntoView).not.toHaveBeenCalled();
    expect(wrapper.emitted("jumped")).toHaveLength(1);
  });

  it("treats the first index past the end as out of range, and the last message as in range", async () => {
    const past = mountList({ jumpIndex: FOUR.length });
    await flushPromises();
    expect(scrollIntoView).not.toHaveBeenCalled();
    expect(past.emitted("jumped")).toHaveLength(1);

    const last = mountList({ jumpIndex: FOUR.length - 1 });
    await flushPromises();
    expect((scrollIntoView.mock.contexts[0] as HTMLElement).dataset.index).toBe("3");
    expect(last.emitted("jumped")).toHaveLength(1);
  });

  it("does nothing without a target", async () => {
    const wrapper = mountList({ jumpIndex: null });
    await flushPromises();

    expect(scrollIntoView).not.toHaveBeenCalled();
    expect(wrapper.emitted("jumped")).toBeUndefined();
  });

  it("wraps every message once, in order, with its index", () => {
    const wrapper = mountList();

    expect(wrapper.findAll(".msg").map((m) => m.attributes("data-index"))).toEqual(["0", "1", "2", "3"]);
  });
});

describe("regenerate button", () => {
  it("appears on the last answer only, and emits regenerate", async () => {
    const wrapper = mountList();
    const buttons = wrapper.findAll('button[aria-label="Regenerate answer"]');

    expect(buttons).toHaveLength(1);
    expect(wrapper.findAll(".msg")[3]!.find('button[aria-label="Regenerate answer"]').exists()).toBe(true);

    await buttons[0]!.trigger("click");
    expect(wrapper.emitted("regenerate")).toHaveLength(1);
  });

  it.each([
    ["nothing to redo", { regenerateIndex: -1 }],
    ["an answer is running", { canChange: false }],
    ["the parent gave no index", { regenerateIndex: undefined }],
  ])("is hidden when %s", (_name, props) => {
    const wrapper = mountList(props);

    expect(wrapper.find('button[aria-label="Regenerate answer"]').exists()).toBe(false);
  });
});

describe("editing a question", () => {
  const editButtons = (wrapper: ReturnType<typeof mountList>) => wrapper.findAll('button[aria-label="Edit and resend"]');

  it("offers an edit on every typed question, not on answers", () => {
    expect(editButtons(mountList())).toHaveLength(2);
  });

  it("is not offered while an answer is running", () => {
    expect(editButtons(mountList({ canChange: false }))).toHaveLength(0);
  });

  it("opens with the typed text, and Save & resend emits the new text", async () => {
    const wrapper = mountList();
    await editButtons(wrapper)[0]!.trigger("click");
    const area = wrapper.find("textarea");

    expect((area.element as HTMLTextAreaElement).value).toBe("q1");
    await area.setValue("q1 edited");
    await wrapper.find("button.primary").trigger("click");
    await wrapper.getComponent(ConfirmModal).get(".confirm").trigger("click");

    expect(wrapper.emitted("edit")).toEqual([[0, "q1 edited"]]);
    expect(wrapper.find("textarea").exists()).toBe(false);
  });

  it("asks before discarding later exchanges, and stays open on 'no'", async () => {
    const wrapper = mountList();
    await editButtons(wrapper)[0]!.trigger("click"); // q1 has q2 after it
    await wrapper.find("textarea").setValue("changed");

    await wrapper.find("button.primary").trigger("click");
    expect(wrapper.getComponent(ConfirmModal).props("message")).toContain("discards the messages after it");
    await wrapper.getComponent(ConfirmModal).get(".cancel").trigger("click");

    expect(wrapper.findComponent(ConfirmModal).exists()).toBe(false);
    expect(wrapper.emitted("edit")).toBeUndefined();
    expect(wrapper.find("textarea").exists()).toBe(true);
  });

  it("does not ask when editing the last question", async () => {
    const wrapper = mountList();
    await editButtons(wrapper)[1]!.trigger("click"); // q2 is the last
    await wrapper.find("textarea").setValue("q2 edited");

    await wrapper.find("button.primary").trigger("click");

    expect(wrapper.findComponent(ConfirmModal).exists()).toBe(false);
    expect(wrapper.emitted("edit")).toEqual([[2, "q2 edited"]]);
  });

  it("Enter saves, Shift+Enter does not, Esc cancels", async () => {
    const wrapper = mountList();
    await editButtons(wrapper)[1]!.trigger("click");
    const area = wrapper.find("textarea");
    await area.setValue("again");

    await area.trigger("keydown", { key: "Enter", shiftKey: true });
    expect(wrapper.emitted("edit")).toBeUndefined();

    await area.trigger("keydown", { key: "Escape" });
    expect(wrapper.find("textarea").exists()).toBe(false);
    expect(wrapper.emitted("edit")).toBeUndefined();

    await editButtons(wrapper)[1]!.trigger("click");
    await wrapper.find("textarea").setValue("again");
    await wrapper.find("textarea").trigger("keydown", { key: "Enter" });
    expect(wrapper.emitted("edit")).toEqual([[2, "again"]]);
  });

  it("will not save a blank question, but will for one that has a file", async () => {
    const wrapper = mountList({
      messages: [user("plain"), assistant("a"), user(withAttachments("with file", [FILE])), assistant("b")],
    });

    await editButtons(wrapper)[0]!.trigger("click");
    await wrapper.find("textarea").setValue("   ");
    await wrapper.find("button.primary").trigger("click");
    expect(wrapper.emitted("edit")).toBeUndefined();
    await wrapper.find("button.ghost").trigger("click");

    await editButtons(wrapper)[1]!.trigger("click");
    expect(wrapper.find(".edit-note").text()).toContain("Attached files stay");
    await wrapper.find("textarea").setValue("");
    await wrapper.find("button.primary").trigger("click");
    expect(wrapper.emitted("edit")).toEqual([[2, ""]]);
  });

  it("closes the editor when an answer starts running", async () => {
    const wrapper = mountList();
    await editButtons(wrapper)[0]!.trigger("click");
    expect(wrapper.find("textarea").exists()).toBe(true);

    await wrapper.setProps({ busy: true, canChange: false });

    expect(wrapper.find("textarea").exists()).toBe(false);
  });
});

describe("copy buttons", () => {
  it("are on questions and answers; a question shows its typed text apart from its file", () => {
    const wrapper = mountList({ messages: [user(withAttachments("look at this", [FILE])), assistant("ok")] });

    const labels = wrapper
      .findAll('button[aria-label="Copy message"], button[aria-label="Copy answer"]')
      .map((b) => b.attributes("aria-label"));

    expect(labels).toEqual(["Copy message", "Copy answer"]);
    expect(wrapper.find(".user-bubble").text()).toContain("look at this");
  });
});

describe("save as a prompt", () => {
  const saveButtons = (wrapper: ReturnType<typeof mountList>) => wrapper.findAll("button.save-button");

  it("is not offered unless the saved prompts are given", () => {
    expect(saveButtons(mountList())).toHaveLength(0);
  });

  it("is on each question: Save, or Saved when a prompt holds the same text", () => {
    const wrapper = mountList({ savedPrompts: ["q2"] });

    const buttons = saveButtons(wrapper);
    expect(buttons.map((b) => b.text())).toEqual(["Save", "Saved"]);
    expect(buttons.map((b) => b.attributes("aria-pressed"))).toEqual(["false", "true"]);
  });

  it("compares the typed text, not the attached file", () => {
    const wrapper = mountList({ messages: [user(withAttachments("look at this", [FILE])), assistant("ok")], savedPrompts: ["look at this"] });

    expect(saveButtons(wrapper).map((b) => b.text())).toEqual(["Saved"]);
  });

  it("is not on a question that is only attached files", () => {
    const wrapper = mountList({ messages: [user(withAttachments("", [FILE])), assistant("ok")], savedPrompts: [] });

    expect(saveButtons(wrapper)).toHaveLength(0);
  });

  it("asks to save the question's text when clicked", async () => {
    const wrapper = mountList({ savedPrompts: [] });

    await saveButtons(wrapper)[1]!.trigger("click");

    expect(wrapper.emitted("save-prompt")).toEqual([["q2"]]);
  });
});

describe("branch button", () => {
  const branchButtons = (wrapper: ReturnType<typeof mountList>) => wrapper.findAll('button[aria-label="Branch from this answer"]');

  it("is on every answer, not on questions, and emits the answer's index", async () => {
    const wrapper = mountList();
    const buttons = branchButtons(wrapper);

    expect(buttons).toHaveLength(2);
    expect(wrapper.findAll(".msg")[0]!.find('button[aria-label="Branch from this answer"]').exists()).toBe(false);

    await buttons[0]!.trigger("click");
    await buttons[1]!.trigger("click");
    expect(wrapper.emitted("branch")).toEqual([[1], [3]]);
  });

  it("is hidden while an answer is running or another change is under way", () => {
    expect(branchButtons(mountList({ canChange: false }))).toHaveLength(0);
  });

  it("is not on summaries, raw logs or command results", () => {
    const wrapper = mountList({
      messages: [
        assistant("S", { kind: "summary" }),
        assistant("raw", { kind: "log_attachment" }),
        { role: "user", content: "/x y", kind: "command" },
        assistant("result", { kind: "command" }),
        user("q"),
        assistant("a"),
      ],
      regenerateIndex: 4,
    });

    expect(branchButtons(wrapper)).toHaveLength(1);
    expect(wrapper.findAll(".msg")[5]!.find('button[aria-label="Branch from this answer"]').exists()).toBe(true);
  });

  it("sits beside the regenerate button on the last answer", () => {
    const wrapper = mountList();

    const labels = wrapper.findAll(".msg")[3]!.findAll(".actions button").map((b) => b.attributes("aria-label"));

    expect(labels).toContain("Regenerate answer");
    expect(labels).toContain("Branch from this answer");
  });
});

describe("tool approval cards", () => {
  const STOP_APP = { id: "step0", tool: "tool_srv_stopApp", label: "", arguments: { app: "web", force: true } };
  const cards = (wrapper: ReturnType<typeof mountList>) => wrapper.findAll(".approval");
  const buttons = (card: DOMWrapper<Element>) => card.findAll(".buttons button");

  it("shows nothing when no tool is waiting", () => {
    expect(cards(mountList({ busy: true, approvals: [] })).length).toBe(0);
    expect(cards(mountList({ busy: true })).length).toBe(0);
  });

  it("shows a card for each waiting tool while the answer is being written", () => {
    const wrapper = mountList({ busy: true, approvals: [STOP_APP, { ...STOP_APP, id: "step1", tool: "tool_srv_startApp" }] });

    expect(cards(wrapper)).toHaveLength(2);
    expect(cards(wrapper)[0]!.find("header strong").text()).toBe("Stop App");
    expect(cards(wrapper)[1]!.find("header strong").text()).toBe("Start App");
    expect(cards(wrapper)[0]!.find("header code").text()).toBe("tool_srv_stopApp");
    expect(cards(wrapper)[0]!.text()).toContain("will not run until you allow it");
    expect(cards(wrapper)[0]!.text()).toContain("counts as Deny");
  });

  it("uses the tool's own display label when it has one", () => {
    const wrapper = mountList({ busy: true, approvals: [{ ...STOP_APP, label: "Stop an application" }] });

    expect(cards(wrapper)[0]!.find("header strong").text()).toBe("Stop an application");
  });

  it("shows the real arguments, as text", () => {
    const wrapper = mountList({
      busy: true,
      approvals: [{ ...STOP_APP, arguments: { app: "<img src=x onerror=alert(1)>", force: true } }],
    });

    const shown = cards(wrapper)[0]!.find("pre");
    expect(shown.text()).toContain('"app": "<img src=x onerror=alert(1)>"');
    expect(shown.text()).toContain('"force": true');
    expect(cards(wrapper)[0]!.find("img").exists()).toBe(false);
  });

  it("opens short arguments, folds long ones, and says when there are none", () => {
    const short = mountList({ busy: true, approvals: [STOP_APP] });
    expect(cards(short)[0]!.find("details").attributes("open")).toBeDefined();

    const long = mountList({ busy: true, approvals: [{ ...STOP_APP, arguments: { text: "x".repeat(600) } }] });
    expect(cards(long)[0]!.find("details").attributes("open")).toBeUndefined();
    expect(cards(long)[0]!.find("pre").text()).toContain("x".repeat(600)); // still all there to read

    const none = mountList({ busy: true, approvals: [{ ...STOP_APP, arguments: {} }] });
    expect(cards(none)[0]!.find("pre").text()).toBe("(no arguments)");
  });

  it("leaves out Allow for this chat while the administrator requires approval", () => {
    const required = mountList({ busy: true, approvalRequired: true, approvals: [STOP_APP] });
    const open = mountList({ busy: true, approvalRequired: false, approvals: [STOP_APP] });

    expect(buttons(cards(required)[0]!).map((b) => b.text())).toEqual(["Allow once", "Deny"]);
    expect(buttons(cards(open)[0]!).map((b) => b.text())).toEqual(["Allow once", "Allow for this chat", "Deny"]);
  });

  it("has three answers, each sent for its own step", async () => {
    const wrapper = mountList({ busy: true, approvals: [STOP_APP, { ...STOP_APP, id: "step1" }] });
    const [first, second] = cards(wrapper);

    expect(buttons(first!).map((b) => b.text())).toEqual(["Allow once", "Allow for this chat", "Deny"]);
    await buttons(first!)[0]!.trigger("click");
    await buttons(first!)[1]!.trigger("click");
    await buttons(second!)[2]!.trigger("click");

    expect(wrapper.emitted("decide")).toEqual([
      ["step0", "allow"],
      ["step0", "always"],
      ["step1", "deny"],
    ]);
  });

  it("turns the buttons off for a step whose answer is on its way", () => {
    const wrapper = mountList({ busy: true, approvals: [STOP_APP, { ...STOP_APP, id: "step1" }], deciding: ["step0"] });

    expect(buttons(cards(wrapper)[0]!).every((b) => b.attributes("disabled") !== undefined)).toBe(true);
    expect(buttons(cards(wrapper)[1]!).every((b) => b.attributes("disabled") === undefined)).toBe(true);
  });

  it("does not answer through a disabled button", async () => {
    const wrapper = mountList({ busy: true, approvals: [STOP_APP], deciding: ["step0"] });

    await buttons(cards(wrapper)[0]!)[0]!.trigger("click");

    expect(wrapper.emitted("decide")).toBeUndefined();
  });

  it("is a labelled group a screen reader can find", () => {
    const wrapper = mountList({ busy: true, approvals: [STOP_APP] });

    expect(cards(wrapper)[0]!.attributes("role")).toBe("group");
    expect(cards(wrapper)[0]!.attributes("aria-label")).toBe("Allow Stop App?");
  });
});

describe("the welcome card", () => {
  const COMMANDS = [{ capability: "files", name: "list", description: "", tool_name: "files_list" }];

  it("is shown in an empty chat, with a tip and what can be done", () => {
    const wrapper = mountList({ messages: [], commands: COMMANDS });

    expect(wrapper.find(".welcome").exists()).toBe(true);
    expect(wrapper.find(".welcome .tip").text()).toContain("Type / to run a command");
    expect(wrapper.find(".welcome .caps").text()).toContain("Files (/files)");
  });

  it("works without any commands", () => {
    const wrapper = mountList({ messages: [] });

    expect(wrapper.find(".welcome").exists()).toBe(true);
    expect(wrapper.find(".welcome .caps").exists()).toBe(false);
  });

  it("is gone once the chat has messages", () => {
    expect(mountList({ commands: COMMANDS }).find(".welcome").exists()).toBe(false);
  });

  it("is not shown while the first answer is being written", () => {
    expect(mountList({ messages: [], busy: true }).find(".welcome").exists()).toBe(false);
  });
});

describe("the running clock", () => {
  const T0 = Date.parse("2026-10-01T10:00:00Z");
  const live = (extra: Partial<Props> = {}) => mountList({ busy: true, ...extra });

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(T0);
  });

  it("shows how long the answer has been running", () => {
    const wrapper = live({ since: T0 - 12_400 });

    expect(wrapper.find(".live .elapsed").text()).toBe("12.4 s");
  });

  it("ticks", async () => {
    const wrapper = live({ since: T0 });

    await vi.advanceTimersByTimeAsync(2000);

    expect(wrapper.find(".live .elapsed").text()).toBe("2.0 s");
  });

  it("shows beside the streamed text too", () => {
    const wrapper = live({ since: T0, streaming: "partial answer" });

    expect(wrapper.find(".live").text()).toContain("partial answer");
    expect(wrapper.find(".live .elapsed").exists()).toBe(true);
  });

  it("is not shown without a start time", () => {
    expect(live({ since: null }).find(".elapsed").exists()).toBe(false);
    expect(live().find(".elapsed").exists()).toBe(false);
  });

  it("is not shown when nothing is running", () => {
    expect(mountList({ since: T0 }).find(".elapsed").exists()).toBe(false);
  });
});

describe("a slash command's reply", () => {
  const command = (extra: Partial<ChatMessage> = {}): ChatMessage[] => [
    { role: "user", kind: "command", content: "/files list" },
    assistant("two files", { kind: "command", ...extra }),
  ];

  it("shows the usage chip with 'Direct tool call' and the time", () => {
    const wrapper = mountList({ messages: command({ duration_s: 0.8 }) });

    expect(wrapper.find(".usage .chip").text()).toBe("No AI used · direct tool call · 0.8 s");
  });

  it("keeps the result in its own box, above the chip", () => {
    const wrapper = mountList({ messages: command({ duration_s: 0.8 }) });

    const reply = wrapper.findAll(".msg")[1]!;
    expect(reply.find(".command-result").text()).toBe("two files");
    expect(reply.find(".actions .chip").exists()).toBe(true);
  });

  it("has no copy, regenerate or branch buttons", () => {
    const wrapper = mountList({ messages: command() });

    expect(wrapper.findAll(".msg")[1]!.findAll("button").map((b) => b.classes())).toEqual([["chip"]]);
  });

  it("shows no chip on the command the user typed", () => {
    const wrapper = mountList({ messages: command() });

    expect(wrapper.findAll(".msg")[0]!.find(".chip").exists()).toBe(false);
  });
});

describe("the agent tag under an answer", () => {
  const tagged = (agent?: string): ChatMessage[] => [user("q"), assistant("a", { agent, model: "m", total_tokens: 10 })];

  it("names the agent by its label", () => {
    const wrapper = mountList({ messages: tagged("claude-agent"), agentLabels: { "claude-agent": "Claude Agent" } });

    expect(wrapper.find(".usage .chip").text()).toBe("Claude Agent · m · 10 tokens");
  });

  it("shows the saved id when the agent is no longer listed", () => {
    const wrapper = mountList({ messages: tagged("gone-agent"), agentLabels: { "claude-agent": "Claude Agent" } });

    expect(wrapper.find(".usage .chip").text()).toBe("gone-agent · m · 10 tokens");
  });

  it("shows the saved id when no labels are given", () => {
    const wrapper = mountList({ messages: tagged("claude-agent") });

    expect(wrapper.find(".usage .chip").text()).toBe("claude-agent · m · 10 tokens");
  });

  it("shows no agent for an answer saved without one", () => {
    const wrapper = mountList({ messages: tagged(), agentLabels: { "claude-agent": "Claude Agent" } });

    expect(wrapper.find(".usage .chip").text()).toBe("m · 10 tokens");
  });

  it("tags each answer with its own agent", () => {
    const messages = [user("q1"), assistant("a1", { agent: "a" }), user("q2"), assistant("a2", { agent: "b" })];
    const wrapper = mountList({ messages, agentLabels: { a: "Alpha", b: "Beta" } });

    expect(wrapper.findAll(".usage .chip").map((c) => c.text())).toEqual(["Alpha", "Beta"]);
  });
});

describe("download cards", () => {
  const MARKER = '[[DOWNLOAD filename="a.csv" bytes="2048" url="/server/download?path=x" label="EXPORT"]]';

  it("turns a marker in an answer into a card and hides the marker text", () => {
    const wrapper = mountList({ messages: [user("q"), assistant(`Here you go.\n\n${MARKER}`)] });

    const link = wrapper.find(".downloads a.file");
    expect(link.attributes("href")).toBe("/api/server/download?path=x");
    expect(link.text()).toBe("⬇ Download a.csv (2 KB)");
    expect(wrapper.find(".assistant").text()).not.toContain("[[DOWNLOAD");
    expect(wrapper.find(".assistant").text()).toContain("Here you go.");
  });

  it("copies the answer without the marker", () => {
    const wrapper = mountList({ messages: [user("q"), assistant(`Here you go.\n\n${MARKER}`)] });

    expect(wrapper.find(".assistant").findComponent({ name: "CopyButton" }).props("text")).toBe("Here you go.");
  });

  it("shows a card in a command's result too", () => {
    const messages = [
      { role: "user", kind: "command", content: "/files export" } as ChatMessage,
      assistant(`${MARKER}\n\nExported.`, { kind: "command" }),
    ];
    const wrapper = mountList({ messages });

    expect(wrapper.find(".command-result").text()).toBe("Exported.");
    expect(wrapper.find(".downloads a.file").exists()).toBe(true);
  });

  it("shows no cards for an answer without a marker", () => {
    const wrapper = mountList();

    expect(wrapper.find(".downloads").exists()).toBe(false);
  });

  it("hides a marker while the answer is still streaming", () => {
    const wrapper = mountList({ messages: [user("q")], busy: true, streaming: 'Almost [[DOWNLOAD filename="a' });

    expect(wrapper.text()).toContain("Almost");
    expect(wrapper.text()).not.toContain("[[DOWNLOAD");
  });

  it("does not make a link out of an address that is not a download route", () => {
    const bad = '[[DOWNLOAD filename="x.exe" bytes="1" url="https://evil.example/x.exe"]]';
    const wrapper = mountList({ messages: [user("q"), assistant(bad)] });

    expect(wrapper.find(".downloads a").exists()).toBe(false);
    expect(wrapper.find(".downloads .unavailable").exists()).toBe(true);
  });
});

describe("who is working", () => {
  it("shows the agent chain while an answer runs with a delegated agent, and nothing otherwise", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    useEntryAgentStore().entry = { id: "main", label: "Ember" };
    useChatStore().activeAgents = [{ agent_id: "calc", label: "Calculator", since: "2026-10-04T09:12:03.512Z", step_id: "d1" }];
    const mountWith = (busy: boolean) =>
      mount(MessageList, {
        props: { messages: FOUR, streaming: "", activity: "", steps: [], busy, canChange: !busy },
        global: { plugins: [pinia] },
        attachTo: document.body,
      });

    expect(mountWith(true).find(".agent-activity").text()).toContain("Ember → Calculator");
    expect(mountWith(false).find(".agent-activity").exists()).toBe(false);
  });
});

describe("the mark beside an answer", () => {
  it("is on an agent's answer and on the live one, but not on a command's result", () => {
    const answers = mountList({ messages: [user("q"), assistant("a"), assistant("result", { kind: "command" })] });

    const blocks = answers.findAll(".assistant");
    expect(blocks[0]!.classes()).not.toContain("command-reply");
    expect(blocks[1]!.classes()).toContain("command-reply");

    const live = mountList({ busy: true, streaming: "partial" });
    expect(live.get(".assistant.live").classes()).not.toContain("command-reply");
  });
});

describe("question cards", () => {
  const PENDING = {
    id: "q1",
    questions: [
      { header: "Format", question: "Which format?", multi_select: false, options: [{ label: "CSV" }, { label: "JSON" }] },
    ],
  };

  it("shows none without a question", () => {
    expect(mountList({ busy: true, questions: [] }).findAll(".question-card")).toHaveLength(0);
  });

  it("shows one card per waiting question set while an answer is running", () => {
    const wrapper = mountList({ busy: true, questions: [PENDING, { ...PENDING, id: "q2" }] });

    expect(wrapper.findAll(".question-card")).toHaveLength(2);
  });

  it("passes the answer and the skip up", async () => {
    const wrapper = mountList({ busy: true, questions: [PENDING] });

    await wrapper.find("button.opt").trigger("click");
    await wrapper.find(".question-card").trigger("submit");
    await wrapper.find("button.skip").trigger("click");

    expect(wrapper.emitted("answer-question")).toEqual([["q1", [{ selected: ["CSV"], other: null }]]]);
    expect(wrapper.emitted("skip-question")).toEqual([["q1"]]);
  });

  it("turns the card's buttons off while its answer is on its way", () => {
    const wrapper = mountList({ busy: true, questions: [PENDING], answeringQuestions: ["q1"] });

    expect((wrapper.find("button.submit").element as HTMLButtonElement).disabled).toBe(true);
    expect((wrapper.find("button.skip").element as HTMLButtonElement).disabled).toBe(true);
  });
});
