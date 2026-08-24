const $ = (id) => document.getElementById(id);
let meetings = [];
let tasks = [];
let polling = null;
let lastCompletedPath = null;
let currentNotePath = null;
let currentNoteContent = "";
let currentNoteView = "minutes";
let currentNotesLanguage = "English";
const discussionSummaries = new Map();
const translatedTranscripts = new Map();
const discussionRequests = new Map();
const translationRequests = new Map();

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
    if (Array.isArray(detail)) detail = detail[0]?.msg || "Invalid request";
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

function parseDate(value) {
  if (!value) return null;
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value);
  const parsed = new Date(dateOnly ? `${value}T12:00:00` : value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function longDate(value) {
  const parsed = parseDate(value);
  return parsed ? new Intl.DateTimeFormat(undefined, {
    weekday: "long", day: "numeric", month: "long", year: "numeric",
  }).format(parsed) : value;
}

function shortDate(value) {
  const parsed = parseDate(value);
  return parsed ? new Intl.DateTimeFormat(undefined, {
    day: "numeric", month: "short", year: "numeric",
  }).format(parsed) : value;
}

function meetingTime(recordedAt) {
  const parsed = parseDate(recordedAt);
  return parsed ? new Intl.DateTimeFormat(undefined, {
    hour: "numeric", minute: "2-digit",
  }).format(parsed) : "Time not recorded";
}

const LABELS = {
  idle: "Ready to record",
  recording: "Recording in progress",
  stopping: "Securing your recording…",
  transcribing: "Transcribing the meeting…",
  analysing: "Writing structured notes…",
  done: "Meeting saved",
  failed: "Something went wrong",
};
const DETAILS = {
  idle: "Name the meeting, then start when everyone is ready.",
  recording: "Audio is being captured locally. Keep this app open.",
  stopping: "Finalizing the audio file before transcription.",
  transcribing: "Turning the recording into a searchable transcript.",
  analysing: "Creating the summary, decisions and action items.",
  done: "Your note and transcript are ready in the local library.",
};
const BUSY = ["stopping", "transcribing", "analysing"];

function renderStatus(s) {
  const busy = BUSY.includes(s.phase);
  const btn = $("record");
  const recording = Boolean(s.recording);

  $("state").textContent = recording && s.name
    ? s.name
    : LABELS[s.phase] || s.phase;
  $("statusEyebrow").textContent = recording ? "Recording now" : "Meeting recorder";
  $("detail").textContent = s.phase === "failed"
    ? "See the recovery details below."
    : s.detail || DETAILS[s.phase] || "";
  $("timerWrap").hidden = !recording;
  if (recording) $("timer").textContent = clock(s.elapsed_seconds);

  btn.disabled = busy;
  $("recordLabel").textContent = busy ? LABELS[s.phase] : recording ? "Stop recording" : "Start recording";
  btn.classList.toggle("stop", recording);
  btn.classList.toggle("busy", busy);
  $("name").hidden = recording || busy;
  $("liveIndicator").classList.toggle("active", recording);
  $("recorderCard")?.classList?.toggle("recording", recording);

  $("recordingBadge").classList.toggle("active", recording);
  $("recordingBadgeText").textContent = recording ? `Recording · ${clock(s.elapsed_seconds)}` : busy ? LABELS[s.phase] : "Not recording";

  const wedged = Boolean(s.state_error);
  const failed = s.phase === "failed";
  $("alert").hidden = !(failed || wedged || s.rollover_error);
  if (!$("alert").hidden) {
    $("alertText").textContent = wedged
      ? `Recording state is unreadable: ${s.state_error}`
      : s.error || s.rollover_error || "Note generation failed.";
    $("retry").hidden = wedged || !s.transcript_path;
    $("retry").dataset.transcript = s.transcript_path || "";
    $("reset").hidden = !(wedged || failed);
    $("reset").textContent = wedged ? "Clear recording state" : "Dismiss";
  }

  const shouldPoll = recording || busy;
  if (shouldPoll && !polling) polling = setInterval(refresh, 1000);
  if (!shouldPoll && polling) {
    clearInterval(polling);
    polling = null;
  }
  if (s.phase === "done" && s.note_path !== lastCompletedPath) {
    lastCompletedPath = s.note_path;
    loadMeetings();
    loadTasks();
  }
}

function pill(text, className = "pill") {
  const element = document.createElement("span");
  element.className = className;
  element.textContent = text;
  return element;
}

function meetingCard(meeting) {
  const item = document.createElement("button");
  item.type = "button";
  item.className = "meetingCard";
  item.onclick = () => openNote(meeting.link, meeting.title, meeting);

  const content = document.createElement("span");
  content.className = "meetingContent";
  const title = document.createElement("strong");
  title.className = "meetingTitle";
  title.textContent = meeting.title;
  content.append(title);
  if (meeting.summary) {
    const summary = document.createElement("span");
    summary.className = "meetingSummary";
    summary.textContent = meeting.summary;
    content.append(summary);
  }

  const meta = document.createElement("span");
  meta.className = "meetingMeta";
  meta.append(pill(meetingTime(meeting.recorded_at), "metaText"));
  if (meeting.project) meta.append(pill(meeting.project));
  meta.append(pill(`${meeting.tasks || 0} action ${meeting.tasks === 1 ? "item" : "items"}`));
  content.append(meta);

  const arrow = document.createElement("span");
  arrow.className = "meetingArrow";
  arrow.setAttribute("aria-hidden", "true");
  arrow.textContent = "›";
  item.append(content, arrow);
  return item;
}

function renderMeetings() {
  const query = $("search").value.trim().toLowerCase();
  $("clearSearch").hidden = !query;
  const rows = query
    ? meetings.filter((m) =>
        `${m.title} ${m.summary} ${m.project} ${m.date}`.toLowerCase().includes(query))
    : meetings;

  $("meetingCount").textContent = meetings.length;
  $("meetingNoun").textContent = meetings.length === 1
    ? " meeting"
    : " meetings";
  $("lastMeeting").textContent = meetings.length
    ? `Latest · ${shortDate(meetings[0].date)}`
    : "No meetings yet";
  $("empty").hidden = rows.length > 0;
  $("empty").querySelector("strong").textContent = meetings.length
    ? "No matching meetings"
    : "No meetings yet";
  $("empty").querySelector("p").textContent = meetings.length
    ? "Try a different title, project, date or summary."
    : "Your completed meeting notes will appear here, grouped by date.";

  const groups = new Map();
  for (const meeting of rows) {
    if (!groups.has(meeting.date)) groups.set(meeting.date, []);
    groups.get(meeting.date).push(meeting);
  }
  $("list").replaceChildren(...[...groups].map(([date, entries]) => {
    const group = document.createElement("section");
    group.className = "dateGroup";
    const heading = document.createElement("header");
    heading.className = "dateHeading";
    const when = document.createElement("time");
    when.dateTime = date;
    when.textContent = longDate(date);
    const count = document.createElement("span");
    count.textContent = `${entries.length} ${entries.length === 1 ? "meeting" : "meetings"}`;
    heading.append(when, count);
    const cards = document.createElement("div");
    cards.className = "meetingCards";
    cards.append(...entries.map(meetingCard));
    group.append(heading, cards);
    return group;
  }));
}

function renderTasks() {
  $("taskCount").textContent = tasks.length;
  $("taskEmpty").hidden = tasks.length > 0;
  $("taskList").replaceChildren(...tasks.map((task) => {
    const item = document.createElement(task.meeting ? "button" : "div");
    if (task.meeting) item.type = "button";
    item.className = `taskCard${task.meeting ? " clickable" : ""}`;
    if (task.meeting) item.onclick = () => openNote(task.meeting, task.title);
    const priority = pill(task.priority || "MEDIUM", `priority priority${task.priority || "MEDIUM"}`);
    const title = document.createElement("strong");
    title.textContent = task.title;
    const meta = document.createElement("span");
    meta.className = "taskMeta";
    meta.textContent = [task.project, task.owner && `Owner: ${task.owner}`, task.due && `Due: ${shortDate(task.due)}`].filter(Boolean).join(" · ");
    item.append(priority, title);
    if (task.description) {
      const description = document.createElement("span");
      description.className = "taskDescription";
      description.textContent = task.description;
      item.append(description);
    }
    if (meta.textContent) item.append(meta);
    return item;
  }));
}

function renderMarkdown(markdown) {
  const body = $("noteBody");
  body.replaceChildren();
  const lines = markdown.replace(/^---\n[\s\S]*?\n---\n/, "").split("\n");
  let list = null;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) { list = null; continue; }
    let element;
    if (line.startsWith("## ")) {
      element = document.createElement("h2"); element.textContent = line.slice(3);
    } else if (line.startsWith("# ")) {
      element = document.createElement("h1"); element.textContent = line.slice(2);
    } else if (/^- (?:\[[ x]\] )?/.test(line)) {
      if (!list) { list = document.createElement("ul"); body.append(list); }
      element = document.createElement("li");
      element.textContent = line.replace(/^- (?:\[[ x]\] )?/, "").replace(/\*\*/g, "");
      list.append(element); continue;
    } else if (line.startsWith(">")) {
      element = document.createElement("blockquote");
      element.textContent = line.replace(/^>\s*(\[!\w+\][+-]?\s*)?/, "").replace(/\[\[|\]\]/g, "");
    } else {
      element = document.createElement("p");
      element.textContent = line.replace(/\*\*/g, "").replace(/\[\[|\]\]/g, "");
      if (line.startsWith("*Transcribed")) element.className = "byline";
    }
    body.append(element);
  }
}

