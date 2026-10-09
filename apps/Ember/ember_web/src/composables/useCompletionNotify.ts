/** Completion alerts for this open page; no answer text appears on the desktop. */
let originalTitle: string | null = null;
let unread = 0;
const notifications = new Set<Notification>();

export function clearCompletionNotifications(): void {
  if (originalTitle !== null) document.title = originalTitle;
  originalTitle = null;
  unread = 0;
  for (const notification of notifications) notification.close();
  notifications.clear();
  window.removeEventListener("focus", clearIfPresent);
  document.removeEventListener("visibilitychange", clearIfPresent);
}

function clearIfPresent(): void {
  if (!document.hidden && document.hasFocus()) clearCompletionNotifications();
}

/** Call directly from the setting's user interaction, never from completion. */
export async function requestCompletionPermission(): Promise<string> {
  if (typeof Notification === "undefined") return "This browser does not support desktop notifications.";
  try {
    const permission = Notification.permission === "default"
      ? await Notification.requestPermission() : Notification.permission;
    if (permission === "granted") return "";
    return permission === "denied"
      ? "Notifications are blocked. Allow them in your browser's site settings, then try again."
      : "Notification permission was not granted. You can try again when ready.";
  } catch {
    return "Notifications are unavailable here. Try opening Ember over HTTPS.";
  }
}

export function notifyCompletion(chatId: string, desktop: boolean, openChat: () => void): void {
  if (!document.hidden && document.hasFocus()) return;
  originalTitle ??= document.title;
  unread += 1;
  document.title = `(${unread}) Answer ready · ${originalTitle}`;
  window.addEventListener("focus", clearIfPresent);
  document.addEventListener("visibilitychange", clearIfPresent);
  if (!desktop || typeof Notification === "undefined" || Notification.permission !== "granted") return;
  try {
    const notification = new Notification("Ember: answer ready", {
      body: "Your answer is ready. Click to open the chat.",
      tag: `ember-answer-${chatId}`,
      silent: true,
    });
    notifications.add(notification);
    notification.onclose = () => notifications.delete(notification);
    notification.onclick = () => {
      notification.close();
      window.focus();
      openChat();
    };
  } catch {
    // Browsers without desktop notification constructors still get the tab indicator.
  }
}
