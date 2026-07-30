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
| Note providers | **Agent CLIs first** (Claude Code / Codex / Gemini CLI), then Ollama, then API keys. Claude Code badged *Recommended* and is the default | **Corrected 2026-07-30 after the real-recording test.** An API-key-only design locked out everyone on a Claude Pro/Max, ChatGPT Plus or Gemini subscription — they have working inference installed but no API credits, and that is most likely users. `claude -p` with the prompt on stdin was verified working on a subscription. Prompt goes over stdin, not argv, because an hour-long transcript exceeds sane argument sizes |
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
| 3 | Providers | GPT/Gemini/Ollama, whisper.cpp, MCP registration | `[x]` code complete — 330 tests green |
| 4 | App | Tray, full page, history, re-run notes | `[x]` code complete — 407 tests green |

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

- [x] Replace the repo URL in `install.sh`, `README.md` and `CONTRIBUTING.md` — now `nikhilm55/beyondmeetings`
- [ ] Add a wizard screenshot to `README.md`
- [x] Confirm the author name in `LICENSE` is how you want to be credited

#### Open question raised during implementation

The generated `CLAUDE.md` / `AGENTS.md` / `GEMINI.md` land in the **vault root**, so a coding agent run there finds them. The cost is that Obsidian indexes them as three near-identical notes that show up in search and the graph view. Alternatives: put them in a subfolder (agents then need `--add-dir` or a `cd`), or make the location a wizard setting. Left as-is for now — decide before shipping.

---

### Milestone 3 — Providers `[x]` code complete

**Goal:** provider choice is real, and MCP registration works per agent.

- [x] `llm/factory.py` — `cli.py` no longer hardcodes Anthropic
- [x] `llm/openai.py` — native JSON mode
- [x] `llm/gemini.py` — native JSON mode; key in a header, never the query string
- [x] `llm/ollama.py` — keyless; actionable errors for a stopped daemon and an un-pulled model
- [x] `transcribe/whispercpp.py` + model download with progress
- [x] `transcribe/factory.py` and `doctor/transcriber.py`
- [x] `doctor/keys.py` — validators for OpenAI and Gemini; Ollama checks daemon + model instead of a key
- [x] `mcp_setup.py` — filesystem MCP into Claude Code / Codex / Gemini CLI configs, merged atomically with a `.bak`
- [x] `doctor/mcp.py` — skips with an explanation when no agent CLI is installed
- [x] `doctor/choices.py` + wizard choice rows — Claude pre-selected with a *recommended* badge
- [x] Tests: 330 passing
- [x] Verified end-to-end: switching provider relabels the key row; switching to whisper.cpp **removes the Groq key row entirely**; MCP refuses without a vault, then registers into Claude Code while preserving existing config and writing a backup
- [x] Verified `doctor` on this machine detects Claude Code as installed-but-unregistered

#### Notable design decisions

- **The Groq key stops being a prerequisite when local transcription is chosen.** The check registry is built from config, so irrelevant rows disappear rather than sitting there red.
- **Ollama has no `fix()`.** The wizard cannot start a daemon or pull a 9 GB model on the user's behalf; it reports exactly what to run instead.
- **MCP is `@modelcontextprotocol/server-filesystem` scoped to the vault**, not `mcp-obsidian` — the latter needs the Local REST API plugin installed *and* a second key copied out of it.
- **`~/.claude.json` safety.** On this machine that file is 79 KB of real config. Registration merges, copies to `.bak`, and writes via a temp file + rename. A corrupt existing config is refused rather than overwritten. Four tests cover this.

#### Known soft spot

**Model defaults will go stale.** `gpt-4o`, `gemini-2.0-flash`, `qwen2.5:14b` and `claude-opus-5` are the current defaults, all overridable via `model` in config. Model names churn faster than this code will; a wrong value produces a clear API error rather than silent misbehaviour. Worth a review before release.

#### Test updated rather than added

`test_doctor_registry.py::test_registry_returns_checks_in_a_stable_order` pinned the old seven-row order and legitimately failed — the registry now returns eleven rows with choices first. `test_doctor_keys.py::test_unsupported_provider_explains_it_arrives_later` asserted OpenAI was unsupported, which milestone 3 made false. Both were replaced rather than deleted.

---

### Milestone 4 — App `[x]` code complete

**Goal:** the daily experience.

