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
| Python bootstrap | **Prefer system Python ≥3.10, fall back to `uv`** | The real failures are a missing `python3-venv` (very common on Ubuntu/Debian → `ensurepip is not available`) and too-old Pythons on LTS distros (Ubuntu 20.04 = 3.8, RHEL 8 = 3.6), not an absent Python. `uv` is one static binary that brings its own CPython and clears all three at once. Probe venv by *attempting* one, not by parsing a version string |
| Rules files | `CLAUDE.md` + `AGENTS.md` + `GEMINI.md`, **generated from one template**, marked *do not edit* | The existing `~/meetings/AGENTS.md` already drifted months stale from `CLAUDE.md` — proof that duplicated prose rots |
| Rules file content | **Thin driver** over the CLI, not full pipeline prose | Two engines would disagree; behaviour belongs in Python |
| Secrets | **OS keyring**, `0600` file fallback | Never a shell env var |
| Project tags | **User-configurable list**, empty by default | `Acme` / `Zenith` are author-specific |
| Spoken language | Default **`auto`** | Current hardcoded `language=en` *translates* Hinglish instead of transcribing it |
| Notes output language | Default **English** | Speak Hinglish, get clean English notes — matches today's experience |

---

## 2. Bugs in the current pipeline that this port must fix

Carried from spec §9. Each one needs a test proving it's fixed.

- [x] **B1** — `FFMPEG_BIN` hardcodes `~/Acme/acme-api/node_modules/@ffmpeg-installer/...` (`stop-meeting.sh:58`). Fatal for every other user. → `transcribe/groq.py:resolve_ffmpeg()` resolves from `PATH`. Confirmed: this machine has ffmpeg at `/usr/bin/ffmpeg`.
- [x] **B2** — **Segmentation is documented but never implemented.** `CLAUDE.md` describes 50-minute segments transcribed in the background *during* recording; `stop-meeting.sh` only chunks the finished file. → `audio/pipewire.py:roll_segment()`. **Note:** implemented and tested, but nothing calls it on a timer until milestone 4 — see "Known gaps" below.
- [x] **B3** — Groq key lives in a shell environment variable. → `secrets.py`, OS keyring with a `0600` file fallback.
- [x] **B4** — Recording state spread across six dotfiles in `~/meetings/`. → one `recording-state.json` owned by `audio/pipewire.py`.
- [x] **B5** — `-F "language=en"` forced on every transcription (`stop-meeting.sh:75`). → `config.spoken_language`, default `auto`; the field is omitted from the request entirely when `auto`.

---

## 3. Milestones

Four milestones, each independently useful. **Ships to GitHub after milestone 2.**

| # | Milestone | Delivers | Status |
|---|---|---|---|
| 1 | Engine | `start`/`stop` works end-to-end from a terminal, correct notes written | `[x]` code complete — 136 tests green; awaiting real-recording verification |
| 2 | Wizard | `install.sh`, checklist UI, % ring — the installable experience | `[x]` code complete — 226 tests green |
| 3 | Providers | GPT/Gemini/Ollama, whisper.cpp, MCP registration | `[~]` next |
| 4 | App | Tray, full page, history, re-run notes | `[ ]` |

---

### Milestone 1 — Engine `[x]` code complete

**Goal:** `beyondmeetings start "name"` then `beyondmeetings stop` produces a correct Obsidian note, Task Board entries, and Home.md update — no UI, no wizard, Claude only.

**Done when:** a real meeting recorded on this machine produces output equivalent to what the current CLAUDE.md pipeline produces, and `pytest` is green.

Branch: `milestone-1-engine`. Run tests with `.venv/bin/python -m pytest`.

