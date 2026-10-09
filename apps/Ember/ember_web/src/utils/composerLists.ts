import type { JSONContent } from "@tiptap/core";

const ITEM = /^( *)([-+*]|\d+[.)]) (.*)$/;

/** Whether a cursor prefix is inside a literal fenced code block. */
export function composerFenceOpen(text: string): boolean {
  let fence = "";
  for (const line of text.split("\n")) {
    const marker = /^\s*(`{3,}|~{3,})/.exec(line)?.[1];
    if (!marker) continue;
    if (!fence) fence = marker;
    else if (marker[0] === fence[0] && marker.length >= fence.length) fence = "";
  }
  return fence !== "";
}

/** Only list syntax is formatted; code fences and other Markdown stay literal. */
export function hasComposerList(text: string): boolean {
  let fence = "";
  return text.split("\n").some((line) => {
    const code = /^\s*(`{3,}|~{3,})/.exec(line);
    if (code) {
      const marker = code[1]!;
      if (!fence) fence = marker;
      else if (marker[0] === fence[0] && marker.length >= fence.length) fence = "";
      return false;
    }
    return !fence && ITEM.test(line);
  });
}

function paragraph(text: string): JSONContent {
  return { type: "paragraph", content: text ? [{ type: "text", text }] : [] };
}

/** A deliberately small document schema: paragraphs, line breaks and nested lists. */
export function parseComposer(text: string): JSONContent {
  const content: JSONContent[] = [];
  const stack: { indent: number; list: JSONContent; item: JSONContent }[] = [];
  let fence = "";
  for (const line of text.split("\n")) {
    const code = /^\s*(`{3,}|~{3,})/.exec(line);
    if (code) {
      const marker = code[1]!;
      if (!fence) fence = marker;
      else if (marker[0] === fence[0] && marker.length >= fence.length) fence = "";
    }
    const match = fence || code ? null : ITEM.exec(line);
    if (!match) {
      const level = stack.at(-1);
      if (!fence && !code && level && line.trim() && line.startsWith(" ".repeat(level.indent + 2))) {
        const body = level.item.content![0]!;
        body.content!.push({ type: "hardBreak" }, { type: "text", text: line.trimStart() });
        continue;
      }
      stack.length = 0;
      content.push(paragraph(line));
      continue;
    }
    const indent = match[1]!.length;
    const marker = match[2]!;
    const type = /^\d/.test(marker) ? "orderedList" : "bulletList";
    while (stack.length && stack.at(-1)!.indent > indent) stack.pop();
    if (stack.at(-1)?.indent === indent && stack.at(-1)!.list.type !== type) stack.pop();
    let level = stack.at(-1);
    if (!level || level.indent !== indent) {
      const list: JSONContent = { type, content: [], ...(type === "orderedList" ? { attrs: { start: parseInt(marker, 10) } } : {}) };
      (level ? level.item.content! : content).push(list);
      level = { indent, list, item: { type: "listItem", content: [] } };
      stack.push(level);
    }
    const item: JSONContent = { type: "listItem", content: [paragraph(match[3]!)] };
    level.list.content!.push(item);
    level.item = item;
  }
  return { type: "doc", content };
}

/** Keep Markdown list markers in the question sent to Ember's existing API. */
export function serializeComposer(doc: JSONContent): string {
  function inline(node: JSONContent): string {
    if (node.type === "text") return node.text ?? "";
    if (node.type === "hardBreak") return "\n";
    return (node.content ?? []).map(inline).join("");
  }
  function blocks(nodes: JSONContent[], indent = 0): string[] {
    const lines: string[] = [];
    for (const [nodeIndex, node] of nodes.entries()) {
      const previous = nodes[nodeIndex - 1];
      const isList = (value: JSONContent | undefined) => value?.type === "bulletList" || value?.type === "orderedList";
      // Paragraphs beside lists need a blank line to remain separate in Markdown.
      if (previous && isList(previous) !== isList(node) && lines.at(-1) !== "" &&
          (isList(node) || inline(node) !== "")) lines.push("");
      if (node.type === "bulletList" || node.type === "orderedList") {
        const start = Number(node.attrs?.start ?? 1);
        for (const [index, item] of (node.content ?? []).entries()) {
          const children = item.content ?? [];
          const marker = node.type === "orderedList" ? `${start + index}. ` : "- ";
          const body = inline(children[0] ?? {});
          const [first, ...rest] = body.split("\n");
          lines.push(" ".repeat(indent) + marker + first);
          lines.push(...rest.map(line => " ".repeat(indent + marker.length) + line));
          lines.push(...blocks(children.slice(1), indent + 4));
        }
      } else {
        lines.push(" ".repeat(indent) + inline(node));
      }
    }
    return lines;
  }
  return blocks(doc.content ?? []).join("\n");
}
