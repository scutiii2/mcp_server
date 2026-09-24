const history = [];
let providersById = {};  // id -> full provider entry (incl. models), used to populate the model dropdown and look up model labels

// --- Chat-scoped jobs -----------------------------------------------------
// A browser may leave a conversation while its server-owned answer keeps
// running.  This map deliberately owns no worker: it only records which
// selected chat is subscribed to which background job.
const chatStates = new Map(); // id -> { history, activity, sequence, streamText, subscription }
let activeSubscription = null;
let manageChatsVisible = false;
let chatBeforeManaging = null;
let chatInitialized = false;
let chatLoading = false;
let chatViewGeneration = 0;
let newChatLaunch = null;

// --- Slash-command autocomplete ------------------------------------------
let capabilityLabels = {}; // capability id -> display label, from mcp_server via /chat/api/capability-labels
let commandsRegistry = {}; // capability -> { toolId: { description, params: [{name, required, type, has_default, default, examples}] } }
let currentSuggestions = []; // [{ stage: 'capability'|'tool'|'param', text, display, hint }]
let activeSuggestionIndex = -1;

// --- Extensions sidebar -----------------------------------------------
// Toggle state is convenience/UX state, not a security boundary - the
// real enforcement is server-side (chat_app filters enabled_extensions
// again before offering tools to the model), so localStorage is fine
// here even though it's fully user-editable.
const EXT_STORAGE_KEY = 'chat.enabledExtensions';
let extensionsById = {}; // id -> full extension entry from the last successful /api/extensions load
let enabledExtensions = loadEnabledExtensionsFromStorage();

function loadEnabledExtensionsFromStorage() {
  try {
    const raw = localStorage.getItem(EXT_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(parsed) ? parsed : []);
  } catch (err) {
    // Corrupt JSON or storage unavailable (private browsing) - the safe
    // default (nothing enabled) is exactly right here too.
    return new Set();
  }
}

function saveEnabledExtensionsToStorage() {
  try {
    localStorage.setItem(EXT_STORAGE_KEY, JSON.stringify([...enabledExtensions]));
  } catch (err) {
    // Quota exceeded / storage disabled - the toggle still works for
    // this page load, it just won't survive a reload. Not worth
    // surfacing to the user over.
  }
}

// --- File attachments -----------------------------------------------
// Staged client-side until the next send() - each entry tracks its own
// upload/extraction lifecycle independently, so one slow or failed file
// doesn't block the others. Never restored on reload and never part of
// `history` itself: only the finished question text (with extracted
// text folded in, see buildAttachmentBlocks()/send() below) is what
// actually gets sent and persisted - this array is purely "what's
// staged for the NEXT send".
let pendingAttachments = []; // { id, filename, status: 'uploading'|'ready'|'error', text, charCount, truncated, error }

function newAttachmentId() {
  return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function removeAttachment(id) {
  pendingAttachments = pendingAttachments.filter(a => a.id !== id);
  renderAttachChips();
}

function renderAttachChips() {
  const list = document.getElementById('attach-chip-list');
  list.innerHTML = '';
  list.classList.toggle('hidden', pendingAttachments.length === 0);
  pendingAttachments.forEach(att => {
    const chip = document.createElement('li');
    chip.className = 'attach-chip' + (att.status === 'error' ? ' is-error' : att.status === 'uploading' ? ' is-uploading' : '');

    const name = document.createElement('span');
    name.className = 'attach-chip-name';
    name.textContent = att.status === 'uploading' ? `Reading ${att.filename}…`
      : att.status === 'error' ? `${att.filename}: ${att.error}`
      : att.filename;
    chip.title = name.textContent;
    chip.appendChild(name);

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'attach-chip-remove';
    removeBtn.setAttribute('aria-label', `Remove ${att.filename}`);
    removeBtn.textContent = '×';
    removeBtn.addEventListener('click', () => removeAttachment(att.id));
    chip.appendChild(removeBtn);

    list.appendChild(chip);
  });
}

// Extraction happens server-side (chat_app/src/services/text_extraction.py)
// the moment a file is attached/dropped, not at send() time - so by the
// time the user hits Send, the text is already sitting on the chip ready
// to fold in, rather than making them wait through an upload right when
// they're trying to leave.
async function addAttachmentFiles(fileList) {
  for (const file of Array.from(fileList)) {
    const att = { id: newAttachmentId(), filename: file.name, status: 'uploading', text: '', charCount: 0, truncated: false, error: '' };
    pendingAttachments.push(att);
    renderAttachChips();

    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch('/chat/api/chat/attach', { method: 'POST', body: formData });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        att.status = 'error';
        att.error = data.error || `Server responded with ${res.status}`;
      } else {
        att.status = 'ready';
        att.text = data.text;
        att.charCount = data.char_count;
        att.truncated = data.truncated;
      }
    } catch (err) {
      att.status = 'error';
      att.error = err.message;
    }
    renderAttachChips();
  }
}

// A single delimited block per ready attachment, appended after the
// typed question - parseAttachmentMarkers() below (used by appendMsg())
// pulls these back out to render as a collapsible chip instead of a wall
// of raw file text, on both a fresh send and a reload of a saved chat
// (both go through the same stored `content` string - see loadChat()).
function buildAttachmentBlocks(attachments) {
  return attachments.map(a =>
    `[[ATTACHMENT filename="${a.filename.replace(/"/g, "'")}" chars="${a.charCount}" truncated="${a.truncated}"]]\n${a.text}\n[[/ATTACHMENT]]`
  );
}

const ATTACHMENT_BLOCK_RE = /\[\[ATTACHMENT filename="([^"]*)" chars="(\d+)" truncated="(true|false)"\]\]\n([\s\S]*?)\n\[\[\/ATTACHMENT\]\]/g;

function parseAttachmentMarkers(text) {
  const attachments = [];
  const mainText = text.replace(ATTACHMENT_BLOCK_RE, (match, filename, chars, truncated, body) => {
    attachments.push({ filename, chars: Number(chars), truncated: truncated === 'true', body });
    return '';
  }).trim();
  return { mainText, attachments };
}

function buildAttachmentDetails(att) {
  const details = document.createElement('details');
  details.className = 'msg-attachment';

  const summary = document.createElement('summary');
  summary.textContent = att.truncated
    ? `${att.filename} (${att.chars} chars, truncated)`
    : `${att.filename} (${att.chars} chars)`;
  details.appendChild(summary);

  const pre = document.createElement('pre');
  pre.textContent = att.body;
  details.appendChild(pre);

  if (att.truncated) {
    const note = document.createElement('p');
    note.className = 'msg-attachment-truncated-note';
    note.textContent = 'Content was truncated before being sent.';
    details.appendChild(note);
  }

  return details;
}

// --- Chat identity ------------------------------------------------------
// The URL's `id` query param is this page's chat identity; no id means a
// new, not-yet-saved chat. This replaces the old sessionStorage-based
// resume mechanism entirely: unlike sessionStorage, server-side
// persistence (via /api/chats) survives a closed tab/browser restart,
// and supports more than one conversation.
//
// NOTE: this file already has a top-level `const history = []` (the
// LLM-facing conversation array, declared at the very top of this
// file) - that shadows the browser's global `window.history` within
// this script's scope. Any URL-manipulation call below MUST go through
// `window.history.*` explicitly, never bare `history.*`, or it will
// silently call Array methods instead of the History API.
let currentChatId = new URLSearchParams(location.search).get('id');

// Set by loadChat() below, from the last assistant message that has both
// fields (an error turn has neither - see chat_api's assistant_entry
// construction) - read once, right after loadChat() resolves, by
// applyLastUsedModel() to restore this chat's dropdown selections.
let lastUsedProviderId = null;
let lastUsedModelId = null;

// Set only when the canned greeting is shown on a genuine fresh chat
// (see the bottom init block); cleared the moment the user actually
// sends something, so the transcript starts clean instead of carrying
// "Hi! I'm ready when you are." into what's about to become a real,
// persisted conversation.
let greetingEl = null;

// The sidebar's client-only placeholder for a brand-new chat that hasn't
// been confirmed by the server yet (see addOptimisticChatEntry). Never
// more than one at a time - a chat only lacks a real id for its own
// first message.
let optimisticChatEntry = null;

// loadChatHistory() is called from several unsynchronized places - a
// rename, a delete, Escape while renaming, and a chat response landing
// (send() below) - so more than one can be in flight at once (e.g.
// renaming one chat while another is still being answered). Without this,
// whichever fetch's response happened to arrive last would win the
// render, even if it reflected an OLDER snapshot than one that arrived
// earlier - a chat created or changed in between would render, then
// silently vanish when the slower, stale response landed and overwrote
// it. Each call claims the next ticket; a response only renders if no
// newer call has started since.
let chatHistoryRequestId = 0;

let chatHistorySelectionMode = false;
const selectedChatIds = new Set();

function updateChatHistoryBulkActions() {
  const selectBtn = document.getElementById('chat-history-select-btn');
  const actions = document.getElementById('chat-history-bulk-actions');
  const count = document.getElementById('chat-history-selection-count');
  const deleteBtn = document.getElementById('chat-history-delete-selected-btn');
  if (!selectBtn || !actions || !count || !deleteBtn) return;

  selectBtn.textContent = chatHistorySelectionMode ? 'Cancel' : 'Select';
  selectBtn.setAttribute('aria-pressed', String(chatHistorySelectionMode));
  actions.classList.toggle('hidden', !chatHistorySelectionMode);
  count.textContent = `${selectedChatIds.size} selected`;
  deleteBtn.disabled = selectedChatIds.size === 0;
}

const DOWNLOAD_MARKER_RE = /\[\[DOWNLOAD filename="([^"]*)" bytes="(\d+)" url="([^"]*)"(?: label="([^"]*)")?\]\]/g;

function parseDownloadMarkers(text) {
  const downloads = [];
  const mainText = text.replace(DOWNLOAD_MARKER_RE, (match, filename, bytes, url, label) => {
    downloads.push({ filename, bytes: Number(bytes), url, label });
    return '';
  }).trim();
  return { mainText, downloads };
}

// The streamed text is shown as it arrives, so a marker being typed out
// ("[[DOWNLOAD filename=...") would flash as raw text until it completes.
// Hide complete markers and any unfinished one at the tail; the finished
// reply turns them into download cards (renderReplyBody()).
function hideDownloadMarkers(text) {
  const complete = text.replace(DOWNLOAD_MARKER_RE, '');
  const open = complete.lastIndexOf('[[');
  if (open === -1) return complete;
  const tail = complete.slice(open);
  if (tail.includes(']]')) return complete;
  return '[[DOWNLOAD'.startsWith(tail) || tail.startsWith('[[DOWNLOAD')
    ? complete.slice(0, open).trimEnd()
    : complete;
}

function formatFileSize(bytes) {
  if (!bytes) return '';
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function buildDownloadAttachment(download) {
  const attachment = document.createElement('div');
  attachment.className = 'msg-download-attachment';
  const label = document.createElement('div');
  label.className = 'msg-label';
  label.textContent = download.label || 'DOWNLOAD';
  attachment.appendChild(label);
  const chip = document.createElement('a');
  chip.className = 'msg-log-chip';
  chip.href = download.url;
  chip.textContent = `⬇ Download ${download.filename}${download.bytes ? ` (${formatFileSize(download.bytes)})` : ''}`;
  chip.title = chip.textContent;
  attachment.appendChild(chip);
  return attachment;
}

// Renders an assistant reply into a bubble that already exists (the one the
// stream was typing into): Markdown for the text, and each [[DOWNLOAD ...]]
// marker as a download card right after it - the same result appendMsg()
// gives a reply loaded from history, so a download button appears the moment
// the reply finishes, not after a reload.
function renderReplyBody(wrap, text) {
  const { mainText, downloads } = parseDownloadMarkers(text);
  const content = ensureMsgContent(wrap);
  renderMarkdown(content, mainText);
  wrap.querySelectorAll(':scope > .msg-download-attachment').forEach(el => el.remove());
  let anchor = content;
  downloads.forEach(download => {
    const card = buildDownloadAttachment(download);
    anchor.after(card);
    anchor = card;
  });
}

function toggleChatHistorySelectionMode() {
  chatHistorySelectionMode = !chatHistorySelectionMode;
  if (!chatHistorySelectionMode) selectedChatIds.clear();
  loadChatHistory();
  updateChatHistoryBulkActions();
}

async function loadExtensions() {
  const banner = document.getElementById('ext-error-banner');
  try {
    const res = await fetch('/chat/api/extensions');
    const data = await res.json();
    const extensions = data.extensions || [];
    extensionsById = Object.fromEntries(extensions.map(e => [e.id, e]));

    if (data.error) {
      // chat_app responded fine, but it couldn't fully reach mcp_server -
      // same "couldn't reach" case /capabilities' browse() surfaces. The
      // banner already explains why the list is empty, so the list area
      // itself skips the separate "no extensions configured" message
      // below - showing both would read as contradictory.
      banner.textContent = `Couldn't reach extensions: ${data.error}`;
      banner.classList.remove('hidden');
      renderExtensions(extensions, { suppressEmptyMessage: true });
    } else {
      banner.classList.add('hidden');
      renderExtensions(extensions, { suppressEmptyMessage: false });
    }
  } catch (err) {
    // fetch() itself failed - chat_app unreachable, distinct from the
    // data.error case above where chat_app answered but mcp_server didn't.
    banner.textContent = `Couldn't load extensions: ${err.message}`;
    banner.classList.remove('hidden');
    extensionsById = {};
    renderExtensions([], { suppressEmptyMessage: true });
  }
  updateExtToggleButtonLabel();
}

// Matches chat_app's own _forward_extension_error() fallback text - it
// falls back to this whenever mcp_server's error body had no usable
// "error" message, i.e. nothing specific came through. A message in this
// shape means "something went wrong talking to mcp_server", not "here's
// what you did wrong" - that's a connectivity problem wearing a status
// code, not a validation error.
const GENERIC_EXTENSION_ERROR_RE = /^mcp_server returned \d+\.$/;

// Plain validation-style message: headline only, no "why might this
// happen" disclosure - the message already says exactly what's wrong.
function showExtAddError(message) {
  resetExtAddError();
  document.getElementById('ext-add-error-text').textContent = message;
  document.getElementById('ext-add-error').classList.remove('hidden');
}

// Connectivity-shaped failure (unreachable server, generic status-only
// message, or a 201 that registered the extension but couldn't connect
// to it): a friendly headline replaces the raw text, the raw text
// survives as a muted "Details" line, and a collapsed list of likely
// causes is offered instead of guessing which one applies.
function showExtAddConnectivityError(details) {
  resetExtAddError();
  document.getElementById('ext-add-error-text').textContent = 'Failed to connect to this MCP Server.';
  const detailsEl = document.getElementById('ext-add-error-details');
  detailsEl.textContent = `Details: ${details}`;
  detailsEl.classList.remove('hidden');
  document.getElementById('ext-add-error-help-toggle').classList.remove('hidden');
  document.getElementById('ext-add-error').classList.remove('hidden');
}

function resetExtAddError() {
  const helpToggle = document.getElementById('ext-add-error-help-toggle');
  document.getElementById('ext-add-error').classList.add('hidden');
  document.getElementById('ext-add-error-text').textContent = '';
  document.getElementById('ext-add-error-details').classList.add('hidden');
  helpToggle.classList.add('hidden');
  helpToggle.setAttribute('aria-expanded', 'false');
  helpToggle.textContent = 'Why might this happen?';
  document.getElementById('ext-add-error-help-list').classList.add('hidden');
}

async function submitAddExtension(event) {
  event.preventDefault();
  const labelInput = document.getElementById('ext-add-label');
  const urlInput = document.getElementById('ext-add-url');
  const addBtn = document.getElementById('ext-add-btn');

  const label = labelInput.value.trim();
  const url = urlInput.value.trim();
  if (!label || !url) {
    showExtAddError('Name and URL are required.');
    return;
  }

  resetExtAddError();
  addBtn.disabled = true;
  try {
    const res = await fetch('/chat/api/extensions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label, url }),
    });
    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      const specific = data.error;
      // No specific message, or one that collapsed to the generic
      // fallback, means mcp_server (or chat_app relaying it) had nothing
      // actionable to say - treat that as connectivity-shaped same as a
      // 502. A real validation message (400 from missing fields or a
      // malformed URL) is specific and stays verbatim.
      const isGenericFallback = !specific || GENERIC_EXTENSION_ERROR_RE.test(specific);
      if (res.status === 502 || isGenericFallback) {
        showExtAddConnectivityError(specific || `Server responded with ${res.status}.`);
      } else {
        showExtAddError(specific);
      }
      return;
    }

    // A 201 still isn't necessarily a clean success: mcp_server registers
    // the extension either way and only reports whether it could reach
    // it via status/error on the body (same shape GET /extensions uses
    // for an already-broken entry). The extension IS registered - it'll
    // show up, disabled and erroring, in the list below - so the form
    // still clears, but this must not read as an unqualified success.
    labelInput.value = '';
    urlInput.value = '';
    if (data.status === 'error') {
      showExtAddConnectivityError(data.error || 'Could not connect to the server.');
    }
    await loadExtensions(); // refresh immediately rather than waiting for the next 15s poll
  } catch (err) {
    // fetch() itself failed - chat_app couldn't be reached at all, the
    // most connectivity-shaped failure of all.
    showExtAddConnectivityError(err.message);
  } finally {
    addBtn.disabled = false;
  }
}

