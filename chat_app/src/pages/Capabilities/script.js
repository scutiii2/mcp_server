// --- Extension groups ---------------------------------------------------
// Shares its enabled/disabled state with the chat page's extensions
// sidebar via the SAME localStorage key and JSON-array-of-ids shape (see
// chat/template/script.js's EXT_STORAGE_KEY / loadEnabledExtensionsFromStorage
// / buildExtensionItem) - both pages are same-origin, so no extra plumbing
// is needed beyond reusing the identical key name. Toggling an extension
// here changes exactly the same "offered to the model in chat" state as
// toggling it in chat's sidebar, and additionally decides whether this
// page shows or hides that extension's tool cards.
const EXT_STORAGE_KEY = 'chat.enabledExtensions';

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

function saveEnabledExtensionsToStorage(enabledExtensions) {
  try {
    localStorage.setItem(EXT_STORAGE_KEY, JSON.stringify([...enabledExtensions]));
  } catch (err) {
    // Quota exceeded / storage disabled - the toggle still works for this
    // page load, it just won't survive a reload. Not worth surfacing.
  }
}

let enabledExtensions = loadEnabledExtensionsFromStorage();

// Renders a single group's body according to its enabled state - swaps
// between the real tool cards (already server-rendered into
// .ext-group-tools) and a placeholder message, without touching the
// group's open/closed state, which is a fully independent axis.
function renderExtGroupBody(group) {
  const enabled = enabledExtensions.has(group.dataset.extensionId);
  const toolsEl = group.querySelector('.ext-group-tools');
  const placeholderEl = group.querySelector('.ext-group-placeholder');
  const count = toolsEl.querySelectorAll(':scope > .tool').length;

  if (enabled) {
    toolsEl.style.display = '';
    placeholderEl.style.display = 'none';
  } else {
    toolsEl.style.display = 'none';
    placeholderEl.textContent = `Disabled — turn on to see its ${count} tool${count === 1 ? '' : 's'}.`;
    placeholderEl.style.display = 'block';
  }
}

function initExtGroups() {
  const groups = document.querySelectorAll('.ext-group');
  for (const group of groups) {
    const extId = group.dataset.extensionId;
    const checkbox = group.querySelector('.ext-group-toggle');
    const switchLabel = group.querySelector('.ext-switch');
    const header = group.querySelector('.ext-group-header');

    checkbox.checked = enabledExtensions.has(extId);
    renderExtGroupBody(group);

    checkbox.addEventListener('change', () => {
      if (checkbox.checked) {
        enabledExtensions.add(extId);
      } else {
        enabledExtensions.delete(extId);
      }
      saveEnabledExtensionsToStorage(enabledExtensions);
      renderExtGroupBody(group);
    });

    // The toggle (and its slider label) must never also fire the header's
    // expand/collapse handler below - they're independent controls that
    // happen to share a row.
    switchLabel.addEventListener('click', event => event.stopPropagation());

    header.addEventListener('click', () => {
      group.classList.toggle('open');
    });
  }
}

initExtGroups();

// --- Top-level Tools/Resources accordions --------------------------------
// Same open/closed mechanics as the per-extension groups above (toggle an
// .open class on click), just one level up and starting pre-opened so the
// page still shows everything by default - this is purely an option to
// collapse a section, not a default hide.
function initCapabilitySections() {
  const sections = document.querySelectorAll('.capability-section');
  for (const section of sections) {
    const header = section.querySelector('.capability-section-header');
    header.addEventListener('click', () => {
      section.classList.toggle('open');
    });
  }
}

initCapabilitySections();

// --- Per-capability accordion groups (built-in tools/resources) ---------
// Groups built-in tools/resources by capability (e.g. "Host Health",
// "OTP") - see tool_capabilities.py. Same open/closed mechanics as
// .ext-group above (toggle .open on header click), collapsed by default
// for visual consistency with the extension groups sitting right below
// them in the Tools section. Unlike .ext-group, there's no toggle switch
// or status dot to wire up - built-ins have no enabled/disabled concept
// and no connection status, so this is simpler than initExtGroups().
function initCapabilityGroups() {
  const groups = document.querySelectorAll('.capability-group');
  for (const group of groups) {
    const header = group.querySelector('.capability-group-header');
    header.addEventListener('click', () => {
      group.classList.toggle('open');
    });
  }
}

initCapabilityGroups();

// --- Tool/resource card toggles and forms --------------------------------
// Moved out of inline onclick/onsubmit attributes (which this app's CSP
// blocks - see config_security_headers.json) into addEventListener calls,
// same mechanics as initExtGroups/initCapabilitySections above. tool.name
// now reaches this code through an HTML attribute (data-toggle-target /
// data-tool-name), which Jinja's autoescaping protects - not through an
// inline JS string literal, which it doesn't.
function initToolCardToggles() {
  const headers = document.querySelectorAll('.tool-header[data-toggle-target]');
  for (const header of headers) {
    header.addEventListener('click', () => {
      const target = document.getElementById(header.dataset.toggleTarget);
      if (target) target.classList.toggle('open');
    });
  }
}

initToolCardToggles();

function initToolForms() {
  const runForms = document.querySelectorAll('form.tool-run-form');
  for (const form of runForms) {
    form.addEventListener('submit', event => runTool(event, form.dataset.toolName));
  }

  const readForms = document.querySelectorAll('form.resource-read-form');
  for (const form of readForms) {
    const params = JSON.parse(form.dataset.params || '[]');
    form.addEventListener('submit', event => readResourceForm(event, form.dataset.uriTemplate, params));
  }
}

initToolForms();

async function runTool(event, toolName) {
  event.preventDefault();
  const form = event.target;
  const container = form.closest('.tool');
  const pre = container.querySelector('.result');
  const args = {};
  new FormData(form).forEach((value, key) => { if (value !== '') args[key] = value; });

  pre.style.display = 'block';
  pre.textContent = 'Running...';
  try {
    const res = await fetch(`/capabilities/api/try/${encodeURIComponent(toolName)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(args),
    });
    const data = await res.json();
    pre.textContent = data.status === 'ok' ? data.result : `Error: ${data.message}`;
  } catch (err) {
    pre.textContent = `Request failed: ${err}`;
  }
  return false;
}

async function readResourceForm(event, uriTemplate, params) {
  event.preventDefault();
  const form = event.target;
  const container = form.closest('.tool');
  const pre = container.querySelector('.result');

  // Substitute each {param} placeholder with the matching form field's
  // value, building a concrete URI from the template - the resource
  // equivalent of collecting a tool's arguments into a JSON body.
  let uri = uriTemplate;
  for (const p of params) {
    const field = form.querySelector(`[name="${p}"]`);
    uri = uri.replace(`{${p}}`, encodeURIComponent(field ? field.value : ''));
  }

  pre.style.display = 'block';
  pre.textContent = 'Reading...';
  try {
    const res = await fetch('/capabilities/api/read-resource', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uri }),
    });
    const data = await res.json();
    pre.textContent = data.status === 'ok' ? data.result : `Error: ${data.message}`;
  } catch (err) {
    pre.textContent = `Request failed: ${err}`;
  }
  return false;
}
