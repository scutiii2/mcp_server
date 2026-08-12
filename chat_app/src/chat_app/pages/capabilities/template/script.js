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
    const res = await fetch(`/capabilities/api/try/${toolName}`, {
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
