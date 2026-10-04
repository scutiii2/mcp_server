// Browser behavior tests without an npm dependency. The small DOM double models
// node identity, focus, event dispatch and the selectors used by these controls.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/pages/Chat/script.js'), 'utf8');

class Element {
  constructor(tag, doc) { this.tagName = tag; this.doc = doc; this.children = []; this.attributes = {}; this.listeners = {}; this.className = ''; this.value = ''; this.textContent = ''; this.disabled = false; }
  get classList() {
    return {
      contains: c => this.className.split(' ').includes(c),
      add: (...cs) => { this.className = [...new Set([...this.className.split(' ').filter(Boolean), ...cs])].join(' '); },
      remove: (...cs) => { this.className = this.className.split(' ').filter(c => !cs.includes(c)).join(' '); },
      toggle: (c, force) => { const on = force ?? !this.classList.contains(c); on ? this.classList.add(c) : this.classList.remove(c); return on; },
    };
  }
  set innerHTML(value) { this.children.forEach(c => c.parent = null); this.children = []; this.html = value; }
  get innerHTML() { return this.html || ''; }
  appendChild(child) { child.remove(); this.children.push(child); child.parent = this; return child; }
  append(...children) { children.forEach(c => this.appendChild(c)); }
  insertBefore(child, before) { child.remove(); const index = before ? this.children.indexOf(before) : this.children.length; this.children.splice(index, 0, child); child.parent = this; }
  remove() { if (this.parent) { this.parent.children.splice(this.parent.children.indexOf(this), 1); this.parent = null; } }
  replaceWith(other) { const p = this.parent; const i = p.children.indexOf(this); this.parent = null; other.parent = p; p.children[i] = other; }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  removeAttribute(k) { delete this.attributes[k]; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  async emit(type, extras = {}) { for (const fn of this.listeners[type] || []) await fn({ target: this, preventDefault() {}, stopPropagation() {}, ...extras }); }
  focus() { this.doc.activeElement = this; }
  select() { this.selectionStart = 0; this.selectionEnd = this.value.length; }
  blur() { this.doc.activeElement = null; return this.emit('blur'); }
  contains(el) { return this === el || this.children.some(child => child.contains(el)); }
  matches(selector) {
    if (selector.startsWith('.')) return this.classList.contains(selector.slice(1));
    if (selector.startsWith('#')) return this.id === selector.slice(1);
    if (selector === 'input[type="checkbox"]') return this.tagName === 'input' && this.type === 'checkbox';
    return this.tagName === selector;
  }
  querySelectorAll(selector) { return this.children.flatMap(c => [...(c.matches(selector) ? [c] : []), ...c.querySelectorAll(selector)]); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  get isConnected() { return !!this.parent; }
  get lastElementChild() { return this.children.at(-1) || null; }
}

function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; }
function reply(data, ok = true) { return { ok, status: ok ? 200 : 500, json: async () => data }; }
function chat(id, text = id) { return { id, messages: [{ role: 'user', content: text }], last_response_at: '2026-09-17T10:00:10Z' }; }
function row(id, status, stamp = '2026-09-15T12:00:00Z') { return { id, title: id, last_response_at: stamp, updated_at: '2026-09-17T12:00:00Z', activity: status ? { status, request_id: id + '-job' } : null }; }
function setup() {
  const doc = { activeElement: null, createElement(tag) { return new Element(tag, this); } };
  const ids = {};
  doc.getElementById = id => ids[id] || doc.root.querySelector('#' + id);
  doc.root = new Element('body', doc);
  for (const id of ['chat-main-view', 'chat-dropzone', 'log', 'q', 'send-btn', 'attach-btn', 'provider', 'model', 'chat-history-list', 'ext-overlay']) {
    const el = new Element('div', doc); el.id = id; ids[id] = el; doc.root.appendChild(el);
  }
  const top = new Element('div', doc); top.className = 'toprow'; ids['chat-main-view'].append(top, ids['chat-dropzone'], ids['ext-overlay']);
  ids['ext-overlay'].classList.add('hidden');
  doc.querySelector = selector => selector === '#chat-main-view > .toprow' ? top : doc.root.querySelector(selector);
  const ctx = vm.createContext({
    document: doc, console, AbortController, TextDecoder, TextEncoder, URLSearchParams,
    crypto: { randomUUID: () => 'request' },
    window: { location: { search: '' }, history: { pushState() {}, replaceState() {} } },
    setInterval: () => 1, setTimeout: () => 1, clearInterval() {}, clearTimeout() {},
    fetch: async url => { throw Error('Unexpected fetch: ' + url); },
    alert: () => {}, confirmModal: async () => true,
  });
  vm.runInContext("const history = []; const chatStates = new Map(); let currentChatId = null, activeSubscription = null, manageChatsVisible = false, chatBeforeManaging = null, chatInitialized = true, chatLoading = false, chatViewGeneration = 0, newChatLaunch = null, greetingEl = null, optimisticChatEntry = null, lastUsedProviderId = null, lastUsedModelId = null, lastContextTokens = null, lastContextWindow = null, pendingAttachments = [], chatListRows = [], chatHistorySelectionMode = false, chatHistoryRequestId = 0; const selectedChatIds = new Set(), _traceRows = new Map(); const THINKING_MESSAGES = ['Thinking'], LONG_WAIT_MESSAGES = ['Still thinking'];", ctx);
  const functions = ['chatState', 'selectedJob', 'composerBlocked', 'updateComposerForJob', 'startChatJob', 'stopChatSubscription', 'createLiveReply', 'subscribeToChat', 'send', 'loadChat', 'openChat', 'setChatContentVisible', 'sortChatRows', 'formatRelativeTime', 'renderChatHistory', 'renderChatHistoryList', 'buildChatHistoryItem', 'addChatActions', 'startRenameChat', 'ensureManageChatsPanel', 'renderManageChats', 'showManageChats', 'leaveManageChats', 'deleteChatEntry', 'deleteSelectedChatEntries', 'appendTrace', 'traceStepStart', 'traceStepEnd', 'finalizeTrace', 'truncateArgs', 'loadChatHistory'];
  for (const name of functions) {
    const match = source.match(new RegExp('^(?:async )?function ' + name + '\\([^]*?^}', 'm'));
    assert.ok(match, name);
    vm.runInContext(match[0], ctx);
  }
  vm.runInContext(source.match(/^function restoreChatFromLocation\([^]*?^}/m)[0], ctx);
  const calls = [];
  Object.assign(ctx, {
    appendMsg(role, text) {
      calls.push([role, text]); const wrap = doc.createElement('div'); wrap.className = 'msg ' + role;
      const content = doc.createElement('div'); content.className = 'msg-content'; content.textContent = text; wrap.append(content);
      ids.log.append(wrap); return wrap;
    },
    buildWelcome(text) { const el = doc.createElement('div'); el.className = 'chat-welcome'; el.textContent = text; return el; },
    createTimerElement(text) { const timer = doc.createElement('span'); timer.className = 'msg-timer'; timer.textContent = text; return timer; },
    renderMarkdown(el, text) { el.textContent = text; },
    pickMessage: pool => pool[0], pickGreetingMessage: () => 'Greeting',
    formatElapsedTime: ms => 'elapsed ' + ms, formatTimerText: (...args) => args.join('|'), formatCommandTimerText: (...args) => 'command|' + args.join('|'),
    modelLabel: (provider, model) => provider + '/' + model,
    playNotificationSound: () => calls.push(['sound']), refreshContextUsage() {}, applyLastUsedModel() {},
    autoResizeInput() {}, hideCommandSuggestions() {}, exitHistoryRecall() {}, renderAttachChips() {},
    buildAttachmentBlocks: () => [], currentEnabledExtensions: () => [], isTokenSaverEnabled: () => false,
    addOptimisticChatEntry() {}, removeOptimisticChatEntry() {}, updateChatHistoryBulkActions() {},
    saveChatsToCache() {}, closeExtPanel: () => ids['ext-overlay'].classList.add('hidden'),
  });
  return { ctx, doc, ids, calls, run: code => vm.runInContext(code, ctx) };
}

test('out-of-order loads and stale errors cannot replace a newer view; sending is blocked while loading', async () => {
  const h = setup(), a = deferred(), b = deferred();
  h.ctx.fetch = url => url.endsWith('/a') ? a.promise : b.promise;
  const first = h.ctx.openChat('a'), second = h.ctx.openChat('b');
  h.ids.q.value = 'must not send';
  await h.ctx.send();
  assert.equal(h.ids['send-btn'].disabled, true);
  b.resolve(reply(chat('b'))); await second;
  a.resolve(reply({}, false)); await first;
  assert.equal(h.run('currentChatId'), 'b');
  assert.deepEqual(h.calls.map(x => x[1]), ['b']);
  assert.equal(h.run('history[0].content'), 'b');
  assert.equal(h.ids.q.disabled, false);
});

test('stale successful load is ignored after New Chat and management navigation', async () => {
  for (const navigate of [h => h.ctx.openChat(null), h => h.ctx.showManageChats()]) {
    const h = setup(), pending = deferred(); h.ctx.fetch = () => pending.promise;
    const loading = h.ctx.openChat('old'); await navigate(h);
    pending.resolve(reply(chat('old'))); await loading;
    assert.ok(!h.calls.some(call => call[1] === 'old'));
    assert.equal(h.run('chatLoading'), false);
  }
});

test('duplicate launch is blocked and a delayed new-chat acknowledgement never steals focus', async () => {
  const h = setup(), pending = deferred(); let posts = 0;
  h.ctx.loadChatHistory = () => {};
  h.ctx.fetch = () => { posts++; return pending.promise; };
  h.ids.q.value = 'first'; const first = h.ctx.send();
  h.ids.q.value = 'duplicate'; await h.ctx.send();
  assert.equal(posts, 1); assert.equal(h.ids.q.disabled, true);
  await h.ctx.openChat(null);
  pending.resolve(reply({ chat_id: 'created' })); await first;
  assert.equal(h.run('currentChatId'), null);
  assert.equal(h.run("chatState('created').activity.status"), 'running');
  assert.equal(h.run('history.length'), 0);
});

test('a failed launch only rolls back its captured history, not a newly opened chat', async () => {
  const h = setup(), pending = deferred();
  h.ctx.fetch = url => url === '/chat/api/chat' ? pending.promise : Promise.resolve(reply(chat('b')));
  h.ids.q.value = 'first'; const sending = h.ctx.send();
  await h.ctx.openChat('b'); pending.reject(Error('old failure')); await sending;
  assert.equal(h.run('history[0].content'), 'b');
  assert.ok(!h.calls.some(call => String(call[1]).includes('old failure')));
});

test('composer combines startup, loading, launch, management, and running state', () => {
  const h = setup();
  for (const flag of ['chatInitialized = false', 'chatLoading = true', 'newChatLaunch = {}', 'manageChatsVisible = true']) {
    h.run('chatInitialized = true; chatLoading = false; newChatLaunch = null; manageChatsVisible = false; ' + flag);
    h.ctx.updateComposerForJob();
    assert.equal(h.ids.q.disabled, true); assert.equal(h.ids['send-btn'].disabled, true);
  }
  h.run("chatInitialized = true; chatLoading = false; newChatLaunch = null; manageChatsVisible = false; currentChatId = 'a'; chatState('a').activity = { status: 'running' };");
  h.ctx.updateComposerForJob();
  assert.equal(h.ids.q.disabled, true); assert.equal(h.ids['send-btn'].disabled, false); assert.equal(h.ids['send-btn'].textContent, 'Stop');
});

test('polling clears vanished activity and reloads a completed response after disconnection', () => {
  const h = setup(); const opened = [];
  h.ctx.openChat = id => opened.push(id);
  h.run("currentChatId = 'a'; chatState('a').activity = { status: 'running' }; chatState('a').needsReload = true;");
  h.ctx.renderChatHistory([row('a', null)]);
  assert.equal(h.run("chatState('a').activity"), null);
  assert.deepEqual(opened, ['a']);
  assert.equal(h.ids['send-btn'].textContent, 'Send');
});

test('already-selected chat click reloads and resubscribes with a fresh cursor', async () => {
  const h = setup(); let subscribed = null;
  h.run("currentChatId = 'a'; chatState('a').activity = { status: 'running' }; chatState('a').sequence = 20;");
  h.ctx.fetch = async () => reply(chat('a')); h.ctx.subscribeToChat = id => { subscribed = id; };
  await h.ctx.openChat('a');
  assert.equal(subscribed, 'a'); assert.equal(h.run("chatState('a').sequence"), 0);
});

test('SSE disconnect and clean EOF both schedule transcript reconciliation', async () => {
  for (const failure of [false, true]) {
    const h = setup();
    h.run("currentChatId = 'a'; chatState('a').activity = { status: 'running' };");
    h.ctx.fetch = async () => ({ ok: true, body: { getReader: () => ({ read: async () => { if (failure) throw Error('disconnected'); return { done: true }; } }) } });
    await h.ctx.subscribeToChat('a');
    assert.equal(h.run("chatState('a').needsReload"), true);
    assert.equal(h.run("chatState('a').subscription"), null);
  }
});

test('subscriber renders token, tool trace, final metadata and one completion notification', async () => {
  const h = setup();
  h.ctx.loadChatHistory = () => {};
  h.ctx.loadChat = async () => true;
  h.run("currentChatId = 'a'; chatState('a').activity = { status: 'running' };");
  const events = [
    { type: 'step_start', id: 'tool', tool: 'lookup', arguments: { key: 1 }, sequence: 1 },
    { type: 'step_end', id: 'tool', ok: true, result: 'found', sequence: 2 },
    { type: 'token', text: 'partial', sequence: 3 },
    { type: 'final', response: 'complete', elapsed_seconds: 2, total_tokens: 14, context_tokens: 8, context_window: 100, provider_id: 'p', model: 'm', chat_id: 'a', failed: false, sequence: 4 },
  ];
  let read = false;
  h.ctx.fetch = async () => ({ ok: true, body: { getReader: () => ({ read: async () => read ? { done: true } : (read = true, { value: new TextEncoder().encode(events.map(e => 'data: ' + JSON.stringify(e) + '\n\n').join('')), done: false }) }) } });
  await h.ctx.subscribeToChat('a');
  assert.equal(h.ids.log.querySelector('.msg-trace-summary').textContent, 'Ran 1 tool');
  assert.equal(h.ids.log.querySelector('.msg-trace').open, false);
  assert.equal(h.ids.log.querySelector('.trace-step-detail').textContent.includes('found'), true);
  assert.equal(h.ids.log.querySelector('.msg-content').textContent, 'complete');
  assert.equal(h.ids.log.querySelector('.msg-timer').textContent, '2000|14|p/m|');
  assert.equal(h.run('lastContextTokens'), 8); assert.equal(h.run('history[0].total_tokens'), 14);
  assert.equal(h.calls.filter(c => c[0] === 'sound').length, 1);
});

test('sidebar rename draft and focus survive polling; response timestamp and title are accessible', async () => {
  const h = setup(); h.ctx.renderChatHistory([row('a', null)]);
  const item = h.ids['chat-history-list'].children[0];
  assert.equal(item.querySelector('.chat-history-link').title, 'a');
  const time = item.querySelector('.chat-history-time');
  assert.equal(time.title, new Date(row('a').last_response_at).toLocaleString());
  assert.ok(time.attributes['aria-label'].startsWith('Last response:'));
  h.ctx.startRenameChat(item, row('a'));
  const input = item.querySelector('.chat-history-rename-input'); input.value = 'unfinished draft'; input.selectionStart = 4;
  h.ctx.renderChatHistory([row('a', 'running')]);
  assert.equal(h.doc.activeElement, input); assert.equal(input.value, 'unfinished draft'); assert.equal(input.selectionStart, 4);
});

test('sidebar focus and an open actions menu survive polling, without duplicate controls', async () => {
  const h = setup(); h.ctx.renderChatHistory([row('a'), row('b')]);
  const item = h.ids['chat-history-list'].children[0];
  const actions = item.querySelector('.chat-history-action-btn');
  actions.focus(); await actions.emit('click');
  const menu = item.querySelector('.chat-history-action-menu');
  h.ctx.renderChatHistory([row('b'), { ...row('a'), title: 'New title' }]);
  assert.equal(h.doc.activeElement, actions);
  assert.equal(item.querySelector('.chat-history-action-menu'), menu);
  assert.equal(menu.classList.contains('hidden'), false);
  assert.equal(item.querySelector('.chat-history-link').title, 'New title');
  assert.equal(item.querySelectorAll('.chat-history-rename-btn').length, 0);
  assert.equal(item.querySelectorAll('.chat-history-delete-btn').length, 0);
  assert.equal(item.querySelector('.chat-history-export-btn').href, '/chat/api/chats/a/export');
  // Keyboard focus on a closed menu or link must also retain its DOM node.
  await actions.emit('click');
  const link = item.querySelector('.chat-history-link'); link.focus();
  h.ctx.renderChatHistory([row('a'), row('b')]);
  assert.equal(h.doc.activeElement, link);
  assert.equal(h.ids['chat-history-list'].children[0], item);
});

test('automatic refreshes and browser Back/Forward do not push navigation entries', async () => {
  const h = setup(), pushed = [];
  h.ctx.window.history.pushState = (_, __, url) => pushed.push(url);
  h.ctx.fetch = async url => reply(chat(url.endsWith('/b') ? 'b' : 'a'));
  await h.ctx.openChat('a');
  await h.ctx.openChat('a', { reload: true });
  h.ctx.window.location.search = '?id=b';
  await h.ctx.restoreChatFromLocation();
  assert.equal(h.run('currentChatId'), 'b');
  h.ctx.window.location.search = '';
  await h.ctx.restoreChatFromLocation();
  assert.equal(h.run('currentChatId'), null);
  assert.deepEqual(pushed, ['/chat?id=a']);
  assert.match(source, /window\.addEventListener\('popstate', restoreChatFromLocation\)/);
});

test('a fresh tab restores the server-owned pending prompt before subscribing', async () => {
  const h = setup(); h.ctx.subscribeToChat = () => {};
  h.ctx.fetch = async () => reply({ id: 'a', messages: [], pending_question: 'Still answering me',
    activity: { status: 'running', request_id: 'active-turn' } });
  await h.ctx.openChat('a');
  assert.equal(h.run('history[0].content'), 'Still answering me');
  assert.equal(h.calls.filter(call => call[1] === 'Still answering me').length, 1);
  assert.equal(h.ids.q.disabled, true);
});

test('persisted request suppresses its complete token and tool replay before a failed or cancelled final', async () => {
  for (const terminal of [{ failed: true }, { cancelled: true }]) {
    const h = setup(); h.ctx.loadChatHistory = () => {};
    const subscribe = h.ctx.subscribeToChat; let subscription;
    h.ctx.subscribeToChat = id => subscription = subscribe(id);
    let read = false;
    const events = [
      { type: 'step_start', id: 'saved-tool', tool: 'lookup' },
      { type: 'token', text: 'partial replay must stay hidden' },
      { type: 'final', response: 'saved terminal', chat_id: 'a', ...terminal },
    ].map((event, index) => ({ ...event, request_id: 'active-turn', sequence: index + 1 }));
    h.ctx.fetch = async url => url.includes('/events')
      ? { ok: true, body: { getReader: () => ({ read: async () => read ? { done: true } : (read = true, { value: new TextEncoder().encode(events.map(event => `data: ${JSON.stringify(event)}\n\n`).join('')), done: false }) }) } }
      : reply({ id: 'a', pending_question: 'already persisted question',
        activity: { status: 'running', request_id: 'active-turn' },
        messages: [{ role: 'user', content: 'already persisted question' }, { role: 'assistant', content: 'saved terminal', request_id: 'active-turn' }] });
    await h.ctx.openChat('a');
    await subscription;
    assert.equal(h.run('history.length'), 2);
    assert.equal(h.calls.filter(call => call[1] === 'already persisted question').length, 1);
    assert.equal(h.calls.filter(call => call[1] === 'saved terminal').length, 1);
    assert.equal(h.ids.log.querySelectorAll('.assistant').length, 1);
    assert.equal(h.ids.log.querySelectorAll('.msg-trace').length, 0);
    assert.equal(h.ids.log.querySelectorAll('.msg-timer').length, 0);
    assert.equal(h.run("chatState('a').sequence"), 3);
  }
});

test('identical question text never identifies the pending request, including historic turns', async () => {
  for (const previousRequestId of [undefined, 'previous-turn']) {
    const h = setup(); h.ctx.loadChatHistory = () => {};
    const subscribe = h.ctx.subscribeToChat; let subscription;
    h.ctx.subscribeToChat = id => subscription = subscribe(id);
    let read = false;
    const events = [
      { type: 'token', text: 'new partial', request_id: 'new-turn', sequence: 1 },
      { type: 'final', response: 'new reply', failed: true, request_id: 'new-turn', sequence: 2 },
    ];
    h.ctx.fetch = async url => url.includes('/events')
      ? { ok: true, body: { getReader: () => ({ read: async () => read ? { done: true } : (read = true, { value: new TextEncoder().encode(events.map(event => `data: ${JSON.stringify(event)}\n\n`).join('')), done: false }) }) } }
      : reply({ id: 'a', pending_question: 'same question', last_response_at: '2026-09-17T10:00:10Z',
        activity: { status: 'running', request_id: 'new-turn', started_at: '2026-09-17T10:00:00Z' },
        messages: [{ role: 'user', content: 'same question' }, { role: 'assistant', content: 'old reply', request_id: previousRequestId }] });
    await h.ctx.openChat('a');
    await subscription;
    assert.equal(h.calls.filter(call => call[1] === 'same question').length, 2);
    assert.equal(h.run('history.length'), 4);
    assert.deepEqual(h.ids.log.querySelectorAll('.assistant').map(wrap => wrap.querySelector('.msg-content').textContent), ['old reply', 'new reply']);
  }
});

test('confirmation cancellation safely restores focus while sidebar polling continues', async () => {
  const h = setup();
  h.doc.body = h.doc.root; h.doc.addEventListener = () => {}; h.doc.removeEventListener = () => {};
  h.ctx.HTMLElement = Element;
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/pages/Chat/modal.js'), 'utf8'), h.ctx);
  h.ctx.renderChatHistory([row('a')]);
  const item = h.ids['chat-history-list'].children[0], actions = item.querySelector('.chat-history-action-btn');
  await actions.emit('click');
  const remove = item.querySelector('.chat-history-action-menu').children[1]; remove.focus();
  const result = h.ctx.confirmModal({ danger: true });
  h.ctx.renderChatHistory([row('a')]);
  await h.doc.querySelector('.chat-modal-btn-cancel').emit('click');
  assert.equal(await result, false); assert.equal(h.doc.activeElement, remove);
  const second = h.ctx.confirmModal({ danger: true });
  item.remove(); remove.remove();
  await h.doc.querySelector('.chat-modal-btn-cancel').emit('click');
  assert.equal(await second, false); assert.equal(h.doc.activeElement, h.ids.q);
});

test('chat stylesheet has balanced blocks and an independently parsed history text rule', () => {
  const css = fs.readFileSync(path.join(__dirname, '../src/pages/Chat/styles.css'), 'utf8').replace(/\/\*[^]*?\*\//g, '');
  let depth = 0;
  for (const char of css) {
    if (char === '{') depth++;
    if (char === '}') depth--;
    assert.ok(depth >= 0, 'unexpected closing CSS block');
  }
  assert.equal(depth, 0);
  assert.match(css, /\.chat-history-text\s*\{\s*display:\s*flex;/);
});

test('management preserves checkbox focus and rename input across polling and supports rename', async () => {
  const h = setup(); h.ctx.renderChatHistory([row('a'), row('b')]); h.ctx.showManageChats();
  const panel = h.ctx.ensureManageChatsPanel();
  const a = panel.querySelector('.chat-manage-list').children[0], checkbox = a.querySelector('input[type="checkbox"]');
  checkbox.checked = true; checkbox.focus(); await checkbox.emit('change');
  h.ctx.renderChatHistory([row('b'), row('a')]);
  assert.equal(h.doc.activeElement, checkbox); assert.equal(checkbox.checked, true);
  const rename = a.children.find(c => c.textContent === 'Rename'); await rename.emit('click');
  const input = a.querySelector('.chat-history-rename-input'); input.value = 'Renamed'; input.selectionStart = 3;
  h.ctx.renderChatHistory([row('a'), row('b')]);
  assert.equal(h.doc.activeElement, input); assert.equal(input.selectionStart, 3);
  const patches = []; h.ctx.fetch = async (url, options) => { patches.push(JSON.parse(options.body)); return reply({}); };
  h.ctx.loadChatHistory = async () => {};
  await input.blur();
  assert.deepEqual(patches, [{ title: 'Renamed' }]);
});

test('single and bulk deletion stay in management and refresh the list', async () => {
  for (const bulk of [false, true]) {
    const h = setup(); h.ctx.renderChatHistory([row('a'), row('b')]);
    h.run("currentChatId = 'a'"); h.ctx.showManageChats(); let refreshed = 0;
    h.ctx.fetch = async () => reply({});
    h.ctx.loadChatHistory = async () => { refreshed++; h.ctx.renderChatHistory([row('b')]); };
    if (bulk) { h.run("selectedChatIds.add('a')"); await h.ctx.deleteSelectedChatEntries(); }
    else await h.ctx.deleteChatEntry(row('a'));
    assert.equal(h.run('manageChatsVisible'), true); assert.equal(h.run('chatBeforeManaging'), null);
    assert.equal(h.run('currentChatId'), null); assert.equal(refreshed, 1);
    assert.equal(h.ctx.ensureManageChatsPanel().querySelector('.chat-manage-list').children.length, 1);
  }
});

test('chat and management transitions never expose the extension overlay', async () => {
  const h = setup(); await h.ctx.openChat(null); assert.equal(h.ids['ext-overlay'].classList.contains('hidden'), true);
  h.ctx.showManageChats(); await h.ctx.leaveManageChats();
  assert.equal(h.ids['ext-overlay'].classList.contains('hidden'), true);
  assert.equal(h.ids['chat-dropzone'].classList.contains('hidden'), false);
});

test('completion racing a chat fetch identifies the persisted request without question text', async () => {
  const h = setup(); let subscriptions = 0;
  h.run("currentChatId = 'a'; chatState('a').activity = { status: 'running', request_id: 'active-turn' }; chatState('a').pendingQuestion = 'question';");
  h.ctx.fetch = async () => reply({ id: 'a', last_response_at: '2026-09-17T10:00:10Z',
    messages: [{ role: 'user', content: 'question' }, { role: 'assistant', content: 'saved answer', elapsed_seconds: 10, request_id: 'active-turn' }] });
  h.ctx.subscribeToChat = () => { if (h.run("chatState('a').activity.status") === 'running') subscriptions++; };
  await h.ctx.openChat('a');
  assert.equal(subscriptions, 1);
  assert.equal(h.run("chatState('a').persistedTerminalRequestId"), 'active-turn');
  assert.equal(h.run('history.length'), 2);
  assert.equal(h.calls.filter(call => call[1] === 'saved answer').length, 1);
});

test('terminal polling recovers a stalled subscriber even before its read throws', () => {
  const h = setup(); const reopened = [];
  h.run("currentChatId = 'a'; chatState('a').activity = { status: 'running' }; chatState('a').subscription = new AbortController();");
  h.ctx.openChat = id => reopened.push(id);
  h.ctx.renderChatHistory([row('a', 'completed')]);
  assert.deepEqual(reopened, ['a']);
});

test('successful final reload restores persisted question and keeps its completed trace', async () => {
  const h = setup(); h.ctx.loadChatHistory = () => {};
  h.run("currentChatId = 'a'; chatState('a').activity = { status: 'running' };");
  const events = [
    { type: 'step_start', id: 'tool', tool: 'lookup', sequence: 1 },
    { type: 'step_end', id: 'tool', ok: false, result: 'unavailable', sequence: 2 },
    { type: 'final', response: 'answer', elapsed_seconds: 2, total_tokens: 14, chat_id: 'a', failed: false, sequence: 3 },
  ];
  let read = false;
  h.ctx.fetch = async url => url.includes('/events')
    ? { ok: true, body: { getReader: () => ({ read: async () => read ? { done: true } : (read = true, { value: new TextEncoder().encode(events.map(e => 'data: ' + JSON.stringify(e) + '\n\n').join('')), done: false }) }) } }
    : reply({ id: 'a', messages: [{ role: 'user', content: 'persisted question' }, { role: 'assistant', content: 'answer', elapsed_seconds: 2, total_tokens: 14 }] });
  await h.ctx.subscribeToChat('a');
  assert.equal(h.run('history.length'), 2);
  assert.equal(h.run('history[0].content'), 'persisted question');
  assert.equal(h.ids.log.querySelector('.msg-trace-summary').textContent, 'Ran 1 tool (1 failed)');
  assert.equal(h.ids.log.children.filter(c => c.classList.contains('assistant')).length, 1);
  assert.equal(h.ids['send-btn'].disabled, false);
});

test('a final transcript-fetch failure leaves the completed reply visible and permits retry', async () => {
  const h = setup(); h.ctx.loadChatHistory = () => {};
  h.run("currentChatId = 'a'; chatState('a').activity = { status: 'running' };");
  let read = false;
  h.ctx.fetch = async url => url.includes('/events')
    ? { ok: true, body: { getReader: () => ({ read: async () => read ? { done: true } : (read = true, { value: new TextEncoder().encode('data: {"type":"final","response":"answer","chat_id":"a","failed":false,"sequence":1}\n\n'), done: false }) }) } }
    : reply({}, false);
  await h.ctx.subscribeToChat('a');
  assert.equal(h.run('currentChatId'), 'a');
  assert.equal(h.run('chatLoading'), false);
  assert.equal(h.run("chatState('a').needsReload"), true);
  assert.equal(h.ids.log.querySelector('.msg-content').textContent, 'answer');
});

test('a failed-persistence final keeps its displayed answer instead of loading an older transcript', async () => {
  const h = setup(); h.ctx.loadChatHistory = () => {};
  h.run("currentChatId = 'a'; chatState('a').activity = { status: 'running' };");
  let read = false;
  h.ctx.fetch = async url => url.includes('/events')
    ? { ok: true, body: { getReader: () => ({ read: async () => read ? { done: true } : (read = true, { value: new TextEncoder().encode('data: {"type":"final","response":"live answer","chat_id":null,"failed":true,"sequence":1}\n\n'), done: false }) }) } }
    : reply({ id: 'a', messages: [{ role: 'user', content: 'older question' }, { role: 'assistant', content: 'older answer' }] });
  await h.ctx.subscribeToChat('a');
  assert.equal(h.ids.log.querySelector('.msg-content').textContent, 'live answer');
  assert.equal(h.run("chatState('a').needsReload"), false);
});

test('relative response labels and active-first sorting execute against response timestamps', () => {
  const h = setup();
  assert.equal(h.ctx.formatRelativeTime(new Date().toISOString()), 'Just now');
  assert.equal(h.ctx.formatRelativeTime(new Date(Date.now() - 12 * 60000).toISOString()), '12m ago');
  const yesterday = new Date(); yesterday.setDate(yesterday.getDate() - 1); yesterday.setHours(0, 0, 0, 0);
  assert.equal(h.ctx.formatRelativeTime(yesterday.toISOString()), 'Yesterday');
  const sorted = h.ctx.sortChatRows([row('old', null, '2026-09-10'), row('new', null, '2026-09-15'), row('running', 'running', null)]);
  assert.deepEqual(Array.from(sorted, item => item.id), ['running', 'new', 'old']);
});
