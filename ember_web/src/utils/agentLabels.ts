/** The name to show for an agent id: its known label, else the id itself
 * (answers saved before the agent list went away name agents ember no longer lists). */
export function agentLabelFor(id: string | undefined, labels: Record<string, string>): string | undefined {
  if (!id) return undefined;
  return labels[id] ?? id;
}
