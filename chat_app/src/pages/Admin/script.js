function initAdminSearch() {
  const input = document.getElementById("admin-search");
  const tabsContainer = document.querySelector("[data-tabs]");
  if (!input || !tabsContainer) return;

  const cards = tabsContainer.querySelectorAll(".role, .account, .permission");
  const panels = tabsContainer.querySelectorAll(".tab-panel");
  const buttons = tabsContainer.querySelectorAll(".tab-btn");

  const cardText = (card) => (card.dataset.search || card.textContent).toLowerCase();

  const panelHasVisibleCard = (panel) =>
    Array.from(panel.querySelectorAll(".role, .account, .permission")).some(
      (card) => !card.classList.contains("search-hidden")
    );

  const switchToTab = (target) => {
    buttons.forEach((button) => button.classList.toggle("active", button.dataset.tab === target));
    panels.forEach((panel) => {
      panel.hidden = panel.dataset.tabPanel !== target;
    });
  };

  input.addEventListener("input", () => {
    const query = input.value.trim().toLowerCase();

    cards.forEach((card) => {
      const matches = !query || cardText(card).includes(query);
      card.classList.toggle("search-hidden", !matches);
    });

    if (!query) return;

    const activePanel = tabsContainer.querySelector(".tab-panel:not([hidden])");
    if (activePanel && panelHasVisibleCard(activePanel)) return;

    const nextPanel = Array.from(panels).find(panelHasVisibleCard);
    if (nextPanel) switchToTab(nextPanel.dataset.tabPanel);
  });
}

function initGrantComboboxes() {
  document.querySelectorAll("[data-combobox]").forEach((combobox) => {
    const input = combobox.querySelector(".combobox-input");
    const hidden = combobox.querySelector(".combobox-value");
    const panel = combobox.querySelector(".combobox-options");
    const options = Array.from(combobox.querySelectorAll(".combobox-option"));
    if (!input || !hidden || !panel) return;

    const open = () => {
      panel.hidden = false;
    };

    const close = () => {
      panel.hidden = true;
    };

    const filter = () => {
      const query = input.value.trim().toLowerCase();
      options.forEach((option) => {
        const matches = !query || option.dataset.label.toLowerCase().includes(query);
        option.hidden = !matches;
      });
    };

    input.addEventListener("focus", () => {
      filter();
      open();
    });

    input.addEventListener("input", () => {
      hidden.value = "";
      filter();
      open();
    });

    input.addEventListener("blur", () => {
      setTimeout(close, 150);
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        close();
        input.blur();
      }
    });

    options.forEach((option) => {
      option.addEventListener("mousedown", (event) => {
        event.preventDefault();
        input.value = option.dataset.label;
        hidden.value = option.dataset.value;
        close();
      });
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initAdminSearch();
  initGrantComboboxes();
});