async function removeExtension(ext) {
  // Cheap guard against a misclick removing a configured extension.
  const confirmed = await confirmModal({
    title: 'Remove extension?',
    message: `Remove "${ext.label || ext.id}"?`,
    confirmLabel: 'Remove',
    danger: true,
  });
  if (!confirmed) return;

  const banner = document.getElementById('ext-error-banner');
  try {
    const res = await fetch(`/chat/api/extensions/${encodeURIComponent(ext.id)}`, { method: 'DELETE' });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `Server responded with ${res.status}`);
    }
    await loadExtensions();
  } catch (err) {
    banner.textContent = `Couldn't remove extension: ${err.message}`;
    banner.classList.remove('hidden');
  }
}

function renderExtensions(extensions, { suppressEmptyMessage = false } = {}) {
  const list = document.getElementById('ext-list');
  list.innerHTML = '';

  if (extensions.length === 0) {
    // Plainly say so rather than leaving an empty box with no
    // explanation - unless an error banner is already explaining it.
    if (!suppressEmptyMessage) {
      list.innerHTML = '<p class="ext-empty">No extensions configured.</p>';
    }
    return;
  }

  for (const ext of extensions) {
    list.appendChild(buildExtensionItem(ext));
  }
}

function buildExtensionItem(ext) {
  const item = document.createElement('div');
  item.className = 'ext-item';

  const top = document.createElement('div');
  top.className = 'ext-item-top';

  const labelWrap = document.createElement('div');
  labelWrap.className = 'ext-item-label';

  const dot = document.createElement('span');
  const connected = ext.status === 'connected';
  dot.className = `ext-status-dot ${connected ? 'connected' : 'error'}`;
  if (!connected && ext.error) {
    dot.title = ext.error; // hover shows the error, per spec
  }
  labelWrap.appendChild(dot);

  const labelText = document.createElement('span');
  labelText.textContent = ext.label || ext.id;
  labelWrap.appendChild(labelText);
  top.appendChild(labelWrap);

  const controls = document.createElement('div');
  controls.className = 'ext-item-controls';

  const removeBtn = document.createElement('button');
  removeBtn.type = 'button';
  removeBtn.className = 'ext-remove-btn';
  removeBtn.setAttribute('aria-label', `Remove ${ext.label || ext.id}`);
  removeBtn.textContent = '×';
  removeBtn.addEventListener('click', () => removeExtension(ext));
  controls.appendChild(removeBtn);

  const switchLabel = document.createElement('label');
  switchLabel.className = 'ext-switch';
  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  // Default OFF: only checked if a previous session already turned it
  // on and that survived into localStorage - never on for a fresh id.
  checkbox.checked = enabledExtensions.has(ext.id);
  checkbox.addEventListener('change', () => {
    if (checkbox.checked) {
      enabledExtensions.add(ext.id);
    } else {
      enabledExtensions.delete(ext.id);
    }
    saveEnabledExtensionsToStorage();
    updateExtToggleButtonLabel();
    loadCommands(); // which extension tools count as commands just changed
  });
  const slider = document.createElement('span');
  slider.className = 'ext-switch-slider';
  switchLabel.appendChild(checkbox);
  switchLabel.appendChild(slider);
  controls.appendChild(switchLabel);
  top.appendChild(controls);

  item.appendChild(top);

  if (ext.description) {
    const desc = document.createElement('p');
    desc.className = 'ext-item-desc';
    desc.textContent = ext.description;
    item.appendChild(desc);
  }

  // Error shown inline too, not just on hover - a dot's tooltip is easy
  // to miss and this is exactly the kind of thing a user needs to know
  // before deciding whether to switch it on.
  if (!connected && ext.error) {
    const errText = document.createElement('p');
    errText.className = 'ext-item-error';
    errText.textContent = ext.error;
    item.appendChild(errText);
  }

  return item;
}

function updateExtToggleButtonLabel() {
  const btn = document.getElementById('ext-toggle-btn');
  // Only count ids that still exist in the last-known catalog - a stale
  // localStorage entry for a since-removed extension shouldn't inflate
  // the count.
  const activeCount = [...enabledExtensions].filter(id => extensionsById[id]).length;
  btn.textContent = activeCount > 0 ? `Extensions (${activeCount})` : 'Extensions';
  btn.classList.toggle('has-enabled', activeCount > 0);
}

function currentEnabledExtensions() {
  // Same "still exists" filter as above - only forward ids send() can
  // actually vouch for as real, currently-known extensions.
  return [...enabledExtensions].filter(id => extensionsById[id]);
}

// Labels come from mcp_server (each capability's own registered label), so a
// new capability needs no change here. Loaded once; loadCommands() retries
// while it is still empty (mcp_server unreachable at page load).
async function loadCapabilityLabels() {
  try {
    const res = await fetch('/chat/api/capability-labels');
    if (res.ok) capabilityLabels = await res.json();
  } catch (err) {
    // Suggestions fall back to the uppercased id - harmless.
  }
  refreshWelcome();
}

function capabilityLabel(id) {
  return capabilityLabels[id] || id.toUpperCase();
}

async function loadCommands() {
  if (!Object.keys(capabilityLabels).length) loadCapabilityLabels();
  try {
    const params = new URLSearchParams({ enabled_extensions: currentEnabledExtensions().join(',') });
    const res = await fetch(`/chat/api/commands?${params}`);
    commandsRegistry = await res.json();
    refreshWelcome();
  } catch (err) {
    // Suggestions are a convenience, not required to send a command by
    // hand - a failed fetch just means no autocomplete this cycle.
    commandsRegistry = {};
  }
}

// "help" always sorts first within a capability's command list - it's
// the one entry every capability has (see commands.py's _help_command())
// and the most useful default to land on, since renderCommandSuggestions()
// below always highlights whichever suggestion ends up at index 0.
function sortHelpFirst(a, b) {
  if (a === 'help') return b === 'help' ? 0 : -1;
  if (b === 'help') return 1;
  return a.localeCompare(b);
}

// Top-level-only ordering (bare "/..." with no capability yet): same
// help-first rule as sortHelpFirst, plus "clear"/"summarize" always sort
// dead last. Both are chat-housekeeping commands (see clearChat()/
// summarizeChat()), not real capabilities/commands backed by
// commands.py, so they don't belong mixed in alphabetically with actual
// commands - parking them at the end keeps the useful stuff up top
// where index-0 highlighting lands.
const _RESERVED_LAST = new Set(['clear', 'summarize']);
function sortTopLevelCommands(a, b) {
  const aReserved = _RESERVED_LAST.has(a);
  const bReserved = _RESERVED_LAST.has(b);
  if (aReserved || bReserved) {
    if (aReserved && bReserved) return a.localeCompare(b);
    return aReserved ? 1 : -1;
  }
  return sortHelpFirst(a, b);
}

function computeCommandSuggestions(value) {
  if (!value.startsWith('/')) return [];
  const body = value.slice(1);
  const spaceIndex1 = body.indexOf(' ');

  if (spaceIndex1 === -1) {
    const partial = body;
    // "help" (bare, no capability) is a reserved top-level command (see
    // commands.py's module docstring on execute_command()'s bare-"/help"
    // check) - it has no entry of its own in commandsRegistry the way a
    // real capability does, so it's added here rather than coming from
    // Object.keys(commandsRegistry). acceptSuggestion() below completes
    // it without a trailing space, since there's no second word to type.
    // "clear" is the same shape (bare, reserved, no registry entry) but
    // handled entirely client-side via its own route calls - see
    // clearChat() and send()'s check at the top - so it never reaches
    // commands.py at all.
    return Array.from(new Set([...Object.keys(commandsRegistry), 'help', 'clear', 'summarize']))
      .filter(cap => cap.startsWith(partial))
      .sort(sortTopLevelCommands)
      .map(cap => ({
        stage: 'capability',
        text: cap,
        display: `/${cap}`,
        hint: cap === 'help'
          ? 'Show every capability and its available commands.'
          : cap === 'clear'
            ? 'Compress this chat for good (or, if the AI is unavailable, keep only the raw log) - shrinks what gets resent to the LLM.'
            : cap === 'summarize'
              ? 'Compress this chat\'s history into one summary, to shrink what gets resent to the LLM.'
              : capabilityLabel(cap),
      }));
  }

  const capability = body.slice(0, spaceIndex1);
  const tools = commandsRegistry[capability];
  if (!tools) return [];
  const afterCapability = body.slice(spaceIndex1 + 1);
  const spaceIndex2 = afterCapability.indexOf(' ');

  if (spaceIndex2 === -1) {
    const partial = afterCapability;
    return Object.keys(tools)
      .filter(t => t.startsWith(partial))
      .sort(sortHelpFirst)
      .map(t => ({ stage: 'tool', text: t, display: t, hint: tools[t].description }));
  }

  const toolId = afterCapability.slice(0, spaceIndex2);
  const tool = tools[toolId];
  if (!tool) return [];
  const paramsText = afterCapability.slice(spaceIndex2 + 1);
  const endsWithSpace = paramsText.endsWith(' ') || paramsText.length === 0;
  const tokens = paramsText.trim().length ? paramsText.trim().split(/\s+/) : [];
  const typedNames = new Set(tokens.map(t => t.split('=')[0]).filter(Boolean));
  const currentToken = !endsWithSpace && tokens.length ? tokens[tokens.length - 1] : '';
  if (currentToken.includes('=')) {
    // Typing a value for a specific param - e.g. "system_label=s4" while
    // completing "system_label=". Suggest from that param's JSON-schema
    // `examples` (if it has any), filtered by what's typed so far. These
    // are hints, not a closed set - nothing stops typing a value that
    // isn't listed, same as `examples` never constrains what a tool
    // accepts.
    const eqIndex = currentToken.indexOf('=');
    const paramName = currentToken.slice(0, eqIndex);
    const partialValue = currentToken.slice(eqIndex + 1);
    const param = tool.params.find(p => p.name === paramName);
    if (!param || !param.examples || !param.examples.length) return [];
    return param.examples
      .filter(v => String(v).startsWith(partialValue))
      .map(v => ({ stage: 'value', text: `${paramName}=${v}`, display: v, hint: '' }));
  }

  return tool.params
    .filter(p => !typedNames.has(p.name) && p.name.startsWith(currentToken))
    .sort((a, b) => Number(b.required) - Number(a.required) || a.name.localeCompare(b.name))
    .map(p => ({ stage: 'param', text: `${p.name}=`, display: `${p.name}=`, hint: paramHint(p) }));
}

// 'required', or 'optional' with the schema's default value spelled out
// so a person doesn't have to go check the tool's docstring for what
// omitting a param actually does.
function paramHint(param) {
  if (param.required) return 'required';
  if (!param.has_default) return 'optional';
  return `optional, default: ${formatDefaultValue(param.default)}`;
}

function formatDefaultValue(value) {
  if (value === null || value === undefined) return 'none';
  if (typeof value === 'string') return value === '' ? '""' : value;
  return JSON.stringify(value);
}

function renderCommandSuggestions(suggestions) {
  currentSuggestions = suggestions;
  activeSuggestionIndex = suggestions.length ? 0 : -1;
  const list = document.getElementById('cmd-suggestions');
  list.innerHTML = '';
  suggestions.forEach((item, index) => {
    const li = document.createElement('li');
    li.className = `cmd-suggestion${index === 0 ? ' active' : ''}`;
    const label = document.createElement('span');
    label.textContent = item.display;
    li.appendChild(label);
    if (item.hint) {
      const hint = document.createElement('span');
      hint.className = 'cmd-suggestion-desc';
      hint.textContent = item.hint;
      li.appendChild(hint);
    }
    li.addEventListener('mousedown', e => {
      e.preventDefault(); // keep focus on #q instead of blurring to the <li>
      acceptSuggestion(item);
    });
    list.appendChild(li);
  });
  list.classList.toggle('hidden', suggestions.length === 0);
}

function hideCommandSuggestions() {
  currentSuggestions = [];
  activeSuggestionIndex = -1;
  document.getElementById('cmd-suggestions').classList.add('hidden');
}

function updateCommandSuggestions() {
  renderCommandSuggestions(computeCommandSuggestions(document.getElementById('q').value));
}

// #q is a <textarea> (not <input>) specifically so Shift+Enter can insert
// a real newline - this grows it to fit what's typed, up to the CSS
// max-height (styles.css), beyond which it scrolls internally instead of
// pushing the rest of the page around. Resetting height to 'auto' first
// is required, not cosmetic: shrinking after deleting a line only works
// if scrollHeight is measured against a collapsed box, otherwise it never
// reports less than the tallest height the textarea already reached.
function autoResizeInput(el) {
  el.style.height = 'auto';
  el.style.height = `${el.scrollHeight}px`;
}

function moveSuggestionActive(delta) {
  if (!currentSuggestions.length) return;
  activeSuggestionIndex = (activeSuggestionIndex + delta + currentSuggestions.length) % currentSuggestions.length;
  const items = [...document.getElementById('cmd-suggestions').children];
  items.forEach((li, index) => {
    li.classList.toggle('active', index === activeSuggestionIndex);
  });
  // The list scrolls internally (max-height + overflow-y: auto - see
  // styles.css) - without this, arrowing past the visible rows moves
  // the highlight off-screen instead of following it into view.
  // block: 'nearest' only scrolls when the row isn't already fully
  // visible, so it does the right thing moving in either direction.
  items[activeSuggestionIndex]?.scrollIntoView({ block: 'nearest' });
}

function acceptSuggestion(item) {
  const input = document.getElementById('q');
  const value = input.value;
  const body = value.slice(1);
  const spaceIndex1 = body.indexOf(' ');

  let newValue;
  if (item.stage === 'capability') {
    // Every real capability has a commandsRegistry[capability] entry to
    // pick a tool from next, so a trailing space walks straight into
    // that second stage. "help"/"clear" (see computeCommandSuggestions
    // above) have none - they're complete commands by themselves - but
    // still get a trailing space: without it, the completed text still
    // matches itself as a suggestion (computeCommandSuggestions sees no
    // space yet and re-offers "help"/"clear"), so Enter would just
    // re-accept the same suggestion instead of sending. The trailing
    // space makes computeCommandSuggestions look up a (nonexistent)
    // registry entry and come back empty, clearing the dropdown so the
    // next Enter sends normally.
    newValue = `/${item.text} `;
  } else if (item.stage === 'tool') {
    const capability = body.slice(0, spaceIndex1);
    const tool = commandsRegistry[capability]?.[item.text];
    if (tool) {
      // Fill params via a modal form instead of continuing free-text
      // entry - see command_form_modal.js. hideCommandSuggestions() closes
      // the dropdown immediately so it isn't still showing underneath the
      // modal; #q is left untouched until (if) the modal resolves.
      hideCommandSuggestions();
      openCommandFormModal({ capability, toolId: item.text, tool }).then(commandString => {
        if (commandString == null) {
          // cancelled - clear the partial "/capability tool" text left in
          // the box rather than leaving it stranded there.
          input.value = '';
          autoResizeInput(input);
          return;
        }
        input.value = commandString;
        autoResizeInput(input);
        send();
      });
      return;
    }
    // commandsRegistry hasn't loaded this tool yet (e.g. the 15s poll
    // hasn't run) - fall back to the old free-text completion rather than
    // silently doing nothing.
    newValue = `/${capability} ${item.text} `;
  } else {
    const capability = body.slice(0, spaceIndex1);
    const afterCapability = body.slice(spaceIndex1 + 1);
    const spaceIndex2 = afterCapability.indexOf(' ');
    const toolId = afterCapability.slice(0, spaceIndex2);
    const paramsText = afterCapability.slice(spaceIndex2 + 1);
    const endsWithSpace = paramsText.endsWith(' ') || paramsText.length === 0;
    const tokens = paramsText.trim().length ? paramsText.trim().split(/\s+/) : [];
    if (!endsWithSpace && tokens.length) {
      tokens[tokens.length - 1] = item.text;
    } else {
      tokens.push(item.text);
    }
    newValue = `/${capability} ${toolId} ${tokens.join(' ')}`;
    // A 'value' suggestion completes the token ("name=value"), so move
    // on with a trailing space, same as accepting a 'tool'/'capability'
    // suggestion does. A 'param' suggestion ("name=") stays without one -
    // typing the value continues right where the cursor is.
    if (item.stage === 'value') newValue += ' ';
  }

  input.value = newValue;
  updateCommandSuggestions();
  autoResizeInput(input);
  input.focus();
}

