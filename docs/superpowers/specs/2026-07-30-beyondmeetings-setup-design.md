# beyondMeetings — Design Spec

**Status:** Approved for planning
**Date:** 2026-07-30
**Location:** `~/meetings/beyondmeetings/` (new, isolated — the existing `~/meetings` pipeline keeps working untouched until cutover)

---

## 1. What this is

An open-source, installable version of the meeting pipeline currently living in `~/meetings`: record a call, transcribe it, generate structured notes and action items, link follow-up meetings into chains, and write it all into an Obsidian vault.

Today that pipeline works, but it is not distributable:

- The logic lives in `CLAUDE.md` as prose instructions to Claude Code. Another user with another agent gets different results, or none.
- `stop-meeting.sh` hardcodes an ffmpeg path inside the author's personal `node_modules`.
- The Groq key lives in a shell environment variable.
- Setup is entirely manual and undocumented.

beyondMeetings turns it into: **one install command, a setup wizard with live prerequisite detection, and a small local app with a Start/Stop button.**

### Scope of v1

| In | Out |
|---|---|
| Linux (PipeWire) | macOS, Windows — behind a clean interface for later contribution |
| Obsidian as the note target | Plain-folder / Logseq targets |
| Groq Whisper (default) + local whisper.cpp (opt-in) | Other STT providers |
| Claude / ChatGPT / Gemini / Ollama as note writers | Fine-tuned or self-hosted non-Ollama models |
| Obsidian MCP registration into the chosen agent's CLI | Shipping our own MCP server |

---

## 2. The central architectural change

**Today:** `CLAUDE.md` asks an agent to read the vault, judge follow-ups, do arithmetic on task counters, and edit three markdown files. This works because Opus is good at it, but it is non-deterministic, unportable across providers, and untestable.

**In beyondMeetings:** the LLM does judgment only and returns JSON. Python performs every file write.

```
Stop
 │
 ├─ audio/pipewire.py     stop capture; earlier 50-min segments already transcribed
 ├─ transcribe/           groq.py │ whispercpp.py            → transcript.txt
 │
 ├─ vault/followup.py     gather last ~30 days of notes' frontmatter + exec summaries
 │                        → passed to the LLM as candidates (it never browses the vault)
 │
 ├─ llm/                  anthropic │ openai │ gemini │ ollama
 │                        one call → one JSON object (schema in §4)
 │
 └─ vault/                pure Python, deterministic, unit-tested
      note.py             render Meetings/YYYY-MM-DD/Title.md
      followup.py         write frontmatter + callout; append to the prior note
      taskboard.py        insert tasks, recompute counters
      home.py             prepend Recent entry, sync counters, bump `updated:`
```

### Why this matters

| Behaviour today | After |
|---|---|
| "Informal call → no tasks" is a paragraph of hints | `is_informal` boolean; Python branches on it |
| Task Board / Home.md counters recomputed by an LLM | `len(pending)` |
| Follow-up detection depends on the agent listing the vault recursively | Python guarantees the candidate set; LLM only picks |
| Each agent produces different output | Every provider produces byte-identical file structure |

None of the author's rules are discarded — they move from a file an agent *might* read into a prompt that *always* runs. See §5 for the full mapping.

---

## 3. Repository layout

```
beyondmeetings/
├── install.sh                  curl|bash bootstrap → python check → venv → wizard
├── pyproject.toml
├── README.md  LICENSE  CONTRIBUTING.md
├── src/beyondmeetings/
│   ├── __main__.py             `beyondmeetings` → tray + local server
│   ├── cli.py                  setup │ start │ stop │ notes │ doctor │ ui
│   ├── config.py               TOML config + OS keyring for secrets
│   ├── server.py               one FastAPI app: /setup (wizard) + / (mini app)
│   ├── tray.py                 pystray icon
│   ├── pipeline.py             stop → transcribe → analyse → write
│   ├── audio/
│   │   ├── base.py             Recorder interface (start/stop/status/segments)
│   │   └── pipewire.py         Linux implementation
│   ├── transcribe/
│   │   ├── base.py │ groq.py │ whispercpp.py
│   ├── llm/
│   │   ├── base.py             summarise(transcript, candidates) → MeetingNote
│   │   └── anthropic.py │ openai.py │ gemini.py │ ollama.py
│   ├── vault/
│   │   ├── scaffold.py │ note.py │ taskboard.py │ home.py │ followup.py
│   ├── doctor/checks.py        prerequisite checks (drive the % ring)
│   ├── rules.py                generate CLAUDE.md / AGENTS.md / GEMINI.md
│   ├── mcp_setup.py            register Obsidian MCP into the chosen agent's config
│   └── web/                    static HTML/CSS/JS
└── tests/
```

