import type { CapabilityInfo } from "../api/CommandsClient";
import { EXTENSION_SEPARATOR, type ExtensionInfo } from "../api/ExtensionsClient";
import type { ToolInfo } from "../api/types";

/** One capability and the tools of it that are shown. */
export interface CapabilityGroup {
  capability: CapabilityInfo;
  tools: ToolInfo[];
}

/** One extension and the tools of it that are shown. */
export interface ExtensionGroup {
  extension: ExtensionInfo;
  tools: ToolInfo[];
}

export interface GroupedTools {
  groups: CapabilityGroup[];
  /** Tools no capability lists that an extension brings. */
  extensionGroups: ExtensionGroup[];
  /** Tools neither a capability nor an extension lists. */
  otherTools: ToolInfo[];
}

/** Whether `name` is namespaced under extension `id` ("<id>__<name>"). */
export function inExtensionNamespace(id: string, name: string): boolean {
  return name.startsWith(`${id}${EXTENSION_SEPARATOR}`);
}

function ownedByExtension(extension: ExtensionInfo, tool: ToolInfo): boolean {
  return extension.tools.includes(tool.name) || inExtensionNamespace(extension.id, tool.name);
}

export interface AddedOnly {
  capabilities: CapabilityInfo[];
  extensions: ExtensionInfo[];
  tools: ToolInfo[];
}

/** What the account has added: only those capabilities and extensions, and the
 * tools left once the ones of everything not added are removed, so they do not
 * turn up as "other tools". */
export function addedOnly(
  capabilities: CapabilityInfo[],
  extensions: ExtensionInfo[],
  tools: ToolInfo[],
  addedCapabilities: readonly string[],
  addedExtensions: readonly string[],
): AddedOnly {
  const capabilityIds = new Set(addedCapabilities);
  const extensionIds = new Set(addedExtensions);
  const hiddenTools = new Set(capabilities.filter((c) => !capabilityIds.has(c.name)).flatMap((c) => c.tools));
  const hiddenExtensions = extensions.filter((e) => !extensionIds.has(e.id));
  return {
    capabilities: capabilities.filter((c) => capabilityIds.has(c.name)),
    extensions: extensions.filter((e) => extensionIds.has(e.id)),
    tools: tools.filter((t) => !hiddenTools.has(t.name) && !hiddenExtensions.some((e) => ownedByExtension(e, t))),
  };
}

function extensionMatches(extension: ExtensionInfo, q: string): boolean {
  return extension.id.toLowerCase().includes(q) || extension.label.toLowerCase().includes(q);
}

function toolMatches(tool: ToolInfo, q: string): boolean {
  return (
    tool.title.toLowerCase().includes(q) || tool.name.toLowerCase().includes(q) || tool.description.toLowerCase().includes(q)
  );
}

function capabilityMatches(capability: CapabilityInfo, q: string): boolean {
  return capability.name.toLowerCase().includes(q) || (capability.label ?? "").toLowerCase().includes(q);
}

/** Sorts `tools` under the capability that lists them, narrowed by `query`
 * (blank = everything). A capability whose own name or label matches keeps all
 * its tools; otherwise it stays only with the tools that match, and a group
 * left with none is dropped. Tools no capability lists then go under the
 * extension that brings them, by the same rules; the rest are `otherTools`. */
export function groupTools(
  capabilities: CapabilityInfo[],
  tools: ToolInfo[],
  query: string,
  extensions: ExtensionInfo[] = [],
): GroupedTools {
  const q = query.trim().toLowerCase();
  const byName = new Map(tools.map((t) => [t.name, t]));
  const claimed = new Set(capabilities.flatMap((c) => c.tools));

  const groups: CapabilityGroup[] = [];
  for (const capability of capabilities) {
    const own = capability.tools.flatMap((name) => byName.get(name) ?? []);
    if (!q) {
      groups.push({ capability, tools: own });
    } else if (capabilityMatches(capability, q)) {
      groups.push({ capability, tools: own });
    } else {
      const matching = own.filter((t) => toolMatches(t, q));
      if (matching.length) groups.push({ capability, tools: matching });
    }
  }
  let others = tools.filter((t) => !claimed.has(t.name));

  const extensionGroups: ExtensionGroup[] = [];
  for (const extension of extensions) {
    const own = others.filter((t) => ownedByExtension(extension, t));
    if (!q || extensionMatches(extension, q)) {
      extensionGroups.push({ extension, tools: own });
    } else {
      const matching = own.filter((t) => toolMatches(t, q));
      if (matching.length) extensionGroups.push({ extension, tools: matching });
    }
    others = others.filter((t) => !own.includes(t));
  }
  return { groups, extensionGroups, otherTools: q ? others.filter((t) => toolMatches(t, q)) : others };
}