// --- Chat-history panel collapse -----------------------------------------
// Persisted per-browser (not per-chat) via localStorage, same approach as
// enabledExtensions above - collapsing is a display preference, not state
// that needs to survive server-side or sync across devices.
const CHAT_HISTORY_COLLAPSED_KEY = 'chat.historyPanelCollapsed';

function applyChatHistoryPanelCollapsed(collapsed) {
  const panel = document.getElementById('chat-history-panel');
  const toggle = document.getElementById('chat-history-toggle-btn');
  panel.classList.toggle('collapsed', collapsed);
  toggle.setAttribute('aria-expanded', String(!collapsed));
  // The icon itself (a left-pointing double chevron) doesn't change markup -
  // styles.css just mirrors it via `.collapsed .chat-history-toggle-btn svg`
  // so it points the direction the panel will move on the next click.
  const toggleLabel = collapsed ? 'Expand chat list' : 'Collapse chat list';
  toggle.setAttribute('aria-label', toggleLabel);
  toggle.title = toggleLabel;
}

function toggleChatHistoryPanel() {
  const collapsed = document.getElementById('chat-history-panel').classList.contains('collapsed');
  applyChatHistoryPanelCollapsed(!collapsed);
  try {
    localStorage.setItem(CHAT_HISTORY_COLLAPSED_KEY, collapsed ? '0' : '1');
  } catch (err) {
    // Storage unavailable (private browsing) - the toggle still works for
    // this page load, it just won't be remembered next time.
  }
}

function openExtPanel() {
  document.getElementById('ext-panel').classList.add('open');
  document.getElementById('ext-panel').setAttribute('aria-hidden', 'false');
  document.getElementById('ext-overlay').classList.remove('hidden');
  document.getElementById('ext-toggle-btn').setAttribute('aria-expanded', 'true');
}

function closeExtPanel() {
  document.getElementById('ext-panel').classList.remove('open');
  document.getElementById('ext-panel').setAttribute('aria-hidden', 'true');
  document.getElementById('ext-overlay').classList.add('hidden');
  document.getElementById('ext-toggle-btn').setAttribute('aria-expanded', 'false');
}

function toggleExtPanel() {
  if (document.getElementById('ext-panel').classList.contains('open')) {
    closeExtPanel();
  } else {
    openExtPanel();
  }
}

// Cached across same-tab navigations (sessionStorage, not localStorage -
// this is a snapshot of a live server-side poll, not a durable
// preference, and it shouldn't follow the user to a different tab/device
// where it might already be stale). Switching chats, starting a new chat,
// and deleting the current chat all do a real `location.href`/`<a href>`
// navigation (see buildChatHistoryItem, deleteChatEntry, and the sidebar's
// "+ New chat" link) rather than client-side routing, so without this the
// entire page - including this list - reloaded from scratch every single
// time. Hydrating from cache below lets the dropdown render instantly
// with last-known-good data instead of showing "Loading providers..."
// again on every navigation; loadProviders() still runs right after to
// refresh it against the live server.
const PROVIDERS_CACHE_KEY = 'chat.providersCache';

function loadProvidersFromCache() {
  try {
    const raw = sessionStorage.getItem(PROVIDERS_CACHE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    return Array.isArray(parsed) && parsed.length ? parsed : null;
  } catch (err) {
    return null; // corrupt JSON / storage unavailable - just skip the cache
  }
}

function saveProvidersToCache(providers) {
  try {
    sessionStorage.setItem(PROVIDERS_CACHE_KEY, JSON.stringify(providers));
  } catch (err) {
    // Quota exceeded / storage disabled - loadProviders() still works for
    // this page load, it just won't have a cache to hydrate from next time.
  }
}

// Builds the dropdown's <option> list from a providers array - shared by
// loadProviders() below and by the cache-hydration at the bottom of this
// file, so a cached render and a live one look identical.
function renderProviderOptions(providers, previousProvider) {
  const providerSelect = document.getElementById('provider');
  providerSelect.innerHTML = '';
  for (const p of providers) {
    const opt = document.createElement('option');
    opt.value = p.id;
    // The dropdown now lists ai_agent instances, not LLM providers -
    // each is pinned to exactly one model (reported in p.model), so
    // there's no "no models configured" case to special-case here the
    // way a per-request-selectable provider used to have.
    if (p.available) {
      opt.textContent = p.model ? `${p.label} - ${p.model}` : p.label;
    } else if (p.reason === 'rate_limited') {
      opt.textContent = `${p.label} (rate-limited, ~${p.cooldown_seconds_remaining}s)`;
    } else if (p.reason === 'unreachable') {
      opt.textContent = `${p.label} (unreachable)`;
    } else if (p.reason === 'missing_key') {
      opt.textContent = `${p.label} (no API key)`;
    } else {
      // Unrecognized reason - surface it raw rather than guessing (and
      // previously, silently mislabeling anything unrecognized as a
      // missing API key - including Ollama, which has no API key
      // concept at all and reports "unreachable" instead) - same idea
      // as describeModelReason()'s fallback below.
      opt.textContent = `${p.label} (${p.reason || 'unavailable'})`;
    }
    opt.disabled = !p.available;
    providerSelect.appendChild(opt);
  }
  // keep whatever the user had selected, if it's still a valid option;
  // only fall back to "first available" on first load or if their pick
  // disappeared entirely (e.g. that agent was removed from
  // config_agents.json).
  const stillExists = providers.some(p => p.id === previousProvider);
  if (stillExists) {
    providerSelect.value = previousProvider;
  } else {
    const firstAvailable = providers.find(p => p.available);
    if (firstAvailable) providerSelect.value = firstAvailable.id;
  }
  updateModelDropdown();
}

async function loadProviders(refresh = false) {
  const providerSelect = document.getElementById('provider');
  const previousProvider = providerSelect.value; // preserve the user's choice across refreshes
  try {
    const res = await fetch(refresh ? '/chat/api/providers?refresh=1' : '/chat/api/providers');
    if (!res.ok) throw new Error(`Server responded with ${res.status}`);
    const providers = await res.json();
    providersById = Object.fromEntries(providers.map(p => [p.id, p]));
    saveProvidersToCache(providers);
    providerSelect.disabled = false; // clears any staleness flag a prior failed poll left (see catch below)
    renderProviderOptions(providers, previousProvider);
    // Keeps the ring's fallback window current against this poll's fresh
    // context_window - a no-op whenever a real per-turn reading is active
    // (refreshContextUsage prefers that over the fallback).
    refreshContextUsage();
  } catch (err) {
    // A poll can fail well after providers loaded fine once (server
    // restart, network blip) - if we already have a working list up
    // (rendered live or hydrated from cache), leave it exactly as-is and
    // just grey it out to flag it as stale, rather than nuking it down to
    // a single "Could not load providers" option. The setInterval below
    // keeps polling every 15s and silently un-disables it the moment a
    // request succeeds again - no separate "reconnecting" backoff needed.
    if (providerSelect.options.length > 0) {
      providerSelect.disabled = true;
    } else {
      providerSelect.innerHTML = '<option>Could not load providers</option>';
    }
  }
}

function updateModelDropdown() {
  const providerSelect = document.getElementById('provider');
  const modelSelect = document.getElementById('model');
  const provider = providersById[providerSelect.value];

  // Every agent is hard-pinned to one model (see ai_agent/src/
  // agent_config.py) - there's never a models list to pick from, so the
  // model picker stays hidden entirely rather than show one that
  // silently does nothing.
  if (!provider || !provider.models || provider.models.length === 0) {
    modelSelect.classList.add('hidden');
    modelSelect.innerHTML = '';
    return;
  }

  modelSelect.classList.remove('hidden');
  const previousModel = modelSelect.value;
  modelSelect.innerHTML = '';
  for (const m of provider.models) {
    const opt = document.createElement('option');
    opt.value = m.id;
    // Same idea as the provider dropdown above: an unavailable entry stays
    // in the list (disabled) with the reason folded into its visible text,
    // rather than just vanishing or relying on a hover tooltip that native
    // <option> elements don't reliably support.
    opt.textContent = m.available ? m.label : `${m.label} — ${describeModelReason(m.reason)}`;
    opt.disabled = !m.available;
    modelSelect.appendChild(opt);
  }
  // Preserve the user's pick by id same as the provider select does, even
  // if it just went unavailable - the option text above already carries
  // the reason, so keeping the selection here doesn't silently look fine,
  // it shows exactly why. Only fall back to the default when the id is
  // gone from the list entirely.
  const stillExists = provider.models.some(m => m.id === previousModel);
  modelSelect.value = stillExists ? previousModel : provider.default_model_id;
}

function describeModelReason(reason) {
  if (reason === 'not_pulled') return 'not pulled';
  if (reason === 'unreachable') return 'Ollama unreachable';
  // Unrecognized reason - surface it raw rather than dropping it silently,
  // so a future reason this code doesn't know about yet still shows up as
  // SOMETHING visible instead of nothing.
  return reason || 'unavailable';
}

// A pool rather than one fixed string - purely to keep the wait from
// feeling like it's stuck (same text, unmoving) versus genuinely
// informative.
const THINKING_MESSAGES = [
  'Thinking...',
  'Working on it...',
  'Reasoning through the request...',
  'Checking in with the tools...',
  'Putting it together...',
  'Almost there...',
];

// Swapped in past the 15s mark (see send()) - keeps rotating too, rather
// than freezing on one sentence while the elapsed timer next to it keeps
// ticking, which read as stuck even though the request wasn't.
const LONG_WAIT_MESSAGES = [
  'Still working - this can take longer with local models or multi-step tool calls...',
  'Still going - a long tool call or a slow model can take a minute or more...',
  'No response yet, but the request is still active...',
];

function pickMessage(pool, exclude) {
  const options = pool.filter(m => m !== exclude);
  return options[Math.floor(Math.random() * options.length)];
}

// Same idea as THINKING_MESSAGES above - a pool rather than one fixed
// string, so the "hi" you get on reload doesn't feel like a canned splash
// screen every single time.
const GREETING_MESSAGES = [
  'Hello! How can I help you today?',
  'Hi there! What can I do for you?',
  "Hey! What's on your mind?",
  'Welcome back! What would you like to know?',
  'Hello! Ask me anything to get started.',
  "Hi! I'm ready when you are.",
  'Hey there! What are we working on today?',
];

// New-chat welcome: centered card, not a chat message. Capabilities come
// from the live command registry, so it is refreshed when that loads.
function buildWelcome(greeting) {
  const el = document.createElement('div');
  el.className = 'chat-welcome';
  const logoUrl = document.getElementById('log').dataset.logo;
  if (logoUrl) {
    const img = document.createElement('img');
    img.className = 'chat-welcome-logo'; img.src = logoUrl; img.alt = '';
    el.appendChild(img);
  }
  const title = document.createElement('h2'); title.className = 'chat-welcome-title'; title.textContent = greeting;
  const tip = document.createElement('p'); tip.className = 'chat-welcome-tip';
  tip.textContent = 'Type / to run a command, or just ask a question.';
  const caps = document.createElement('p'); caps.className = 'chat-welcome-caps';
  el.append(title, tip, caps);
  fillWelcomeCapabilities(el);
  return el;
}

function fillWelcomeCapabilities(el) {
  const caps = el.querySelector('.chat-welcome-caps');
  const ids = Object.keys(commandsRegistry);
  caps.hidden = !ids.length;
  caps.textContent = ids.length
    ? 'I can help you with: ' + ids.map(id => `${capabilityLabel(id)} (/${id})`).join(', ')
    : '';
}

function refreshWelcome() {
  if (greetingEl && greetingEl.classList.contains('chat-welcome')) fillWelcomeCapabilities(greetingEl);
}

function pickGreetingMessage() {
  return GREETING_MESSAGES[Math.floor(Math.random() * GREETING_MESSAGES.length)];
}

// Compact, e.g. "2.4s" under a minute, "1m 03s" past it - one decimal
// place is plenty of precision for something the user is just glancing
// at while waiting.
function formatElapsedTime(ms) {
  const totalSeconds = ms / 1000;
  if (totalSeconds < 60) {
    return `${totalSeconds.toFixed(1)}s`;
  }
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.floor(totalSeconds % 60);
  return `${minutes}m ${String(seconds).padStart(2, '0')}s`;
}

// total_tokens/modelLabel/recursiveRounds are all defensive by design:
// some providers/paths never report usage (undefined/null/non-positive
// all just mean "don't show a token count"), an error turn (no real run
// happened) has no model to show either - see chat_api's assistant_entry
// construction, which omits provider_id/model/total_tokens entirely in
// that case rather than sending empty-string/null noise - and only
// ollama's recursive_chain models ever produce a nonzero round count.
function formatTimerText(ms, totalTokens, modelLabel, recursiveRounds) {
  const parts = [formatElapsedTime(ms)];
  if (typeof totalTokens === 'number' && totalTokens > 0) {
    parts.push(`${totalTokens} tokens`);
  }
  if (modelLabel) {
    parts.push(modelLabel);
  }
  if (typeof recursiveRounds === 'number' && recursiveRounds > 0) {
    parts.push(`${recursiveRounds} recursive round${recursiveRounds === 1 ? '' : 's'}`);
  }
  return parts.join(' · ');
}

// A command-kind reply is a
// direct MCP tool call - no LLM ever touches it, so unlike an ordinary
// assistant turn (always AI, formatTimerText above covers it) it shows
// no token count.
function formatCommandTimerText(ms, aiUsed, totalTokens, modelLabel) {
  const parts = [formatElapsedTime(ms)];
  if (aiUsed) {
    parts.push(`AI used${modelLabel ? ` (${modelLabel})` : ''}`);
    if (typeof totalTokens === 'number' && totalTokens > 0) {
      parts.push(`${totalTokens} tokens`);
    }
  } else {
    parts.push('No AI used (direct tool call)');
  }
  return parts.join(' · ');
}

// Single threshold driving the usage bar's amber/red coloring here in
// phase 1 - the same constant a later auto-summarize trigger and /clear
// warning would read, so all three stay in lockstep rather than three
// independently-tuned numbers drifting apart.
const CONTEXT_USAGE_THRESHOLD_RATIO = 0.6;

// Renders the "context used / limit" bar in .toprow from the last turn's
// context_tokens/context_window (see chat_api's assistant_entry / a
// loaded chat's stored message) - purely a readout, changes nothing
// about what's actually sent to the LLM. Hidden whenever either number
// is missing (e.g. a command turn, or an error turn with no real run).
// contextTokens may be null/undefined (no turn has reported usage yet for
// the selected provider - e.g. OpenRouter's free tier often omits `usage`
// entirely, see openai_provider.py's context_tokens fallback) while
// contextWindow is still known (agent_config.status()'s context_window,
// same value the dropdown's provider entry carries) - in that case the
// ring still renders, unfilled/grey, rather than disappearing, so the
// dropdown always has a same-row counterpart. Only hides when the window
// itself is unknown (no provider selected/reachable yet).
// Per-agent input/output/total tokens for this chat, summed from each
// assistant turn's saved provider_id/model and usage. Turns a provider never
// reported usage for (or command turns without AI) add nothing.
function renderAgentTokenBreakdown() {
  const totals = new Map();
  for (const turn of history) {
    if (turn.role !== 'assistant' || !turn.provider_id) continue;
    // agent_usage lists this turn's own agent plus every delegated one;
    // turns saved before it existed fall back to their own single reading.
    const entries = Array.isArray(turn.agent_usage) && turn.agent_usage.length
      ? turn.agent_usage : [turn];
    for (const entry of entries) {
      if (!entry.provider_id) continue;
      const label = modelLabel(entry.provider_id, entry.model);
      const row = totals.get(label) || { input: 0, output: 0, total: 0 };
      row.input += entry.input_tokens || 0;
      row.output += entry.output_tokens || 0;
      row.total += entry.total_tokens || 0;
      totals.set(label, row);
    }
  }
  const list = document.getElementById('context-usage-agents-list');
  list.replaceChildren();
  if (!totals.size) {
    const empty = document.createElement('div');
    empty.className = 'context-usage-popover-note';
    empty.textContent = 'No agent usage yet in this chat.';
    list.appendChild(empty);
    return;
  }
  for (const [label, row] of totals) {
    const line = document.createElement('div');
    line.className = 'context-usage-popover-row';
    const name = document.createElement('span');
    name.className = 'context-usage-popover-label';
    name.textContent = label;
    const value = document.createElement('span');
    value.className = 'context-usage-popover-value';
    value.textContent = `${row.input.toLocaleString()} in / ${row.output.toLocaleString()} out (${row.total.toLocaleString()})`;
    line.append(name, value);
    list.appendChild(line);
  }
}

function updateContextUsage(contextTokens, contextWindow) {
  const el = document.getElementById('context-usage');
  const ring = document.getElementById('context-usage-btn');
  const popover = document.getElementById('context-usage-popover');
  if (typeof contextWindow !== 'number' || contextWindow <= 0) {
    el.classList.add('hidden');
    popover.classList.add('hidden');
    ring.setAttribute('aria-expanded', 'false');
    return;
  }
  const known = typeof contextTokens === 'number';
  const ratio = known ? Math.min(contextTokens / contextWindow, 1) : 0;
  const pct = known ? Math.round(ratio * 100) : null;
  let level = 'ok';
  let ringColor = 'var(--rail-assistant)';
  if (!known) {
    ringColor = 'var(--ink-muted)';
  } else if (ratio >= CONTEXT_USAGE_THRESHOLD_RATIO) {
    level = 'critical';
    ringColor = '#c0392b';
  } else if (ratio >= CONTEXT_USAGE_THRESHOLD_RATIO * 0.6) {
    level = 'warning';
    ringColor = 'var(--rail-system)';
  }

  el.classList.remove('hidden');
  ring.style.setProperty('--pct', known ? `${(ratio * 100).toFixed(1)}%` : '0%');
  ring.style.setProperty('--ring-color', ringColor);
  ring.title = known
    ? `Context used: ${contextTokens.toLocaleString()} of ${contextWindow.toLocaleString()} tokens (${pct}%)`
    : `Context window: ${contextWindow.toLocaleString()} tokens (usage not reported yet)`;
  document.getElementById('context-usage-pct').textContent = known ? `${pct}%` : '–';

  popover.classList.remove('is-warning', 'is-critical');
  if (level !== 'ok') popover.classList.add(`is-${level}`);
  document.getElementById('context-usage-popover-value').textContent = known
    ? `${contextTokens.toLocaleString()} / ${contextWindow.toLocaleString()} (${pct}%)`
    : `– / ${contextWindow.toLocaleString()}`;
  const fmtTokens = (n) => (typeof n === 'number' ? n.toLocaleString() : '–');
  document.getElementById('context-usage-io-input').textContent = fmtTokens(lastTurnIo.input);
  document.getElementById('context-usage-io-output').textContent = fmtTokens(lastTurnIo.output);
  renderAgentTokenBreakdown();
  document.getElementById('context-usage-popover-bar-fill').style.width = known ? `${(ratio * 100).toFixed(1)}%` : '0%';
  document.getElementById('context-usage-popover-note').textContent = !known
    ? 'This provider has not reported token usage yet - showing its context window only.'
    : level === 'critical'
      ? 'Near context limit - consider /clear or summarizing soon.'
      : level === 'warning'
        ? 'Context usage climbing - keep an eye on it.'
        : 'Usage from the last response in this chat.';
}

// Tracks the most recently known real reading so provider/model switches
// and page reloads can fall back to it (or to the newly selected
// provider's bare context_window - see contextUsageFallbackWindow) without
// re-deriving it from scratch at every call site.
let lastContextTokens = null;
let lastContextWindow = null;
// Input/output tokens summed over the last turn (all tool rounds); shown in
// the context popover next to the context-window reading.
let lastTurnIo = { input: null, output: null };

function contextUsageFallbackWindow() {
  const provider = providersById[document.getElementById('provider').value];
  return provider && typeof provider.context_window === 'number' ? provider.context_window : null;
}

function refreshContextUsage() {
  if (typeof lastContextWindow === 'number') {
    updateContextUsage(lastContextTokens, lastContextWindow);
  } else {
    updateContextUsage(null, contextUsageFallbackWindow());
  }
}

// Shared 6-hour / weekly token usage (GET /api/usage), shown under the
// context bar in the same popover. Fetched on open and after each turn.
function formatUsageReset(iso) {
  if (!iso) return 'No usage';
  const mins = Math.max(0, Math.round(((typeof iso === 'number' ? iso * 1000 : new Date(iso).getTime()) - Date.now()) / 60000));
  const text = mins >= 1440 ? `${Math.floor(mins / 1440)}d ${Math.floor((mins % 1440) / 60)}h`
    : mins >= 60 ? `${Math.floor(mins / 60)}h ${mins % 60}m` : `${mins}m`;
  return `Frees up in ${text}`;
}

// Sidebar "Usage" panel: session (6h) and weekly limit bars plus the
// calendar month's total and top agents, from the same /api/usage payload.
function renderSidebarUsage(data) {
  const pct = (w) => (w.limit > 0 ? Math.min(w.used / w.limit, 1) : 0);
  for (const [key, id] of [['six_hour', 'session'], ['weekly', 'week']]) {
    const ratio = pct(data[key]);
    document.getElementById(`sidebar-usage-${id}-pct`).textContent = `${Math.round(ratio * 100)}% used`;
    const fill = document.getElementById(`sidebar-usage-${id}-fill`);
    fill.style.width = `${(ratio * 100).toFixed(1)}%`;
    fill.classList.toggle('is-full', ratio >= 1);
    document.getElementById(`sidebar-usage-${id}-reset`).textContent = formatUsageReset(data[key].reset_at);
  }
  document.getElementById('sidebar-usage-month').textContent = `${data.month.used.toLocaleString()} tokens`;
  const agents = document.getElementById('sidebar-usage-agents');
  agents.replaceChildren();
  for (const row of data.month.top_agents || []) {
    const line = document.createElement('div');
    line.className = 'usage-table-row';
    const name = document.createElement('span');
    name.textContent = `${row.agent} ${row.model || ''}`.trim();
    const value = document.createElement('span');
    value.textContent = row.tokens.toLocaleString();
    line.append(name, value);
    agents.appendChild(line);
  }
}

async function refreshTokenUsage() {
  try {
    const res = await fetch('/chat/api/usage');
    if (!res.ok) return;
    const data = await res.json();
    for (const [key, id] of [['six_hour', 'six-hour'], ['weekly', 'weekly']]) {
      const w = data[key];
      const ratio = w.limit > 0 ? Math.min(w.used / w.limit, 1) : 0;
      document.getElementById(`usage-${id}-value`).textContent =
        `${w.used.toLocaleString()} / ${w.limit.toLocaleString()} (${Math.round(ratio * 100)}%)`;
      const fill = document.getElementById(`usage-${id}-fill`);
      fill.style.width = `${(ratio * 100).toFixed(1)}%`;
      fill.classList.toggle('is-full', ratio >= 1);
      document.getElementById(`usage-${id}-reset`).textContent = formatUsageReset(w.reset_at);
    }
    renderSidebarUsage(data);
  } catch (_) { /* popover keeps last values */ }
}

// Toggle the context-usage popover on ring click; close on outside click
// or Escape, same interaction pattern as other small popovers on this
// page. Wired once at load since the ring/button elements are static markup.
(function initContextUsagePopover() {
  const btn = document.getElementById('context-usage-btn');
  const popover = document.getElementById('context-usage-popover');
  if (!btn || !popover) return;
  function close() {
    popover.classList.add('hidden');
    btn.setAttribute('aria-expanded', 'false');
  }
  function open() {
    popover.classList.remove('hidden');
    btn.setAttribute('aria-expanded', 'true');
    refreshTokenUsage();
  }
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (popover.classList.contains('hidden')) open(); else close();
  });
  document.addEventListener('click', (e) => {
    if (!popover.classList.contains('hidden') && !popover.contains(e.target) && e.target !== btn) close();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') close();
  });
})();

