const history = [];
let providerLabels = {}; // id -> label, used to render "answered by X"
let providersById = {};  // id -> full provider entry (incl. models), used to populate the model dropdown

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

async function loadExtensions() {
  const banner = document.getElementById('ext-error-banner');
  try {
    const res = await fetch('/api/extensions');
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
    const res = await fetch('/api/extensions', {
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
    const res = await fetch(`/api/extensions/${encodeURIComponent(ext.id)}`, { method: 'DELETE' });
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

async function loadProviders() {
  const providerSelect = document.getElementById('provider');
  const previousProvider = providerSelect.value; // preserve the user's choice across refreshes
  try {
    const res = await fetch('/api/providers');
    const providers = await res.json();
    providerLabels = Object.fromEntries(providers.map(p => [p.id, p.label]));
    providersById = Object.fromEntries(providers.map(p => [p.id, p]));

    providerSelect.innerHTML = '';
    for (const p of providers) {
      const opt = document.createElement('option');
      opt.value = p.id;
      if (p.available) {
        opt.textContent = p.label;
      } else if (p.reason === 'rate_limited') {
        opt.textContent = `${p.label} (rate-limited, ~${p.cooldown_seconds_remaining}s)`;
      } else if (p.reason === 'none_available') {
        opt.textContent = `${p.label} (nothing available)`;
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
    // only fall back to "first available" on first load or if their
    // pick disappeared entirely - since "auto" is always listed first
    // and is available whenever any real provider is, this naturally
    // defaults to Automatic on first load without special-casing it
    const stillExists = providers.some(p => p.id === previousProvider);
    if (stillExists) {
      providerSelect.value = previousProvider;
    } else {
      const firstAvailable = providers.find(p => p.available);
      if (firstAvailable) providerSelect.value = firstAvailable.id;
    }
    updateModelDropdown();
  } catch (err) {
    providerSelect.innerHTML = '<option>Could not load providers</option>';
  }
}

function updateModelDropdown() {
  const providerSelect = document.getElementById('provider');
  const modelSelect = document.getElementById('model');
  const provider = providersById[providerSelect.value];

  // Automatic doesn't take a model override (see router.py's run_chat
  // docstring for why) - hide the model picker entirely rather than
  // show one that silently does nothing.
  if (!provider || provider.id === 'auto' || !provider.models || provider.models.length === 0) {
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
// informative; the 15s escalation below is the one that actually tells
// you something new.
const THINKING_MESSAGES = [
  'Thinking...',
  'Working on it...',
  'Reasoning through the request...',
  'Checking in with the tools...',
  'Putting it together...',
  'Almost there...',
];

function pickThinkingMessage(exclude) {
  const options = THINKING_MESSAGES.filter(m => m !== exclude);
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

// total_tokens is defensive by design: the token-tracking work landing
// this in the response JSON is a separate, parallel change, and some
// providers/paths never report usage at all - undefined, null, and
// non-positive values all just mean "don't show a token count".
function formatTimerText(ms, totalTokens) {
  const base = formatElapsedTime(ms);
  if (typeof totalTokens === 'number' && totalTokens > 0) {
    return `${base} · ${totalTokens} tokens`;
  }
  return base;
}

function createTimerElement(text) {
  const el = document.createElement('div');
  el.className = 'msg-timer';
  el.textContent = text;
  return el;
}

async function send() {
  const input = document.getElementById('q');
  const question = input.value.trim();
  if (!question) return;

  const sendBtn = document.getElementById('send-btn');
  input.value = '';

  if (greetingEl) {
    greetingEl.remove();
    greetingEl = null;
  }
  // Only a chat with no id yet lacks a sidebar entry at all - an
  // existing chat is already listed, and its real ordering/timestamp
  // catches up once the response lands (see loadChatHistory() below).
  if (!currentChatId) {
    addOptimisticChatEntry(question);
  }

  appendMsg('user', question);
  const priorHistory = history.slice();
  history.push({ role: 'user', content: question });

  const selectedProvider = document.getElementById('provider').value;
  const modelSelect = document.getElementById('model');
  const selectedModel = modelSelect.classList.contains('hidden') ? null : modelSelect.value;

  // Visible "still working" state - previously there was NONE: no
  // indicator, no disabled input, and no try/catch around fetch() below,
  // so a genuine crash (chat_app down, MCP server unreachable) looked
  // identical to "still thinking" - silently hung forever with zero
  // feedback either way. Disabling input+button also stops a second
  // send firing mid-request.
  input.disabled = true;
  sendBtn.disabled = true;
  sendBtn.textContent = 'Sending...';
  const requestStartTime = Date.now();

  let currentThinkingText = pickThinkingMessage();
  const thinkingEl = appendMsg('system thinking', currentThinkingText);
  const rotateTimer = setInterval(() => {
    currentThinkingText = pickThinkingMessage(currentThinkingText); // never repeat the same one twice in a row
    thinkingEl.textContent = currentThinkingText;
  }, 3000);
  const slowNoticeTimer = setTimeout(() => {
    clearInterval(rotateTimer); // stop cycling - past this point it's genuinely informative, not just filler
    thinkingEl.textContent = 'Still working - this can take longer with local models or multi-step tool calls...';
  }, 15000);

  // Lives directly below the thinking bubble while the request is in
  // flight, ticking up once per second so the wait itself is visible -
  // not just the final duration after the fact. Gets relocated into the
  // assistant message wrapper on success (see below), or discarded on
  // failure since there's no reply bubble for it to live under.
  const timerEl = createTimerElement(formatElapsedTime(0));
  document.getElementById('log').appendChild(timerEl);
  const timerInterval = setInterval(() => {
    timerEl.textContent = formatElapsedTime(Date.now() - requestStartTime);
  }, 1000);

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        history: priorHistory,
        provider: selectedProvider,
        model: selectedModel,
        enabled_extensions: currentEnabledExtensions(),
        chat_id: currentChatId,
      }),
    });

    if (!res.ok) {
      // The server responded, but with a non-2xx status - a genuine
      // server-side failure, distinct from fetch() itself throwing
      // below (network-level: connection refused, DNS failure, etc).
      // /api/chat's normal provider-level errors (missing key, rate
      // limit) still come back as 200 + a "❌ ..." response string, and
      // are handled further down exactly as before - this only catches
      // the case where the server didn't respond meaningfully at all.
      throw new Error(`Server responded with ${res.status}`);
    }

    const data = await res.json();
    thinkingEl.remove();

    // When "Automatic" resolved to a specific provider, say which one -
    // otherwise the user has no way to know if it was ChatGPT or Claude.
    if (selectedProvider === 'auto' && data.provider_id) {
      const label = providerLabels[data.provider_id] || data.provider_id;
      const note = `Answered by ${label} (Automatic)`;
      appendMsg('system', note);
    }

    // Freeze the timer at the final elapsed value and fold in the token
    // count (if the parallel token-tracking work has landed and this
    // provider/path reported one), then relocate the same node into the
    // assistant bubble rather than creating a second element.
    const finalTimerText = formatTimerText(Date.now() - requestStartTime, data.total_tokens);
    timerEl.textContent = finalTimerText;
    const assistantWrap = appendMsg('assistant', data.response);
    assistantWrap.appendChild(timerEl);
    history.push({ role: 'assistant', content: data.response });

    // A brand-new chat just got its first id back, or an existing one
    // was confirmed - either way the sidebar list (Task 4) may now be
    // stale.
    if (data.chat_id && data.chat_id !== currentChatId) {
      currentChatId = data.chat_id;
      window.history.pushState(null, '', `/chat?id=${encodeURIComponent(currentChatId)}`);
    }
    if (data.chat_id) {
      loadChatHistory(); // also clears the optimistic placeholder - this fully re-renders the list
    } else {
      // Persistence failed server-side (see chat_api()'s save fallback) -
      // nothing was actually created, so the placeholder shouldn't stick
      // around implying otherwise.
      removeOptimisticChatEntry();
    }
  } catch (err) {
    thinkingEl.remove();
    timerEl.remove(); // no reply bubble to attach it to - the error message speaks for itself
    removeOptimisticChatEntry(); // the request never completed - nothing was created
    appendMsg('system', `⚠️ Request failed: ${err.message}. Check that chat_app and the MCP server are both still running.`);
  } finally {
    clearInterval(rotateTimer);
    clearTimeout(slowNoticeTimer);
    clearInterval(timerInterval);
    input.disabled = false;
    sendBtn.disabled = false;
    sendBtn.textContent = 'Send';
    input.focus();
  }
}

const ROLE_LABELS = { user: 'You', assistant: 'Assistant' };

function appendMsg(role, text) {
  const log = document.getElementById('log');
  const wrap = document.createElement('div');
  wrap.className = `msg ${role}`;

  // role can be a space-separated combo (e.g. "system thinking") - only
  // the first token decides how this renders.
  const primaryRole = role.split(' ')[0];

  if (primaryRole === 'user' || primaryRole === 'assistant') {
    const label = document.createElement('div');
    label.className = 'msg-label';
    label.textContent = ROLE_LABELS[primaryRole];
    wrap.appendChild(label);

    const content = document.createElement('div');
    content.className = 'msg-content';
    if (primaryRole === 'assistant') {
      renderMarkdown(content, text);
    } else {
      content.textContent = text;
    }
    wrap.appendChild(content);
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

async function loadChat(chatId) {
  try {
    const res = await fetch(`/api/chats/${encodeURIComponent(chatId)}`);
    if (!res.ok) {
      // Unknown or not-yours chat id - degrade to a fresh chat rather
      // than showing an error for what's just a stale/foreign link.
      currentChatId = null;
      window.history.replaceState(null, '', '/chat');
      return false;
    }
    const chat = await res.json();
    currentChatId = chat.id;
    for (const message of chat.messages) {
      appendMsg(message.role, message.content);
      history.push({ role: message.role, content: message.content });
    }
    return true;
  } catch (err) {
    currentChatId = null;
    window.history.replaceState(null, '', '/chat');
    return false;
  }
}

async function loadChatHistory() {
  const list = document.getElementById('chat-history-list');
  if (!list) return; // not on the chat page's sidebar variant - nothing to do
  try {
    const res = await fetch('/api/chats');
    const chats = await res.json();
    renderChatHistoryList(chats);
  } catch (err) {
    list.innerHTML = '<p class="chat-history-empty">Could not load chat history.</p>';
  }
}

// Compact buckets, e.g. "2h ago" / "3d ago" - falls back to a plain
// date once it's old enough that a relative count stops being useful.
function formatRelativeTime(isoString) {
  const then = new Date(isoString).getTime();
  const diffSeconds = Math.max(0, (Date.now() - then) / 1000);
  if (diffSeconds < 60) return 'just now';
  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d ago`;
  return new Date(isoString).toLocaleDateString();
}

function renderChatHistoryList(chats) {
  const list = document.getElementById('chat-history-list');
  list.innerHTML = ''; // also drops any optimistic placeholder still in the DOM
  optimisticChatEntry = null; // the reference above is now stale either way

  if (chats.length === 0) {
    list.innerHTML = '<p class="chat-history-empty">No chats yet.</p>';
    return;
  }

  for (const chat of chats) {
    list.appendChild(buildChatHistoryItem(chat));
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

function buildChatHistoryItem(chat) {
  const item = document.createElement('div');
  item.className = 'chat-history-item' + (chat.id === currentChatId ? ' active' : '');

  const text = document.createElement('div');
  text.className = 'chat-history-text';

  const link = document.createElement('a');
  link.className = 'chat-history-link';
  link.href = `/chat?id=${encodeURIComponent(chat.id)}`;
  link.textContent = chat.title;
  text.appendChild(link);

  const time = document.createElement('span');
  time.className = 'chat-history-time';
  time.textContent = formatRelativeTime(chat.updated_at);
  text.appendChild(time);

  item.appendChild(text);

  const controls = document.createElement('div');
  controls.className = 'chat-history-controls';

  const renameBtn = document.createElement('button');
  renameBtn.type = 'button';
  renameBtn.className = 'chat-history-rename-btn';
  renameBtn.setAttribute('aria-label', `Rename ${chat.title}`);
  renameBtn.textContent = '✎';
  renameBtn.addEventListener('click', () => startRenameChat(item, chat));
  controls.appendChild(renameBtn);

  const deleteBtn = document.createElement('button');
  deleteBtn.type = 'button';
  deleteBtn.className = 'chat-history-delete-btn';
  deleteBtn.setAttribute('aria-label', `Delete ${chat.title}`);
  deleteBtn.textContent = '×';
  deleteBtn.addEventListener('click', () => deleteChatEntry(chat));
  controls.appendChild(deleteBtn);

  item.appendChild(controls);
  return item;
}

function startRenameChat(item, chat) {
  const link = item.querySelector('.chat-history-link');
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'chat-history-rename-input';
  input.value = chat.title;
  link.replaceWith(input);
  input.focus();
  input.select();

  let settled = false;

  const commit = async () => {
    if (settled) return;
    settled = true;
    const newTitle = input.value.trim();
    if (newTitle && newTitle !== chat.title) {
      try {
        const res = await fetch(`/api/chats/${encodeURIComponent(chat.id)}`, {
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
      settled = true;
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
    const res = await fetch(`/api/chats/${encodeURIComponent(chat.id)}`, { method: 'DELETE' });
    // A 404 here means it's already gone (e.g. deleted from another tab) -
    // treat that as success too, same as a clean 2xx.
    if (!res.ok && res.status !== 404) throw new Error(`Server responded with ${res.status}`);

    if (chat.id === currentChatId) {
      location.href = '/chat';
      return;
    }
    await loadChatHistory();
  } catch (err) {
    // Unlike a successful delete, this must NOT navigate away or refresh
    // the list - the chat record still exists server-side, so silently
    // proceeding would look like a successful delete when it wasn't.
    alert('Could not delete this chat: ' + err.message);
  }
}

document.getElementById('q').addEventListener('keydown', e => {
  if (e.key === 'Enter') send();
});
document.getElementById('provider').addEventListener('change', updateModelDropdown);
document.getElementById('ext-toggle-btn').addEventListener('click', toggleExtPanel);
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

loadProviders();
setInterval(loadProviders, 15000);

loadExtensions();
setInterval(loadExtensions, 15000); // same cadence as the provider poll above

loadChatHistory();

// Only greet on a genuine fresh chat (no id in the URL, or the id
// turned out to be stale/foreign) - loadChat() itself replays every
// restored message, so this only decides whether a greeting is ALSO
// needed on top of that.
(async () => {
  const restored = currentChatId ? await loadChat(currentChatId) : false;
  if (!restored) {
    const greeting = pickGreetingMessage();
    greetingEl = appendMsg('assistant', greeting);
  }
})();