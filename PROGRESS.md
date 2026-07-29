# beyondMeetings — Build Progress

**Living document.** Update the checklists below as work completes. If a session is lost, read this file first — it is written to be resumable from cold with no prior context.

- **Design spec:** [`docs/superpowers/specs/2026-07-30-beyondmeetings-setup-design.md`](docs/superpowers/specs/2026-07-30-beyondmeetings-setup-design.md) — the authority on *why*. This file tracks *what's done*.
- **Repo root:** `~/meetings/beyondmeetings/` (deliberately **not** `~/meetings/`, which holds real client recordings and transcripts)
- **Started:** 2026-07-30
- **Current milestone:** 1 — Engine

---

## Status legend

`[ ]` not started `[~]` in progress `[x]` done `[!]` blocked (reason inline)

---

## 0. Cold-start briefing

**What this project is:** an open-source, installable version of the meeting pipeline in `~/meetings`. Record a call → transcribe → generate structured notes and tasks → write into an Obsidian vault, with follow-up meetings linked into chains.

**The problem it solves:** the working pipeline today lives as *prose instructions* in `~/meetings/CLAUDE.md`. It only works for Claude Code, on the author's machine, with a hardcoded personal ffmpeg path and an API key in a shell variable. beyondMeetings makes it installable by anyone in one command.

**The one architectural idea that everything follows from:** the LLM does judgment only and returns JSON; **Python performs every file write.** Task counters, follow-up back-links, note rendering, and the informal-call rule are all deterministic code. This is what makes provider choice (Claude/GPT/Gemini/Ollama) produce identical output, and it is what makes the thing testable.

---

## 1. Decisions already locked — do not relitigate

These were settled during design. Reopening them wastes a session.

| Decision | Choice | Why |
|---|---|---|
| OS support | **Linux only** (PipeWire) | macOS/Windows untestable from here; `audio/base.py` interface makes them drop-in contributions later |
| Stack | **Python + local web UI + system tray** | Python 3 ships on every Linux; no Node/Rust toolchain; low contributor barrier |
| Wizard form | **Single-screen live checklist** with % ring | Setup is a *detection* problem; also works as a repair tool on re-run |
| Daily UI | **Tray + full page** at `localhost:7788` | Same FastAPI app as the wizard; "re-run notes" recovery must not need a terminal |
| Note providers | **Claude / ChatGPT / Gemini / Ollama** — Claude badged *Recommended* | Ollama noted as weaker on code-mixed (Hinglish) transcripts |
| Transcription | **Groq default, whisper.cpp opt-in** | Groq is fast + free tier; local option for privacy |
| Note target | **Obsidian required** | Task Board / Home.md dashboards are Obsidian-flavoured |
| Distribution | **`curl \| bash` bootstrap** | One README line; script stays short and auditable |
| Rules files | `CLAUDE.md` + `AGENTS.md` + `GEMINI.md`, **generated from one template**, marked *do not edit* | The existing `~/meetings/AGENTS.md` already drifted months stale from `CLAUDE.md` — proof that duplicated prose rots |
| Rules file content | **Thin driver** over the CLI, not full pipeline prose | Two engines would disagree; behaviour belongs in Python |
| Secrets | **OS keyring**, `0600` file fallback | Never a shell env var |
| Project tags | **User-configurable list**, empty by default | `Acme` / `Zenith` are author-specific |
| Spoken language | Default **`auto`** | Current hardcoded `language=en` *translates* Hinglish instead of transcribing it |
| Notes output language | Default **English** | Speak Hinglish, get clean English notes — matches today's experience |

---

## 2. Bugs in the current pipeline that this port must fix

Carried from spec §9. Each one needs a test proving it's fixed.

- [ ] **B1** — `FFMPEG_BIN` hardcodes `~/Acme/acme-api/node_modules/@ffmpeg-installer/...` (`stop-meeting.sh:58`). Fatal for every other user. → resolve from `PATH`.
- [ ] **B2** — **Segmentation is documented but never implemented.** `CLAUDE.md` describes 50-minute segments transcribed in the background *during* recording; `stop-meeting.sh` only chunks the finished file. The org-wide Groq rate limit that broke a 5.7-hour recording on 2026-07-08 is still reachable today.
- [ ] **B3** — Groq key lives in a shell environment variable. → OS keyring.
- [ ] **B4** — Recording state spread across six dotfiles in `~/meetings/` (`.record_pid`, `.current_recording`, `.current_name`, `.current_filename`, `.mix_modules`, `.current_followup`). → one state file owned by `audio/pipewire.py`.
- [ ] **B5** — `-F "language=en"` forced on every transcription (`stop-meeting.sh:75`). → configurable, default `auto`.

---

## 3. Milestones

Four milestones, each independently useful. **Ships to GitHub after milestone 2.**

| # | Milestone | Delivers | Status |
|---|---|---|---|
| 1 | Engine | `start`/`stop` works end-to-end from a terminal, correct notes written | `[~]` in progress |
| 2 | Wizard | `install.sh`, checklist UI, % ring — the installable experience | `[ ]` |
| 3 | Providers | GPT/Gemini/Ollama, whisper.cpp, MCP registration | `[ ]` |
| 4 | App | Tray, full page, history, re-run notes | `[ ]` |