(function initSidebarUsage() {
  const btn = document.getElementById('sidebar-usage-btn');
  const panel = document.getElementById('sidebar-usage-panel');
  if (!btn || !panel) return;
  function close() {
    panel.classList.add('hidden');
    btn.setAttribute('aria-expanded', 'false');
  }
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (panel.classList.contains('hidden')) {
      panel.classList.remove('hidden');
      btn.setAttribute('aria-expanded', 'true');
      refreshTokenUsage();
    } else {
      close();
    }
  });
  document.addEventListener('click', (e) => {
    if (!panel.classList.contains('hidden') && !panel.contains(e.target) && e.target !== btn) close();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') close();
  });
})();

// Human-readable label for a (provider_id, model_id) pair, using the
// same data /api/providers already gave loadProviders() for the
// dropdowns - falls back to the raw model id (or provider label) if the
// providers list hasn't loaded yet or no longer lists that model.
function modelLabel(providerId, modelId) {
  const provider = providersById[providerId];
  if (!provider) return modelId || '';
  const found = (provider.models || []).find(m => m.id === modelId);
  return found ? found.label : (modelId || provider.label || '');
}

function createTimerElement(text) {
  const el = document.createElement('div');
  el.className = 'msg-timer';
  el.textContent = text;
  return el;
}

// Reused across calls rather than created fresh each time - browsers cap
// how many AudioContexts can exist at once, and creation itself has a
// small cost. Lazily created on first actual use (inside
// playNotificationSound()) rather than at page load, so it's built in
// response to the same user gesture (sending a message) that triggers
// the request whose reply it announces - browser autoplay policies are
// more lenient about audio started that way than audio started with no
// gesture in the call chain at all.
let notificationAudioCtx = null;

// Only while the user is away from this tab - document.hidden covers
// "switched tabs or minimized"; hasFocus() additionally covers "this
// window is visible but another window has focus" (e.g. side-by-side
// windows), which hidden alone wouldn't catch. Silent whenever the user
// is already looking at the conversation - they don't need a sound to
// notice a reply they're watching arrive.
function shouldPlayNotificationSound() {
  return document.hidden || !document.hasFocus();
}

function playNotificationSound() {
  if (!shouldPlayNotificationSound()) return;
  try {
    if (!notificationAudioCtx) {
      notificationAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    const ctx = notificationAudioCtx;
    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();
    oscillator.type = 'sine';
    oscillator.frequency.value = 880; // A5 - a short, clean, unobtrusive chime
    // Exponential ramps (never a hard on/off) avoid the audible "click"
    // a sudden gain change produces; ramping to/from a near-zero floor
    // rather than literal 0 because exponentialRampToValueAtTime can't
    // target exactly 0.
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.2, ctx.currentTime + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.3);
    oscillator.connect(gain);
    gain.connect(ctx.destination);
    oscillator.start();
    oscillator.stop(ctx.currentTime + 0.3);
  } catch (err) {
    // Web Audio unavailable, blocked by an autoplay policy, or otherwise
    // unsupported - a missed notification sound isn't worth surfacing as
    // a user-facing error over.
  }
}


function chatState(chatId) {
  if (!chatStates.has(chatId)) {
    chatStates.set(chatId, { history: [], activity: null, sequence: 0, streamText: '', subscription: null, launching: false, needsReload: false });
  }
  return chatStates.get(chatId);
}

function selectedJob() {
  return currentChatId ? chatState(currentChatId).activity : null;
}

function composerBlocked() {
  return !chatInitialized || chatLoading || manageChatsVisible ||
    !!(currentChatId ? chatState(currentChatId).launching : newChatLaunch);
}

function updateComposerForJob() {
  const running = selectedJob()?.status === 'running';
  const blocked = composerBlocked();
  document.getElementById('q').disabled = blocked || running;
  document.getElementById('attach-btn').disabled = blocked || running;
  const sendBtn = document.getElementById('send-btn');
  sendBtn.disabled = blocked;
  sendBtn.textContent = running ? 'Stop' : 'Send';
  sendBtn.classList.toggle('send-btn-stop', running);
}

function cancelSend() {
  if (composerBlocked() || !currentChatId || selectedJob()?.status !== 'running') return;
  fetch('/chat/api/chats/' + encodeURIComponent(currentChatId) + '/cancel', { method: 'POST' }).catch(() => {});
}

// The launch captures its own view and transcript before yielding. A late
// acknowledgement may register a background job, but cannot select another view.
async function startChatJob(question) {
  if (composerBlocked() || selectedJob()?.status === 'running') return;
  const originalId = currentChatId;
  const generation = chatViewGeneration;
  const state = originalId ? chatState(originalId) : null;
  const launch = { generation, history: history.slice(), priorHistory: history.slice(0, -1) };
  if (state) state.launching = launch;
  else newChatLaunch = launch;
  updateComposerForJob();
  const selectedProvider = document.getElementById('provider').value;
  const selectedModel = document.getElementById('model');
  const requestId = crypto.randomUUID ? crypto.randomUUID() : Date.now() + '-' + Math.random().toString(36).slice(2);
  try {
    const res = await fetch('/chat/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question, history: launch.priorHistory, provider: selectedProvider,
        model: selectedModel.classList.contains('hidden') ? null : selectedModel.value,
        enabled_extensions: currentEnabledExtensions(), chat_id: originalId,
        request_id: requestId, background: true, caveman: cavemanEnabled(),
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || 'Server responded with ' + res.status);
    const jobState = chatState(data.chat_id);
    jobState.history = launch.history;
    jobState.pendingQuestion = question;
    jobState.activity = { status: 'running', request_id: data.request_id || requestId,
      provider_id: selectedProvider, started_at: new Date().toISOString() };
    jobState.sequence = 0;
    jobState.streamText = '';
    jobState.persistedTerminalRequestId = null;
    jobState.needsReload = true;
    if (generation === chatViewGeneration && !manageChatsVisible) {
      currentChatId = data.chat_id;
      if (originalId !== data.chat_id) {
        window.history.pushState(null, '', '/chat?id=' + encodeURIComponent(data.chat_id));
      }
      removeOptimisticChatEntry();
      subscribeToChat(data.chat_id);
    }
    loadChatHistory();
  } catch (err) {
    if (state) state.history = launch.priorHistory;
    if (generation === chatViewGeneration && !manageChatsVisible) {
      removeOptimisticChatEntry();
      history.splice(0, history.length, ...launch.priorHistory);
      appendMsg('system', '⚠️ Request failed: ' + err.message);
    }
  } finally {
    if (state?.launching === launch) state.launching = false;
    if (newChatLaunch === launch) newChatLaunch = null;
    updateComposerForJob();
  }
}

function stopChatSubscription() {
  if (activeSubscription) activeSubscription.abort();
  activeSubscription = null;
  for (const state of chatStates.values()) {
    state.subscription = null;
    state.liveView?.dispose();
    state.liveView = null;
  }
}

// appendMsg() skips the .msg-content bubble when a message starts with empty
// text (the live reply is created on its first token, or with an empty
// response), so a later renderMarkdown(wrap.querySelector('.msg-content'))
// would hit null and throw - leaving just the label until a reload. Create the
// bubble on demand instead.
function ensureMsgContent(wrap) {
  let content = wrap.querySelector('.msg-content');
  if (!content) {
    content = document.createElement('div');
    content.className = 'msg-content';
    const label = wrap.querySelector('.msg-label');
    if (label) label.after(content); else wrap.prepend(content);
  }
  return content;
}

