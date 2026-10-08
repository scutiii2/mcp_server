/** 16px grid, stroke only: a box (built-in capability), a plug (extension), a wrench (other tools). */
export const CAPABILITY_ICONS = {
  builtin: "M8 1.5l5.5 3v7L8 14.5l-5.5-3v-7zM2.5 4.5L8 7.5l5.5-3M8 7.5v7",
  extension: "M6 2v3M10 2v3M4.5 5h7v3a3.5 3.5 0 0 1-7 0zM8 11.5V14",
  other: "M10.5 2.5a3 3 0 0 0-3.2 4L2.5 11.3 4.7 13.5 9.5 8.7a3 3 0 0 0 4-3.2l-1.8 1.8-1.7-.5-.5-1.7z",
} as const;
