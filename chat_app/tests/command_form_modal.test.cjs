// Command form modal: how a tool's server-provided input hints (select /
// options / depends_on / sets / shows / initial / hidden) become form controls
// and a final command string. Same no-dependency DOM double approach as
// chat_client.test.cjs.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../src/pages/Chat/command_form_modal.js'), 'utf8');

class HTMLElement {}
class Element extends HTMLElement {
  constructor(tag, doc) { super(); this.tagName = tag; this.doc = doc; this.children = []; this.attributes = {}; this.listeners = {}; this.className = ''; this.value = ''; this.textContent = ''; this.disabled = false; this.dataset = {}; this.id = ''; }
  get classList() {
    return {
      contains: c => this.className.split(' ').includes(c),
      add: (...cs) => { this.className = [...new Set([...this.className.split(' ').filter(Boolean), ...cs])].join(' '); },
      remove: (...cs) => { this.className = this.className.split(' ').filter(c => !cs.includes(c)).join(' '); },
    };
  }
  set innerHTML(v) { this.children.forEach(c => { c.parent = null; }); this.children = []; }
  get innerHTML() { return ''; }
  appendChild(child) { if (child.parent) child.remove(); this.children.push(child); child.parent = this; return child; }
  append(...cs) { cs.forEach(c => this.appendChild(c)); }
  remove() { if (this.parent) { this.parent.children.splice(this.parent.children.indexOf(this), 1); this.parent = null; } }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  async emit(type) { for (const fn of this.listeners[type] || []) await fn({ target: this, preventDefault() {}, stopPropagation() {} }); }
  focus() { this.doc.activeElement = this; }
  get offsetParent() { return this.parent || null; }
  get selectedOptions() { return this.children.filter(c => c.tagName === 'option' && c.value === this.value); }
  matches(selector) {
    return selector.split(',').map(x => x.trim()).some(sel => {
      if (sel.startsWith('.')) return this.classList.contains(sel.slice(1));
      if (sel === '[tabindex="0"]') return this.attributes.tabindex === '0';
      return this.tagName === sel;
    });
  }
  querySelectorAll(selector) { return this.children.flatMap(c => [...(c.matches(selector) ? [c] : []), ...c.querySelectorAll(selector)]); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

function setup(fetchImpl) {
  const doc = { activeElement: null, body: null, createElement(tag) { return new Element(tag, this); }, addEventListener() {}, removeEventListener() {} };
  doc.body = new Element('body', doc);
  const ctx = vm.createContext({ document: doc, console, HTMLElement, encodeURIComponent, fetch: fetchImpl || (async () => { throw Error('unexpected fetch'); }) });
  vm.runInContext(source, ctx);
  const open = spec => {
    const promise = vm.runInContext('openCommandFormModal', ctx)(spec);
    return { promise, dialog: doc.body.querySelector('.chat-modal-dialog') };
  };
  return { doc, ctx, open };
}

const param = (name, extra = {}) => ({ name, required: false, type: 'string', has_default: false, default: null, examples: [], format: null, ...extra });
const rows = dialog => dialog.querySelectorAll('.chat-modal-form-row');
const rowFor = (dialog, name) => rows(dialog).find(r => r.children[0].textContent.startsWith(name));
const control = (dialog, name) => rowFor(dialog, name).children.find(c => c.tagName === 'select' || c.tagName === 'input' || c.tagName === 'textarea');
const optionValues = select => select.children.map(o => o.value);
// The dependent select fetches without blocking the change event; let it settle.
const settle = () => new Promise(resolve => setImmediate(resolve));
const submit = dialog => dialog.children.find(c => c.tagName === 'form').emit('submit');

test('a select with server options renders a blank first option plus the options, and its value goes into the command', async () => {
  const h = setup();
  const { promise, dialog } = h.open({
    capability: 'sys', toolId: 'check',
    tool: { description: 'd', params: [param('capability', { input: 'select', options: [{ value: 'server', label: 'Server Manager' }] })] },
  });
  const select = control(dialog, 'capability');
  assert.equal(select.tagName, 'select');
  assert.deepEqual(optionValues(select), ['', 'server']);
  assert.equal(select.children[1].textContent, 'Server Manager');
  select.value = 'server'; await select.emit('change');
  await submit(dialog);
  assert.equal(await promise, '/server check capability=server');
});

test('a param with no value chosen is left out of the command', async () => {
  const h = setup();
  const { promise, dialog } = h.open({
    capability: 'sys', toolId: 'check',
    tool: { description: 'd', params: [param('capability', { input: 'select', options: [{ value: 'server', label: 'x' }] })] },
  });
  await submit(dialog);
  assert.equal(await promise, '/server check');
});

test('start_job: choosing a system shows its variant and the job name is prefilled', async () => {
  const h = setup();
  const systems = [{ value: 'srv2', label: 'srv2', variant: 'Z_ONE' }, { value: 'srv1', label: 'srv1', variant: 'Z_OTHER' }];
  const { promise, dialog } = h.open({
    capability: 'server', toolId: 'start_job',
    tool: {
      description: 'd',
      params: [
        param('system_name', { required: true, input: 'select', options: systems, shows: { variant_name: 'variant' } }),
        param('job_name', { initial: 'JOB_DATA_{timestamp}' }),
      ],
    },
  });
  const embed = dialog.querySelector('.chat-modal-form-embed');
  assert.equal(embed.querySelector('.chat-modal-form-embed-value').textContent, '—');

  const select = control(dialog, 'system_name');
  select.value = 'srv2'; await select.emit('change');
  assert.equal(embed.querySelector('.chat-modal-form-embed-value').textContent, 'Z_ONE');
  assert.match(control(dialog, 'job_name').value, /^JOB_DATA_\d{14}$/);

  await submit(dialog);
  assert.match(await promise, /^\/server start_job system_name=srv2 job_name=\S*JOB_DATA_\d{14}\S*$/);
});

test('start_job: Run stays disabled until a system is chosen', async () => {
  const h = setup();
  const { dialog } = h.open({
    capability: 'server', toolId: 'start_job',
    tool: { description: 'd', params: [param('system_name', { required: true, input: 'select', options: [{ value: 'srv2', label: 'srv2' }] })] },
  });
  const run = dialog.querySelector('.chat-modal-btn-confirm');
  assert.equal(run.disabled, true);
  const select = control(dialog, 'system_name');
  select.value = 'srv2'; await select.emit('change');
  assert.equal(run.disabled, false);
});

function downloadTool() {
  return {
    description: 'd',
    params: [
      param('system_name', { required: true, input: 'select', options: [{ value: 'srv2', label: 'srv2' }] }),
      param('job_name', {
        required: true, input: 'select', depends_on: 'system_name', sets: { job_count: 'job_count' },
        options_url: '/server/jobs/options?system_name={system_name}',
      }),
      param('job_count', { required: true, input: 'hidden' }),
    ],
  };
}

test('download: the job select waits for a system, then loads that system\'s jobs and fills the hidden job_count', async () => {
  const urls = [];
  const h = setup(async url => {
    urls.push(url);
    return { ok: true, json: async () => [{ value: 'JOB_A', label: '(0001) JOB_A', job_count: '0001' }, { value: 'JOB_B', label: '(0002) JOB_B', job_count: '0002' }] };
  });
  const { promise, dialog } = h.open({ capability: 'server', toolId: 'download_job', tool: downloadTool() });

  const jobSelect = control(dialog, 'job_name');
  assert.equal(jobSelect.disabled, true);
  assert.equal(jobSelect.children[0].textContent, '— choose system_name first —');
  assert.equal(rowFor(dialog, 'job_count'), undefined, 'the hidden job_count has no row');
  const run = dialog.querySelector('.chat-modal-btn-confirm');
  assert.equal(run.disabled, true);

  const system = control(dialog, 'system_name');
  system.value = 'srv2'; await system.emit('change'); await settle();
  assert.deepEqual(urls, ['/chat/api/param-options?template=%2Fserver%2Fjobs%2Foptions%3Fsystem_name%3D%7Bsystem_name%7D&arg.system_name=srv2']);
  assert.equal(jobSelect.disabled, false);
  assert.deepEqual(optionValues(jobSelect), ['', 'JOB_A', 'JOB_B']);
  assert.equal(run.disabled, true, 'still needs a job');

  jobSelect.value = 'JOB_B'; await jobSelect.emit('change');
  assert.equal(run.disabled, false);
  await submit(dialog);
  assert.equal(await promise, '/server download_job system_name=srv2 job_name=JOB_B job_count=0002');
});

test('download: changing the system clears the chosen job and its job_count', async () => {
  const h = setup(async () => ({ ok: true, json: async () => [{ value: 'JOB_A', label: 'JOB_A', job_count: '0001' }] }));
  const tool = downloadTool();
  tool.params[0].options.push({ value: 'srv1', label: 'srv1' });
  const { dialog } = h.open({ capability: 'server', toolId: 'download_job', tool });
  const system = control(dialog, 'system_name');
  const jobSelect = control(dialog, 'job_name');
  const run = dialog.querySelector('.chat-modal-btn-confirm');

  system.value = 'srv2'; await system.emit('change'); await settle();
  jobSelect.value = 'JOB_A'; await jobSelect.emit('change');
  assert.equal(run.disabled, false);

  system.value = 'srv1'; await system.emit('change'); await settle();
  assert.equal(run.disabled, true, 'the job must be picked again for the new system');
});

test('download: a failed options fetch leaves the job select disabled with a message', async () => {
  const h = setup(async () => { throw Error('down'); });
  const { dialog } = h.open({ capability: 'server', toolId: 'download_job', tool: downloadTool() });
  const system = control(dialog, 'system_name');
  system.value = 'srv2'; await system.emit('change'); await settle();
  const jobSelect = control(dialog, 'job_name');
  assert.equal(jobSelect.children[0].textContent, '— failed to load —');
});

test('a range, textarea, password, date and number param render as those controls', () => {
  const h = setup();
  const { dialog } = h.open({
    capability: 'x', toolId: 'y',
    tool: {
      description: 'd',
      params: [
        param('level', { type: 'integer', input: 'range', minimum: 1, maximum: 5 }),
        param('notes', { input: 'textarea' }),
        param('secret', { input: 'password' }),
        param('when', { input: 'date' }),
        param('count', { type: 'integer', minimum: 0, maximum: 9 }),
      ],
    },
  });
  assert.equal(control(dialog, 'level').type, 'range');
  assert.equal(control(dialog, 'level').min, 1);
  assert.equal(control(dialog, 'level').max, 5);
  assert.equal(control(dialog, 'notes').tagName, 'textarea');
  assert.equal(control(dialog, 'secret').type, 'password');
  assert.equal(control(dialog, 'when').type, 'date');
  assert.equal(control(dialog, 'count').type, 'number');
  assert.equal(control(dialog, 'count').max, 9);
});
