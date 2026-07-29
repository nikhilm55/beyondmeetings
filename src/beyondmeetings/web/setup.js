const $ = (id) => document.getElementById(id);

async function api(path, body) {
  const options = body === undefined
    ? {}
    : {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      };
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      detail = (await res.json()).detail || detail;
    } catch (_) { /* non-JSON error body */ }
    throw new Error(detail);
  }
  return res.json();
}

function render(state) {
  const pct = state.percent;
  $("pct").textContent = `${pct}%`;
  $("ring").style.background =
    `conic-gradient(var(--accent) 0% ${pct}%, var(--line) ${pct}% 100%)`;

  const blocking = state.checks.filter((c) => c.required && c.status !== "ok");
  $("summary").textContent = blocking.length
    ? `${blocking.length} item${blocking.length > 1 ? "s" : ""} still need attention`
    : "Everything required is in place";

  const autoFixable = state.checks.filter(
    (c) => c.status !== "ok" && c.fixable && c.inputs.length === 0
  );
  $("fixall").hidden = autoFixable.length === 0;
  $("done").hidden = pct !== 100;

  $("rows").replaceChildren(...state.checks.map(renderRow));
}

function renderRow(check) {
  const row = document.createElement("div");
  row.className = "row";

  const ok = check.status === "ok";
  const dot = document.createElement("span");
  dot.className = `dot ${ok ? "ok" : check.required ? "bad" : "optional"}`;
  dot.textContent = ok ? "✓" : check.required ? "✗" : "○";
  row.append(dot);

  const meta = document.createElement("div");
  meta.className = "meta";

  const name = document.createElement("div");
  name.className = "name";
  name.textContent = check.label;
  if (!check.required) {
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = "optional";
    name.append(tag);
  }
  meta.append(name);

  const detail = document.createElement("div");
  detail.className = "detail";
  detail.textContent = check.detail || check.description;
  meta.append(detail);

  if (!ok && check.inputs.length) meta.append(renderPanel(check));
  row.append(meta);

  if (!ok && check.fixable && !check.inputs.length) {
    const btn = document.createElement("button");
    btn.className = "btn";
    btn.textContent = "Fix";
    btn.onclick = () => runFix(check.id, {}, btn);
    row.append(btn);
  }
  return row;
}

function renderPanel(check) {
  const panel = document.createElement("div");
  panel.className = "panel";
  const fields = {};

  const submit = () => {
    const payload = {};
    for (const [key, el] of Object.entries(fields)) payload[key] = el.value;
    runFix(check.id, payload, btn);
  };

  for (const input of check.inputs) {
    const el = document.createElement("input");
    el.type = input.secret ? "password" : "text";
    el.placeholder = input.placeholder || input.label;
    el.setAttribute("aria-label", input.label);
    el.onkeydown = (e) => { if (e.key === "Enter") submit(); };
    fields[input.name] = el;
    panel.append(el);
  }

  const btn = document.createElement("button");
  btn.className = "btn primary";
  btn.textContent = "Save & verify";
  btn.onclick = submit;
  panel.append(btn);
  return panel;
}

async function runFix(id, payload, btn) {
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Working…";
  try {
    render(await api(`/api/fix/${id}`, payload));
  } catch (err) {
    btn.disabled = false;
    btn.textContent = original;
    window.alert(`Could not complete: ${err.message}`);
  }
}

$("fixall").onclick = async () => {
  const btn = $("fixall");
  btn.disabled = true;
  btn.textContent = "Working…";
  try {
    let state = await api("/api/status");
    for (const check of state.checks) {
      if (check.status !== "ok" && check.fixable && !check.inputs.length) {
        state = await api(`/api/fix/${check.id}`, {});
      }
    }
    render(state);
  } catch (err) {
    window.alert(`Could not complete: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Fix everything I can";
  }
};

api("/api/status")
  .then(render)
  .catch((err) => {
    $("summary").textContent = `Could not reach the setup server: ${err.message}`;
  });
