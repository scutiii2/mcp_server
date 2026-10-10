/** Ascension Types (the Ascension game's types). For now they only filter and group the
 * collection. An Ascended holds zero or more; the order below is the display order. */
export const ASCENSION_TYPES = [
  { id: "pure", label: "Pure" },
  { id: "abyss", label: "Abyss" },
  { id: "divine", label: "Divine" },
  { id: "crimson", label: "Crimson" },
  { id: "enchant", label: "Enchant" },
  { id: "synthetic", label: "Synthetic" },
] as const;

export interface TypeGroup<T> {
  /** null for the Ascendeds with no type. */
  typeId: string | null;
  label: string;
  items: T[];
}

export function typeLabel(typeId: string): string {
  return ASCENSION_TYPES.find((t) => t.id === typeId)?.label ?? typeId.charAt(0).toUpperCase() + typeId.slice(1);
}

/** The types that at least one item has, in display order (unknown ids last, as sent). */
export function typesPresent(items: readonly { ascension_types: readonly string[] }[]): string[] {
  const seen = new Set(items.flatMap((item) => item.ascension_types));
  const known: string[] = ASCENSION_TYPES.map((t) => t.id).filter((id) => seen.has(id));
  return [...known, ...[...seen].filter((id) => !known.includes(id))];
}

/** Items with the type, or all of them when no type is chosen. */
export function filterByType<T extends { ascension_types: readonly string[] }>(items: readonly T[], typeId: string | null): T[] {
  return typeId === null ? [...items] : items.filter((item) => item.ascension_types.includes(typeId));
}

/** One group per type present, in display order; an item with several types is in each
 * of its groups, and items with none go in a last "No type" group. */
export function groupByType<T extends { ascension_types: readonly string[] }>(items: readonly T[]): TypeGroup<T>[] {
  const groups: TypeGroup<T>[] = typesPresent(items).map((typeId) => ({
    typeId,
    label: typeLabel(typeId),
    items: items.filter((item) => item.ascension_types.includes(typeId)),
  }));
  const untyped = items.filter((item) => item.ascension_types.length === 0);
  if (untyped.length) groups.push({ typeId: null, label: "No type", items: untyped });
  return groups;
}
