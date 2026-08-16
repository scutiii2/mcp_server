// Builds a small "<code>...</code> [Copy]" chip - shared shape used
// wherever a just-generated invite code is shown (here, overview's
// script.js, and account's script.js each have their own copy since
// there's no shared JS module system in this app, only shared markup/CSS
// via sidebar.html/sidebar.css). Only the plaintext handed back at
// creation time can ever be copied this way - see auth/store.py's module
// docstring: nothing after that stores the code itself, only its hash.
function buildCopyChip(code) {
  const chip = document.createElement('span');
  chip.className = 'copy-chip';
  const codeEl = document.createElement('code');
  codeEl.textContent = code;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'copy-chip-btn';
  btn.textContent = 'Copy';
  btn.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(code);
      btn.textContent = 'Copied!';
    } catch (err) {
      btn.textContent = 'Copy failed';
    }
    setTimeout(() => { btn.textContent = 'Copy'; }, 1500);
  });
  chip.append(codeEl, btn);
  return chip;
}

(function () {
  // Collapse/expand: toggles a class on <body> rather than on the
  // sidebar itself, so every rule this needs (shrinking .app-sidebar,
  // resetting the page's own margin-left, moving the toggle handle) can
  // live in one place - see sidebar.css's top-of-file comment. Persisted
  // in localStorage so it survives navigating between pages, since this
  // is a multi-page app with a full reload on every link click, not an
  // SPA that could just keep the state in memory.
  const STORAGE_KEY = 'sidebar-collapsed';
  const toggle = document.getElementById('sidebar-toggle');
  if (!toggle) return;

  const apply = (collapsed) => {
    document.body.classList.toggle('sidebar-collapsed', collapsed);
    toggle.setAttribute('aria-expanded', String(!collapsed));
    toggle.setAttribute('aria-label', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
  };

  let collapsed = localStorage.getItem(STORAGE_KEY) === 'true';
  apply(collapsed);

  toggle.addEventListener('click', () => {
    collapsed = !collapsed;
    try {
      localStorage.setItem(STORAGE_KEY, String(collapsed));
    } catch (err) {
      // Storage disabled (private browsing, quota) - the toggle still
      // works for this page load, it just won't stick across navigation.
    }
    apply(collapsed);
  });
})();

(function () {
  const btn = document.getElementById('sidebar-generate-invite');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    const result = document.getElementById('sidebar-invite-result');
    result.textContent = 'Generating…';
    try {
      const response = await fetch('/api/invites', { method: 'POST' });
      if (!response.ok) throw new Error(`Server returned ${response.status}`);
      const data = await response.json();
      result.textContent = '';
      result.append('Code: ', buildCopyChip(data.code));
      // Only defined on the account manager page (account/script.js,
      // loaded before this file - see that page's index.html). Generating
      // a code from the sidebar while the Invitations tab is open should
      // update its list the same as generating one from the tab's own
      // form does, not leave it looking stale until a reload.
      if (typeof prependInviteRow === 'function') prependInviteRow(data);
    } catch (err) {
      result.textContent = `Failed: ${err.message}`;
    }
  });
})();

(function () {
  // Identity chip: click to reveal a small "Log out" popover. Toggle on
  // click, close on outside click or Escape, keep aria-expanded in sync.
  const toggle = document.getElementById('sidebar-user-toggle');
  const menu = document.getElementById('sidebar-user-menu');
  if (!toggle || !menu) return;

  const openMenu = () => {
    menu.hidden = false;
    toggle.setAttribute('aria-expanded', 'true');
  };
  const closeMenu = ({ focusToggle } = {}) => {
    if (menu.hidden) return;
    menu.hidden = true;
    toggle.setAttribute('aria-expanded', 'false');
    if (focusToggle) toggle.focus();
  };

  toggle.addEventListener('click', () => {
    if (menu.hidden) openMenu();
    else closeMenu();
  });

  document.addEventListener('click', (event) => {
    if (menu.hidden) return;
    if (event.target === toggle || toggle.contains(event.target) || menu.contains(event.target)) return;
    closeMenu();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !menu.hidden) closeMenu({ focusToggle: true });
  });
})();
