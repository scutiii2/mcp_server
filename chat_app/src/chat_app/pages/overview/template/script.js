// Builds a small "<code>...</code> [Copy]" chip - same shape as
// sidebar.js's buildCopyChip() and account/template/script.js's, each its
// own copy since there's no shared JS module system in this app (only
// shared markup/CSS, via sidebar.html/sidebar.css). Only the plaintext
// handed back at creation time can ever be copied this way - see
// auth/store.py's module docstring: nothing after that stores the code
// itself, only its hash.
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

const generateInviteButton = document.getElementById('generate-invite');
if (generateInviteButton) {
  generateInviteButton.addEventListener('click', async () => {
    const result = document.getElementById('invite-result');
    result.textContent = 'Generating…';
    try {
      const response = await fetch('/api/invites', { method: 'POST' });
      if (!response.ok) throw new Error(`Server returned ${response.status}`);
      const data = await response.json();
      result.textContent = '';
      result.append('Invite code: ', buildCopyChip(data.code), ' (one-time use)');
    } catch (err) {
      result.textContent = `Failed to generate a code: ${err.message}`;
    }
  });
}

// --- account chip dropdown ------------------------------------------------
const chipToggle = document.getElementById('user-chip-toggle');
const chipMenu = document.getElementById('user-chip-menu');
if (chipToggle && chipMenu) {
  const openMenu = () => {
    chipMenu.hidden = false;
    chipToggle.setAttribute('aria-expanded', 'true');
  };
  const closeMenu = () => {
    chipMenu.hidden = true;
    chipToggle.setAttribute('aria-expanded', 'false');
  };

  chipToggle.addEventListener('click', (event) => {
    event.stopPropagation();
    if (chipMenu.hidden) {
      openMenu();
    } else {
      closeMenu();
    }
  });

  document.addEventListener('click', (event) => {
    if (!chipMenu.hidden && !chipMenu.contains(event.target) && event.target !== chipToggle) {
      closeMenu();
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !chipMenu.hidden) {
      closeMenu();
      chipToggle.focus();
    }
  });
}