// Reuses the existing message, trace, Markdown and metadata renderers.
function createLiveReply(state) {
  _traceRows.clear();
  const started = new Date(state.activity?.started_at || Date.now()).getTime();
  let pool = THINKING_MESSAGES;
  let thinkingText = pickMessage(pool);
  const thinking = appendMsg('system thinking', thinkingText);
  const timer = createTimerElement(formatElapsedTime(Date.now() - started));
  document.getElementById('log').appendChild(timer);
  // Running token count from "usage" events; "~" while it is still an estimate.
  let liveTokens = '';
  const renderTimer = () => { timer.textContent = formatElapsedTime(Date.now() - started) + liveTokens; };
  const tick = setInterval(renderTimer, 1000);
  const rotate = setInterval(() => { thinkingText = pickMessage(pool, thinkingText); thinking.textContent = thinkingText; }, 3000);
  const slow = setTimeout(() => { pool = LONG_WAIT_MESSAGES; thinking.textContent = pickMessage(pool); }, 15000);
  let wrap = null;
  let trace = null;
  let disposed = false;
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    clearInterval(tick); clearInterval(rotate); clearTimeout(slow);
    thinking.remove();
  };
  return {
    dispose,
    get trace() { return trace?.outer; },
    event(event) {
      if (event.type === 'step_start') {
        thinking.remove();
        if (!trace) trace = appendTrace();
        traceStepStart(trace.container, event);
      } else if (event.type === 'step_end') {
        traceStepEnd(event);
      } else if (event.type === 'step_progress') {
        traceStepProgress(event);
      } else if (event.type === 'progress') {
        // A running tool reported what it is doing: show it in place of the
        // rotating filler, and stop the filler overwriting it.
        clearInterval(rotate); clearTimeout(slow);
        thinking.textContent = '⏳ ' + event.message;
        document.getElementById('log').scrollTop = document.getElementById('log').scrollHeight;
      } else if (event.type === 'usage') {
        liveTokens = ` · ${event.estimated ? '~' : ''}${Number(event.total_tokens).toLocaleString()} tokens`;
        renderTimer();
      } else if (event.type === 'token_reset') {
        // A tool-using round streamed some text that is not the final answer.
        state.streamText = '';
        if (wrap) { wrap.remove(); wrap = null; }
      } else if (event.type === 'token') {
        thinking.remove();
        if (!wrap) wrap = appendMsg('assistant', '', new Date().toISOString());
        renderMarkdown(ensureMsgContent(wrap), hideDownloadMarkers(state.streamText));
        document.getElementById('log').scrollTop = document.getElementById('log').scrollHeight;
      } else if (event.type === 'final' || event.type === 'error') {
        dispose();
        const note = event.cancelled ? 'cancelled' : event.failed || event.type === 'error' ? 'error' : null;
        if (trace) finalizeTrace(trace.outer, trace.summary, note);
        if (event.type === 'error' || event.cancelled) {
          wrap?.remove(); timer.remove();
          appendMsg('system', event.cancelled ? '⏹️ Cancelled.' : '⚠️ ' + (event.message || 'Response failed.'));
        } else {
          const role = event.kind === 'command' ? 'command' : 'assistant';
          if (wrap && event.kind === 'command') { wrap.remove(); wrap = null; }
          if (!wrap) wrap = appendMsg(role, event.response, new Date().toISOString());
          else renderReplyBody(wrap, event.response);
          const elapsed = typeof event.elapsed_seconds === 'number' ? event.elapsed_seconds * 1000 : Date.now() - started;
          timer.textContent = event.kind === 'command'
            ? formatCommandTimerText(elapsed, event.ai_used, event.total_tokens, modelLabel(event.provider_id, event.model))
            : formatTimerText(elapsed, event.total_tokens, modelLabel(event.provider_id, event.model), event.recursive_rounds);
          wrap.appendChild(timer);
          const turn = { role: 'assistant', content: event.response };
          for (const field of ['kind', 'ai_used', 'elapsed_seconds', 'provider_id', 'model', 'total_tokens', 'context_tokens', 'input_tokens', 'output_tokens', 'agent_usage', 'context_window', 'recursive_rounds']) {
            if (event[field] !== undefined && event[field] !== null) turn[field] = event[field];
          }
          history.push(turn);
          state.history = history.slice();
          lastContextTokens = typeof event.context_tokens === 'number' ? event.context_tokens : null;
          lastTurnIo = { input: event.input_tokens, output: event.output_tokens };
          lastContextWindow = typeof event.context_window === 'number' ? event.context_window : null;
          refreshContextUsage();
          refreshTokenUsage();
        }
        if (!event.cancelled) playNotificationSound();
      }
    },
  };
}

async function subscribeToChat(chatId) {
  if (currentChatId !== chatId || manageChatsVisible || chatLoading) return;
  const state = chatState(chatId);
  if (state.activity?.status !== 'running' || state.subscription) return;
  stopChatSubscription();
  const controller = new AbortController();
  const generation = chatViewGeneration;
  state.subscription = controller;
  activeSubscription = controller;
  const visible = () => !controller.signal.aborted && generation === chatViewGeneration && currentChatId === chatId && !manageChatsVisible;
  // A replaced transcript needs the full retained trace; a reconnect to the
  // same DOM resumes its cursor, so tokens and tools are never duplicated.
  let live = state.persistedTerminalRequestId ? null : (state.liveView = createLiveReply(state));
  let terminal = false;
  try {
    const res = await fetch('/chat/api/chats/' + encodeURIComponent(chatId) + '/events?after_sequence=' + state.sequence, { signal: controller.signal });
    if (!res.ok || !res.body) throw new Error('Server responded with ' + res.status);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (visible()) {
      const { done, value } = await reader.read();
      if (!visible() || done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split('\n\n');
      buffer = frames.pop();
      for (const frame of frames) {
        if (!visible()) break;
        const line = frame.split('\n').find(value => value.startsWith('data: '));
        if (!line) continue;
        const event = JSON.parse(line.slice(6));
        if (event.sequence && event.sequence <= state.sequence) continue;
        state.sequence = Math.max(state.sequence, Number(event.sequence) || 0);
        // Persistence may beat the terminal SSE frame. Suppress every frame
        // from that saved request, including tokens and tools before final.
        const persistedTerminal = !!state.persistedTerminalRequestId &&
          event.request_id === state.persistedTerminalRequestId;
        if (!persistedTerminal) {
          if (!live) live = state.liveView = createLiveReply(state);
          if (event.type === 'token') state.streamText += event.text || '';
          live.event(event);
        }
        if (event.type === 'final' || event.type === 'error') {
          terminal = true;
          state.justCompleted = true;
          state.activity = { ...state.activity, status: event.cancelled ? 'cancelled'
            : event.failed || event.type === 'error' ? 'failed' : 'completed' };
          // Everything this turn produced was already appended live - never reload over it.
          state.needsReload = false;
          state.streamText = '';
          loadChatHistory();
          break;
        }
      }
      if (terminal) break;
    }
  } catch (err) {
    if (visible()) state.needsReload = true;
  } finally {
    live?.dispose();
    if (state.subscription === controller) state.subscription = null;
    if (activeSubscription === controller) activeSubscription = null;
    if (visible() && !terminal) {
      // No terminal frame (including a clean EOF) is a disconnect. The next
      // list poll obtains authoritative status and reloads persisted history.
      state.needsReload = true;
    }
    updateComposerForJob();
  }
}

async function send() {
  if (composerBlocked() || selectedJob()?.status === 'running') return;
  exitHistoryRecall(false);
  const input = document.getElementById('q');
  const question = input.value.trim();
  const isCommand = question.startsWith('/');
  const readyAttachments = isCommand ? [] : pendingAttachments.filter(a => a.status === 'ready');
  if (!question && !readyAttachments.length) return;
  if (!isCommand && pendingAttachments.some(a => a.status === 'uploading')) return;
  if (question === '/clear') { input.value = ''; autoResizeInput(input); hideCommandSuggestions(); clearChat(); return; }
  if (question === '/summarize') { input.value = ''; autoResizeInput(input); hideCommandSuggestions(); summarizeChat(); return; }
  const attachmentBlocks = buildAttachmentBlocks(readyAttachments);
  const fullQuestion = attachmentBlocks.length ? (question || 'Please review the attached file(s).') + '\n\n' + attachmentBlocks.join('\n\n') : question;
  input.value = ''; autoResizeInput(input); hideCommandSuggestions();
  if (greetingEl) { greetingEl.remove(); greetingEl = null; }
  if (!currentChatId) addOptimisticChatEntry(question || readyAttachments.map(a => a.filename).join(', '));
  appendMsg('user', fullQuestion, new Date().toISOString());
  history.push({ role: 'user', content: fullQuestion });
  if (currentChatId) chatState(currentChatId).history = history.slice();
  if (!isCommand && readyAttachments.length) { pendingAttachments = pendingAttachments.filter(a => a.status !== 'ready'); renderAttachChips(); }
  await startChatJob(fullQuestion);
}

const ROLE_LABELS = { user: 'You', assistant: 'Assistant', command: 'Command', summary: 'Summary', log_attachment: 'Full history log' };

// Triggers a client-side file download of a log-attachment message's
// full raw-text content (see services/summarization.py) - built as a
// Blob rather than a server round-trip, since the content is already
// sitting in the chat JSON appendMsg() just rendered.
function downloadLogAttachment(text, chatId) {
  const blob = new Blob([text], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${chatId || 'chat'}-history.txt`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// Shared network call behind both "/summarize" (summarizeChat()) and
// "/clear" (clearChat()) below - phase 3's summarize_chat_api, wrapped
// once so neither caller repeats the fetch/response-shape handling.
// Never touches the DOM itself; returns { ok: true } on a clean success
// or { ok: false, error } with the same "❌ <headline> - {<dict>}" shape
// ask() itself surfaces for a provider error (see renderErrorMessage/
// matchOpenRouterDailyLimit below), so a failure renders identically
// wherever the caller chooses to show it.
async function postSummarize() {
  const res = await fetch(`/chat/api/chats/${encodeURIComponent(currentChatId)}/summarize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider: document.getElementById('provider').value }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const errorText = data.error || `Server responded with ${res.status}`;
    return { ok: false, error: errorText.startsWith('❌') ? errorText : `❌ ${errorText}` };
  }
  return { ok: true };
}

// "/summarize" - a real, server-persisted change (see
// __index__.py's summarize_chat_api), so instead of just editing the DOM
// in place it fully reloads the chat from the server afterward: the
// stored transcript is now exactly one summary message and one
// log-attachment message, and loadChat() below already knows how to
// render each kind and rebuild `history` (skipping the log attachment -
// see its own filter) from that.
async function summarizeChat() {
  if (!currentChatId) {
    appendMsg('system', 'Nothing to summarize yet - send a message first.');
    return;
  }
  const thinkingEl = appendMsg('system thinking', 'Summarizing...');
  let result;
  try {
    result = await postSummarize();
  } catch (err) {
    thinkingEl.remove();
    appendMsg('summarize-error', `❌ ${err.message}`);
    return;
  }
  thinkingEl.remove();
  if (!result.ok) {
    appendMsg('summarize-error', result.error);
    return;
  }
  document.getElementById('log').innerHTML = '';
  history.length = 0;
  await loadChat(currentChatId);
}

// The actual no-AI clear (keeps only the cumulative raw log) - shared by
// both of clearChat()'s branches below ("Just clear", and "Generate
// summary"'s own AI-unavailable fallback). Never triggers a download -
// neither branch forces one; the full history stays available any time
// via the sidebar's export button (a plain <a href>, see
// buildChatHistoryItem), downloaded on the user's own terms instead.
async function postRawClear() {
  const thinkingEl = appendMsg('system thinking', 'Clearing...');
  try {
    const res = await fetch(`/chat/api/chats/${encodeURIComponent(currentChatId)}/clear`, { method: 'POST' });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `Server responded with ${res.status}`);
    }
    thinkingEl.remove();
    document.getElementById('log').innerHTML = '';
    history.length = 0;
    await loadChat(currentChatId);
  } catch (err) {
    thinkingEl.remove();
    appendMsg('summarize-error', `❌ Could not clear: ${err.message}`);
  }
}

// "/clear" - real, server-persisted trim (no more client-only
// localStorage hide). Asks up front which kind of clear the user wants -
// never forces a summarize attempt as the only path:
//   - "Generate summary": phase 3's summarize_chat is the actual clear (a
//     fresh summary + log IS "cleared"). If the agent can't be reached,
//     warns again and offers to clear anyway via postRawClear() above -
//     keeping only the raw log, no summary, and no forced download; the
//     export button stays available any time if they want one.
//   - "Just clear": skips summarization entirely and goes straight to
//     postRawClear() - no forced download either; the sidebar's export
//     button is always there if they want the full history afterward.
// Cancelling (Escape / backdrop / Cancel button) at any step changes
// nothing.
async function clearChat() {
  if (!currentChatId) {
    appendMsg('system', 'Nothing to clear yet - send a message first.');
    return;
  }
  const choice = await choiceModal({
    title: 'Clear conversation?',
    message: 'Nothing already saved is deleted either way - the full history always stays downloadable. Choose how to clear what gets resent to the LLM from here on.',
    choices: [
      { value: 'summarize', label: 'Generate summary' },
      { value: 'clear', label: 'Just clear', danger: true },
    ],
  });
  if (!choice) return;

  if (choice === 'clear') {
    await postRawClear();
    return;
  }

  const thinkingEl = appendMsg('system thinking', 'Summarizing...');
  let result;
  try {
    result = await postSummarize();
  } catch (err) {
    result = { ok: false, error: `❌ ${err.message}` };
  }
  thinkingEl.remove();

  if (result.ok) {
    document.getElementById('log').innerHTML = '';
    history.length = 0;
    await loadChat(currentChatId);
    return;
  }

  const fallbackConfirmed = await confirmModal({
    title: 'AI unavailable',
    message: 'Could not reach the AI to summarize. Clear anyway? What gets sent to the LLM is trimmed to the raw log - the full history stays available any time via the export button.',
    confirmLabel: 'Clear anyway',
    danger: true,
  });
  if (!fallbackConfirmed) return;

  await postRawClear();
}

// One <details> row per tool call, live: created open+pending on
// step_start, filled in and closed on step_end. Mirrors Claude Code's
// own tool-call trace - checkmark once resolved, red mark on failure,
// raw tool name + truncated args when the tool has no display_label
// (see mcp_server's capability_meta / tool.py meta={"display_label":...}).
const _traceRows = new Map(); // step id -> <details> element, scoped per in-flight turn

// Outer group is itself a <details>, open while the turn is in flight so
// steps stream into view live (same as before), then collapsed by
// finalizeTrace() once the turn ends into one "Ran N tools (M failed)"
// line - mirrors Claude Code's own collapsed session-trace summary.
function appendTrace() {
  const outer = document.createElement('details');
  outer.className = 'msg-trace';
  outer.open = true;
  const summary = document.createElement('summary');
  summary.className = 'msg-trace-summary';
  summary.textContent = 'Running tools…';
  outer.appendChild(summary);
  const container = document.createElement('div');
  container.className = 'msg-trace-steps';
  outer.appendChild(container);
  document.getElementById('log').appendChild(outer);
  document.getElementById('log').scrollTop = document.getElementById('log').scrollHeight;
  return { outer, summary, container };
}

// Counts come from the DOM itself (the trace-step-ok/-failed classes
// traceStepEnd already applies) rather than a separately tracked counter,
// so this can't drift out of sync with what's actually rendered.
function finalizeTrace(outer, summary, note) {
  const total = outer.querySelectorAll('.trace-step').length;
  const failed = outer.querySelectorAll('.trace-step-failed').length;
  let text = `Ran ${total} tool${total === 1 ? '' : 's'}`;
  if (failed > 0) text += ` (${failed} failed)`;
  if (note) text += ` · ${note}`;
  summary.textContent = text;
  outer.open = false;
}

// Rebuilds the collapsed "Ran N tools" block for a saved assistant message
// (message.steps, see __index__.py's generate()) - same DOM the live
// appendTrace()/traceStepStart()/traceStepEnd() produce, already finished.
function renderSavedTrace(steps) {
  const trace = appendTrace();
  steps.forEach((step, index) => {
    const id = `saved-${index}`;
    traceStepStart(trace.container, {
      id, tool: step.tool, label: step.label, arguments: step.arguments,
    });
    traceStepEnd({ id, ok: step.ok, result: step.result });
    _traceRows.delete(id);
  });
  finalizeTrace(trace.outer, trace.summary, null);
}

function truncateArgs(args) {
  const text = JSON.stringify(args ?? {});
  return text.length > 120 ? `${text.slice(0, 117)}...` : text;
}

function traceStepStart(traceEl, event) {
  const row = document.createElement('details');
  row.className = 'trace-step trace-step-pending';
  const summary = document.createElement('summary');
  const icon = document.createElement('span');
  icon.className = 'trace-step-icon';
  icon.textContent = '⏳';
  const label = document.createElement('span');
  label.className = 'trace-step-label';
  label.textContent = event.label || `${event.tool} — ${truncateArgs(event.arguments)}`;
  summary.appendChild(icon);
  summary.appendChild(label);
  row.appendChild(summary);
  const pre = document.createElement('pre');
  pre.className = 'trace-step-detail';
  pre.textContent = `${event.tool}\n${JSON.stringify(event.arguments ?? {}, null, 2)}`;
  row.appendChild(pre);
  traceEl.appendChild(row);
  _traceRows.set(event.id, { row, icon, pre });
}

// A running tool reported what it is doing: show the latest message in the
// step's summary, and keep every message in its detail pane.
function traceStepProgress(event) {
  const entry = _traceRows.get(event.id);
  if (!entry) return;
  entry.pre.textContent += `\n… ${event.message}`;
  let note = entry.row.querySelector('.trace-step-progress');
  if (!note) {
    note = document.createElement('span');
    note.className = 'trace-step-progress';
    entry.row.querySelector('summary').appendChild(note);
  }
  note.textContent = ` — ${event.message}`;
}

