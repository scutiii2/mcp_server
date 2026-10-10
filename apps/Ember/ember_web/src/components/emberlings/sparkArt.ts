import channeler from "../../assets/emberlings/sparks/channeler.webp";
import forbidden from "../../assets/emberlings/sparks/forbidden.webp";
import guardian from "../../assets/emberlings/sparks/guardian.webp";
import scout from "../../assets/emberlings/sparks/scout.webp";
import sentinel from "../../assets/emberlings/sparks/sentinel.webp";
import striker from "../../assets/emberlings/sparks/striker.webp";

/** A Spark's portrait for the card's artwork window. The window is wider than the
 * portraits, so `focus` says where to look: the vertical position (0 to 100, as in CSS
 * `object-position`) that keeps the face in view, one for the wide window of the large
 * card and one for the squarer window of the small card. */
export interface SparkArt {
  url: string;
  focus: number;
  focusCompact: number;
}

/** Portraits by Spark id. A Spark with no portrait yet (Bruiser) is not listed; its
 * card shows the letter placeholder. To add one: put `<id>.webp` in
 * assets/emberlings/sparks/ and a line here. */
const PORTRAITS: Record<string, SparkArt> = {
  guardian: { url: guardian, focus: 21, focusCompact: 50 },
  scout: { url: scout, focus: 10, focusCompact: 50 },
  striker: { url: striker, focus: 10, focusCompact: 50 },
  sentinel: { url: sentinel, focus: 12, focusCompact: 14 },
  channeler: { url: channeler, focus: 30, focusCompact: 43 },
  forbidden: { url: forbidden, focus: 18, focusCompact: 29 },
};

export function sparkArt(sparkId: string): SparkArt | null {
  return PORTRAITS[sparkId] ?? null;
}
