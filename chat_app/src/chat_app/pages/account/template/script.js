// Only the plaintext handed back at creation time can ever be copied this
// way - see auth/store.py's module docstring: nothing after that stores
// the code itself, only its hash. That's also why the "All invite codes"
// table only ever gets a working copy control on the row for a code
// generated in this page load (see prependInviteRow below) - every other
// row has nothing to copy from.

// "<code>...</code> [Copy]" - used in the generate-result banner, where
// showing the code itself is the point.
function buildCopyChip(code) {
  const chip = document.createElement('span');
  chip.className = 'copy-chip';
  const codeEl = document.createElement('code');
  codeEl.textContent = code;
  chip.append(codeEl, buildCopyButton(code));
  return chip;
}

// Just the button, no visible code text - used in the table row, which is
// already crowded with columns; the code itself is visible in the banner
// above at the moment it matters.
function buildCopyButton(code) {
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
  return btn;
}

function activateTab(name) {
  const target = document.getElementById(`tab-${name}`);
  if (!target) return;
  document.querySelectorAll('.tab-btn').forEach((btn) => {
    const active = btn.dataset.tab === name;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', String(active));
  });
  document.querySelectorAll('.tab-panel').forEach((panel) => panel.classList.toggle('active', panel === target));
}

document.querySelectorAll('.tab-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    activateTab(btn.dataset.tab);
    history.replaceState(null, '', `#${btn.dataset.tab}`);
  });
});

activateTab((location.hash || '#users').slice(1));

function showStatus(message, isError) {
  const banner = document.getElementById('status-banner');
  banner.textContent = message;
  banner.classList.remove('hidden');
  banner.classList.toggle('error', !!isError);
}

async function callApi(url, options) {
  const response = await fetch(url, options);
  let data = {};
  try { data = await response.json(); } catch (err) { /* no body */ }
  if (!response.ok) throw new Error(data.error || `Server returned ${response.status}`);
  return data;
}

document.getElementById('create-user-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target;
  const body = {
    username: form.username.value.trim(),
    password: form.password.value,
    role: form.role.value,
  };
  try {
    await callApi('/accounts/api/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    location.reload();
  } catch (err) {
    showStatus(`Failed to create user: ${err.message}`, true);
  }
});

document.getElementById('create-role-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target;
  const scopes = [...form.querySelectorAll('input[name="scopes"]:checked')].map((el) => el.value);
  try {
    await callApi('/accounts/api/roles', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: form.name.value.trim(), scopes }),
    });
    location.reload();
  } catch (err) {
    showStatus(`Failed to create role: ${err.message}`, true);
  }
});

function addCell(row, content) {
  const cell = document.createElement('td');
  if (content instanceof Node) cell.appendChild(content);
  else cell.textContent = content;
  row.appendChild(cell);
  return cell;
}

// Prepends a real row for a code just generated in this page load - the
// only moment its plaintext exists client-side. Server-rendered rows (and
// this same row, after a reload) can never show the code itself, only its
// hash is stored - see auth/store.py's module docstring.
function prependInviteRow(invite) {
  const body = document.getElementById('invites-body');
  body.querySelector('.empty-row')?.closest('tr')?.remove();

  const row = document.createElement('tr');
  row.dataset.codeId = invite.code_id;
  addCell(row, buildCopyButton(invite.code));
  addCell(row, invite.role);
  addCell(row, invite.created_by);
  addCell(row, invite.created_at);
  addCell(row, invite.expires_at || 'Never');
  const deleteBtn = document.createElement('button');
  deleteBtn.type = 'button';
  deleteBtn.className = 'delete-invite danger';
  deleteBtn.textContent = 'Delete';
  addCell(row, deleteBtn);

  body.insertBefore(row, body.firstChild);
}

document.getElementById('create-invite-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target;
  const result = document.getElementById('invite-result');
  result.textContent = 'Generating…';
  try {
    const data = await callApi('/accounts/api/invites', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role: form.role.value, ttl_hours: form.ttl_hours.value || null }),
    });
    result.textContent = '';
    result.append(`Invite code (${data.role}, expires: ${data.expires_at || 'never'}): `, buildCopyChip(data.code));
    prependInviteRow(data);
  } catch (err) {
    result.textContent = `Failed to generate a code: ${err.message}`;
  }
});

document.getElementById('users-body').addEventListener('click', async (event) => {
  if (!event.target.classList.contains('delete-user')) return;
  const row = event.target.closest('tr');
  const username = row.dataset.username;
  const confirmed = await confirmModal({
    title: 'Delete user?',
    message: `Delete user "${username}"? This can't be undone.`,
    confirmLabel: 'Delete',
    danger: true,
  });
  if (!confirmed) return;
  try {
    await callApi(`/accounts/api/users/${encodeURIComponent(username)}`, { method: 'DELETE' });
    location.reload();
  } catch (err) {
    showStatus(`Failed to delete user: ${err.message}`, true);
  }
});

document.getElementById('users-body').addEventListener('change', async (event) => {
  if (!event.target.classList.contains('role-select')) return;
  const row = event.target.closest('tr');
  const username = row.dataset.username;
  const role = event.target.value;
  try {
    await callApi(`/accounts/api/users/${encodeURIComponent(username)}/role`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role }),
    });
    showStatus(`${username} is now ${role}.`, false);
  } catch (err) {
    showStatus(`Failed to change role: ${err.message}`, true);
  }
});

document.getElementById('roles-body').addEventListener('click', async (event) => {
  if (!event.target.classList.contains('delete-role')) return;
  const row = event.target.closest('tr');
  const name = row.dataset.role;
  const confirmed = await confirmModal({
    title: 'Delete role?',
    message: `Delete role "${name}"?`,
    confirmLabel: 'Delete',
    danger: true,
  });
  if (!confirmed) return;
  try {
    await callApi(`/accounts/api/roles/${encodeURIComponent(name)}`, { method: 'DELETE' });
    location.reload();
  } catch (err) {
    showStatus(`Failed to delete role: ${err.message}`, true);
  }
});

document.getElementById('invites-body').addEventListener('click', async (event) => {
  if (!event.target.classList.contains('delete-invite')) return;
  const row = event.target.closest('tr');
  const codeId = row.dataset.codeId;
  const confirmed = await confirmModal({
    title: 'Delete invite code?',
    message: 'Anyone still holding it will no longer be able to use it.',
    confirmLabel: 'Delete',
    danger: true,
  });
  if (!confirmed) return;
  try {
    await callApi(`/accounts/api/invites/${encodeURIComponent(codeId)}`, { method: 'DELETE' });
    location.reload();
  } catch (err) {
    showStatus(`Failed to delete invite code: ${err.message}`, true);
  }
});