async function openNote(path, title, meeting = null) {
  try {
    const note = await api(`/api/note?path=${encodeURIComponent(path)}`);
    currentNotePath = path;
    currentNoteContent = note.content;
    currentNoteView = "minutes";
    currentNotesLanguage = note.notes_language || "English";
    discussionSummaries.clear();
    translatedTranscripts.clear();
    $("translationLanguage").value = "Hinglish";
    $("viewerTitle").textContent = title || "Meeting note";
    $("viewerDate").textContent = meeting
      ? `${longDate(meeting.date)} · ${meetingTime(meeting.recorded_at)}`
      : "Meeting note";
    renderMarkdown(note.content);
    updateViewerTabs();
    $("viewerStatus").hidden = true;
    $("viewerStatus").classList.remove("error");
    $("viewer").showModal();
  } catch (err) {
    window.alert(`Could not open note: ${err.message}`);
  }
}

function updateViewerTabs() {
  $("minutesView").classList.toggle("active", currentNoteView === "minutes");
  $("discussionView").classList.toggle("active", currentNoteView === "discussion");
  $("translationView").classList.toggle("active", currentNoteView === "translation");
  $("minutesView").setAttribute("aria-selected", currentNoteView === "minutes");
  $("discussionView").setAttribute("aria-selected", currentNoteView === "discussion");
  $("translationView").setAttribute("aria-selected", currentNoteView === "translation");
  $("translationLanguageWrap").hidden = currentNoteView !== "translation";
}

