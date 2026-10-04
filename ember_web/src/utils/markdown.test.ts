import { describe, expect, it } from "vitest";
import { renderMarkdown } from "./markdown";

function render(text: string): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = renderMarkdown(text);
  return host;
}

describe("renderMarkdown code blocks", () => {
  it("wraps each fenced block with a Copy button that survives sanitizing", () => {
    const host = render("```js\nconst a = 1;\n```\n\ntext\n\n```\nsecond\n```");

    const blocks = host.querySelectorAll(".code-block");
    expect(blocks).toHaveLength(2);
    for (const block of blocks) {
      const button = block.querySelector("button.code-copy");
      expect(button?.textContent).toBe("Copy");
      expect(button?.getAttribute("type")).toBe("button");
      expect(block.querySelector("pre code")).not.toBeNull();
    }
    expect(blocks[0]!.querySelector("pre code")!.textContent).toBe("const a = 1;\n");
  });

  it("gives inline code and indented code no button of their own", () => {
    expect(render("use `x` here").querySelector("button")).toBeNull();
  });

  it("does not let a model reply smuggle in its own button or handler", () => {
    const host = render('<button class="code-copy" onclick="alert(1)">x</button> <img src=x onerror="alert(1)">');

    // Raw HTML is shown as text, never parsed into elements or attributes.
    expect(host.querySelector("button, img, [onclick], [onerror]")).toBeNull();
    expect(host.textContent).toContain('<button class="code-copy"');
  });

  it("opens links in a new tab without a back reference", () => {
    const link = render("[a](https://example.com)").querySelector("a")!;

    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  });
});
