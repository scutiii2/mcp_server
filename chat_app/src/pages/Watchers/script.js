function showError(message) {
  const el = document.getElementById('watchers-error');
  el.textContent = `Could not reach mcp_server: ${message}`;
  el.classList.remove('hidden');
}

function hideError() {
  const el = document.getElementById('watchers-error');
  el.textContent = '';
  el.classList.add('hidden');
}

const STATUS_LABELS = {
  running: 'Running',
  completed: 'Success',
  failed: 'Failed',
  timed_out: 'Failed',
};

// Chip filter value -> phases it covers ('failed' chip covers timed_out too).
const STATUS_CHIP_PHASES = {
  running: ['running'],
  completed: ['completed'],
  failed: ['failed', 'timed_out'],
};

let allWatchers = [];

function escapeHtml(text) {
  return String(text ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

function formatDuration(startIso, endIso) {
  const start = new Date(startIso);
  const end = new Date(endIso);
  let totalSeconds = Math.max(0, Math.round((end - start) / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  totalSeconds -= hours * 3600;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds - minutes * 60;
  const parts = [];
  if (hours) parts.push(`${hours}h`);
  if (hours || minutes) parts.push(`${minutes}m`);
  parts.push(`${seconds}s`);
  return parts.join(' ');
}

function activeChipValues(groupId) {
  const group = document.getElementById(groupId);
  return Array.from(group.querySelectorAll('.chip.active')).map((el) => el.dataset.capability || el.dataset.status);
}

function syncCapabilityChips(watchers) {
  const group = document.getElementById('watchers-filter-capability');
  const labels = Array.from(new Set(watchers.map((w) => w.capability))).sort();
  const known = new Set(Array.from(group.querySelectorAll('.chip')).map((el) => el.dataset.capability));

  // Only add chips for newly-seen capabilities - don't touch active state
  // on ones already rendered, so a running filter session isn't reset by
  // the 15s refresh.
  labels.forEach((label) => {
    if (known.has(label)) return;
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'chip active';
    chip.dataset.capability = label;
    chip.textContent = label;
    chip.addEventListener('click', () => {
      chip.classList.toggle('active');
      applyFilters();
    });
    group.appendChild(chip);
  });
}

function watcherKey(w) {
  return w.key || w.name || '';
}

function applyFilters() {
  const activeCapabilities = new Set(activeChipValues('watchers-filter-capability'));
  const activePhases = new Set(
    activeChipValues('watchers-filter-status').flatMap((status) => STATUS_CHIP_PHASES[status] || [])
  );
  const startFrom = document.getElementById('watchers-filter-start').value;
  const startUntil = document.getElementById('watchers-filter-end').value;
  const search = document.getElementById('watchers-filter-search').value.trim().toLowerCase();

  const filtered = allWatchers.filter((w) => {
    if (!activeCapabilities.has(w.capability)) return false;
    if (!activePhases.has(w.phase)) return false;
    if (startFrom && new Date(w.started_at) < new Date(startFrom)) return false;
    if (startUntil && new Date(w.started_at) > new Date(startUntil)) return false;
    if (search && !`${w.capability} ${watcherKey(w)}`.toLowerCase().includes(search)) return false;
    return true;
  });

  renderRows(filtered);
}

// Recipients are display-only here; they are set on the mcp_server side
// (tool_<alias>_setWatcherRecipients).
function recipientsCell(w) {
  const recipients = w.recipients || [];
  return recipients.map(escapeHtml).join('<br>') || '<span class="muted">none</span>';
}

function renderRows(watchers) {
  const tbody = document.getElementById('watchers-body');

  if (!watchers.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="notice">${tbody.dataset.emptyMessage}</td></tr>`;
    return;
  }

  tbody.innerHTML = watchers.map((w) => {
    const statusLabel = STATUS_LABELS[w.phase] || w.phase;
    const isRunning = w.phase === 'running';
    const started = w.started_at ? new Date(w.started_at).toLocaleString() : '';
    const finished = w.last_polled_at ? new Date(w.last_polled_at).toLocaleString() : '';
    const end = isRunning ? new Date() : w.last_polled_at;
    const duration = w.started_at && end ? formatDuration(w.started_at, end) : '';
    const finishedLine = isRunning ? '' : `<br><span class="muted">Finished at: ${finished}</span>`;
    const detail = w.detail && Object.keys(w.detail).length
      ? `<details class="watcher-detail"><summary>Detail</summary><pre>${escapeHtml(JSON.stringify(w.detail, null, 2))}</pre></details>` : '';

    return `<tr>
      <td>${escapeHtml(watcherKey(w))}<br><span class="muted">${escapeHtml(w.capability)}</span>${detail}</td>
      <td><span class="badge badge-${escapeHtml(w.phase)}">${escapeHtml(statusLabel)}</span></td>
      <td>${duration}<br><span class="muted">Started at: ${started}</span>${finishedLine}</td>
      <td>${recipientsCell(w)}</td>
    </tr>`;
  }).join('');
}

async function refreshWatchers() {
  try {
    const res = await fetch('/watchers/api/watchers');
    const data = await res.json();
    if (data.status === 'ok') {
      allWatchers = data.watchers;
      syncCapabilityChips(allWatchers);
      applyFilters();
      if (data.errors && data.errors.length) showError(data.errors.join('; '));
      else hideError();
    } else {
      showError(data.message);
    }
  } catch (err) {
    showError(`Request failed: ${err}`);
  }
}

function initFilters() {
  document.querySelectorAll('#watchers-filter-status .chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      chip.classList.toggle('active');
      applyFilters();
    });
  });
  ['watchers-filter-start', 'watchers-filter-end', 'watchers-filter-search'].forEach((id) => {
    document.getElementById(id).addEventListener('input', applyFilters);
  });
  document.getElementById('watchers-filter-clear').addEventListener('click', () => {
    document.querySelectorAll('#watchers-filter-capability .chip, #watchers-filter-status .chip')
      .forEach((chip) => chip.classList.add('active'));
    document.getElementById('watchers-filter-start').value = '';
    document.getElementById('watchers-filter-end').value = '';
    document.getElementById('watchers-filter-search').value = '';
    applyFilters();
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initFilters();
  refreshWatchers();
  setInterval(refreshWatchers, 15000);
});
