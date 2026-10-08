import type { UserExtension } from "../api/UserExtensionsClient";

/** The short pill text of a private extension: what it brings, or why it brings nothing. */
export function userExtensionSummary(item: UserExtension): string {
  if (!item.enabled) return "Not enabled";
  if (item.status === "connected") return `${item.tools.length} tool${item.tools.length === 1 ? "" : "s"}`;
  if (item.status === "error") return "Not connected";
  return "Not checked yet";
}

/** Whether `item` matches the filter typed on the Capabilities page (label, id or a tool name). */
export function matchesUserExtension(item: UserExtension, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [item.label, item.id, ...item.tools].some((text) => text.toLowerCase().includes(needle));
}
