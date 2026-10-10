/** Icon path data on a 24 x 24 grid (docs/design/ascension/screens.js). Straight
 * strokes, miter joins, square caps; drawn with the text colour. Heart = HP, flame =
 * Essence and EMBLEM, feather = Speed, shield = Defense, sword = Attack. */
export const ICONS = {
  play: "M7 4L19 12L7 20Z",
  battle: "M4 3L16 15M8 3L19 14L15 18L4 7ZM12 16L7 21M3 17L7 21L11 17",
  shop: "M3 8L5 3H19L21 8V11H3ZM5 11V21H19V11M9 21V15H15V21",
  book: "M3 4H9L12 7L15 4H21V20H15L12 22L9 20H3ZM12 7V22",
  reset: "M4 9A8 8 0 1 1 4 16M4 3V9H10",
  heart: "M12 21L3 12V7L6 4H9L12 7L15 4H18L21 7V12Z",
  flame: "M12 2L16 9L19 7L21 13L19 19L12 22L5 19L3 13L7 6L9 11ZM12 12L9 17L12 20L15 17Z",
  feather: "M5 21L17 3H21V9L11 18H7M8 15L13 14M12 10L17 9",
  shield: "M4 3H20V13L17 18L12 22L7 18L4 13Z",
  sword: "M5 21L10 16M7 13L13 19M10 16L20 6V3H17L7 13",
  arrow: "M4 12H20M14 6L20 12L14 18",
  close: "M5 5L19 19M19 5L5 19",
  check: "M4 12L9 17L20 6",
  coin: "M7 3H17L22 8V16L17 21H7L2 16V8ZM12 6V18M8 9H15M9 15H16",
  clock: "M12 3A9 9 0 1 1 11.99 3M12 7V12L16 14",
  lock: "M6 10V7A6 6 0 0 1 18 7V10M4 10H20V22H4ZM12 15V18",
  warning: "M12 3L22 21H2ZM12 9V14M12 17V18",
  ascended: "M12 2L15 9L22 12L15 15L12 22L9 15L2 12L9 9",
} as const;

export type IconName = keyof typeof ICONS;
