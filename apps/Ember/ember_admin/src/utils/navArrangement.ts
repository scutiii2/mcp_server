import type { NavPrefs } from "../stores/navPrefs";

/** Pure rules for the nav rail arrangement, shared by the rail and the Settings
 * editor. A page is pinned (top group), hidden (not in the rail) or neither;
 * hiding wins, so a page is never both. Pages the arrangement does not know
 * (new, or newly permitted) follow the known ones in their default order, and
 * ids it holds for pages the account can't open are ignored. */

export const EMPTY_PREFS: NavPrefs = { order: [], pinned: [], hidden: [] };

type Page = { to: string };

export interface Arranged<T> {
  pinned: T[];
  /** Everything not pinned, hidden pages included. */
  rest: T[];
}

export function isDefault(prefs: NavPrefs): boolean {
  return prefs.order.length === 0 && prefs.pinned.length === 0 && prefs.hidden.length === 0;
}

/** Every page, pinned ones first, each group in the saved order. */
export function arrange<T extends Page>(pages: T[], prefs: NavPrefs): Arranged<T> {
  const rank = new Map(prefs.order.map((id, i) => [id, i]));
  const ordered = [...pages].sort((a, b) => (rank.get(a.to) ?? prefs.order.length) - (rank.get(b.to) ?? prefs.order.length));
  const hidden = new Set(prefs.hidden);
  const pinned = new Set(prefs.pinned);
  const isPinned = (p: T) => pinned.has(p.to) && !hidden.has(p.to);
  return { pinned: ordered.filter(isPinned), rest: ordered.filter((p) => !isPinned(p)) };
}

/** What the rail draws: the same groups without the hidden pages. */
export function railPages<T extends Page>(pages: T[], prefs: NavPrefs): Arranged<T> {
  const hidden = new Set(prefs.hidden);
  const { pinned, rest } = arrange(pages, prefs);
  return { pinned, rest: rest.filter((p) => !hidden.has(p.to)) };
}

function build<T extends Page>(pinned: T[], rest: T[], hidden: Iterable<string>): NavPrefs {
  return {
    order: [...pinned, ...rest].map((p) => p.to),
    pinned: pinned.map((p) => p.to),
    hidden: [...hidden],
  };
}

/** Moves a page to where another page is: before it when moving up, after it
 * when moving down. It joins the target's group (pinned or not), and a page
 * dropped among the pinned ones is shown. Returns `prefs` itself if nothing moves. */
export function dropPage<T extends Page>(pages: T[], prefs: NavPrefs, from: string, onto: string): NavPrefs {
  const { pinned, rest } = arrange(pages, prefs);
  const flat = [...pinned, ...rest];
  const a = flat.findIndex((p) => p.to === from);
  const b = flat.findIndex((p) => p.to === onto);
  if (a < 0 || b < 0 || a === b) return prefs;
  const intoPinned = pinned.some((p) => p.to === onto);
  const [moved] = flat.splice(a, 1);
  flat.splice(b, 0, moved!);
  const hidden = new Set(prefs.hidden);
  if (intoPinned) hidden.delete(from);
  const stillPinned = new Set(pinned.map((p) => p.to));
  if (intoPinned) stillPinned.add(from);
  else stillPinned.delete(from);
  return build(
    flat.filter((p) => stillPinned.has(p.to)),
    flat.filter((p) => !stillPinned.has(p.to)),
    hidden,
  );
}

/** Pinning puts the page last among the pinned (and shows it); unpinning puts it first among the rest. */
export function setPinned<T extends Page>(pages: T[], prefs: NavPrefs, id: string, on: boolean): NavPrefs {
  const { pinned, rest } = arrange(pages, prefs);
  const page = pages.find((p) => p.to === id);
  if (!page) return prefs;
  const others = (list: T[]) => list.filter((p) => p.to !== id);
  const hidden = new Set(prefs.hidden);
  if (on) {
    hidden.delete(id);
    return build([...others(pinned), page], others(rest), hidden);
  }
  return build(others(pinned), [page, ...others(rest)], hidden);
}

/** Hiding also unpins the page. */
export function setHidden<T extends Page>(pages: T[], prefs: NavPrefs, id: string, on: boolean): NavPrefs {
  const hidden = new Set(prefs.hidden);
  const { pinned, rest } = arrange(pages, prefs);
  if (!on) {
    hidden.delete(id);
    return build(pinned, rest, hidden);
  }
  hidden.add(id);
  const page = pages.find((p) => p.to === id);
  if (!page) return prefs;
  const wasPinned = pinned.some((p) => p.to === id);
  return wasPinned
    ? build(pinned.filter((p) => p.to !== id), [page, ...rest.filter((p) => p.to !== id)], hidden)
    : build(pinned, rest, hidden);
}
