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

/** A stand-in for the browser's Notification that records what is shown. */
function fakeNotification(permission: NotificationPermission, asked: NotificationPermission = permission) {
  const shown: FakeShown[] = [];
  const request = vi.fn(async () => asked);
  class FakeNotification implements FakeShown {
    static permission = permission;
    static requestPermission = request;
    onclick: (() => void) | null = null;
    close = vi.fn();
    title: string;
    options: NotificationOptions;
    constructor(title: string, options: NotificationOptions) {
      this.title = title;
      this.options = options;
      shown.push(this);
    }
  }
  vi.stubGlobal("Notification", FakeNotification);
  return { shown, request };
}

interface FakeShown {
  title: string;
  options: NotificationOptions;
  onclick: (() => void) | null;
  close: ReturnType<typeof vi.fn>;
}

const NOTICE = { chatId: "chat-0001", title: "Plan the trip", silent: false, onOpen: vi.fn() };

describe("notificationsSupported", () => {
  it("is true when the browser has the Notification API", async () => {
    fakeNotification("default");

    expect((await load()).notificationsSupported()).toBe(true);
  });

  it("is false when it does not", async () => {
    vi.stubGlobal("Notification", undefined);

    expect((await load()).notificationsSupported()).toBe(false);
  });
});

describe("requestNotifyPermission", () => {
  it("asks the browser when nothing was decided yet", async () => {
    const { request } = fakeNotification("default", "granted");

    expect(await (await load()).requestNotifyPermission()).toBe("granted");
    expect(request).toHaveBeenCalledOnce();
  });

  it("returns a refusal as it is", async () => {
    fakeNotification("default", "denied");

    expect(await (await load()).requestNotifyPermission()).toBe("denied");
  });

  it.each(["granted", "denied"] as const)("does not ask again when it is already %s", async (state) => {
    const { request } = fakeNotification(state);

    expect(await (await load()).requestNotifyPermission()).toBe(state);
    expect(request).not.toHaveBeenCalled();
  });

  it("says unsupported without a Notification API", async () => {
    vi.stubGlobal("Notification", undefined);

    expect(await (await load()).requestNotifyPermission()).toBe("unsupported");
  });

  it("treats a prompt that fails as a refusal", async () => {
    const { request } = fakeNotification("default");
    request.mockRejectedValue(new Error("not from a click"));

    expect(await (await load()).requestNotifyPermission()).toBe("denied");
  });
});

describe("notifyIfAway", () => {
  beforeEach(() => {
    NOTICE.onOpen.mockClear();
  });

  it("shows one notification with the chat's title, never the answer, when the page is away", async () => {
    setAway(true, false);
    const { shown } = fakeNotification("granted");

    (await load()).notifyIfAway(NOTICE);

    expect(shown).toHaveLength(1);
    expect(shown[0]!.title).toBe("Answer ready");
    expect(shown[0]!.options).toEqual({ body: "Plan the trip", tag: "chat-0001", silent: false });
  });

  it("passes on that it should be silent", async () => {
    setAway(true, false);
    const { shown } = fakeNotification("granted");

    (await load()).notifyIfAway({ ...NOTICE, silent: true });

    expect(shown[0]!.options.silent).toBe(true);
  });

  it("shows nothing while the user is looking at the page", async () => {
    setAway(false, true);
    const { shown } = fakeNotification("granted");

    (await load()).notifyIfAway(NOTICE);

    expect(shown).toHaveLength(0);
  });

  it.each(["default", "denied"] as const)("shows nothing when permission is %s", async (state) => {
    setAway(true, false);
    const { shown } = fakeNotification(state);

    (await load()).notifyIfAway(NOTICE);

    expect(shown).toHaveLength(0);
  });

  it("does nothing without a Notification API", async () => {
    setAway(true, false);
    vi.stubGlobal("Notification", undefined);

    const { notifyIfAway } = await load();

    expect(() => notifyIfAway(NOTICE)).not.toThrow();
  });

  it("brings the tab forward, opens the chat and closes the notification when clicked", async () => {
    setAway(true, false);
    const { shown } = fakeNotification("granted");
    const focus = vi.spyOn(window, "focus").mockImplementation(() => {});
    (await load()).notifyIfAway(NOTICE);

    shown[0]!.onclick!();

    expect(focus).toHaveBeenCalledOnce();
    expect(NOTICE.onOpen).toHaveBeenCalledOnce();
    expect(shown[0]!.close).toHaveBeenCalledOnce();
  });

  it("does not throw when the browser refuses to construct one", async () => {
    setAway(true, false);
    class Refusing {
      static permission = "granted";
      constructor() {
        throw new TypeError("Illegal constructor");
      }
    }
    vi.stubGlobal("Notification", Refusing);
    const { notifyIfAway } = await load();

    expect(() => notifyIfAway(NOTICE)).not.toThrow();
  });
});
