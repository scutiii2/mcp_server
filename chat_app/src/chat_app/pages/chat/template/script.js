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

async function send() {
  const input = document.getElementById('q');
  const question = input.value.trim();
  if (!question) return;
  input.value = '';
  appendMsg('user', question);
  history.push({ role: 'user', content: question });

  const selectedProvider = document.getElementById('provider').value;
  const modelSelect = document.getElementById('model');
  const selectedModel = modelSelect.classList.contains('hidden') ? null : modelSelect.value;

  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, history, provider: selectedProvider, model: selectedModel }),
  });
  const data = await res.json();

  // When "Automatic" resolved to a specific provider, say which one -
  // otherwise the user has no way to know if it was ChatGPT or Claude.
  if (selectedProvider === 'auto' && data.provider_id) {
    const label = providerLabels[data.provider_id] || data.provider_id;
    appendMsg('system', `Answered by ${label} (Automatic)`);
  }

  appendMsg('assistant', data.response);
  history.push({ role: 'assistant', content: data.response });
}

function appendMsg(role, text) {
  const log = document.getElementById('log');
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  div.textContent = (role === 'user' ? 'You: ' : '') + text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

document.getElementById('q').addEventListener('keydown', e => {
  if (e.key === 'Enter') send();
});
document.getElementById('provider').addEventListener('change', updateModelDropdown);

loadProviders();
setInterval(loadProviders, 15000);