Each module has one job and a stated interface. `audio/base.py` in particular exists so a macOS contributor adds one file rather than editing the pipeline.

---

## 4. Data contract

The LLM returns exactly this object. Adapters are responsible for coercing their provider's output into it (JSON mode where available, brace-extraction repair where not).

```jsonc
{
  "title": "Estimations Call",
  "date": "2026-07-30",
  "tags": ["meeting", "acme"],
  "attendees": ["Jordan", "Alex"],
  "executive_summary": "2–3 sentences.",
  "sections": [ { "heading": "Key Discussion Points", "bullets": ["…"] } ],
  // `sections` is free-form narrative content only. Decisions, open questions,
  // risks and action items are always their own typed fields below and must
  // never also appear in `sections` — Python renders each into its own heading.
  "decisions": ["…"],
  "open_questions": ["…"],
  "risks": ["…"],
  "action_items": [
    { "task": "…", "owner": "Alex", "due": "2026-08-02",
      "project": "Acme", "priority": "HIGH" }
  ],
  "is_informal": false,
  "follow_up_of": "2026-07-29/Design QA Review"   // or null
}
```

`follow_up_of` must be one of the candidate IDs supplied in the prompt, or `null`. Python rejects anything else and falls back to standalone — the model cannot invent a link to a note that does not exist.

---

## 5. Preserved behaviour

Every rule in the current `CLAUDE.md`, and where it lives now:

| Rule | New home | Net effect |
|---|---|---|
| Never ask for a meeting name | Rules file says don't ask; `beyondmeetings start` with no arg auto-names `recording-HH-MM` | Stronger — code backstop |
| Real title derived from transcript later | LLM returns `title`; Python names the note | Same |
| Follow-up judged from transcript, never the name | Python supplies 30-day candidates; LLM picks | Stronger |
| Strong-evidence bar; most recent wins; standalone when unsure | Verbatim in the prompt | Same |
| Informal/personal call → zero tasks | `is_informal` → Python branch | Stronger, inspectable |
| Extract implied work, not just stated action items | Verbatim in the prompt | Same |
| Task Board ↔ Home.md counters in sync | `len(pending)` | Much stronger |
| Date-wise `YYYY-MM-DD/` folders; bare note filenames; full-path wikilinks | `vault/note.py`, `vault/scaffold.py` | Same |
| Follow-up callout + `follow_up_of` frontmatter + back-link in prior note | `vault/followup.py` | Same |

**Deliberately made configurable:** the `Acme` / `Zenith` project tags are hardcoded to the author today. They become a user-defined project list, empty by default.

---

## 6. Setup wizard

**Form:** single-screen live checklist (not a linear stepper). A completion ring shows `passing_required / total_required`. Each row auto-detects, and each failing row has its own Fix button. Steps needing input (provider choice, keys, vault path) open a panel in place.

This form was chosen because setup here is fundamentally a *detection* problem — a stepper would make users click Next through screens that all say "already fine" — and because it doubles as a repair tool when someone re-runs it months later with an expired key.

Every check is one object: `id`, `label`, `detect() -> ok|missing|broken`, `fix()`, `required`. The same objects back `beyondmeetings doctor`, so wizard and terminal can never disagree.

