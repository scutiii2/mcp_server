// Drop-in replacement for the browser's native confirm(), styled to match
// the rest of the app instead of the OS's own dialog chrome. Usage:
//
//   if (!(await confirmModal({ title: '...', message: '...', danger: true }))) return;
//
// Returns a Promise<boolean> (true = confirmed) rather than confirm()'s
// synchronous return, since a custom dialog can't actually block the
// script the way the native one does - every call site here already runs
// inside an async function, so `await` reads the same as the old
// `if (!confirm(...))` guard did.
function confirmModal({ title = "Are you sure?", message = "", confirmLabel = "Confirm", cancelLabel = "Cancel", danger = false } = {}) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "chat-modal-overlay";

    const dialog = document.createElement("div");
    dialog.className = "chat-modal-dialog";
    dialog.setAttribute("role", "alertdialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-labelledby", "chat-modal-title");
    dialog.setAttribute("aria-describedby", "chat-modal-message");

    const titleEl = document.createElement("h2");
    titleEl.id = "chat-modal-title";
    titleEl.className = "chat-modal-title";
    titleEl.textContent = title;

    const messageEl = document.createElement("p");
    messageEl.id = "chat-modal-message";
    messageEl.className = "chat-modal-message";
    messageEl.textContent = message;

    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "chat-modal-btn chat-modal-btn-cancel";
    cancelBtn.textContent = cancelLabel;

    const confirmBtn = document.createElement("button");
    confirmBtn.type = "button";
    confirmBtn.className = `chat-modal-btn ${danger ? "chat-modal-btn-danger" : "chat-modal-btn-confirm"}`;
    confirmBtn.textContent = confirmLabel;

    const actions = document.createElement("div");
    actions.className = "chat-modal-actions";
    actions.append(cancelBtn, confirmBtn);

    dialog.append(titleEl, messageEl, actions);
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    const focusables = [cancelBtn, confirmBtn];
    const previouslyFocused = document.activeElement;

    function cleanup(result) {
      document.removeEventListener("keydown", onKeydown);
      overlay.remove();
      if (previouslyFocused instanceof HTMLElement && previouslyFocused.isConnected && !previouslyFocused.disabled) {
        previouslyFocused.focus();
      } else {
        const management = document.getElementById('chat-manage-panel');
        const fallback = management && !management.classList.contains('hidden')
          ? management.querySelector('button') : document.getElementById('q');
        if (fallback && !fallback.disabled) fallback.focus();
      }
      resolve(result);
    }

    function onKeydown(event) {
      if (event.key === "Escape") {
        cleanup(false);
        return;
      }
      if (event.key !== "Tab") return;
      // Small manual focus trap - only two buttons ever live in here.
      event.preventDefault();
      const from = focusables.indexOf(document.activeElement);
      const step = event.shiftKey ? -1 : 1;
      focusables[(from + step + focusables.length) % focusables.length].focus();
    }

    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) cleanup(false);
    });
    cancelBtn.addEventListener("click", () => cleanup(false));
    confirmBtn.addEventListener("click", () => cleanup(true));
    document.addEventListener("keydown", onKeydown);

    // Defaults focus to Cancel for a danger action, so a stray Enter
    // press doesn't complete the destructive one.
    (danger ? cancelBtn : confirmBtn).focus();
  });
}

// Same visual system as confirmModal above, but for a choice among more
// than one non-cancel outcome (e.g. script.js's clearChat(): "Generate
// summary" vs "Just clear" - neither should be forced as the only path).
// Usage:
//
//   const choice = await choiceModal({
//     title: '...', message: '...',
//     choices: [{ value: 'a', label: 'Do A' }, { value: 'b', label: 'Do B', danger: true }],
//   });
//   if (!choice) return; // dismissed - Escape, backdrop click, or Cancel
//
// Resolves the clicked choice's `value`, or null if dismissed.
function choiceModal({ title = "Choose an option", message = "", choices = [], cancelLabel = "Cancel" } = {}) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "chat-modal-overlay";

    const dialog = document.createElement("div");
    dialog.className = "chat-modal-dialog";
    dialog.setAttribute("role", "alertdialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-labelledby", "chat-modal-title");
    dialog.setAttribute("aria-describedby", "chat-modal-message");

    const titleEl = document.createElement("h2");
    titleEl.id = "chat-modal-title";
    titleEl.className = "chat-modal-title";
    titleEl.textContent = title;

    const messageEl = document.createElement("p");
    messageEl.id = "chat-modal-message";
    messageEl.className = "chat-modal-message";
    messageEl.textContent = message;

    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "chat-modal-btn chat-modal-btn-cancel";
    cancelBtn.textContent = cancelLabel;

    const choiceBtns = choices.map((choice) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `chat-modal-btn ${choice.danger ? "chat-modal-btn-danger" : "chat-modal-btn-confirm"}`;
      btn.textContent = choice.label;
      btn.addEventListener("click", () => cleanup(choice.value));
      return btn;
    });

    const actions = document.createElement("div");
    actions.className = "chat-modal-actions";
    actions.append(cancelBtn, ...choiceBtns);

    dialog.append(titleEl, messageEl, actions);
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    const focusables = [cancelBtn, ...choiceBtns];
    const previouslyFocused = document.activeElement;

    function cleanup(result) {
      document.removeEventListener("keydown", onKeydown);
      overlay.remove();
      if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
      resolve(result);
    }

    function onKeydown(event) {
      if (event.key === "Escape") {
        cleanup(null);
        return;
      }
      if (event.key !== "Tab") return;
      event.preventDefault();
      const from = focusables.indexOf(document.activeElement);
      const step = event.shiftKey ? -1 : 1;
      focusables[(from + step + focusables.length) % focusables.length].focus();
    }

    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) cleanup(null);
    });
    cancelBtn.addEventListener("click", () => cleanup(null));
    document.addEventListener("keydown", onKeydown);

    cancelBtn.focus();
  });
}
