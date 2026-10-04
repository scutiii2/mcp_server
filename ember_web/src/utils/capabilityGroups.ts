import type { CapabilityInfo } from "../api/CommandsClient";
import type { ToolInfo } from "../api/types";

/** One capability and the tools of it that are shown. */
export interface CapabilityGroup {
  capability: CapabilityInfo;
  tools: ToolInfo[];
}

export interface GroupedTools {
  groups: CapabilityGroup[];
  /** Tools no capability lists (e.g. from an extension). */
  otherTools: ToolInfo[];
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
 * left with none is dropped. */
export function groupTools(capabilities: CapabilityInfo[], tools: ToolInfo[], query: string): GroupedTools {
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
  const others = tools.filter((t) => !claimed.has(t.name));
  return { groups, otherTools: q ? others.filter((t) => toolMatches(t, q)) : others };
}