function traceStepEnd(event) {
  const entry = _traceRows.get(event.id);
  if (!entry) return;
  entry.row.classList.remove('trace-step-pending');
  entry.row.classList.add(event.ok ? 'trace-step-ok' : 'trace-step-failed');
  entry.icon.textContent = event.ok ? '✓' : '✗';
  entry.row.querySelector('.trace-step-progress')?.remove();
  entry.pre.textContent += `\n\n${event.result ?? ''}`;
}

// Copies the message's rendered text; label flips to "Copied" briefly.
function buildCopyButton(wrap) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'msg-copy-btn';
  btn.title = 'Copy';
  btn.setAttribute('aria-label', 'Copy response');
  const svg = d => `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
  const copyIcon = svg('<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>');
  const checkIcon = svg('<path d="M20 6 9 17l-5-5"/>');
  btn.innerHTML = copyIcon;
  btn.addEventListener('click', async () => {
    const content = wrap.querySelector('.msg-content');
    try {
      await navigator.clipboard.writeText(content ? content.innerText : '');
      btn.innerHTML = checkIcon;
      btn.title = 'Copied';
    } catch (err) {
      btn.title = 'Copy failed';
    }
    setTimeout(() => { btn.innerHTML = copyIcon; btn.title = 'Copy'; }, 1500);
  });
  return btn;
}

function appendMsg(role, text, sentAt = null) {
  const log = document.getElementById('log');
  const wrap = document.createElement('div');
  wrap.className = `msg ${role}`;

  // role can be a space-separated combo (e.g. "system thinking") - only
  // the first token decides how this renders.
  const primaryRole = role.split(' ')[0];

  if (primaryRole === 'summary') {
    // A summarize cycle's fresh summary (see services/summarization.py) -
    // rendered like an assistant reply (it IS LLM-produced prose, same
    // markdown treatment) but with its own label/rail so it visibly
    // reads as "this replaced the raw history above", not a normal turn.
    const label = document.createElement('div');
    label.className = 'msg-label';
    label.textContent = ROLE_LABELS.summary;
    wrap.appendChild(label);
    const content = document.createElement('div');
    content.className = 'msg-content';
    renderMarkdown(content, text);
    wrap.appendChild(content);
  } else if (primaryRole === 'log_attachment') {
    // The cumulative raw-history text a summarize cycle set aside - never
    // dumped inline (it can be the entire original transcript), offered
    // as a download chip instead, same idea as .msg-attachment's
    // collapsible file chips but for the whole chat's raw log.
    const label = document.createElement('div');
    label.className = 'msg-label';
    label.textContent = ROLE_LABELS.log_attachment;
    wrap.appendChild(label);
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'msg-log-chip';
    chip.textContent = `⬇ Download full history (${text.length.toLocaleString()} chars)`;
    chip.addEventListener('click', () => downloadLogAttachment(text, currentChatId));
    wrap.appendChild(chip);
  } else if (primaryRole === 'summarize-error') {
    // A failed "/summarize" (see summarizeChat()) - same headline/hint/
    // details treatment as a normal assistant "❌ ..." error (including
    // matchOpenRouterDailyLimit's rate-limit-specific formatting below),
    // just labeled as the Summary action that actually failed rather
    // than a chat reply.
    const label = document.createElement('div');
    label.className = 'msg-label';
    label.textContent = ROLE_LABELS.summary;
    wrap.appendChild(label);
    wrap.classList.add('error');
    const content = document.createElement('div');
    content.className = 'msg-content';
    renderErrorMessage(content, text);
    wrap.appendChild(content);
  } else if (primaryRole === 'user' || primaryRole === 'assistant' || primaryRole === 'command') {
    const label = document.createElement('div');
    label.className = 'msg-label';
    label.textContent = ROLE_LABELS[primaryRole];
    wrap.appendChild(label);

    if (primaryRole === 'assistant' || primaryRole === 'command') {
      const content = document.createElement('div');
      content.className = 'msg-content';
      // Both an LLM reply and a "/" command failure use the same "❌ ..."
      // prefix (see commands.py / __index__.py) to signal an error turn -
      // route those through the collapsible-detail treatment instead of
      // dumping a raw provider error payload straight into the bubble.
      if (text.startsWith('❌')) {
        wrap.classList.add('error');
        renderErrorMessage(content, text);
      } else {
        // A command reply already went through
        // command_formatting.format_command_result() server-side (see
        // commands.py) - Markdown same as an LLM reply, just from a
        // direct tool call instead of a model.
        const { mainText, downloads } = parseDownloadMarkers(text);
        if (mainText) renderMarkdown(content, mainText);
      }
      if (content.childNodes.length) wrap.appendChild(content);
      if (!text.startsWith('❌')) {
        const { downloads } = parseDownloadMarkers(text);
        downloads.forEach(download => wrap.appendChild(buildDownloadAttachment(download)));
      }
      if (sentAt) {
        const sentTime = new Date(sentAt);
        if (!Number.isNaN(sentTime.getTime())) {
          const timestamp = document.createElement('div');
          timestamp.className = 'msg-sent-time';
          timestamp.textContent = `Sent ${sentTime.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`;
          wrap.appendChild(timestamp);
        }
      }
      wrap.appendChild(buildCopyButton(wrap));
    } else {
      // A user message may carry one or more [[ATTACHMENT ...]] blocks
      // (see buildAttachmentBlocks()/send()) - stripped out here and
      // rendered as collapsible chips instead of dumping the raw file
      // text into the bubble. Applies identically on a fresh send and on
      // loadChat()'s reload, since both pass the same stored `content`
      // string through this same function.
      const { mainText, attachments } = parseAttachmentMarkers(text);
      if (mainText) {
        const content = document.createElement('div');
        content.className = 'msg-content';
        content.textContent = mainText;
        wrap.appendChild(content);
      }
      attachments.forEach(att => wrap.appendChild(buildAttachmentDetails(att)));
      if (sentAt) {
        const sentTime = new Date(sentAt);
        if (!Number.isNaN(sentTime.getTime())) {
          const timestamp = document.createElement('div');
          timestamp.className = 'msg-sent-time';
          timestamp.textContent = `Sent ${sentTime.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`;
          wrap.appendChild(timestamp);
        }
      }
    }
  } else {
    // system / thinking notices - short, single-line, never markdown -
    // the wrapper IS the text node, so send()'s thinkingEl.remove() and
    // thinkingEl.textContent = '...' calls keep working unchanged.
    wrap.textContent = text;
  }

  log.appendChild(wrap);
  log.scrollTop = log.scrollHeight;
  return wrap;
}

// OpenRouter's free-tier daily cap (Error code: 429, error_type
// 'rate_limit_exceeded') is common enough to deserve its own plain-English
// headline instead of the raw provider dict - returns the provider's own
// 'message' field to show as a hint, or null if this isn't that error.
function matchOpenRouterDailyLimit(text) {
  if (!/Error code:\s*429\b/.test(text)) return null;
  if (!/'error_type':\s*'rate_limit_exceeded'/.test(text)) return null;
  const m = text.match(/'message':\s*'([^']*)'/);
  return m ? m[1] : null;
}

// A provider/tool error string is "❌ <headline> - {<raw payload>}" (see
// ai_agent's error formatting) - the headline alone is the useful part,
// the trailing dict is a debug dump nobody wants inline. Show the
// headline plain, tuck the dump behind a <details> instead of markdown
// (this text is never LLM-authored, so no XSS surface / no DOMPurify
// needed here, plain textContent throughout).
function renderErrorMessage(container, text) {
  const marker = ' - {';
  const splitAt = text.indexOf(marker);

  const dailyLimitMessage = matchOpenRouterDailyLimit(text);
  const headline = document.createElement('div');
  headline.className = 'msg-error-headline';
  if (dailyLimitMessage !== null) {
    headline.textContent = '❌ You have exceeded the limit for the day.';
    container.appendChild(headline);
    const hint = document.createElement('div');
    hint.className = 'msg-error-hint';
    hint.textContent = `Hint: ${dailyLimitMessage}`;
    container.appendChild(hint);
  } else {
    headline.textContent = splitAt === -1 ? text : text.slice(0, splitAt);
    container.appendChild(headline);
  }

  if (splitAt !== -1) {
    const raw = text.slice(splitAt + 3); // drop the " - " separator, keep the "{...}"
    const details = document.createElement('details');
    details.className = 'msg-error-details';
    const summary = document.createElement('summary');
    summary.textContent = 'Show details';
    details.appendChild(summary);
    const pre = document.createElement('pre');
    pre.textContent = raw;
    details.appendChild(pre);
    container.appendChild(details);
  }
}

function renderMarkdown(container, text) {
  // marked/DOMPurify come from CDN <script> tags in index.html - fall
  // back to plain text rather than crashing the whole page if either
  // failed to load (offline, CDN blocked, etc), a failure mode that
  // didn't exist before this page had any external dependency.
  if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
    container.textContent = text;
    return;
  }
  // marked does NOT sanitize its own output (their own docs say so
  // explicitly) - this is LLM-generated text landing in innerHTML, so
  // DOMPurify here isn't optional polish, it's the only thing standing
  // between a crafted response and a script running in this page.
  container.innerHTML = DOMPurify.sanitize(marked.parse(text));
}

async function loadChat(chatId, generation = chatViewGeneration) {
  const isCurrent = () => generation === chatViewGeneration && currentChatId === chatId && !manageChatsVisible;
  try {
    const res = await fetch(`/chat/api/chats/${encodeURIComponent(chatId)}`);
    if (!isCurrent()) return false;
    if (!res.ok) {
      // Unknown or not-yours chat id - degrade to a fresh chat rather
      // than showing an error for what's just a stale/foreign link.
      return false;
    }
    const chat = await res.json();
    if (!isCurrent()) return false;
    const state = chatState(chatId);
    // A response may finish between the list poll and this transcript fetch.
    // Never replay its tokens into an already-complete persisted answer.
    if (chat.activity) {
      state.activity = chat.activity;
      state.pendingQuestion = chat.pending_question || null;
    }
    state.persistedTerminalRequestId = null;
    // The detail endpoint snapshots the job before reading the transcript.
    // A saved assistant's request ID proves which pending turn completed.
    // Text and timestamps cannot identify requests: users may repeat a prompt
    // and old transcripts may have no request IDs. In that case keep replaying.
    const requestId = state.activity?.request_id;
    if (requestId && chat.messages.some(message =>
        message.role === 'assistant' && message.request_id === requestId)) {
      state.persistedTerminalRequestId = requestId;
      state.pendingQuestion = null;
    }
    currentChatId = chat.id;
    document.getElementById('log').innerHTML = '';
    history.length = 0;
    lastUsedProviderId = null;
    lastUsedModelId = null;
    // Tracks the most recent assistant turn's usage numbers as messages
    // are walked in order, so the ring restores to the LAST persisted
    // turn's reading rather than resetting to zero on reload (see
    // refreshContextUsage() call after this loop) - writes into the
    // module-level lastContextTokens/lastContextWindow, not a shadowing
    // local, so later provider switches still see this chat's reading.
    lastContextTokens = null;
    lastTurnIo = { input: null, output: null };
    lastContextWindow = null;
    chat.messages.forEach((message) => {
      const displayRole = message.kind === 'command' ? 'command'
        : message.kind === 'summary' ? 'summary'
        : message.kind === 'log_attachment' ? 'log_attachment'
        : message.role;
      if (message.role === 'assistant' && Array.isArray(message.steps) && message.steps.length) {
        renderSavedTrace(message.steps);
      }
      const wrap = appendMsg(displayRole, message.content, message.sent_at);
      // A log-attachment message is never resent to the LLM (see
      // __index__.py's chat_api docstring on its own llm_history filter,
      // and services/summarization.py's module docstring) - it's the raw
      // history a summary already replaced, so it's rendered above but
      // deliberately never pushed into `history`, the array this file
      // sends back as `data.history` on every subsequent send().
      if (message.kind === 'log_attachment') return;
      const turn = { role: message.role, content: message.content };
      if (message.kind) turn.kind = message.kind;
      if (message.role === 'assistant') {
        turn.elapsed_seconds = message.elapsed_seconds;
        if (message.kind === 'command') turn.ai_used = !!message.ai_used;
        if (message.provider_id) turn.provider_id = message.provider_id;
        if (message.model) turn.model = message.model;
        if (typeof message.total_tokens === 'number') turn.total_tokens = message.total_tokens;
        if (typeof message.context_tokens === 'number') turn.context_tokens = message.context_tokens;
        if (typeof message.input_tokens === 'number') turn.input_tokens = message.input_tokens;
        if (typeof message.output_tokens === 'number') turn.output_tokens = message.output_tokens;
        if (Array.isArray(message.agent_usage)) turn.agent_usage = message.agent_usage;
        if (typeof message.context_window === 'number') turn.context_window = message.context_window;
        if (message.recursive_rounds) turn.recursive_rounds = message.recursive_rounds;
        if (typeof message.context_tokens === 'number' && typeof message.context_window === 'number') {
          lastContextTokens = message.context_tokens;
          lastContextWindow = message.context_window;
          lastTurnIo = { input: message.input_tokens, output: message.output_tokens };
        }
        if (typeof message.elapsed_seconds === 'number' && wrap) {
          const text = message.kind === 'command'
            ? formatCommandTimerText(
                message.elapsed_seconds * 1000, message.ai_used, message.total_tokens,
                modelLabel(message.provider_id, message.model)
              )
            : formatTimerText(
                message.elapsed_seconds * 1000,
                message.total_tokens,
                modelLabel(message.provider_id, message.model),
                message.recursive_rounds
              );
          wrap.appendChild(createTimerElement(text));
        }
        if (message.provider_id && message.model) {
          lastUsedProviderId = message.provider_id;
          lastUsedModelId = message.model;
        }
      }
      history.push(turn);
    });
    if (state.activity?.status === 'running' && state.pendingQuestion) {
      appendMsg('user', state.pendingQuestion);
      history.push({ role: 'user', content: state.pendingQuestion });
    }
    state.history = history.slice();
    refreshContextUsage();
    return true;
  } catch (err) {
    if (!isCurrent()) return false;
    return false;
  }
}

// One live DOM transcript is intentionally reused.  Before replacing it,
// capture the selected chat's LLM history; opening another chat never asks
// the server to stop the first chat's worker.
async function openChat(chatId, { reload = false, navigation = reload ? 'none' : 'push' } = {}) {
  // Clicking the selected row is an explicit refresh/reconnect too.
  const completedTrace = currentChatId === chatId && chatId && selectedJob()?.status !== 'running'
    ? chatState(chatId).liveView?.trace : null;
  if (completedTrace) finalizeTrace(completedTrace, completedTrace.querySelector('.msg-trace-summary'));
  const generation = ++chatViewGeneration;
  stopChatSubscription();
  currentChatId = chatId || null;
  newChatLaunch = null;
  manageChatsVisible = false;
  setChatContentVisible(true);
  document.getElementById('chat-manage-panel')?.classList.add('hidden');
  chatLoading = !!chatId;
  updateComposerForJob();
  document.getElementById('log').innerHTML = '';
  history.length = 0;
  greetingEl = null;
  lastUsedProviderId = null;
  lastUsedModelId = null;
  lastContextTokens = null;
  lastTurnIo = { input: null, output: null };
  lastContextWindow = null;
  exitHistoryRecall(false);
  document.getElementById('q').value = '';
  pendingAttachments = [];
  renderAttachChips();
  if (navigation !== 'none') {
    const url = chatId ? '/chat?id=' + encodeURIComponent(chatId) : '/chat';
    window.history[navigation === 'replace' ? 'replaceState' : 'pushState'](null, '', url);
  }
  if (!chatId) {
    greetingEl = buildWelcome(pickGreetingMessage());
    document.getElementById('log').appendChild(greetingEl);
    refreshContextUsage();
  } else {
    const restored = await loadChat(chatId, generation);
    if (generation !== chatViewGeneration) return;
    if (!restored) return openChat(null, { navigation: 'replace' });
    if (completedTrace) {
      const log = document.getElementById('log');
      log.insertBefore(completedTrace, log.lastElementChild);
    }
    applyLastUsedModel();
    const state = chatState(chatId);
    state.sequence = 0;
    state.streamText = '';
    state.needsReload = false;
  }
  chatLoading = false;
  // A view that finished loading is usable even if startup's own openChat
  // was skipped (user navigated first) or is still awaiting providers.
  chatInitialized = true;
  renderChatHistoryList(chatListRows);
  updateComposerForJob();
  if (chatId) subscribeToChat(chatId);
}

function restoreChatFromLocation() {
  return openChat(new URLSearchParams(window.location.search).get('id'), { navigation: 'none' });
}

window.addEventListener('popstate', restoreChatFromLocation);

// Only the ordinary toolbar and transcript/composer belong to this mode.
// Extension panel/overlay visibility remains owned by its own toggle.
function setChatContentVisible(visible) {
  document.querySelector('#chat-main-view > .toprow').classList.toggle('hidden', !visible);
  document.getElementById('chat-dropzone').classList.toggle('hidden', !visible);
}

// Same idea as PROVIDERS_CACHE_KEY above: chat switching/deleting/renaming
// are real page navigations, so without this the sidebar list blanks to
// nothing and refetches from scratch on every single click. Hydrating from
// last tab's snapshot first lets it render instantly; loadChatHistory()
// still runs right after to refresh it against the live server.
const CHATS_CACHE_KEY = 'chat.chatsCache';

function loadChatsFromCache() {
  try {
    const raw = sessionStorage.getItem(CHATS_CACHE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    return Array.isArray(parsed) && parsed.length ? parsed : null;
  } catch (err) {
    return null; // corrupt JSON / storage unavailable - just skip the cache
  }
}

function saveChatsToCache(chats) {
  try {
    sessionStorage.setItem(CHATS_CACHE_KEY, JSON.stringify(chats));
  } catch (err) {
    // Quota exceeded / storage disabled - loadChatHistory() still works for
    // this page load, it just won't have a cache to hydrate from next time.
  }
}

async function loadChatHistory() {
  const list = document.getElementById('chat-history-list');
  if (!list) return; // not on the chat page's sidebar variant - nothing to do
  const requestId = ++chatHistoryRequestId;
  try {
    const res = await fetch('/chat/api/chats');
    if (!res.ok) throw new Error(`Server responded with ${res.status}`);
    const chats = await res.json();
    if (requestId !== chatHistoryRequestId) return; // a newer call already landed - this one is stale
    saveChatsToCache(chats);
    renderChatHistory(chats);
  } catch (err) {
    if (requestId !== chatHistoryRequestId) return;
    // A cached list (rendered from a previous navigation) is still better
    // than wiping the sidebar to an error message - same "leave it as-is"
    // treatment loadProviders() gives a stale-but-working dropdown.
    if (!list.children.length || list.querySelector('.chat-history-empty')) {
      list.innerHTML = '<p class="chat-history-empty">Could not load chat history.</p>';
    }
  }
}

function sortChatRows(rows) {
  return [...rows].sort((left, right) => {
    const leftRunning = left.activity?.status === 'running';
    const rightRunning = right.activity?.status === 'running';
    if (leftRunning !== rightRunning) return leftRunning ? -1 : 1;
    const leftTime = leftRunning ? left.activity.started_at : left.last_response_at;
    const rightTime = rightRunning ? right.activity.started_at : right.last_response_at;
    return String(rightTime || '').localeCompare(String(leftTime || ''));
  });
}

// Compact buckets, e.g. "2h ago" / "3d ago" - falls back to a plain
// date once it's old enough that a relative count stops being useful.
function formatRelativeTime(isoString) {
  const then = new Date(isoString).getTime();
  const diffSeconds = Math.max(0, (Date.now() - then) / 1000);
  if (diffSeconds < 60) return 'Just now';
  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const today = new Date();
  const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
  if (then >= yesterday.getTime()) return 'Yesterday';
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d ago`;
  return new Date(isoString).toLocaleDateString();
}

function renderChatHistory(rows) {
  chatListRows = sortChatRows(rows || []);
  let reloadSelected = false;
  for (const row of chatListRows) {
    const state = chatState(row.id);
    const wasRunning = state.activity?.status === 'running';
    const changedResponse = state.lastResponseAt !== undefined && state.lastResponseAt !== row.last_response_at;
    const changedRequest = state.activity?.request_id && row.activity?.request_id && state.activity.request_id !== row.activity.request_id;
    state.activity = row.activity || null;
    state.lastResponseAt = row.last_response_at;
    if (row.id === currentChatId && !state.launching) {
      // A connection can stall without throwing. Terminal list status also
      // reconciles that selected transcript, even with an outstanding read.
      const finished = wasRunning && state.activity?.status !== 'running' && !state.justCompleted;
      reloadSelected = finished || (!state.subscription && (state.needsReload ||
        (!state.justCompleted && (changedResponse || changedRequest))));
    }
    if (state.activity?.status !== 'running') state.justCompleted = false;
  }
  renderChatHistoryList(chatListRows);
  if (manageChatsVisible) renderManageChats();
  if (!manageChatsVisible && currentChatId && !chatLoading && chatInitialized) {
    if (reloadSelected) openChat(currentChatId, { reload: true });
    else if (chatState(currentChatId).activity?.status === 'running') subscribeToChat(currentChatId);
  }
  updateComposerForJob();
}

function renderChatHistoryList(chats) {
  const list = document.getElementById('chat-history-list');
  const existing = new Map([...list.children].filter(item => item.chatData).map(item => [item.chatData.id, item]));
  const interacting = [...existing.values()].some(item => item.contains(document.activeElement) ||
    item.querySelector('.chat-history-rename-input') ||
    (item.querySelector('.chat-history-action-menu') && !item.querySelector('.chat-history-action-menu').classList.contains('hidden')));
  for (const item of [...list.children]) {
    if (!item.chatData || !chats.some(chat => chat.id === item.chatData.id)) item.remove();
  }
  optimisticChatEntry = null;
  const availableIds = new Set(chats.map(chat => chat.id));
  for (const chatId of selectedChatIds) {
    if (!availableIds.has(chatId)) selectedChatIds.delete(chatId);
  }
  updateChatHistoryBulkActions();

  if (chats.length === 0) {
    list.innerHTML = '<p class="chat-history-empty">No chats yet.</p>';
    return;
  }

  for (const chat of chats) {
    let item = existing.get(chat.id);
    const menu = item?.querySelector('.chat-history-action-menu');
    const preserve = item && (item.contains(document.activeElement) || item.querySelector('.chat-history-rename-input') ||
      (menu && !menu.classList.contains('hidden')));
    if (!preserve) {
      const replacement = buildChatHistoryItem(chat);
      if (item) item.replaceWith(replacement);
      else list.appendChild(replacement);
      item = replacement;
    } else {
      item.chatData = chat;
      item.classList.toggle('active', chat.id === currentChatId);
      const link = item.querySelector('.chat-history-link');
      if (link) { link.textContent = chat.title; link.title = chat.title; }
      const time = item.querySelector('.chat-history-time');
      time.textContent = chat.last_response_at ? formatRelativeTime(chat.last_response_at) : 'No response yet';
      time.title = chat.last_response_at ? new Date(chat.last_response_at).toLocaleString() : 'No completed response yet';
      time.setAttribute('aria-label', 'Last response: ' + time.title);
    }
    // Moving a focused DOM node can blur it, so defer ordering during interaction.
    if (!interacting) list.appendChild(item);
  }
}

// Shown the instant a brand-new chat's first message is sent, before the
// server has confirmed anything - the real entry (with its real id,
// rename/delete controls, and link) replaces this via loadChatHistory()
// once the response lands. No href/controls here since there's nothing
// real yet to navigate to or act on.
function addOptimisticChatEntry(title) {
  const list = document.getElementById('chat-history-list');
  if (!list) return; // not on a page with the sidebar's chat-history panel

  const empty = list.querySelector('.chat-history-empty');
  if (empty) empty.remove();

  const item = document.createElement('div');
  item.className = 'chat-history-item active';

  // Task 4 replaces this reserved left-hand slot with the active spinner.
  // Keeping the geometry now prevents title movement when that happens.
  const actionSlot = document.createElement('div');
  actionSlot.className = 'chat-history-row-action-slot';
  actionSlot.setAttribute('role', 'status');
  actionSlot.setAttribute('aria-label', 'Response in progress');
  actionSlot.textContent = '⟳';
  item.appendChild(actionSlot);

  const text = document.createElement('div');
  text.className = 'chat-history-text';
  const titleEl = document.createElement('span');
  titleEl.className = 'chat-history-link';
  titleEl.textContent = title;
  text.appendChild(titleEl);
  item.appendChild(text);

  list.insertBefore(item, list.firstChild);
  optimisticChatEntry = item;
}

function removeOptimisticChatEntry() {
  if (optimisticChatEntry) {
    optimisticChatEntry.remove();
    optimisticChatEntry = null;
  }
}

function addChatActions(actionSlot, item, chat) {
  actionSlot.removeAttribute('aria-hidden');
  if (chat.activity?.status === 'running') {
    actionSlot.setAttribute('role', 'status');
    actionSlot.setAttribute('aria-label', `Response in progress for ${chat.title}`);
    actionSlot.textContent = '⟳';
    return;
  }
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'chat-history-action-btn';
  button.textContent = '…';
  button.title = `Actions for ${chat.title}`;
  button.setAttribute('aria-label', `Actions for ${chat.title}`);
  button.addEventListener('click', event => {
    event.stopPropagation();
    const menu = item.querySelector('.chat-history-action-menu');
    menu.classList.toggle('hidden');
    button.setAttribute('aria-expanded', String(!menu.classList.contains('hidden')));
  });
  const menu = document.createElement('div');
  menu.className = 'chat-history-action-menu hidden';
  const rename = document.createElement('button');
  rename.type = 'button'; rename.textContent = 'Rename';
  rename.addEventListener('click', event => { event.stopPropagation(); startRenameChat(item, item.chatData); });
  const remove = document.createElement('button');
  remove.type = 'button'; remove.textContent = 'Delete';
  remove.addEventListener('click', event => { event.stopPropagation(); deleteChatEntry(item.chatData); });
  const exportMd = document.createElement('button');
  exportMd.type = 'button'; exportMd.textContent = 'Export as .md';
  exportMd.addEventListener('click', event => {
    event.stopPropagation();
    menu.classList.add('hidden');
    button.setAttribute('aria-expanded', 'false');
    downloadChatMarkdown(item.chatData.id);
  });
  menu.append(rename, exportMd, remove);
  actionSlot.append(button, menu);
}

// The export route's Content-Disposition: attachment header (see
// __index__.py's export_chat_api) makes the browser download the file
// without leaving the page.
function downloadChatMarkdown(chatId) {
  if (!chatId) return;
  window.location.href = `/chat/api/chats/${encodeURIComponent(chatId)}/export`;
}

document.getElementById('chat-export-btn')?.addEventListener('click', () => downloadChatMarkdown(currentChatId));

function buildChatHistoryItem(chat) {
  const item = document.createElement('div');
  item.className = 'chat-history-item' + (chat.id === currentChatId ? ' active' : '');
  item.chatData = chat;

  // Running rows show their spinner; idle rows expose rename/delete here.
  const actionSlot = document.createElement('div');
  actionSlot.className = 'chat-history-row-action-slot';
  item.appendChild(actionSlot);
  addChatActions(actionSlot, item, chat);

  const text = document.createElement('div');
  text.className = 'chat-history-text';

  const link = document.createElement('a');
  link.className = 'chat-history-link';
  link.href = `/chat?id=${encodeURIComponent(chat.id)}`;
  link.textContent = chat.title;
  link.title = chat.title;
  link.addEventListener('click', event => { event.preventDefault(); openChat(chat.id); });
  text.appendChild(link);

  const time = document.createElement('span');
  time.className = 'chat-history-time';
  const responseAt = chat.last_response_at;
  const exactTime = responseAt ? new Date(responseAt).toLocaleString() : 'No completed response yet';
  time.textContent = responseAt ? formatRelativeTime(responseAt) : 'No response yet';
  time.title = exactTime;
  time.setAttribute('aria-label', 'Last response: ' + exactTime);
  text.appendChild(time);

  item.appendChild(text);

  const controls = document.createElement('div');
  controls.className = 'chat-history-controls';

  if (chatHistorySelectionMode) {
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'chat-history-select-checkbox';
    checkbox.checked = selectedChatIds.has(chat.id);
    checkbox.setAttribute('aria-label', `Select ${chat.title}`);
    checkbox.addEventListener('click', event => event.stopPropagation());
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) selectedChatIds.add(chat.id);
      else selectedChatIds.delete(chat.id);
      updateChatHistoryBulkActions();
    });
    controls.appendChild(checkbox);
  }

  item.appendChild(controls);

  // The whole row navigates to this chat, not just the title text -
  // except clicks on the rename/delete controls (handled above) or the
  // rename `<input>` that replaces the title while renaming (see
  // startRenameChat), and except the link itself, which already
  // navigates on its own via the browser's native anchor behavior.
  item.addEventListener('click', e => {
    if (e.target.closest('.chat-history-controls')) return;
    if (e.target.closest('.chat-history-rename-input')) return;
    if (e.target.closest('a.chat-history-link')) return;
    openChat(chat.id);
  });

  return item;
}