- [x] `pyproject.toml` + package skeleton + dev deps
- [x] `config.py` — TOML at `~/.config/beyondmeetings/config.toml`
- [x] `secrets.py` — keyring wrapper with `0600` file fallback *(fixes B3)*
- [x] `models.py` — `MeetingNote` / `ActionItem` / `Section` / `MeetingRef` (spec §4)
- [x] `audio/base.py` — `Recorder` interface + `RecordingState` *(fixes B4)*
- [x] `audio/pipewire.py` — null-sink mix, segment rollover, single state file *(fixes B2)*
- [x] `transcribe/base.py` — `Transcriber` interface
- [x] `transcribe/groq.py` — model fallback, rate-limit backoff, configurable language *(fixes B1, B5)*
- [x] `llm/base.py` — `LLMProvider` interface, JSON repair, candidate-id validation
- [x] `llm/anthropic.py`
- [x] `prompts.py` — analysis prompt porting every rule from spec §5
- [x] `labels.py` — display names, so notes never print raw config ids
- [x] `vault/paths.py` — filename sanitising + wikilinks
- [x] `vault/scaffold.py` — idempotent `Home.md` / `Tasks/Task Board.md` / `Meetings/`
- [x] `vault/note.py` — render `Meetings/YYYY-MM-DD/Title.md`
- [x] `vault/followup.py` — gather candidates; back-link into the previous note
- [x] `vault/taskboard.py` — insert tasks, recompute counters
- [x] `vault/home.py` — prepend Recent entry, sync counters, bump `updated:`
- [x] `pipeline.py` — transcript → analyse → write, with the informal-call rule
- [x] `cli.py` — `start` / `stop` / `notes`
- [x] Tests: 136 passing across 14 files
- [ ] **Manual verification: real recording on this machine** — the one step left; see §6

#### Bugs found during implementation (all fixed, all with regression tests)

1. **Follow-up back-link landed inside the YAML frontmatter.** `rpartition("\n---")` matched the frontmatter's own closing fence, not the footer rule, corrupting the note. Now `_split_frontmatter()` separates them first. The original test passed because it only asserted substrings existed — it never checked *position*.
2. **Callout header regexes swallowed a following blank line.** `\s*$` under `re.MULTILINE` matches newlines, so inserting the first task deleted the blank line before `> [!success]- Done`. Now `[ \t]*$`.
3. **Note footer printed raw config ids** — "Transcribed with groq · Generated by beyondMeetings (anthropic)". Now goes through `labels.py`.
4. **`stop` with no active recording dumped a traceback.** Now exits with `Nothing to stop — no active recording.`
5. **`safe_filename` dropped colons entirely**, turning "Phase 4: Planning" into "Phase 4 Planning". Colons are separators and now become hyphens, matching the vault's existing style.

Findings 1–3 were caught by running the pipeline end-to-end and *reading the output*, not by the unit tests. Worth repeating in later milestones.

---

### Milestone 2 — Wizard `[x]` code complete

**Goal:** a stranger runs one `curl` command and reaches a working install.

- [x] `doctor/base.py` — `Check`, `CheckResult`, `InputField`, `run_all()`, `completion_percent()`
- [x] `doctor/system.py` — PipeWire, ffmpeg, package-manager hints
- [x] `doctor/keys.py` — Groq + provider keys, **validated by live API call**
- [x] `doctor/obsidian.py` — detection (PATH, flatpak, snap) + flatpak install
- [x] `doctor/vault.py` — path selection, scaffold, config persistence
- [x] `doctor/rules_check.py` + `rules.py` — one template → three files
- [x] `doctor/registry.py` — ordered check list
- [x] `server.py` — `/api/status`, `/api/fix/{id}`, `/api/settings`, static page
- [x] `web/` — checklist UI, % ring, per-row Fix buttons, in-place input panels, light + dark
- [x] `install.sh` — system Python probe (creates a real venv, not a version check), `uv` fallback, `--no-uv`, `--dry-run`
- [x] `cli.py doctor` / `cli.py setup` — same check objects as the wizard
- [x] `README.md`, `LICENSE`, `CONTRIBUTING.md`
- [x] Tests: 226 passing
- [x] Verified on this machine: `doctor` reports 50%, correctly detecting PipeWire ✓, ffmpeg ✓, Obsidian ✓ (found at `/snap/bin/obsidian`), and the three missing items
- [x] Verified the wizard boots, serves its assets, and the full fix flow works end-to-end against a throwaway vault (scaffold → config persisted → ring 50→67% → rules written)
- [ ] **Ship to GitHub** — see release blockers below

