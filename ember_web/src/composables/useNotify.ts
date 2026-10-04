const FREQUENCY_HZ = 880; // A5: short, clean, unobtrusive
const DURATION_S = 0.3;
const PEAK_GAIN = 0.2;
// exponentialRampToValueAtTime cannot target exactly 0.
const FLOOR_GAIN = 0.0001;

/** The page is out of sight or out of focus: the user wouldn't otherwise
 * notice an answer arriving. */
export function pageIsAway(): boolean {
  return document.hidden || !document.hasFocus();
}

// One context for the page's life; browsers limit how many may exist.
let context: AudioContext | null = null;

/** A short chime. Silent when Web Audio is missing or the browser blocks it
 * (no click on the page yet): a missed chime is not worth an error. */
export function playChime(): void {
  try {
    context ??= new AudioContext();
    const ctx = context;
    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();
    oscillator.type = "sine";
    oscillator.frequency.value = FREQUENCY_HZ;
    // Ramps instead of a hard on and off: a sudden gain change clicks.
    gain.gain.setValueAtTime(FLOOR_GAIN, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(PEAK_GAIN, ctx.currentTime + 0.01);
    gain.gain.exponentialRampToValueAtTime(FLOOR_GAIN, ctx.currentTime + DURATION_S);
    oscillator.connect(gain);
    gain.connect(ctx.destination);
    oscillator.start();
    oscillator.stop(ctx.currentTime + DURATION_S);
  } catch {
    // see above
  }
}

/** Chimes, but only when the page is away. */
export function chimeIfAway(): void {
  if (pageIsAway()) playChime();
}
