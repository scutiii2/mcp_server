import { onActivated, onBeforeUnmount, onDeactivated, onMounted } from "vue";

export interface ChatShortcutActions {
  /** Esc: only offered while an answer is being written. */
  canStop: () => boolean;
  stop: () => void;
  focusInput: () => void;
  newChat: () => void;
}

/** Window-level chat shortcuts: Esc stops the running answer, Ctrl+K focuses
 * the input, Ctrl+Shift+O starts a new chat. Active only while the chat page
 * is shown - it lives in a KeepAlive, so mounted/activated both count. */
export function useChatShortcuts(actions: ChatShortcutActions): void {
  let attached = false;

  function onKeydown(event: KeyboardEvent): void {
    // Something (a rename box, the IME) already used the key.
    if (event.defaultPrevented || event.isComposing) return;
    // A modal (the command form) owns the keyboard while open.
    if (document.querySelector("dialog[open]")) return;

    const mod = event.ctrlKey || event.metaKey;
    if (event.key === "Escape" && !mod && !event.shiftKey && !event.altKey && actions.canStop()) {
      event.preventDefault();
      actions.stop();
    } else if (mod && !event.shiftKey && !event.altKey && event.key.toLowerCase() === "k") {
      event.preventDefault();
      actions.focusInput();
    } else if (mod && event.shiftKey && !event.altKey && event.code === "KeyO") {
      event.preventDefault();
      actions.newChat();
    }
  }

  function attach(): void {
    if (attached) return;
    window.addEventListener("keydown", onKeydown);
    attached = true;
  }

  function detach(): void {
    if (!attached) return;
    window.removeEventListener("keydown", onKeydown);
    attached = false;
  }

  onMounted(attach);
  onActivated(attach);
  onDeactivated(detach);
  onBeforeUnmount(detach);
}
