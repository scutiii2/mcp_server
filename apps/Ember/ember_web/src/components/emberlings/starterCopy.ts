/** The words around a starter on the starter pick: a short motto beside its small card
 * and a line about it in the side panel. A starter with no entry gets the fallback. */
export interface StarterCopy {
  motto: string;
  blurb: string;
}

const COPY: Record<string, StarterCopy> = {
  guardian: { motto: "Endure. Protect. Prevail.", blurb: "A steady shield for the journey ahead." },
  scout: { motto: "Move first. Stay nimble.", blurb: "Quick on its feet, and first to act." },
  striker: { motto: "Hit hard. Burn bright.", blurb: "A fierce fighter that burns brightest in a tight spot." },
};

const FALLBACK: StarterCopy = { motto: "A new companion.", blurb: "A companion for the journey ahead." };

export function starterCopy(sparkId: string): StarterCopy {
  return COPY[sparkId] ?? FALLBACK;
}