function startRenameChat(item, chat) {
  const link = item.querySelector('.chat-history-link');
  if (!link) return;
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'chat-history-rename-input';
  input.value = chat.title;
  input.setAttribute('aria-label', 'Rename ' + chat.title);
  link.replaceWith(input);
  input.focus();
  input.select();

  let settled = false;

  const commit = async () => {
    if (settled) return;
    settled = true;
    const newTitle = input.value.trim();
    input.replaceWith(link);
    if (newTitle && newTitle !== chat.title) {
      try {
        const res = await fetch(`/chat/api/chats/${encodeURIComponent(chat.id)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: newTitle }),
        });
        if (!res.ok) throw new Error(`Server responded with ${res.status}`);
      } catch (err) {
        // The list reload below shows the true (unrenamed) title either
        // way, which is enough feedback that the rename didn't take -
        // no separate error UI for a sidebar-scoped action this small.
      }
    }
    await loadChatHistory();
  };

  input.addEventListener('blur', commit);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') input.blur(); // triggers commit via the blur handler above
    if (e.key === 'Escape') {
      e.preventDefault();
      settled = true;
      input.replaceWith(link);
      link.focus();
      loadChatHistory();
    }
  });
}

async function deleteChatEntry(chat) {
  const confirmed = await confirmModal({
    title: 'Delete chat?',
    message: `Delete "${chat.title}"? This can't be undone.`,
    confirmLabel: 'Delete',
    danger: true,
  });
  if (!confirmed) return;

  try {
    // The server repeats this before deletion, but asking first makes the
    // intent explicit and gives a selected subscriber a terminal event.
    if (chat.activity?.status === 'running') {
      await fetch(`/chat/api/chats/${encodeURIComponent(chat.id)}/cancel`, { method: 'POST' });
    }
    const res = await fetch(`/chat/api/chats/${encodeURIComponent(chat.id)}`, { method: 'DELETE' });
    // A 404 here means it's already gone (e.g. deleted from another tab) -
    // treat that as success too, same as a clean 2xx.
    if (!res.ok && res.status !== 404) throw new Error(`Server responded with ${res.status}`);

    chatStates.delete(chat.id);
    selectedChatIds.delete(chat.id);
    if (chat.id === chatBeforeManaging) chatBeforeManaging = null;
    if (chat.id === currentChatId) {
      if (manageChatsVisible) currentChatId = null;
      else await openChat(null);
    }
    await loadChatHistory();
  } catch (err) {
    // Unlike a successful delete, this must NOT navigate away or refresh
    // the list - the chat record still exists server-side, so silently
    // proceeding would look like a successful delete when it wasn't.
    alert('Could not delete this chat: ' + err.message);
  }
}

async function deleteSelectedChatEntries() {
  const chatIds = [...selectedChatIds];
  if (!chatIds.length) return;
  const confirmed = await confirmModal({
    title: 'Delete selected chats?',
    message: `Delete ${chatIds.length} selected chat${chatIds.length === 1 ? '' : 's'}? This can't be undone.`,
    confirmLabel: 'Delete selected',
    danger: true,
  });
  if (!confirmed) return;

  try {
    await Promise.all(chatIds.map(chatId => {
      const row = chatListRows.find(chat => chat.id === chatId);
      return row?.activity?.status === 'running'
        ? fetch(`/chat/api/chats/${encodeURIComponent(chatId)}/cancel`, { method: 'POST' })
        : Promise.resolve();
    }));
    const res = await fetch('/chat/api/chats', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_ids: chatIds }),
    });
    if (!res.ok) throw new Error(`Server responded with ${res.status}`);
    const currentChatWasDeleted = currentChatId && chatIds.includes(currentChatId);
    chatIds.forEach(id => chatStates.delete(id));
    if (chatIds.includes(chatBeforeManaging)) chatBeforeManaging = null;
    selectedChatIds.clear();
    chatHistorySelectionMode = false;
    if (currentChatWasDeleted) {
      if (manageChatsVisible) currentChatId = null;
      else await openChat(null);
    }
    await loadChatHistory();
    updateChatHistoryBulkActions();
  } catch (err) {
    alert('Could not delete selected chats: ' + err.message);
  }
}