function noteLoading(message) {
  const body = $("noteBody");
  body.replaceChildren();
  const loading = document.createElement("div");
  loading.className = "noteLoading";
  const content = document.createElement("div");
  const icon = document.createElement("span");
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = "✦";
  content.append(icon, message);
  loading.append(content);
  body.append(loading);
}

function renderTranscript(result, language) {
  const transcript = typeof result === "string" ? result : result.content;
  const turns = typeof result === "string" ? [] : (result.turns || []);
  const body = $("noteBody");
  body.replaceChildren();
  const title = document.createElement("h1");
  title.textContent = "Conversation Transcript";
  const meta = document.createElement("div");
  meta.className = "transcriptMeta";
  meta.textContent = `${language} · Full conversation · AI-estimated speakers`;
  body.append(title, meta);

  if (!turns.length) {
    const text = document.createElement("div");
    text.className = "transcriptText";
    text.textContent = transcript;
    body.append(text);
    return;
  }

  const conversation = document.createElement("div");
  conversation.className = "chatTranscript";
  const speakerSides = new Map();
  for (const turn of turns) {
    if (!speakerSides.has(turn.speaker)) {
      speakerSides.set(turn.speaker, speakerSides.size % 2);
    }
    const message = document.createElement("section");
    message.className = `transcriptMessage ${speakerSides.get(turn.speaker) ? "right" : "left"}`;
    const speaker = document.createElement("strong");
    speaker.className = "transcriptSpeaker";
    speaker.textContent = turn.speaker;
    const bubble = document.createElement("div");
    bubble.className = "transcriptBubble";
    bubble.textContent = turn.text;
    message.append(speaker, bubble);
    conversation.append(message);
  }
  body.append(conversation);
}