- [x] `segments.py` — per-segment transcript cache; earlier audio discarded once cached
- [x] `rollover.py` — `tick()` over an injected clock, so segmentation is tested without threads
- [x] `session.py` — `SessionManager`; `run_stop()` is synchronous for tests, `stop()` wraps it in a thread
- [x] `history.py` — meeting listing from the vault
- [x] `server.py` — `/` is the app, `/setup` the wizard; recording, meetings and regenerate endpoints
- [x] `web/app.{html,css,js}` — Start/Stop, live timer, transcription progress, searchable history
- [x] Re-run notes on an existing transcript (recovery without a terminal)
- [x] `tray.py` — optional pystray icon reflecting recording state
- [x] `doctor/autostart.py` — `.desktop` entry, with `--no-browser` so login doesn't fling a tab open
- [x] `cli.py serve` — page + tray, degrading to a printed hint without the extra
- [x] Tests: 407 passing
- [x] Verified `serve` boots and every route responds; unknown assets 404
- [x] Verified the tray icon renders in both states (idle centre indigo, recording centre white)

#### B2 is now genuinely closed

Verified by simulating a **3-hour meeting** with a fake clock ticking every 20 seconds:

```
Meeting ran 09:00 -> 12:00, 4 segments
API calls DURING the meeting:  09:50, 10:40, 11:30
Extra API calls at stop time:  1  (only the final segment)
Audio left on disk:            seg003.wav only
Cached transcripts:            all four, assembled in order
```

That is the behaviour the old `CLAUDE.md` described but never implemented. The 2026-07-08 failure mode — hours of audio submitted in one burst — is no longer reachable.

#### Design decisions worth keeping

- **The transcript is written to disk before the LLM is called.** A note-generation failure surfaces the transcript path plus a Regenerate button in the UI. Losing an hour of audio to an API outage would be the worst possible failure for this tool, so it is structurally impossible.
- **Threads are kept thin and untested on purpose.** `RolloverWorker.tick(now)` and `SessionManager.run_stop()` hold all the logic and are called directly by tests. The threads do nothing but schedule.
- **The tray is an optional extra.** pystray pulls a GTK/AppIndicator stack that varies by desktop; the page is fully usable without it and `serve` says so.
- **No auth on the local server.** It binds `127.0.0.1` only — same posture as the wizard.

#### Test updated rather than added

`test_doctor_registry.py::test_registry_returns_checks_in_a_stable_order` failed again when `autostart` joined the registry — correctly. Updated to twelve rows.

---

## 4. Migration (after milestone 4)

- [ ] Run wizard against the existing vault at `~/Documents/Obsidian Vault` — scaffold must not overwrite existing content
- [ ] Confirm parity on a real meeting
- [ ] Delete `~/meetings/scripts/*.sh`, `~/meetings/CLAUDE.md`, and the stale `~/meetings/AGENTS.md`

---

## 4b. Code review — 2026-07-30

An external review found **13 findings**, most CONFIRMED by reproduction. Tier 1 (blockers) and Tier 2 (ship-blockers) are fixed; every fix has a regression test. **488 tests passing.**

### The blocker

**The app's Start/Stop button could not work at all.** `compress_for_upload` had exactly one caller — `cli.py` — so the app path uploaded raw WAV to Groq: ~1.15 GB per 50-minute segment against a 25 MB cap, retried six times. Compression now lives *inside* `GroqTranscriber.transcribe_file`, where no caller can forget it.

Root cause: `cli.py stop` and `session.run_stop()` were two independent stop pipelines that diverged — only one compressed, only one used the segment cache, only one closed B2. `cli.py stop` now delegates to `run_stop()`. This is the same duplication failure this project cites as its reason for generating the three rules files from one template.

### Fixed, with regression tests

