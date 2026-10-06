/** Where a menu should open, and which button to give focus back to afterwards. */
export interface MenuPoint {
  x: number;
  y: number;
  trigger: HTMLElement | null;
}
