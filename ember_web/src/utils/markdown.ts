import DOMPurify from "dompurify";
import MarkdownIt from "markdown-it";

// html: false - raw HTML in a model reply is shown as text, never parsed.
// DOMPurify below is the second guard, for anything markdown-it itself emits.
const md = new MarkdownIt({ html: false, linkify: true, breaks: true });

// Links from a reply open in a new tab and can't reach back into this page.
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
});

/** Markdown to sanitized HTML, safe to bind with v-html. */
export function renderMarkdown(text: string): string {
  return DOMPurify.sanitize(md.render(text), { ADD_ATTR: ["target"] });
}
