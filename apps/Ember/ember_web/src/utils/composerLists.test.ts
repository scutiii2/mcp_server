import { describe, expect, it } from "vitest";
import { composerFenceOpen, hasComposerList, parseComposer, serializeComposer } from "./composerLists";

describe("composer list Markdown", () => {
  it("recognizes bullets and ordered items, including an empty next item", () => {
    for (const text of ["- first", "* first", "+ first", "1. first", "3) third", "- "]) expect(hasComposerList(text)).toBe(true);
    for (const text of ["plain text", "-", "1.5", "/data top", "```\n- literal\n```", "```\n~~~\n- literal\n``` "]) expect(hasComposerList(text)).toBe(false);
  });
  it("preserves plain text, newlines, spacing and HTML as literal text", () => {
    const text = '  /apps start name="x"\n\n<script>literal</script>\n';
    expect(serializeComposer(parseComposer(text))).toBe(text);
  });
  it("keeps ordered starts and nesting through an editor round trip", () => {
    const text = "intro\n\n3. third\n    - nested\n4. fourth\n\noutro";
    const doc = parseComposer(text);
    expect(doc.content![2]!.attrs?.start).toBe(3);
    expect(serializeComposer(doc)).toBe(text);
  });
  it("continues wrapped item text and separates following paragraphs", () => {
    expect(serializeComposer(parseComposer("- first\n  continued\nnormal"))).toBe("- first\n  continued\n\nnormal");
  });
  it("leaves fenced list-looking text literal", () => {
    const text = "```\n- literal\n~~~\n1. literal\n```\n\n- actual";
    expect(serializeComposer(parseComposer(text))).toBe(text);
  });
  it("keeps typed list prefixes literal inside matching fences", () => {
    expect(composerFenceOpen("```\n~~~\n- ")).toBe(true);
    expect(composerFenceOpen("```\n- literal\n```\n- ")).toBe(false);
  });
});
