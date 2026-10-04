// Command-form modal: fills a "/capability tool key=value ..." command
// from a form instead of typing it into the chat textarea by hand - see
// script.js's acceptSuggestion(), whose 'tool' stage opens this instead
// of continuing free-text completion.
//
//   openCommandFormModal({ capability, toolId, tool }).then(cmd => ...)
//
// `tool` is commandsRegistry[capability][toolId] - the same
// {description, params: [{name, required, type, format, has_default,
// default, examples}]} shape /api/commands already returns. Resolves to
// the assembled command string, or null if the user cancelled - same
// Promise<boolean|null>-style convention modal.js's confirmModal() uses,
// just returning the built string instead of a yes/no.

function shellQuote(value) {
  const s = String(value);
  // commands.py's parse_command() runs the assembled string through
  // Python's shlex.split() (POSIX mode) - anything with whitespace or a
  // shell-special character needs quoting to survive that round-trip
  // intact as one token, most importantly a Windows path's spaces.
  if (s === '' || /[\s"'\\$`!*?~|&;<>(){}\[\]#]/.test(s)) {
    return '"' + s.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
  }
  return s;
}

function newAttachmentId() {
  return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

// How a param is rendered. Order: file/boolean (from type/format), then an
// explicit server hint (`input`), then what the schema implies (options,
// enum or examples -> select), else a number or text box.
function paramInputKind(param) {
  if (param.format === 'file') return 'file';
  if (param.type === 'boolean') return 'checkbox';
  if (param.input) return param.input;
  if (selectOptions(param).length) return 'select';
  return (param.type === 'integer' || param.type === 'number') ? 'number' : 'text';
}

// [{ value, label }] for a select: server-resolved options, else enum, else
// (string params only) the suggested examples.
function selectOptions(param) {
  if (param.options && param.options.length) return param.options;
  if (param.enum && param.enum.length) return param.enum.map(v => ({ value: v, label: v }));
  if (param.examples && param.examples.length && param.type !== 'number' && param.type !== 'integer') {
    return param.examples.map(v => ({ value: v, label: v }));
  }
  return [];
}

function openCommandFormModal({ capability, toolId, tool }) {
  return new Promise((resolve) => {
    const params = tool.params || [];
    const hasFileParam = params.some(p => p.format === 'file');

    // --- State, scoped to this one modal instance ---------------------
    const attachments = []; // { id, file }[]
    const values = {}; // paramName -> string (non-file params) / checkbox 'true'|'false'
    const fileParamSelections = {}; // paramName -> attachmentId | ''
    const fileSelectEls = {}; // paramName -> <select>
    const rowEls = {}; // paramName -> { input, errorEl }

    const overlay = document.createElement('div');
    overlay.className = 'chat-modal-overlay';

    const dialog = document.createElement('div');
    dialog.className = 'chat-modal-dialog chat-modal-dialog--form';
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-labelledby', 'chat-modal-form-title');

    const titleEl = document.createElement('h2');
    titleEl.id = 'chat-modal-form-title';
    titleEl.className = 'chat-modal-title';
    titleEl.textContent = `/${capability} ${toolId}`;
    dialog.appendChild(titleEl);

    if (tool.description) {
      const descEl = document.createElement('p');
      descEl.className = 'chat-modal-message';
      descEl.textContent = tool.description;
      dialog.appendChild(descEl);
    }

    const form = document.createElement('form');
    form.noValidate = true;

    let dropZoneEl = null;
    let attachmentListEl = null;

    function isEmpty(param) {
      if (param.format === 'file') return !fileParamSelections[param.name];
      if (param.type === 'boolean') return false; // unchecked is a valid false, never "empty"
      const v = values[param.name];
      return v === undefined || v === '';
    }

    function updateSubmitEnabled() {
      submitBtn.disabled = params.some(p => p.required && isEmpty(p));
    }

    function renderFileSelectOptions(select, selectedId) {
      select.innerHTML = '';
      const empty = document.createElement('option');
      empty.value = '';
      empty.textContent = attachments.length ? '\u2014 choose a file \u2014' : '\u2014 drop a file below first \u2014';
      select.appendChild(empty);
      attachments.forEach(({ id, file }) => {
        const opt = document.createElement('option');
        opt.value = id;
        opt.textContent = file.name;
        select.appendChild(opt);
      });
      select.value = attachments.some(a => a.id === selectedId) ? selectedId : '';
    }

    function syncFileSelects() {
      Object.entries(fileSelectEls).forEach(([name, select]) => {
        renderFileSelectOptions(select, fileParamSelections[name]);
        fileParamSelections[name] = select.value;
      });
      updateSubmitEnabled();
    }

    function renderAttachmentList() {
      if (!attachmentListEl) return;
      attachmentListEl.innerHTML = '';
      attachments.forEach(({ id, file }) => {
        const chip = document.createElement('li');
        chip.className = 'chat-modal-attachment-chip';
        const label = document.createElement('span');
        label.textContent = file.name;
        chip.appendChild(label);
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.setAttribute('aria-label', `Remove ${file.name}`);
        removeBtn.textContent = '\u00d7';
        removeBtn.addEventListener('click', () => {
          const idx = attachments.findIndex(a => a.id === id);
          if (idx !== -1) attachments.splice(idx, 1);
          renderAttachmentList();
          syncFileSelects();
        });
        chip.appendChild(removeBtn);
        attachmentListEl.appendChild(chip);
      });
    }

    function addFiles(fileList) {
      Array.from(fileList).forEach(file => {
        attachments.push({ id: newAttachmentId(), file });
      });
      renderAttachmentList();
      syncFileSelects();
    }

    if (hasFileParam) {
      dropZoneEl = document.createElement('div');
      dropZoneEl.className = 'chat-modal-dropzone';
      dropZoneEl.textContent = 'Drag and drop files here, or click to browse';
      dropZoneEl.tabIndex = 0;

      const fileInput = document.createElement('input');
      fileInput.type = 'file';
      fileInput.multiple = true;
      fileInput.style.display = 'none';
      fileInput.addEventListener('change', () => {
        if (fileInput.files.length) addFiles(fileInput.files);
        fileInput.value = '';
      });

      dropZoneEl.addEventListener('click', () => fileInput.click());
      dropZoneEl.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
      });
      dropZoneEl.addEventListener('dragover', e => {
        e.preventDefault();
        dropZoneEl.classList.add('chat-modal-dropzone--dragover');
      });
      dropZoneEl.addEventListener('dragleave', () => {
        dropZoneEl.classList.remove('chat-modal-dropzone--dragover');
      });
      dropZoneEl.addEventListener('drop', e => {
        e.preventDefault();
        dropZoneEl.classList.remove('chat-modal-dropzone--dragover');
        if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
      });

      form.appendChild(dropZoneEl);
      form.appendChild(fileInput);

      attachmentListEl = document.createElement('ul');
      attachmentListEl.className = 'chat-modal-attachment-list';
      form.appendChild(attachmentListEl);
    }

    // Selects fed by the server (options / options_url). A select can:
    //  - depend on another param (`depends_on`): its options_url holds a
    //    {that_param} placeholder, refetched via /chat/api/param-options
    //    whenever that param changes;
    //  - fill other params from the chosen option (`sets`: {param: option
    //    field}), e.g. a job's count travelling with its name;
    //  - show read-only lines from the chosen option (`shows`: {label:
    //    option field}), e.g. a system's variant.
    const selectHolders = {}; // param name -> { param, select, data, embedEl }

    function fillSelect(holder, options, blankText) {
      const { select } = holder;
      select.innerHTML = '';
      holder.data = {};
      const blank = document.createElement('option');
      blank.value = ''; blank.textContent = blankText;
      select.appendChild(blank);
      options.forEach(o => {
        holder.data[o.value] = o;
        const option = document.createElement('option');
        option.value = o.value; option.textContent = o.label ?? o.value;
        select.appendChild(option);
      });
    }

    function applyOptionSideEffects(holder) {
      const chosen = holder.data[values[holder.param.name]];
      Object.entries(holder.param.sets || {}).forEach(([target, field]) => {
        values[target] = chosen ? (chosen[field] ?? '') : '';
      });
      if (holder.embedEl) {
        holder.embedEl.innerHTML = '';
        Object.entries(holder.param.shows || {}).forEach(([label, field]) => {
          const line = document.createElement('div');
          line.className = 'chat-modal-form-embed-row';
          const key = document.createElement('span'); key.className = 'chat-modal-form-embed-key'; key.textContent = label;
          const val = document.createElement('span'); val.className = 'chat-modal-form-embed-value'; val.textContent = (chosen && chosen[field]) || '—';
          line.appendChild(key); line.appendChild(val);
          holder.embedEl.appendChild(line);
        });
      }
    }

    function notifyDependents(name) {
      Object.values(selectHolders).forEach(holder => {
        if (holder.param.depends_on === name) loadDependentOptions(holder);
      });
    }

    async function loadDependentOptions(holder) {
      const { param, select } = holder;
      const dependency = param.depends_on;
      const dependencyValue = values[dependency];
      values[param.name] = '';
      applyOptionSideEffects(holder);
      if (!dependencyValue) {
        fillSelect(holder, [], `— choose ${dependency} first —`);
        select.disabled = true;
      } else {
        fillSelect(holder, [], 'loading…');
        select.disabled = true;
        try {
          const query = `template=${encodeURIComponent(param.options_url)}&arg.${encodeURIComponent(dependency)}=${encodeURIComponent(dependencyValue)}`;
          const res = await fetch(`/chat/api/param-options?${query}`);
          const options = res.ok ? await res.json() : [];
          // Ignore a slow response for a value the user has since changed.
          if (values[dependency] !== dependencyValue) return;
          fillSelect(holder, options, options.length ? '— choose —' : '— no options —');
          select.disabled = options.length === 0;
        } catch {
          fillSelect(holder, [], '— failed to load —');
        }
      }
      notifyDependents(param.name);
      updateSubmitEnabled();
    }

    params.forEach(param => {
      if (param.input === 'hidden') {
        // No row: filled by another param's `sets`, submitted like any other.
        values[param.name] = '';
        rowEls[param.name] = { input: { value: '' }, errorEl: document.createElement('div') };
        return;
      }

      const row = document.createElement('div');
      row.className = 'chat-modal-form-row';

      const label = document.createElement('label');
      label.className = 'chat-modal-form-label';
      label.textContent = param.name;
      if (param.required) {
        const star = document.createElement('span');
        star.className = 'chat-modal-form-required';
        star.textContent = '*';
        label.appendChild(star);
      }
      row.appendChild(label);

      let input;
      if (param.format === 'file') {
        input = document.createElement('select');
        renderFileSelectOptions(input, '');
        input.addEventListener('change', () => {
          fileParamSelections[param.name] = input.value;
          updateSubmitEnabled();
        });
        fileParamSelections[param.name] = '';
        fileSelectEls[param.name] = input;
      } else if (param.type === 'boolean') {
        input = document.createElement('input');
        input.type = 'checkbox';
        if (param.has_default && param.default) input.checked = true;
        values[param.name] = String(input.checked);
        input.addEventListener('change', () => {
          values[param.name] = String(input.checked);
          updateSubmitEnabled();
        });
      } else if (paramInputKind(param) === 'select' && (selectOptions(param).length || param.depends_on)) {
        // Options come from mcp_server: an options_url the Chat route already
        // resolved, else the schema's enum, else its examples - or, for a
        // `depends_on` select, fetched once that param has a value. The blank
        // first option lets an optional param be left out.
        input = document.createElement('select');
        const holder = { param, select: input, data: {}, embedEl: null };
        selectHolders[param.name] = holder;
        const blankText = param.required
          ? '— choose —'
          : (param.has_default && param.default !== null && param.default !== undefined && param.default !== ''
            ? `(default: ${param.default})` : '(none)');
        if (param.depends_on) {
          fillSelect(holder, [], `— choose ${param.depends_on} first —`);
          input.disabled = true;
        } else {
          fillSelect(holder, selectOptions(param), blankText);
        }
        values[param.name] = '';
        input.addEventListener('change', () => {
          values[param.name] = input.value;
          applyOptionSideEffects(holder);
          notifyDependents(param.name);
          updateSubmitEnabled();
        });
      } else if (paramInputKind(param) === 'range') {
        const wrap = document.createElement('div');
        wrap.className = 'chat-modal-form-range';
        input = document.createElement('input');
        input.type = 'range';
        input.min = param.minimum ?? 0;
        input.max = param.maximum ?? 100;
        input.step = param.step ?? (param.type === 'integer' ? 1 : 'any');
        input.value = param.has_default && param.default !== null && param.default !== undefined ? param.default : input.min;
        const readout = document.createElement('output');
        readout.textContent = input.value;
        values[param.name] = '';
        // Left unset (the tool's default applies) until the slider is moved.
        input.addEventListener('input', () => { values[param.name] = input.value; readout.textContent = input.value; updateSubmitEnabled(); });
        wrap.appendChild(input); wrap.appendChild(readout);
        row.appendChild(wrap);
      } else if (paramInputKind(param) === 'textarea') {
        input = document.createElement('textarea');
        input.rows = 4;
        if (param.max_length) input.maxLength = param.max_length;
        values[param.name] = '';
        input.addEventListener('input', () => { values[param.name] = input.value; updateSubmitEnabled(); });
      } else if (paramInputKind(param) === 'password' || paramInputKind(param) === 'date') {
        input = document.createElement('input');
        input.type = paramInputKind(param);
        if (input.type === 'password') input.autocomplete = 'off';
        values[param.name] = '';
        input.addEventListener('input', () => { values[param.name] = input.value; updateSubmitEnabled(); });
      } else {
        input = document.createElement('input');
        input.type = (param.type === 'integer' || param.type === 'number') ? 'number' : 'text';
        if (param.type === 'number') input.step = 'any';
        if (param.minimum !== null && param.minimum !== undefined) input.min = param.minimum;
        if (param.maximum !== null && param.maximum !== undefined) input.max = param.maximum;
        if (param.max_length) input.maxLength = param.max_length;
        if (param.pattern) input.pattern = param.pattern;
        if (param.examples && param.examples.length) {
          const listId = `cfm-datalist-${capability}-${toolId}-${param.name}`;
          input.setAttribute('list', listId);
          const datalist = document.createElement('datalist');
          datalist.id = listId;
          param.examples.forEach(ex => {
            const opt = document.createElement('option');
            opt.value = ex;
            datalist.appendChild(opt);
          });
          row.appendChild(datalist);
        }
        if (param.has_default && param.default !== null && param.default !== undefined) {
          input.placeholder = String(param.default);
        }
        values[param.name] = '';
        if (param.initial) {
          const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
          input.value = param.initial.replace('{timestamp}', stamp);
          values[param.name] = input.value;
        }
        input.addEventListener('input', () => {
          values[param.name] = input.value;
          updateSubmitEnabled();
        });
      }
      row.appendChild(input);

      if (!param.required) {
        const hint = document.createElement('div');
        hint.className = 'chat-modal-form-hint';
        hint.textContent = param.has_default
          ? `optional, default: ${param.default === null || param.default === undefined ? 'none' : param.default}`
          : 'optional';
        row.appendChild(hint);
      }

      const errorEl = document.createElement('div');
      errorEl.className = 'chat-modal-form-error hidden';
      row.appendChild(errorEl);

      rowEls[param.name] = { input, errorEl };
      form.appendChild(row);

      const holder = selectHolders[param.name];
      if (holder && param.shows && Object.keys(param.shows).length) {
        holder.embedEl = document.createElement('div');
        holder.embedEl.className = 'chat-modal-form-embed';
        form.appendChild(holder.embedEl);
        applyOptionSideEffects(holder);
      }
    });

    const globalError = document.createElement('div');
    globalError.className = 'chat-modal-form-error hidden';
    form.appendChild(globalError);

    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'chat-modal-btn chat-modal-btn-cancel';
    cancelBtn.textContent = 'Cancel';

    const submitBtn = document.createElement('button');
    submitBtn.type = 'submit';
    submitBtn.className = 'chat-modal-btn chat-modal-btn-confirm';
    submitBtn.textContent = 'Run';

    const actions = document.createElement('div');
    actions.className = 'chat-modal-actions';
    actions.append(cancelBtn, submitBtn);
    form.appendChild(actions);

    dialog.appendChild(form);
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    updateSubmitEnabled();

    const previouslyFocused = document.activeElement;

    function focusables() {
      return Array.from(dialog.querySelectorAll('button, input, select, [tabindex="0"]'))
        .filter(el => !el.disabled && el.offsetParent !== null);
    }

    function cleanup(result) {
      document.removeEventListener('keydown', onKeydown);
      overlay.remove();
      if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
      resolve(result);
    }

    function onKeydown(event) {
      if (event.key === 'Escape') {
        cleanup(null);
        return;
      }
      if (event.key !== 'Tab') return;
      const els = focusables();
      if (!els.length) return;
      const from = els.indexOf(document.activeElement);
      event.preventDefault();
      const step = event.shiftKey ? -1 : 1;
      const nextIndex = from === -1 ? 0 : (from + step + els.length) % els.length;
      els[nextIndex].focus();
    }

    overlay.addEventListener('click', event => {
      if (event.target === overlay) cleanup(null);
    });
    cancelBtn.addEventListener('click', () => cleanup(null));
    document.addEventListener('keydown', onKeydown);

    function showError(param, message) {
      const target = param ? rowEls[param]?.errorEl : globalError;
      if (!target) return;
      target.textContent = message;
      target.classList.remove('hidden');
    }

    function clearErrors() {
      globalError.classList.add('hidden');
      Object.values(rowEls).forEach(({ errorEl }) => errorEl.classList.add('hidden'));
    }

    async function uploadFile(file) {
      const formData = new FormData();
      formData.append('file', file);
      const response = await fetch('/chat/api/upload', { method: 'POST', body: formData });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.error || `Upload failed (${response.status})`);
      return body.path;
    }

    form.addEventListener('submit', async event => {
      event.preventDefault();
      clearErrors();
      updateSubmitEnabled();
      if (submitBtn.disabled) return;

      submitBtn.disabled = true;
      submitBtn.textContent = 'Running...';

      // Resolved values, param name -> final string to send. File params
      // start as an attachment id and get swapped for a real server path
      // below; everything else is already its final value.
      const resolved = { ...values };

      try {
        // Sequential, not parallel: today there's at most one file param
        // per tool, and sequential makes "stop at the first failure"
        // trivial with no partial-upload bookkeeping.
        for (const param of params) {
          if (param.format !== 'file') continue;
          const attachmentId = fileParamSelections[param.name];
          if (!attachmentId) continue; // optional file param left unset
          const attachment = attachments.find(a => a.id === attachmentId);
          if (!attachment) continue;
          try {
            resolved[param.name] = await uploadFile(attachment.file);
          } catch (err) {
            showError(param.name, err.message || String(err));
            throw err;
          }
        }
      } catch {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Run';
        return; // form state (attachments/values) stays intact for retry
      }

      const parts = [`/${capability}`, toolId];
      params.forEach(param => {
        const value = resolved[param.name];
        if (param.type === 'boolean') {
          // Always include a required boolean (commands.py's _coerce needs
          // a token to parse); an optional one is only sent when checked,
          // same as omitting any other optional param left at its default.
          if (param.required || value === 'true') parts.push(`${param.name}=${value}`);
          return;
        }
        if (value === undefined || value === '') return; // optional, left blank
        parts.push(`${param.name}=${shellQuote(value)}`);
      });

      cleanup(parts.join(' '));
    });

    // Focus the first real input, not Cancel - unlike confirmModal()'s
    // danger-defaults-to-Cancel, there's nothing destructive about a form
    // appearing with focus on its first field.
    (focusables().find(el => el !== cancelBtn) || cancelBtn).focus();
  });
}