#### Release blockers before pushing to GitHub

- [ ] Replace `REPLACE_ME` in `install.sh` (`REPO`), `README.md` and `CONTRIBUTING.md` with the real GitHub org/repo
- [ ] Add a wizard screenshot to `README.md`
- [ ] Confirm the author name in `LICENSE` is how you want to be credited

#### Open question raised during implementation

The generated `CLAUDE.md` / `AGENTS.md` / `GEMINI.md` land in the **vault root**, so a coding agent run there finds them. The cost is that Obsidian indexes them as three near-identical notes that show up in search and the graph view. Alternatives: put them in a subfolder (agents then need `--add-dir` or a `cd`), or make the location a wizard setting. Left as-is for now — decide before shipping.

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

## 5. Known gaps carried forward

- **Segment rollover has no timer yet.** `roll_segment()` is implemented and unit-tested, but nothing calls it on a schedule until the server's background loop in milestone 4. A meeting over 50 minutes still transcribes correctly (one long segment), it simply does not yet get the rate-limit spreading that B2 is ultimately about. **B2 is not fully closed until milestone 4.**
- **Only Claude works as a note writer.** The other three providers land in milestone 3. `ProviderKeyCheck` returns a clear "arrives in milestone 3" message if one is selected, rather than storing a key that cannot be used.
- **MCP registration (check 8) and the provider picker UI are deferred to milestone 3**, where the other providers land — a picker offering providers that cannot yet write notes would be a trap.
- **Tray autostart (check 9) is deferred to milestone 4**, with the tray itself.
- **Milestone 1 has still not been verified with a real recording.** Deferred at the user's request to the end of milestone 2. This is the only part of the engine never exercised against real audio.

---

## 6. Manual verification

The wizard now exists, so this is the real path:

```bash
cd ~/meetings/beyondmeetings
.venv/bin/beyondmeetings setup      # opens http://127.0.0.1:7788/setup
```

Work the checklist to 100%: paste your Groq and Claude keys (each is verified with a live API call before it is stored), point the vault row at a folder, and hit the rules row's Fix button.

**Rehearse against a throwaway vault first.** Point the vault row at an empty directory — `scaffold_vault()` populates it and never overwrites existing files, but a dry run means the real vault is untouched if something is wrong.

Then record:

```bash
.venv/bin/beyondmeetings start "Engine Smoke Test"
# speak for ~60 seconds
.venv/bin/beyondmeetings stop
```

Confirm all five:

1. The note exists at `Meetings/YYYY-MM-DD/<Title>.md` with a **real derived title**, not `recording-HH-MM`
2. Tasks appear in `Tasks/Task Board.md` as nested `> >` entries
3. The Pending counter matches in **both** `Task Board.md` and `Home.md`
4. The meeting is at the top of Home's Recent callout
5. The blank line before `> [!success]- Done` is intact

`beyondmeetings doctor` reports the same state as the wizard at any time — they share the check objects.

---

## 7. Session log

Append one line per session. Newest last.

- **2026-07-30** — Design brainstormed and spec written (`781d85f`). Repo created at `~/meetings/beyondmeetings/`, git initialised, `.gitignore` added.
- **2026-07-30** — Milestone 1 plan written (`f0871b2`), then implemented on branch `milestone-1-engine`. 136 tests passing. Five bugs found and fixed during implementation (see milestone 1 section). Remaining: manual verification with a real recording.
- **2026-07-30** — Python bootstrap strategy decided (system Python, `uv` fallback) and recorded in spec §11.
- **2026-07-30** — Milestone 2 planned and implemented on the same branch. 226 tests passing. Wizard verified booting and driving its full fix flow against a throwaway vault; `doctor` verified against this machine at 50%. Remaining before GitHub: the three release blockers above, plus milestone 1's real-recording check.