| # | Finding | Fix |
|---|---|---|
| 1 | App uploaded raw WAV; two divergent stop pipelines | Compression inside the transcriber; one pipeline |
| 2 | `stop()` raced a mid-flight `roll_segment()`, wedging the app permanently | Join the ticker before teardown; recorder owns a lock |
| 3 | Follow-up back-link landed under the *last* section, not `## Follow-ups` | Section ends at the next heading; handles renamed headings, EOF headings, code fences |
| 4 | `add_tasks` not idempotent — Regenerate duplicated every task and counter | Skips entries already on the board for that meeting |
| 5 | Model-controlled `date` reached the filesystem; `../../tmp` escaped the vault, and `2026-7-9` wrote invisible notes | Pattern-validated `IsoDate`; containment assert at the write; malformed date degrades to the recording date |
| 6 | `~/.claude.json` downgraded to 0644, symlinks clobbered, no fsync, `.bak` overwritten | Mode preserved, symlink followed, fsync before rename, pristine backup kept; Claude Code's own CLI preferred |
| 7 | Four crash paths on realistic API responses (null content, missing content key, HTML error body, truncation) | Shared `llm/http.py`; finish-reason checks; `max_tokens` 8000→16000 |
| 8 | `start()` check-then-act — four concurrent calls all loaded PipeWire modules | Guards and `recorder.start()` inside the lock |
| 9 | A corrupt state file 500'd every poll with no UI way out | `status()` reports it; **Clear recording state** button |
| 10 | Ollama sent no `num_ctx`, silently dropping ~3/4 of an hour-long transcript | Explicit `num_ctx`; oversized prompts refused, not truncated |
| 11 | Secrets world-readable during write; keyring failure silent | `os.open` with 0600; failure logged and surfaced; key fragments redacted from error text |
| 12 | `fix()` unguarded while `detect()` was guarded | `run_fix()` contains failures the same way |
| 13 | YAML frontmatter injection; `retry-after: "7.66s"` crashed `float()` | Values escaped (verified with PyYAML); tolerant `retry-after` parsing |

Plus a **DNS-rebinding + file-exfiltration hole** the review found that wasn't in the original list: binding 127.0.0.1 doesn't stop an attacker's domain resolving there, and `/api/regenerate` read any path and shipped it to a third-party API. Now Host must be loopback, and only files under `data_dir/transcripts` are readable.

### Verified against real behaviour, not just tests

- Exfiltration attempt on `id_rsa` → **403**, contents never in the response
- `Host: evil.example.com` → **421**; `localhost:7788` → 200
- A 0600 symlinked `~/.claude.json` → symlink intact, mode `0o600`, existing keys preserved
- The real `~/.claude.json` md5 is **unchanged** across the whole suite

### Deferred (Tier 3, architecture)

The reviewer argued three designs are wrong, not just their code. I agree, and none are done:

1. **Regexes are the wrong tool for editing live user files.** Eight regexes across `taskboard.py`/`home.py`/`followup.py` must agree about document structure, and #3 was two of them disagreeing. Seven bugs have now shipped in this layer. The fix that closes the class is explicit region markers (`%% beyondmeetings:pending-start %%`) or a parsed structural model — which would also make #4 idempotent for free rather than by string matching.
2. **Recording state still has two owners.** Both now lock, but `SessionManager` guards Python fields while the JSON file decides whether a recording exists. Correct today; still the wrong shape.
3. **`generate_notes` is not transactional.** Four writes (note, back-link, board, dashboard), any of which can fail mid-way. Idempotency makes a retry safe, but a partial vault is still reachable.

---

## 5. What remains before shipping

**The project is feature-complete against the spec.** All four milestones are code complete and all five original bugs are fixed. What is left is verification and release hygiene, not features.

### Real-recording test — 2026-07-30 ✅

Ran for the first time. **Six things worked on the first try:**

| | Result |
|---|---|
| `pw-record` capture | ✅ 5.6 MB WAV from a real 30s recording |
| Compression + Groq upload | ✅ no 413 — review fix #1 validated live |
| **Hindi kept in Devanagari, not translated** | ✅ **B5 proven fixed** — the old `language=en` would have mangled it |
| Segment transcript cache | ✅ `seg000.txt` written beside the audio |
| Transcript saved before the LLM ran | ✅ the recording survived a provider failure |
| Recorder state cleaned up | ✅ no wedge, no orphaned modules |
| `is_informal` on real content | ✅ recognised a tooling smoke test as personal — note kept its action item, Task Board stayed at 0 |
| Filename sanitising | ✅ em-dash title → `-` in the filename, em-dash preserved in the display link |

**The one failure was architectural, not a bug:** note generation needs an API key, and the user is on a subscription with no credits. Gemini API returned `429 limit: 0` for an account that has never used it. Fixed by adding agent-CLI providers (see the decisions table). Regenerating the same transcript through `claude-cli` produced a correct, high-quality note including a `transcription_note` that flagged the garbled Hindi and listed its inferred substitutions.

