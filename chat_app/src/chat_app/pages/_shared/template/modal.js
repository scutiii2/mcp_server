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
    overlay.className = "modal-overlay";

    const dialog = document.createElement("div");
    dialog.className = "modal-dialog";
    dialog.setAttribute("role", "alertdialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-labelledby", "modal-title");
    dialog.setAttribute("aria-describedby", "modal-message");

    const titleEl = document.createElement("h2");
    titleEl.id = "modal-title";
    titleEl.className = "modal-title";
    titleEl.textContent = title;

    const messageEl = document.createElement("p");
    messageEl.id = "modal-message";
    messageEl.className = "modal-message";
    messageEl.textContent = message;

    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "modal-btn modal-btn-cancel";
    cancelBtn.textContent = cancelLabel;

    const confirmBtn = document.createElement("button");
    confirmBtn.type = "button";
    confirmBtn.className = `modal-btn ${danger ? "modal-btn-danger" : "modal-btn-confirm"}`;
    confirmBtn.textContent = confirmLabel;

    const actions = document.createElement("div");
    actions.className = "modal-actions";
    actions.append(cancelBtn, confirmBtn);

    dialog.append(titleEl, messageEl, actions);
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    const focusables = [cancelBtn, confirmBtn];
    const previouslyFocused = document.activeElement;

    function cleanup(result) {
      document.removeEventListener("keydown", onKeydown);
      overlay.remove();
      if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
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
