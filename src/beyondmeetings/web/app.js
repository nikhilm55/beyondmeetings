const $ = (id) => document.getElementById(id);
let meetings = [];
let polling = null;

async function api(path, body) {
  const options = body === undefined ? {} : {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  };
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = `${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch (_) { /* not JSON */ }
    throw new Error(detail);
  }
  return res.json();
}

function clock(seconds) {
  const pad = (n) => String(n).padStart(2, "0");
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

const LABELS = {
  idle: "Ready to record",
  recording: "Recording",
  stopping: "Stopping…",
  transcribing: "Transcribing…",
  analysing: "Writing notes…",
  done: "Notes saved",
  failed: "Something went wrong",
};

const BUSY = ["stopping", "transcribing", "analysing"];

function renderStatus(s) {
  const busy = BUSY.includes(s.phase);
  const btn = $("record");

  $("state").textContent = s.recording && s.name
    ? `Recording — ${s.name}`
    : LABELS[s.phase] || s.phase;
  $("detail").textContent = s.detail || "";
  $("timer").hidden = !s.recording;
  if (s.recording) $("timer").textContent = clock(s.elapsed_seconds);

  btn.disabled = busy;
  btn.textContent = busy ? "…" : s.recording ? "Stop" : "Start";
  btn.classList.toggle("stop", s.recording);
  $("name").hidden = s.recording || busy;

  // A wedged/corrupt state and a dead segmentation ticker both used to be
  // invisible until stop time.
  const wedged = Boolean(s.state_error);
  const failed = s.phase === "failed";
  $("alert").hidden = !(failed || wedged || s.rollover_error);
  if (!$("alert").hidden) {
    $("alertText").textContent = wedged
      ? `Recording state is unreadable: ${s.state_error}`
      : s.error || s.rollover_error || "Note generation failed.";
    $("retry").hidden = wedged || !s.transcript_path;
    $("retry").dataset.transcript = s.transcript_path || "";
    $("reset").hidden = !wedged;
  }

  // Poll only while something is in flight.
  const shouldPoll = s.recording || busy;
  if (shouldPoll && !polling) polling = setInterval(refresh, 1000);
  if (!shouldPoll && polling) {
    clearInterval(polling);
    polling = null;
  }
  if (s.phase === "done") loadMeetings();
}

function renderMeetings() {
  const query = $("search").value.trim().toLowerCase();
  const rows = query
    ? meetings.filter((m) =>
        `${m.title} ${m.summary} ${m.project}`.toLowerCase().includes(query))
    : meetings;

  $("empty").hidden = rows.length > 0;
  $("empty").textContent = meetings.length
    ? "Nothing matches that search."
    : "No meetings yet.";

  $("list").replaceChildren(...rows.map((m) => {
    const item = document.createElement("div");
    item.className = "item";

    const top = document.createElement("div");
    top.className = "itemTop";
    const title = document.createElement("span");
    title.className = "itemTitle";
    title.textContent = m.title;
    top.append(title);

    const pills = [m.date, m.project, m.tasks ? `${m.tasks} tasks` : "no tasks"];
    for (const text of pills) {
      if (!text) continue;
      const pill = document.createElement("span");
      pill.className = "pill";
      pill.textContent = text;
      top.append(pill);
    }
    item.append(top);

    if (m.summary) {
      const summary = document.createElement("div");
      summary.className = "itemSummary";
      summary.textContent = m.summary;
      item.append(summary);
    }
    return item;
  }));
}

async function refresh() {
  try {
    renderStatus(await api("/api/recording"));
  } catch (err) {
    $("detail").textContent = `Lost the server: ${err.message}`;
  }
}

async function loadMeetings() {
  try {
    meetings = (await api("/api/meetings")).meetings;
    renderMeetings();
  } catch (_) { /* history is not critical to recording */ }
}

$("record").onclick = async () => {
  const btn = $("record");
  btn.disabled = true;
  try {
    const current = await api("/api/recording");
    renderStatus(current.recording
      ? await api("/api/recording/stop", {})
      : await api("/api/recording/start", { name: $("name").value }));
  } catch (err) {
    btn.disabled = false;
    window.alert(err.message);
  }
};

$("retry").onclick = async (event) => {
  const btn = event.currentTarget;
  btn.disabled = true;
  btn.textContent = "Working…";
  try {
    await api("/api/regenerate", { transcript: btn.dataset.transcript });
    await loadMeetings();
    await refresh();
  } catch (err) {
    window.alert(`Could not regenerate: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Regenerate notes";
  }
};

$("reset").onclick = async (event) => {
  const btn = event.currentTarget;
  btn.disabled = true;
  try {
    renderStatus(await api("/api/recording/reset", {}));
  } catch (err) {
    window.alert(`Could not reset: ${err.message}`);
  } finally {
    btn.disabled = false;
  }
};

$("search").oninput = renderMeetings;
$("name").onkeydown = (e) => { if (e.key === "Enter") $("record").click(); };

refresh();
loadMeetings();