async function showNoteView(view) {
  if (!currentNotePath) return;
  const notePath = currentNotePath;
  currentNoteView = view;
  updateViewerTabs();
  viewerStatus("");
  if (view === "minutes") {
    renderMarkdown(currentNoteContent);
    return;
  }

  if (view === "translation") {
    const language = $("translationLanguage").value;
    const cacheKey = `${notePath}\n${language}`;
    if (translatedTranscripts.has(cacheKey)) {
      renderTranscript(translatedTranscripts.get(cacheKey), language);
      return;
    }

    noteLoading(`Preparing the complete conversation in ${language} without summarizing…`);
    try {
      let request = translationRequests.get(cacheKey);
      if (!request) {
        request = api("/api/note/translation", {
          path: notePath,
          language,
        });
        translationRequests.set(cacheKey, request);
      }
      const result = await request;
      translatedTranscripts.set(cacheKey, result);
      if (
        currentNotePath === notePath
        && currentNoteView === "translation"
        && $("translationLanguage").value === language
      ) {
        renderTranscript(result, language);
      }
    } catch (err) {
      if (currentNotePath === notePath && currentNoteView === "translation") {
        renderTranscript(
          "The full transcript could not be translated.",
          language,
        );
        viewerStatus(`Could not translate transcript: ${err.message}`, true);
      }
    } finally {
      translationRequests.delete(cacheKey);
    }
    return;
  }

  const language = currentNotesLanguage;
  const cacheKey = `${notePath}\n${language}`;
  if (discussionSummaries.has(cacheKey)) {
    renderMarkdown(discussionSummaries.get(cacheKey));
    return;
  }

  noteLoading("Creating a clear discussion summary…");
  try {
    let request = discussionRequests.get(cacheKey);
    if (!request) {
      request = api("/api/note/discussion", {
        path: notePath,
        language,
      });
      discussionRequests.set(cacheKey, request);
    }
    const result = await request;
    discussionSummaries.set(cacheKey, result.content);
    if (currentNotePath === notePath && currentNoteView === "discussion") {
      renderMarkdown(result.content);
    }
  } catch (err) {
    if (currentNotePath === notePath && currentNoteView === "discussion") {
      renderMarkdown("# Discussion Summary\n\nThe AI summary could not be generated.");
      viewerStatus(`Could not create discussion summary: ${err.message}`, true);
    }
  } finally {
    discussionRequests.delete(cacheKey);
  }
}

function activeExportLanguage() {
  return currentNoteView === "translation"
    ? $("translationLanguage").value
    : currentNotesLanguage;
}

function viewerStatus(message, isError = false) {
  const status = $("viewerStatus");
  status.textContent = message;
  status.classList.toggle("error", isError);
  status.hidden = !message;
}

async function createCurrentPdf(button) {
  if (!currentNotePath) throw new Error("Open a meeting note first.");
  button.disabled = true;
  const original = button.innerHTML;
  button.textContent = "Creating…";
  try {
    const result = await api("/api/note/pdf", {
      path: currentNotePath,
      view: currentNoteView,
      language: activeExportLanguage(),
    });
    viewerStatus(`PDF saved to ${result.pdf_path}`);
    return result;
  } finally {
    button.disabled = false;
    button.innerHTML = original;
  }
}

async function shareCurrentPdf(button) {
  if (!currentNotePath) throw new Error("Open a meeting note first.");
  button.disabled = true;
  const original = button.innerHTML;
  button.textContent = "Preparing…";
  try {
    const request = {
      path: currentNotePath,
      view: currentNoteView,
      language: activeExportLanguage(),
    };
    const created = await api("/api/note/pdf", request);
    if (typeof navigator.share === "function" && typeof File === "function") {
      try {
        const query = new URLSearchParams(request);
        const response = await fetch(`/api/note/pdf?${query}`);
        if (!response.ok) throw new Error("Could not read the generated PDF.");
        const file = new File([await response.blob()], created.filename, {
          type: "application/pdf",
        });
        const shareData = {
          title: $("viewerTitle").textContent,
          text: currentNoteView === "translation"
            ? `Complete meeting conversation in ${request.language} from BeyondMeetings`
            : currentNoteView === "discussion"
              ? "Meeting discussion summary from BeyondMeetings"
              : "Meeting minutes from BeyondMeetings",
          files: [file],
        };
        const canShare = typeof navigator.canShare !== "function"
          || navigator.canShare(shareData);
        if (canShare) {
          await navigator.share(shareData);
          viewerStatus("PDF shared.");
          return;
        }
      } catch (err) {
        if (err.name === "AbortError") {
          viewerStatus("Sharing cancelled.");
          return;
        }
      }
    }

    const fallback = await api("/api/note/share", request);
    viewerStatus(
      `PDF ready in Downloads/BeyondMeetings. Its folder is open, so you can attach ${fallback.filename} in any app without copying it.`
    );
  } finally {
    button.disabled = false;
    button.innerHTML = original;
  }
}