| # | Check | Required | Auto-fix |
|---|---|---|---|
| 1 | PipeWire (`pactl info`, `pw-record`) | yes | no — hard blocker, explains why |
| 2 | ffmpeg on `PATH` | yes | yes — apt/dnf/pacman |
| 3 | Groq key, **validated by live API call** | yes¹ | key entry |
| 4 | Note provider + key, validated | yes | provider picker |
| 5 | Obsidian installed | yes | yes — flatpak from Flathub |
| 6 | Vault chosen + scaffolded | yes | yes — writes `Home.md`, `Tasks/Task Board.md`, `Meetings/` |
| 7 | Rules file(s) generated | yes | yes |
| 8 | Obsidian MCP registered | no | yes — into the chosen agent's config |
| 9 | Tray autostart `.desktop` | no | yes |

¹ Not required if local whisper.cpp is selected instead.

Keys are validated with a real request, never a regex. "I pasted my key and nothing happened" is the most common first-run failure in projects of this kind.

**Provider picker:** Claude / ChatGPT / Gemini / Ollama shown together, **Claude pre-selected and badged "Recommended"** for note quality. Ollama is labelled as weaker on code-mixed (e.g. Hinglish) transcripts.

**MCP choice:** a filesystem-based Obsidian MCP requiring only a vault path. The popular alternative needs Obsidian's Local REST API community plugin plus a second key copied out of it — three extra failure points inside the wizard, for a bonus feature rather than the core loop.

---

## 7. Generated rules files

The wizard writes `CLAUDE.md`, `AGENTS.md`, and `GEMINI.md` from **one template**, each marked *generated — do not edit*.

They are **thin drivers**, roughly 40 lines: how to start and stop a recording via the CLI, and the vault conventions so an agent can answer questions about past meetings through the MCP. Behaviour lives in Python.

**Rationale, from evidence in this very repo:** the existing `~/meetings/AGENTS.md` is already a stale copy of `CLAUDE.md`. It still performs keyword-based follow-up detection on the meeting *name* — the approach `CLAUDE.md` explicitly replaced with transcript-based detection — and has neither date-wise subfolders nor the informal-call rule. One author, one machine, one project, and the duplicate drifted months out of date. Four such files across an open-source repo with outside contributors would drift faster. Generating them from a single template makes drift structurally impossible.

---

## 8. Language handling

`stop-meeting.sh` currently hardcodes `-F "language=en"`, which instructs Whisper to *translate* non-English speech rather than transcribe it. For Hinglish calls this silently degrades the transcript before the note writer ever sees it.

Two settings:

- **Spoken language** — default `auto`. Produces a faithful transcript of code-mixed speech.
- **Notes output language** — default English. The note writer receives the transcript in whatever language was spoken and emits notes in the configured output language.

Net effect: speak Hinglish, get clean English notes — the current experience, on a better transcript.

---

## 9. Bugs fixed during the port

1. **`FFMPEG_BIN` hardcodes `~/Acme/acme-api/node_modules/@ffmpeg-installer/...`** (`stop-meeting.sh:58`). Fatal for every other user. Resolve from `PATH`.
2. **Segmentation is documented but not implemented.** `CLAUDE.md` describes 50-minute segments transcribed in the background during recording, to spread Groq API calls across the meeting's real duration. `stop-meeting.sh` only chunks the already-finished file, so the org-wide rate limit that broke a 5.7-hour recording on 2026-07-08 is still reachable. Implement real segmentation in `audio/pipewire.py`.
3. **Secrets in a shell environment variable.** Move to the OS keyring, with a `0600` file fallback.
4. **Recording state spread across six dotfiles** in `~/meetings/` (`.record_pid`, `.current_recording`, `.current_name`, `.current_filename`, `.mix_modules`, `.current_followup`). Replace with a single state file owned by `audio/pipewire.py`.
5. **Forced `language=en`** — see §8.

---

## 10. Day-to-day UI

Tray icon plus a full local page at `localhost:7788`, served by the same FastAPI app as the wizard.

The page holds: a large Start/Stop control with live elapsed time and transcription progress; a searchable meeting history; settings; and re-run-notes on an existing transcript. That last one matters — when note generation fails, recovery must not require a terminal.

The tray icon gives one-click Start/Stop without opening the page, and reflects recording state.

---

## 11. Distribution

```
curl -fsSL https://raw.githubusercontent.com/<user>/beyondmeetings/main/install.sh | bash
```