---

### Milestone 1 — Engine `[~]`

**Goal:** `beyondmeetings start "name"` then `beyondmeetings stop` produces a correct Obsidian note, Task Board entries, and Home.md update — no UI, no wizard, Claude only.

**Done when:** a real meeting recorded on this machine produces output equivalent to what the current CLAUDE.md pipeline produces, and `pytest` is green.

- [ ] `pyproject.toml` + package skeleton + dev deps
- [ ] `config.py` — TOML at `~/.config/beyondmeetings/config.toml`, keyring wrapper with file fallback *(fixes B3)*
- [ ] `audio/base.py` — `Recorder` interface: `start`, `stop`, `status`, segment callbacks
- [ ] `audio/pipewire.py` — null-sink mix, 50-min segment rollover, single state file *(fixes B2, B4)*
- [ ] `transcribe/base.py` — `Transcriber` interface
- [ ] `transcribe/groq.py` — chunked upload, model fallback, rate-limit backoff, configurable language *(fixes B1, B5)*
- [ ] `llm/base.py` — `MeetingNote` schema (spec §4), `LLMProvider` interface, JSON repair
- [ ] `llm/anthropic.py`
- [ ] `prompts/` — analysis prompt + follow-up candidate prompt (ports every rule from spec §5)
- [ ] `vault/scaffold.py` — idempotent `Home.md` / `Tasks/Task Board.md` / `Meetings/`
- [ ] `vault/note.py` — render `Meetings/YYYY-MM-DD/Title.md`
- [ ] `vault/followup.py` — gather candidates; write frontmatter, callout, back-link
- [ ] `vault/taskboard.py` — insert tasks, recompute counters
- [ ] `vault/home.py` — prepend Recent entry, sync counters, bump `updated:`
- [ ] `pipeline.py` — stop → transcribe → analyse → write
- [ ] `cli.py` — `start` / `stop` / `notes` (re-run on existing transcript)
- [ ] Tests: `vault/*` counter math, back-linking, scaffold idempotency
- [ ] Tests: JSON repair across malformed/fenced LLM output
- [ ] Tests: pipeline end-to-end with fixture transcript + stub LLM
- [ ] Manual verification: real recording on this machine

---

### Milestone 2 — Wizard `[ ]`

**Goal:** a stranger runs one `curl` command and reaches a working install.

**Done when:** wiping config and running `install.sh` reaches 100% and records a meeting successfully.

- [ ] `doctor/checks.py` — check object: `id`, `label`, `detect()`, `fix()`, `required`
- [ ] Checks 1–7 (PipeWire, ffmpeg, Groq key, provider key, Obsidian, vault, rules files) — see spec §6
- [ ] Key validation via **live API call**, never regex
- [ ] `server.py` — FastAPI app, `/setup` routes + JSON API
- [ ] `web/` — checklist UI, % ring, per-row Fix buttons, in-place input panels
- [ ] `rules.py` + single template → `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`
- [ ] Obsidian install via flatpak (Flathub)
- [ ] `install.sh` — Python check, venv, symlink `~/.local/bin`, launch wizard
- [ ] `cli.py doctor` — same check objects as the wizard
- [ ] `README.md` (with screenshot), `LICENSE`, `CONTRIBUTING.md`
- [ ] Tests: ring percentage, fix dispatch, rules-file generation
- [ ] **Ship to GitHub**

---

### Milestone 3 — Providers `[ ]`

**Goal:** provider choice is real, and MCP registration works per agent.

- [ ] `llm/openai.py`
- [ ] `llm/gemini.py`
- [ ] `llm/ollama.py` (+ note weaker code-mixed handling in the picker)
- [ ] `transcribe/whispercpp.py` + model download with progress
- [ ] `mcp_setup.py` — filesystem-based Obsidian MCP into Claude Code / Codex / Gemini CLI configs
- [ ] Skip-with-explanation when the chosen agent's CLI isn't installed
- [ ] Provider picker in wizard, Claude pre-selected + *Recommended* badge
- [ ] Tests: mocked HTTP per provider — request shape + JSON coercion

---

### Milestone 4 — App `[ ]`

**Goal:** the daily experience.

- [ ] `server.py` `/` route
- [ ] `web/` app page — Start/Stop, live elapsed time, transcription progress
- [ ] `tray.py` — pystray icon reflecting recording state
- [ ] Meeting history, searchable
- [ ] Re-run notes on an existing transcript (recovery without a terminal)
- [ ] Settings page
- [ ] Autostart `.desktop` entry
- [ ] Tests

---

## 4. Migration (after milestone 4)

- [ ] Run wizard against the existing vault at `~/Documents/Obsidian Vault` — scaffold must not overwrite existing content
- [ ] Confirm parity on a real meeting
- [ ] Delete `~/meetings/scripts/*.sh`, `~/meetings/CLAUDE.md`, and the stale `~/meetings/AGENTS.md`

---

## 5. Session log

Append one line per session. Newest last.

- **2026-07-30** — Design brainstormed and spec written (`781d85f`). Repo created at `~/meetings/beyondmeetings/`, git initialised, `.gitignore` added. Starting milestone 1.