async function refresh() {
  try {
    renderStatus(await api("/api/recording"));
  } catch (err) {
    $("detail").textContent = `Cannot reach the local app: ${err.message}`;
    $("recordingBadgeText").textContent = "App offline";
  }
}

async function loadMeetings() {
  try {
    meetings = (await api("/api/meetings")).meetings;
    renderMeetings();
  } catch (_) { /* history is not critical to recording */ }
}

async function loadTasks() {
  try {
    tasks = (await api("/api/tasks")).tasks;
    renderTasks();
  } catch (_) { /* tasks are not critical to recording */ }
}

function showPanel(name) {
  for (const panel of ["meetings", "tasks", "chat"]) {
    $(`${panel}Panel`).hidden = panel !== name;
    $(`${panel}Tab`).classList.toggle("active", panel === name);
  }
  if (name === "tasks") loadTasks();
  if (name === "chat") setTimeout(() => $("chatInput").focus(), 0);
}

function chatMessage(text, who = "assistant") {
  const row = document.createElement("div");
  row.className = `message ${who === "user" ? "userMessage" : "assistantMessage"}`;
  if (who !== "user") {
    const avatar = document.createElement("div");
    avatar.className = "assistantAvatar small";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = "✦";
    row.append(avatar);
  }
  const bubble = document.createElement("div");
  bubble.className = "messageBubble";
  bubble.textContent = text;
  row.append(bubble);
  $("chatMessages").append(row);
  row.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return row;
}

function appendChatSources(sources) {
  if (!sources.length) return;
  const wrap = document.createElement("div");
  wrap.className = "chatSources";
  for (const source of sources) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "sourceCard";
    card.onclick = () => openNote(source.link, source.title, source);
    const date = document.createElement("span");
    date.className = "sourceDate";
    date.textContent = shortDate(source.date);
    const title = document.createElement("strong");
    title.textContent = source.title;
    const excerpt = document.createElement("span");
    excerpt.textContent = source.excerpt || source.summary || "Open meeting note";
    card.append(date, title, excerpt);
    wrap.append(card);
  }
  $("chatMessages").append(wrap);
  wrap.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function askLibrary(query) {
  query = query.trim();
  if (!query) return;
  chatMessage(query, "user");
  $("chatInput").value = "";
  $("chatSend").disabled = true;
  const waiting = chatMessage("Searching your local meeting library…");
  waiting.classList.add("thinking");
  try {
    const result = await api("/api/library/chat", { query });
    waiting.remove();
    chatMessage(result.answer);
    appendChatSources(result.sources || []);
  } catch (err) {
    waiting.remove();
    chatMessage(`I could not search the library: ${err.message}`);
  } finally {
    $("chatSend").disabled = false;
    $("chatInput").focus();
  }
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

$("openFolder").onclick = async () => {
  const btn = $("openFolder");
  btn.disabled = true;
  try { await api("/api/library/open", {}); }
  catch (err) { window.alert(`Could not open notes folder: ${err.message}`); }
  finally { btn.disabled = false; }
};
$("search").oninput = renderMeetings;
$("clearSearch").onclick = () => { $("search").value = ""; renderMeetings(); $("search").focus(); };
$("name").onkeydown = (e) => { if (e.key === "Enter") $("record").click(); };
$("meetingsTab").onclick = () => showPanel("meetings");
$("tasksTab").onclick = () => showPanel("tasks");
$("chatTab").onclick = () => showPanel("chat");
$("chatForm").onsubmit = (e) => { e.preventDefault(); askLibrary($("chatInput").value); };
$("suggestions").onclick = (e) => { if (e.target.matches("button")) askLibrary(e.target.textContent); };
$("minutesView").onclick = () => showNoteView("minutes");
$("discussionView").onclick = () => showNoteView("discussion");
$("translationView").onclick = () => showNoteView("translation");
$("translationLanguage").onchange = () => showNoteView("translation");
$('convertPdf').onclick = async (event) => {
  try { await createCurrentPdf(event.currentTarget); }
  catch (err) { viewerStatus(`Could not create PDF: ${err.message}`, true); }
};
$('sharePdf').onclick = async (event) => {
  try { await shareCurrentPdf(event.currentTarget); }
  catch (err) { viewerStatus(`Could not share PDF: ${err.message}`, true); }
};
$("closeViewer").onclick = () => $("viewer").close();
$("viewer").onclick = (e) => { if (e.target === $("viewer")) $("viewer").close(); };

refresh();
loadMeetings();
loadTasks();
