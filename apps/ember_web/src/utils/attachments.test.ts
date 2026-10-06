import { describe, expect, it } from "vitest";
import type { ChatMessage } from "../api/types";
import { questionHistory, splitAttachments, withAttachments } from "./attachments";

const user = (content: string, extra: Partial<ChatMessage> = {}): ChatMessage => ({ role: "user", content, ...extra });
const assistant = (content: string, extra: Partial<ChatMessage> = {}): ChatMessage => ({ role: "assistant", content, ...extra });

describe("questionHistory", () => {
  it("lists what the user typed, oldest first, and leaves the answers out", () => {
    const messages = [user("first"), assistant("answer 1"), user("second"), assistant("answer 2")];

    expect(questionHistory(messages)).toEqual(["first", "second"]);
  });

  it("is empty for an empty chat", () => {
    expect(questionHistory([])).toEqual([]);
  });

  it("includes slash commands the user ran", () => {
    const messages = [
      user("/files list path=docs", { kind: "command" }),
      assistant("two files", { kind: "command" }),
      user("and a question"),
    ];

    expect(questionHistory(messages)).toEqual(["/files list path=docs", "and a question"]);
  });

  it("leaves out summaries and attached logs, which the user did not type", () => {
    const messages = [
      user("typed"),
      user("Summary of the earlier chat", { kind: "summary" }),
      user("raw log text", { kind: "log_attachment" }),
    ];

    expect(questionHistory(messages)).toEqual(["typed"]);
  });

  it("gives back the typed text without the attached files", () => {
    const messages = [user(withAttachments("read this", [{ filename: "a.txt", chars: 3, truncated: false, text: "abc" }]))];

    expect(questionHistory(messages)).toEqual(["read this"]);
  });

  it("skips an empty message", () => {
    expect(questionHistory([user(""), user("kept")])).toEqual(["kept"]);
  });
});

describe("splitAttachments round trip", () => {
  it("returns the text and the files that withAttachments joined", () => {
    const joined = withAttachments("look", [{ filename: "n.txt", chars: 2, truncated: true, text: "hi" }]);

    expect(splitAttachments(joined)).toEqual({
      text: "look",
      attachments: [{ filename: "n.txt", chars: 2, truncated: true, text: "hi" }],
    });
  });
});
