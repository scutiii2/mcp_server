function initSidebarToggle() {
  const toggle = document.getElementById("sidebar-toggle");
  const sidebar = document.getElementById("sidebar");
  if (!toggle || !sidebar) return;

  const STORAGE_KEY = "sidebar-collapsed";

  const applyCollapsed = (collapsed) => {
    sidebar.classList.toggle("collapsed", collapsed);
    toggle.setAttribute("aria-expanded", String(!collapsed));
  };

  applyCollapsed(localStorage.getItem(STORAGE_KEY) === "1");

  toggle.addEventListener("click", () => {
    const collapsed = sidebar.classList.contains("collapsed");
    applyCollapsed(!collapsed);
    localStorage.setItem(STORAGE_KEY, collapsed ? "0" : "1");
  });
}

function initToasts() {
  const TOAST_TIMEOUT_MS = 5000;

  document.querySelectorAll(".toast").forEach((toast) => {
    const dismiss = () => {
      toast.classList.add("hide");
      toast.addEventListener("transitionend", () => toast.remove(), { once: true });
    };

    const closeButton = toast.querySelector(".toast-close");
    if (closeButton) {
      closeButton.addEventListener("click", dismiss);
    }
    if (!toast.classList.contains("toast-persistent")) {
      setTimeout(dismiss, TOAST_TIMEOUT_MS);
    }
  });
}

function initConfirmModals() {
  const forms = document.querySelectorAll("form[data-confirm]");
  if (!forms.length) return;

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal" role="alertdialog" aria-modal="true">
      <p class="modal-message"></p>
      <div class="modal-actions">
        <button type="button" class="modal-cancel">Cancel</button>
        <button type="button" class="modal-confirm">Confirm</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  const messageEl = overlay.querySelector(".modal-message");
  const cancelButton = overlay.querySelector(".modal-cancel");
  const confirmButton = overlay.querySelector(".modal-confirm");
  let pendingForm = null;

  const close = () => {
    overlay.classList.remove("open");
    pendingForm = null;
  };

  forms.forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (form.dataset.confirmed === "true") return;
      event.preventDefault();
      pendingForm = form;
      messageEl.textContent = form.dataset.confirm;
      overlay.classList.add("open");
    });
  });

  cancelButton.addEventListener("click", close);
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) close();
  });
  confirmButton.addEventListener("click", () => {
    if (pendingForm) {
      pendingForm.dataset.confirmed = "true";
      pendingForm.requestSubmit();
    }
    close();
  });
}

function initAccountMenus() {
  document.querySelectorAll(".account-menu").forEach((menu) => {
    const trigger = menu.querySelector("[data-account-menu-trigger]");
    const dropdown = menu.querySelector("[data-account-menu-dropdown]");
    if (!trigger || !dropdown) return;

    const close = () => {
      dropdown.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
    };

    const open = () => {
      dropdown.hidden = false;
      trigger.setAttribute("aria-expanded", "true");
    };

    trigger.addEventListener("click", (event) => {
      event.stopPropagation();
      if (dropdown.hidden) {
        open();
      } else {
        close();
      }
    });

    document.addEventListener("click", (event) => {
      if (!dropdown.hidden && !menu.contains(event.target)) close();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !dropdown.hidden) close();
    });
  });
}

function initTabs() {
  document.querySelectorAll("[data-tabs]").forEach((container) => {
    const buttons = container.querySelectorAll(".tab-btn");
    const panels = container.querySelectorAll(".tab-panel");

    buttons.forEach((button) => {
      button.addEventListener("click", () => {
        const target = button.dataset.tab;
        buttons.forEach((b) => b.classList.toggle("active", b === button));
        panels.forEach((panel) => {
          panel.hidden = panel.dataset.tabPanel !== target;
        });
      });
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initSidebarToggle();
  initToasts();
  initConfirmModals();
  initAccountMenus();
  initTabs();
});