The script creates an isolated environment under `~/.local/share/beyondmeetings`, installs the package, symlinks `beyondmeetings` into `~/.local/bin`, and opens the wizard in the browser. It stays short and readable so a cautious user can audit it first. `CONTRIBUTING.md` documents the `git clone && ./install.sh` path.

### Python bootstrap

The wizard is served by the Python app itself, so there is no way to show a graphical installer before Python exists. The bootstrap is unavoidably terminal-level; the UI begins at step two.

"No Python at all" is the rare case. Three failures actually matter, in order of likelihood:

| Failure | Where it bites | Symptom |
|---|---|---|
| `python3-venv` not installed | Ubuntu/Debian, very common | `ensurepip is not available` |
| Python older than 3.10 | Ubuntu 20.04 (3.8), Debian 11 (3.9), RHEL 8 (3.6) | version check fails |
| No `python3` on `PATH` | rare on desktops | `command not found` |

**Strategy: prefer system Python, fall back to `uv`.** The script probes for Python ≥3.10 *and* a working `venv` (by actually attempting one, not by parsing a version string — the venv package can be missing on a perfectly modern Python). If that succeeds, it is used directly and nothing is downloaded. If any check fails, the script bootstraps [`uv`](https://github.com/astral-sh/uv) — a single static binary with no dependencies that installs its own standalone CPython — and builds the environment with that instead. This clears all three failures at once, including on distros where no package-manager command can reach 3.10.

The fallback is announced before it downloads anything, and `--no-uv` skips it in favour of printing the distro-specific fix (`sudo apt install python3-venv`, etc.) for users who would rather not fetch a binary.

All runtime dependencies (pydantic, httpx, keyring, tomli-w) are pure-Python or ship manylinux wheels, so a compiler is never required.

Config: `~/.config/beyondmeetings/config.toml`. Secrets: OS keyring.

**The repository root is `~/meetings/beyondmeetings/`, not `~/meetings/`.** The parent directory contains real recordings and transcripts of client calls; a repo at that level risks publishing them.

---

## 12. Testing

| Area | Approach |
|---|---|
| `vault/` | Pure functions over temp dirs: counter arithmetic, follow-up back-linking, note rendering, scaffold idempotency. This is where note-corrupting bugs live. |
| `llm/` | Mocked HTTP. Assert request shape per provider, and that malformed/fenced JSON is repaired into a valid `MeetingNote`. |
| `doctor/` | Injected detect results; assert ring percentage and fix dispatch. |
| `pipeline.py` | End-to-end with a fixture transcript and a stub LLM; assert the exact set of files written. |
| `audio/` | Manual — requires a live sound server. Documented in `CONTRIBUTING.md`. |

---

## 13. Build order

This spec is larger than one implementation plan. It decomposes into four milestones, each independently useful and testable:

| # | Milestone | Delivers |
|---|---|---|
| 1 | **Engine** — `config`, `audio/pipewire`, `transcribe/groq`, `llm/anthropic`, `vault/*`, `pipeline` | `beyondmeetings start` / `stop` works end-to-end from a terminal, writing correct notes. Fixes §9 bugs 1–5. |
| 2 | **Wizard** — `doctor/checks`, `server` `/setup` route, `rules.py`, `scaffold` | The installable experience: `install.sh`, checklist UI, % ring. Ships to GitHub after this. |
| 3 | **Providers** — `llm/openai`, `llm/gemini`, `llm/ollama`, `transcribe/whispercpp`, `mcp_setup` | Provider choice and MCP registration. |
| 4 | **App** — `server` `/` route, `tray`, history, re-run notes | The daily UI. |

Milestone 1 is the natural first plan: everything else depends on the data contract in §4 being real.

---

## 14. Migration

The existing `~/meetings` pipeline is untouched while beyondMeetings is built. Cutover is a wizard run pointed at the existing vault; `vault/scaffold.py` is idempotent and will not overwrite existing `Home.md` or `Task Board.md` content. The old bash scripts and the stale root-level `AGENTS.md` are deleted only once the new path is confirmed working.