function ensureManageChatsPanel() {
  let panel = document.getElementById('chat-manage-panel');
  if (panel) return panel;
  panel = document.createElement('section');
  panel.id = 'chat-manage-panel';
  panel.className = 'chat-manage-panel hidden';
  document.getElementById('chat-main-view').appendChild(panel);
  return panel;
}

function renderManageChats() {
  const panel = ensureManageChatsPanel();
  if (!panel.querySelector('.chat-manage-list')) {
    const heading = document.createElement('h2'); heading.textContent = 'Manage Chats';
    const controls = document.createElement('div'); controls.className = 'chat-manage-controls';
    const selectAll = document.createElement('button'); selectAll.type = 'button'; selectAll.textContent = 'Select all';
    selectAll.addEventListener('click', () => { chatListRows.forEach(chat => selectedChatIds.add(chat.id)); renderManageChats(); });
    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Delete selected';
    remove.className = 'chat-manage-delete-selected';
    remove.addEventListener('click', deleteSelectedChatEntries);
    const done = document.createElement('button'); done.type = 'button'; done.textContent = 'Done';
    done.addEventListener('click', leaveManageChats);
    controls.append(selectAll, remove, done);
    const list = document.createElement('div'); list.className = 'chat-manage-list';
    panel.append(heading, controls, list);
  }
  const list = panel.querySelector('.chat-manage-list');
  const available = new Set(chatListRows.map(chat => chat.id));
  for (const id of selectedChatIds) if (!available.has(id)) selectedChatIds.delete(id);
  panel.querySelector('.chat-manage-delete-selected').disabled = !selectedChatIds.size;
  // Polling edits rows in place. A keyboard selection or rename keeps its
  // node and focus; movement is deferred for the duration of a live edit.
  const editing = !!list.querySelector('.chat-history-rename-input');
  const rows = new Map(Array.from(list.children, row => [row.chatData.id, row]));
  for (const chat of chatListRows) {
    let row = rows.get(chat.id);
    if (!row) {
      row = document.createElement('div'); row.className = 'chat-manage-row';
      const checkbox = document.createElement('input'); checkbox.type = 'checkbox';
      checkbox.addEventListener('change', () => {
        checkbox.checked ? selectedChatIds.add(row.chatData.id) : selectedChatIds.delete(row.chatData.id);
        panel.querySelector('.chat-manage-delete-selected').disabled = !selectedChatIds.size;
      });
      const title = document.createElement('span'); title.className = 'chat-history-link'; title.tabIndex = 0;
      const rename = document.createElement('button'); rename.type = 'button'; rename.textContent = 'Rename';
      rename.addEventListener('click', () => startRenameChat(row, row.chatData));
      const deleteOne = document.createElement('button'); deleteOne.type = 'button'; deleteOne.textContent = 'Delete';
      deleteOne.addEventListener('click', () => deleteChatEntry(row.chatData));
      row.append(checkbox, title, rename, deleteOne);
      list.appendChild(row);
    }
    row.chatData = chat;
    const checkbox = row.querySelector('input[type="checkbox"]');
    checkbox.checked = selectedChatIds.has(chat.id);
    checkbox.setAttribute('aria-label', 'Select ' + chat.title);
    const title = row.querySelector('.chat-history-link');
    if (title) { title.textContent = chat.title; title.title = chat.title; }
    rows.delete(chat.id);
  }
  for (const row of rows.values()) row.remove();
  if (!editing && !list.contains(document.activeElement)) {
    chatListRows.forEach((chat, index) => {
      const row = Array.from(list.children).find(item => item.chatData.id === chat.id);
      if (list.children[index] !== row) list.insertBefore(row, list.children[index] || null);
    });
  }
}

function showManageChats() {
  if (manageChatsVisible) return leaveManageChats();
  chatBeforeManaging = currentChatId;
  ++chatViewGeneration;
  chatLoading = false;
  manageChatsVisible = true;
  stopChatSubscription();
  closeExtPanel();
  setChatContentVisible(false);
  ensureManageChatsPanel().classList.remove('hidden');
  renderManageChats();
  updateComposerForJob();
}

async function leaveManageChats() {
  if (!manageChatsVisible) return;
  const restoreId = chatBeforeManaging;
  chatBeforeManaging = null;
  selectedChatIds.clear();
  if (restoreId && chatListRows.some(chat => chat.id === restoreId)) await openChat(restoreId, { reload: true });
  else await openChat(null);
}

// Restores the provider/model dropdowns to whatever this chat last used,
// set by loadChat() above - only once /api/providers has actually loaded
// (providersById), since that's what says whether the restored choice is
// still available at all. Silently does nothing (leaving the normal
// Automatic default) if the provider's gone, the specific model's gone,
// or either is just currently unavailable (missing key, rate-limited,
// not pulled) - restoring something unusable would be worse than the
// default.
function applyLastUsedModel() {
  if (!lastUsedProviderId || !lastUsedModelId) return;
  const provider = providersById[lastUsedProviderId];
  if (!provider || !provider.available) return;
  const model = (provider.models || []).find(m => m.id === lastUsedModelId);
  if (!model || !model.available) return;
  document.getElementById('provider').value = lastUsedProviderId;
  updateModelDropdown();
  document.getElementById('model').value = lastUsedModelId;
}

document.getElementById('q').addEventListener('input', e => {
  // A paste, drag-drop, or IME edit changes the box without going through
  // the keydown handler below - exit recall here too so the badge doesn't
  // linger over text that's no longer the recalled message.
  if (historyRecallIndex !== null) exitHistoryRecall(false);
  updateCommandSuggestions();
  autoResizeInput(e.target);
});
// Shell-style history recall: ArrowUp/ArrowDown on the composer walks
// backward/forward through every message this chat has actually sent to
// the LLM (not just the last one), with a "History N/M" badge (see
// #history-recall-badge) making clear the box is showing a past message,
// not a live draft. `index` is null while not recalling; otherwise an
// index into `historyRecallEntries` (oldest first), with `historyRecallDraft`
// holding whatever was typed before recall started so ArrowDown past the
// newest entry restores it instead of leaving the box on the last recalled
// message.
let historyRecallEntries = [];
let historyRecallIndex = null;
let historyRecallDraft = '';

function historyRecallBadge() {
  return document.getElementById('history-recall-badge');
}

function showHistoryRecall(index) {
  const q = document.getElementById('q');
  historyRecallIndex = index;
  q.value = historyRecallEntries[index];
  autoResizeInput(q);
  q.setSelectionRange(q.value.length, q.value.length);
  const badge = historyRecallBadge();
  badge.textContent = `History ${index + 1}/${historyRecallEntries.length}`;
  badge.classList.remove('hidden');
}

function exitHistoryRecall(restoreDraft) {
  if (historyRecallIndex === null) return;
  historyRecallIndex = null;
  historyRecallBadge().classList.add('hidden');
  if (restoreDraft) {
    const q = document.getElementById('q');
    q.value = historyRecallDraft;
    autoResizeInput(q);
    q.setSelectionRange(q.value.length, q.value.length);
  }
}

document.getElementById('q').addEventListener('keydown', e => {
  if (currentSuggestions.length) {
    if (e.key === 'ArrowDown') { e.preventDefault(); moveSuggestionActive(1); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); moveSuggestionActive(-1); return; }
    if (e.key === 'Tab' || e.key === 'Enter') { e.preventDefault(); acceptSuggestion(currentSuggestions[activeSuggestionIndex]); return; }
    if (e.key === 'Escape') { e.preventDefault(); hideCommandSuggestions(); return; }
  }
  if (e.key === 'ArrowUp' && (historyRecallIndex !== null || !e.target.value)) {
    e.preventDefault();
    if (historyRecallIndex === null) {
      // Freshly entering recall - snapshot the full sent-message list
      // (oldest first) and whatever the user had typed (empty, per the
      // guard above, but kept symmetric with exitHistoryRecall's restore).
      historyRecallEntries = history
        .filter(turn => turn.role === 'user')
        .map(turn => parseAttachmentMarkers(turn.content).mainText);
      if (!historyRecallEntries.length) return;
      historyRecallDraft = e.target.value;
      showHistoryRecall(historyRecallEntries.length - 1);
    } else if (historyRecallIndex > 0) {
      showHistoryRecall(historyRecallIndex - 1);
    }
    return;
  }
  if (e.key === 'ArrowDown' && historyRecallIndex !== null) {
    e.preventDefault();
    if (historyRecallIndex < historyRecallEntries.length - 1) {
      showHistoryRecall(historyRecallIndex + 1);
    } else {
      exitHistoryRecall(true);
    }
    return;
  }
  // Any other key while recalling means the user is editing the recalled
  // text directly - stop tracking it as a history position so further
  // typing isn't silently overwritten by a later ArrowUp/Down, and drop
  // the badge since the box no longer reflects that exact past message.
  if (historyRecallIndex !== null && e.key !== 'Shift' && e.key !== 'Enter') {
    exitHistoryRecall(false);
  }
  // Shift+Enter inserts a newline (the textarea's own default behavior,
  // left alone); plain Enter sends - e.preventDefault() stops it from
  // also inserting a newline right before send() clears the field.
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
document.getElementById('send-btn').addEventListener('click', () => {
  if (selectedJob()?.status === 'running') cancelSend();
  else send();
});

document.getElementById('attach-btn').addEventListener('click', () => {
  document.getElementById('attach-input').click();
});
document.getElementById('attach-input').addEventListener('change', e => {
  if (e.target.files.length) addAttachmentFiles(e.target.files);
  e.target.value = ''; // otherwise re-selecting the exact same file wouldn't fire 'change' a second time
});

// Drag-and-drop a file onto the whole chat area (log + composer, see
// .chat-dropzone in chat.html/styles.css) - dragenter/dragleave also fire
// on every child element underneath the cursor (event bubbling), so a
// plain enter/leave toggle would flicker .drag-active off and on as the
// cursor crosses between #log, #attach-chip-list and #row; a nesting
// counter only clears the highlight once the cursor has actually left
// every element of the zone.
let dragDepth = 0;
const chatDropzone = document.getElementById('chat-dropzone');
chatDropzone.addEventListener('dragenter', e => {
  e.preventDefault();
  dragDepth++;
  chatDropzone.classList.add('drag-active');
});
chatDropzone.addEventListener('dragover', e => e.preventDefault()); // required for 'drop' to fire at all
chatDropzone.addEventListener('dragleave', () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) chatDropzone.classList.remove('drag-active');
});
chatDropzone.addEventListener('drop', e => {
  e.preventDefault();
  dragDepth = 0;
  chatDropzone.classList.remove('drag-active');
  if (e.dataTransfer.files.length) addAttachmentFiles(e.dataTransfer.files);
});
document.getElementById('provider').addEventListener('change', () => {
  updateModelDropdown();
  // A different provider/model invalidates the last reading - its
  // token count and context window belonged to whatever was previously
  // selected. Falls straight back to the newly-selected provider's bare
  // context_window until its own next real turn reports usage.
  lastContextTokens = null;
  lastTurnIo = { input: null, output: null };
  lastContextWindow = null;
  refreshContextUsage();
});
document.getElementById('chat-history-toggle-btn').addEventListener('click', toggleChatHistoryPanel);

document.querySelector('.sidebar-new-chat-btn').addEventListener('click', event => {
  if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  openChat(null);
});
document.getElementById('chat-history-select-btn').addEventListener('click', showManageChats);
document.getElementById('ext-toggle-btn').addEventListener('click', toggleExtPanel);

// Caveman mode: terse AI replies. Sent with every chat request; the flag
// lives only in the browser (localStorage) - the server keeps no state.
const CAVEMAN_STORAGE_KEY = 'chat.caveman';
function cavemanEnabled() {
  return localStorage.getItem(CAVEMAN_STORAGE_KEY) === '1';
}
function renderCavemanToggle() {
  document.getElementById('caveman-toggle-btn').setAttribute('aria-pressed', String(cavemanEnabled()));
}
document.getElementById('caveman-toggle-btn').addEventListener('click', () => {
  localStorage.setItem(CAVEMAN_STORAGE_KEY, cavemanEnabled() ? '0' : '1');
  renderCavemanToggle();
});
renderCavemanToggle();
document.getElementById('ext-close-btn').addEventListener('click', closeExtPanel);
document.getElementById('ext-overlay').addEventListener('click', closeExtPanel);
document.getElementById('ext-add-form').addEventListener('submit', submitAddExtension);
document.getElementById('ext-add-error-help-toggle').addEventListener('click', () => {
  const list = document.getElementById('ext-add-error-help-list');
  const toggle = document.getElementById('ext-add-error-help-toggle');
  const expanding = list.classList.contains('hidden');
  list.classList.toggle('hidden');
  toggle.setAttribute('aria-expanded', String(expanding));
  toggle.textContent = expanding ? 'Hide' : 'Why might this happen?';
});

// Hydrate the dropdown from last tab's cache (if any) BEFORE the network
// round-trip below - this is what makes chat-switching/new-chat/delete
// (all real page navigations, see renderProviderOptions's comment above)
// feel instant instead of flashing "Loading providers..." every time.
const cachedProviders = loadProvidersFromCache();
const hasCachedProviders = !!cachedProviders;
if (cachedProviders) {
  providersById = Object.fromEntries(cachedProviders.map(p => [p.id, p]));
  renderProviderOptions(cachedProviders, null);
  refreshContextUsage(); // ring visible immediately off the cache, no network wait
}

// Disabled until the agent dropdown and any existing chat history have
// both finished their first load - sending earlier would let the user
// pick from a still-"Loading providers..." dropdown, or race loadChat()'s
// history.push() calls above with a message of their own. Re-enabled by
// the init IIFE below once both have resolved. Skipped for the dropdown
// half when a cache already rendered something usable above - only a
// genuinely first-ever load in this tab has nothing to show yet.
updateComposerForJob();
const initialLoadEl = appendMsg('system thinking',
  hasCachedProviders ? 'Loading chat history...' : 'Loading agents and chat history...');

// Captured, not fire-and-forget: the init block below awaits this same
// call (rather than firing a second /api/providers request) so
// providersById is populated before loadChat() renders any stored
// per-message model labels, and before applyLastUsedModel() runs. Kicked
// off regardless of the cache above - the cache is only for instant
// rendering, this is what actually validates/refreshes it against the
// live server.
const providersReady = loadProviders();
setInterval(loadProviders, 15000);

// Forces a config_agents.json re-read (an ai_agent instance started or
// stopped since page load - see loadProviders()'s `refresh` param) rather
// than waiting on the poll above, which only re-checks each already-known
// agent's live status.
document.getElementById('provider-refresh-btn').addEventListener('click', async () => {
  const btn = document.getElementById('provider-refresh-btn');
  btn.disabled = true;
  btn.classList.add('is-refreshing');
  try {
    await loadProviders(true);
  } finally {
    btn.disabled = false;
    btn.classList.remove('is-refreshing');
  }
});

loadExtensions();
setInterval(loadExtensions, 15000); // same cadence as the provider poll above

loadCommands();
setInterval(loadCommands, 15000); // same cadence as the extension poll above

// Hydrate the sidebar from last tab's cache (if any) BEFORE the network
// round-trip, same reasoning as the provider dropdown hydration above -
// removes the blank-then-refill flash on every chat-switch/delete/rename
// navigation.
const cachedChats = loadChatsFromCache();
if (cachedChats) {
  renderChatHistory(cachedChats);
}
updateChatHistoryBulkActions();

loadChatHistory();
setInterval(() => {
  if (!document.hidden) loadChatHistory();
}, 5000);

let chatHistoryCollapsedFromStorage = false;
try {
  chatHistoryCollapsedFromStorage = localStorage.getItem(CHAT_HISTORY_COLLAPSED_KEY) === '1';
} catch (err) {
  // Storage unavailable (private browsing) - default to expanded.
}
applyChatHistoryPanelCollapsed(chatHistoryCollapsedFromStorage);

// Only greet on a genuine fresh chat (no id in the URL, or the id
// turned out to be stale/foreign) - loadChat() itself replays every
// restored message, so this only decides whether a greeting is ALSO
// needed on top of that.
(async () => {
  // Only block on the network round-trip when there was nothing cached to
  // render already (see hasCachedProviders above) - otherwise the cached
  // dropdown from renderProviderOptions() is good enough to unblock on,
  // and loadProviders()'s own fetch (already in flight) will silently
  // refresh it in place whenever it lands.
  if (!hasCachedProviders) await providersReady;
  // User navigation during provider initialization owns the selected view.
  if (chatViewGeneration === 0) await openChat(currentChatId, { navigation: 'none' });
  initialLoadEl.remove();
  chatInitialized = true;
  updateComposerForJob();
})();
