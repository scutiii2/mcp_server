import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/** A stand-in for the browser's AudioContext that records what is done to it. */
function fakeAudio() {
  const gainParam = { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() };
  const oscillator = { type: "", frequency: { value: 0 }, connect: vi.fn(), start: vi.fn(), stop: vi.fn() };
  const gain = { gain: gainParam, connect: vi.fn() };
  const instances: unknown[] = [];
  class FakeAudioContext {
    currentTime = 10;
    destination = { id: "speakers" };
    constructor() {
      instances.push(this);
    }
    createOscillator = () => oscillator;
    createGain = () => gain;
  }
  return { FakeAudioContext, oscillator, gain, gainParam, instances };
}

function setAway(hidden: boolean, focused: boolean): void {
  Object.defineProperty(document, "hidden", { configurable: true, value: hidden });
  vi.spyOn(document, "hasFocus").mockReturnValue(focused);
}

// A fresh module per test: it keeps one AudioContext for the page's life.
async function load() {
  vi.resetModules();
  return import("./useNotify");
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  Object.defineProperty(document, "hidden", { configurable: true, value: false });
});

describe("pageIsAway", () => {
  it("is false while the page is visible and focused", async () => {
    setAway(false, true);
    const { pageIsAway } = await load();

    expect(pageIsAway()).toBe(false);
  });

  it("is true while the tab is hidden", async () => {
    setAway(true, true);
    const { pageIsAway } = await load();

    expect(pageIsAway()).toBe(true);
  });

  it("is true while the page is visible but not focused", async () => {
    setAway(false, false);
    const { pageIsAway } = await load();

    expect(pageIsAway()).toBe(true);
  });
});

describe("playChime", () => {
  let audio: ReturnType<typeof fakeAudio>;
  beforeEach(() => {
    audio = fakeAudio();
    vi.stubGlobal("AudioContext", audio.FakeAudioContext);
  });

  it("plays a short 880 Hz sine tone through the speakers", async () => {
    const { playChime } = await load();

    playChime();

    expect(audio.oscillator.type).toBe("sine");
    expect(audio.oscillator.frequency.value).toBe(880);
    expect(audio.oscillator.connect).toHaveBeenCalledWith(audio.gain);
    expect(audio.gain.connect).toHaveBeenCalledWith({ id: "speakers" });
    expect(audio.oscillator.start).toHaveBeenCalledOnce();
    expect(audio.oscillator.stop).toHaveBeenCalledWith(10.3);
  });

  it("fades in and out instead of switching the sound on and off (no click)", async () => {
    const { playChime } = await load();

    playChime();

    expect(audio.gainParam.setValueAtTime).toHaveBeenCalledWith(0.0001, 10);
    expect(audio.gainParam.exponentialRampToValueAtTime.mock.calls).toEqual([
      [0.2, 10.01],
      [0.0001, 10.3],
    ]);
  });

  it("reuses one AudioContext for every chime", async () => {
    const { playChime } = await load();

    playChime();
    playChime();
    playChime();

    expect(audio.instances).toHaveLength(1);
  });

  it("stays silent, without an error, when Web Audio is missing", async () => {
    vi.stubGlobal("AudioContext", undefined);
    const { playChime } = await load();

    expect(() => playChime()).not.toThrow();
  });

  it("stays silent when the browser refuses to start the sound", async () => {
    audio.oscillator.start.mockImplementation(() => {
      throw new Error("The AudioContext was not allowed to start");
    });
    const { playChime } = await load();

    expect(() => playChime()).not.toThrow();
  });
});

describe("chimeIfAway", () => {
  let audio: ReturnType<typeof fakeAudio>;
  beforeEach(() => {
    audio = fakeAudio();
    vi.stubGlobal("AudioContext", audio.FakeAudioContext);
  });

  it("chimes when the tab is hidden", async () => {
    setAway(true, false);
    const { chimeIfAway } = await load();

    chimeIfAway();

    expect(audio.oscillator.start).toHaveBeenCalledOnce();
  });

  it("chimes when the page is visible but not focused", async () => {
    setAway(false, false);
    const { chimeIfAway } = await load();

    chimeIfAway();

    expect(audio.oscillator.start).toHaveBeenCalledOnce();
  });

  it("is silent when the user is looking at the page", async () => {
    setAway(false, true);
    const { chimeIfAway } = await load();

    chimeIfAway();

    expect(audio.oscillator.start).not.toHaveBeenCalled();
    expect(audio.instances).toHaveLength(0);
  });
});
