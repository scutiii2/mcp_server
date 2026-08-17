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

activateTab((location.hash || '#chats').slice(1));

function addCell(row, content) {
  const cell = document.createElement('td');
  if (content instanceof Node) cell.appendChild(content);
  else cell.textContent = content;
  row.appendChild(cell);
  return cell;
}

function formatBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

// --- chat logs -----------------------------------------------------------

document.getElementById('chat-user-select').addEventListener('change', async (event) => {
  const username = event.target.value;
  document.getElementById('chat-trace-block').hidden = true;
  const listBlock = document.getElementById('user-chats-block');
  const body = document.getElementById('user-chats-body');
  body.innerHTML = '';
  if (!username) {
    listBlock.hidden = true;
    return;
  }
  listBlock.hidden = false;
  body.innerHTML = '<tr><td colspan="4" class="empty-row">Loading…</td></tr>';
  try {
    const res = await fetch(`/logs/api/chats/${encodeURIComponent(username)}`);
    const chats = await res.json();
    body.innerHTML = '';
    if (chats.length === 0) {
      body.innerHTML = '<tr><td colspan="4" class="empty-row">No chat logs for this user.</td></tr>';
      return;
    }
    for (const chat of chats) {
      const row = document.createElement('tr');
      addCell(row, chat.chat_id);
      addCell(row, new Date(chat.updated_at).toLocaleString());
      addCell(row, formatBytes(chat.size));
      const viewBtn = document.createElement('button');
      viewBtn.type = 'button';
      viewBtn.className = 'view-btn';
      viewBtn.textContent = 'View';
      viewBtn.addEventListener('click', () => showChatTrace(username, chat.chat_id));
      addCell(row, viewBtn);
      body.appendChild(row);
    }
  } catch (err) {
    body.innerHTML = `<tr><td colspan="4" class="empty-row">Could not load: ${err.message}</td></tr>`;
  }
});

function renderToolCall(call) {
  const el = document.createElement('div');
  el.className = 'trace-tool-call';
  el.textContent = `${call.name}(${JSON.stringify(call.arguments)}) → ${call.result}`;
  return el;
}

function renderTurn(turn) {
  const card = document.createElement('div');
  card.className = 'trace-turn';

  const meta = document.createElement('div');
  meta.className = 'trace-meta';
  const parts = [new Date(turn.timestamp).toLocaleString()];
  if (turn.provider_id) parts.push(turn.provider_id);
  if (turn.model) parts.push(turn.model);
  if (typeof turn.total_tokens === 'number') parts.push(`${turn.total_tokens} tokens`);
  if (typeof turn.elapsed_seconds === 'number') parts.push(`${turn.elapsed_seconds}s`);
  if (turn.recursive_rounds && turn.recursive_rounds.length > 0) {
    parts.push(`${turn.recursive_rounds.length} recursive round${turn.recursive_rounds.length === 1 ? '' : 's'}`);
  }
  meta.textContent = parts.join(' · ');
  card.appendChild(meta);

  const question = document.createElement('div');
  question.className = 'trace-question';
  question.textContent = turn.question;
  card.appendChild(question);

  if (turn.tool_calls && turn.tool_calls.length > 0) {
    const toolCalls = document.createElement('div');
    toolCalls.className = 'trace-tool-calls';
    for (const call of turn.tool_calls) {
      toolCalls.appendChild(renderToolCall(call));
    }
    card.appendChild(toolCalls);
  }

  const response = document.createElement('div');
  response.className = 'trace-response';
  response.textContent = turn.response;
  card.appendChild(response);

  // Each self-review round's own answer, in order - the initial answer
  // above is what "response" already is once every round has run (the
  // last round's text, or the last one before an earlier round matched
  // it verbatim and stopped the loop early - see
  // ollama_provider.py's run_chat). This shows how it got there.
  if (turn.recursive_rounds && turn.recursive_rounds.length > 0) {
    const rounds = document.createElement('div');
    rounds.className = 'trace-recursive-rounds';
    for (const round of turn.recursive_rounds) {
      rounds.appendChild(renderRecursiveRound(round));
    }
    card.appendChild(rounds);
  }

  return card;
}

function renderRecursiveRound(round) {
  const el = document.createElement('div');
  el.className = 'trace-recursive-round';
  const label = document.createElement('div');
  label.className = 'trace-recursive-round-label';
  label.textContent = `Round ${round.round}${round.converged ? ' (converged)' : ''}`;
  el.appendChild(label);
  const text = document.createElement('div');
  text.className = 'trace-recursive-round-text';
  text.textContent = round.response;
  el.appendChild(text);
  return el;
}

async function showChatTrace(username, chatId) {
  const block = document.getElementById('chat-trace-block');
  const view = document.getElementById('chat-trace-view');
  block.hidden = false;
  view.textContent = 'Loading…';
  try {
    const res = await fetch(`/logs/api/chats/${encodeURIComponent(username)}/${encodeURIComponent(chatId)}`);
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    const turns = await res.json();
    view.innerHTML = '';
    if (turns.length === 0) {
      view.textContent = 'This log is empty.';
      return;
    }
    for (const turn of turns) {
      view.appendChild(renderTurn(turn));
    }
  } catch (err) {
    view.textContent = `Could not load this trace: ${err.message}`;
  }
}

// --- error logs ------------------------------------------------------------

async function loadErrorLogs() {
  const body = document.getElementById('errors-body');
  try {
    const res = await fetch('/logs/api/errors');
    const entries = await res.json();
    body.innerHTML = '';
    if (entries.length === 0) {
      body.innerHTML = '<tr><td colspan="4" class="empty-row">No error logs.</td></tr>';
      return;
    }
    for (const entry of entries) {
      const row = document.createElement('tr');
      addCell(row, entry.reference);
      addCell(row, new Date(entry.created_at).toLocaleString());
      addCell(row, formatBytes(entry.size));
      const viewBtn = document.createElement('button');
      viewBtn.type = 'button';
      viewBtn.className = 'view-btn';
      viewBtn.textContent = 'View';
      viewBtn.addEventListener('click', () => showErrorLog(entry.reference));
      addCell(row, viewBtn);
      body.appendChild(row);
    }
  } catch (err) {
    body.innerHTML = `<tr><td colspan="4" class="empty-row">Could not load: ${err.message}</td></tr>`;
  }
}

async function showErrorLog(reference) {
  const block = document.getElementById('error-view-block');
  const view = document.getElementById('error-content-view');
  block.hidden = false;
  view.textContent = 'Loading…';
  try {
    const res = await fetch(`/logs/api/errors/${encodeURIComponent(reference)}`);
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    const data = await res.json();
    view.textContent = data.content;
  } catch (err) {
    view.textContent = `Could not load this error log: ${err.message}`;
  }
}

loadErrorLogs();
