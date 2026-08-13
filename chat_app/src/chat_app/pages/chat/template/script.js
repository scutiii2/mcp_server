const history = [];
let providerLabels = {}; // id -> label, used to render "answered by X"
let providersById = {};  // id -> full provider entry (incl. models), used to populate the model dropdown

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
      } else {
        opt.textContent = `${p.label} (no API key)`;
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
    opt.textContent = m.label;
    modelSelect.appendChild(opt);
  }
  const stillExists = provider.models.some(m => m.id === previousModel);
  modelSelect.value = stillExists ? previousModel : provider.default_model_id;
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

async function send() {
  const input = document.getElementById('q');
  const question = input.value.trim();
  if (!question) return;

  const sendBtn = document.getElementById('send-btn');
  input.value = '';
  appendMsg('user', question);
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

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, history, provider: selectedProvider, model: selectedModel }),
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
      appendMsg('system', `Answered by ${label} (Automatic)`);
    }

    appendMsg('assistant', data.response);
    history.push({ role: 'assistant', content: data.response });
  } catch (err) {
    thinkingEl.remove();
    appendMsg('system', `⚠️ Request failed: ${err.message}. Check that chat_app and the MCP server are both still running.`);
  } finally {
    clearInterval(rotateTimer);
    clearTimeout(slowNoticeTimer);
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

document.getElementById('q').addEventListener('keydown', e => {
  if (e.key === 'Enter') send();
});
document.getElementById('provider').addEventListener('change', updateModelDropdown);

loadProviders();
setInterval(loadProviders, 15000);