**Two orphans found during setup, both pre-existing:**

- `pw-record` from the **old bash pipeline, running since 2026-07-17 — 13 days, 73 GB**, capturing mic and system audio continuously. Its PID lived in `~/meetings/.record_pid`, which was long gone, so nothing knew it existed. B4 in its most literal form.
- A 2.6 GB orphan from one of this session's intermediate test runs. The current suite spawns nothing — verified by process count before/after and by grep for `PipeWireRecorder(` without an injected runner.

### Still never exercised against reality

1. **Long-meeting rollover has not run for real.** The 3-hour simulation used a fake clock; a real 50-minute rollover has never happened. Every layer above the audio capture is tested, but `pw-record`/`pactl` have only ever been driven by a fake runner. This is the largest untested surface in the project, and the code review is a reminder of what that hides — the app's Start button was broken in a way no test caught. Steps are in §6.
2. **Only Groq and `claude-cli` have run for real.** The OpenAI, Gemini, Anthropic and Ollama adapters remain mock-tested only. `codex-cli` and `gemini-cli` command shapes are unverified — neither CLI is installed here — which is why `agent_command` exists as a config override.
3. **whisper.cpp has never actually run.** The binary exists on this machine at `~/whispercpp/whisper.cpp/build/bin/whisper-cli`; the adapter's argument construction is tested with a fake runner but never invoked for real.
4. **The tray icon has never been displayed.** `pystray` is installed in the dev venv and the icon images render correctly (verified pixel values), but `icon.run()` has not been called on a real desktop session.

### Release blockers

- [x] Replace the repo URL in `install.sh`, `README.md` and `CONTRIBUTING.md` — now `nikhilm55/beyondmeetings`
- [ ] Add a wizard/app screenshot to `README.md`
- [x] Confirm the author name in `LICENSE`
- [ ] Review model defaults (`gpt-4o`, `gemini-2.0-flash`, `qwen2.5:14b`, `claude-opus-5`) — these churn fast
- [ ] Decide whether to do the Tier 3 architecture work (§4b) before or after first release
- [ ] Decide where the generated rules files live (see the milestone 2 open question about vault-root clutter)

---

## 6. Manual verification

```bash
cd ~/meetings/beyondmeetings
.venv/bin/beyondmeetings setup      # opens http://127.0.0.1:7788/setup
```

Work the checklist to 100%: paste your Groq and Claude keys (each is verified with a live API call before it is stored), point the vault row at a folder, and hit the rules row's Fix button.

**Rehearse against a throwaway vault first.** Point the vault row at an empty directory — `scaffold_vault()` populates it and never overwrites existing files, but a dry run means the real vault is untouched if something is wrong.

Then record — either from the app, which shows progress as it happens:

```bash
.venv/bin/beyondmeetings serve      # click Start, speak, click Stop
```

or from the terminal:

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
- **2026-07-30** — Milestone 3 planned and implemented. 330 tests passing. All four providers, whisper.cpp, both factories, and MCP registration done. Verified provider/transcriber switching reshapes the check list, and MCP registration preserves an existing `~/.claude.json`. Still outstanding: the real-recording test, and no provider has yet made a live API call.
- **2026-07-30** — **First real recording test.** Capture, compression, Groq transcription, Hindi fidelity, segment caching, transcript-safety and the informal-call rule all worked first time. Note generation failed for a structural reason: API-key-only providers exclude subscription users. Added agent-CLI providers (`claude-cli` default, verified working with no key); 510 tests passing. Also found a 13-day / 73 GB orphaned recorder left by the old bash pipeline.
- **2026-07-30** — External code review; 13 findings. Tier 1 + 2 fixed across 5 commits, 488 tests passing. Biggest: the app's Start/Stop could never have worked (raw WAV to Groq), caused by two divergent stop pipelines. Also fixed a DNS-rebinding + file-exfiltration hole the review found beyond its own list. Tier 3 architecture work deferred and documented.
- **2026-07-30** — Milestone 4 planned and implemented. 407 tests passing. **Project is feature-complete against the spec.** App page, tray, history, regenerate-on-failure, autostart. **B2 verified closed** by simulating a 3-hour meeting: API calls at 09:50/10:40/11:30 and only one at stop time. `pystray` + `pillow` installed in the dev venv so the icon tests run rather than skip. Everything in §5 "never exercised against reality" is what remains.
