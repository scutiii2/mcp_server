import channeler from "../../assets/ascension/ascended/channeler.webp";
import forbidden from "../../assets/ascension/ascended/forbidden.webp";
import guardian from "../../assets/ascension/ascended/guardian.webp";
import scout from "../../assets/ascension/ascended/scout.webp";
import sentinel from "../../assets/ascension/ascended/sentinel.webp";
import striker from "../../assets/ascension/ascended/striker.webp";

/** An Ascended's portrait for the card's artwork window. The window is wider than the
 * portraits, so `focus` says where to look: the vertical position (0 to 100, as in CSS
 * `object-position`) that keeps the face in view, one for the wide window of the large
 * card and one for the squarer window of the small card. */
export interface AscendedArt {
  url: string;
  focus: number;
  focusCompact: number;
}

/** Portraits by Ascended id. An Ascended with no portrait yet (Bruiser) is not listed; its
 * card shows the letter placeholder. To add one: put `<id>.webp` in
 * assets/ascension/ascended/ and a line here. */
const PORTRAITS: Record<string, AscendedArt> = {
  guardian: { url: guardian, focus: 21, focusCompact: 50 },
  scout: { url: scout, focus: 10, focusCompact: 50 },
  striker: { url: striker, focus: 10, focusCompact: 50 },
  sentinel: { url: sentinel, focus: 12, focusCompact: 14 },
  channeler: { url: channeler, focus: 30, focusCompact: 43 },
  forbidden: { url: forbidden, focus: 18, focusCompact: 29 },
};

export function ascendedArt(ascendedId: string): AscendedArt | null {
  return PORTRAITS[ascendedId] ?? null;
}
