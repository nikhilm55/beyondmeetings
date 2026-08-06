# BeyondMeetings

Record a meeting, get structured notes in Obsidian. Locally, on Linux.

beyondMeetings captures every voice on the call, transcribes it, and writes a
meeting note with an executive summary, decisions, action items and open
questions — then adds the action items to a task board, updates a dashboard,
and links follow-up meetings into chains.

## Installation

**Step 1 — install it.** One command:

```bash
curl -fsSL https://raw.githubusercontent.com/nikhilm55/beyondmeetings/main/install.sh | bash
```

Prefer to read the script first? That is reasonable:

```bash
curl -fsSL https://raw.githubusercontent.com/nikhilm55/beyondmeetings/main/install.sh -o install.sh
less install.sh
bash install.sh
```

It checks your system, installs into `~/.local/share/beyondmeetings-app`, adds
a `beyondmeetings` command to `~/.local/bin`, puts an app icon in your
applications menu, and opens the setup wizard.

**Step 2 — finish the wizard.** It opens at `http://127.0.0.1:7788/setup`
automatically. Work down the checklist until the ring reads 100%:

- **Note writer** → **Claude Code** (needs no API key, uses your subscription)
- **Groq API key** → paste one from [console.groq.com](https://console.groq.com);
  it is verified with a live call before being saved
- **Obsidian vault** → the folder you want your notes in

**Step 3 — use it.** Click the **beyondMeetings** icon in your applications, or:

```bash
beyondmeetings open
```

Then hit **Start**, have your meeting, hit **Stop**. Or skip the UI:

```bash
beyondmeetings start "Client kickoff"
# … have your meeting …
beyondmeetings stop
```

Either way, stopping does everything: transcribes, analyses, writes the note,
updates your task board.

### If `beyondmeetings` is not found

`~/.local/bin` is not on your `PATH`. Add it:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
```

The installer warns you if this applies.

### Updating

```bash
curl -fsSL https://raw.githubusercontent.com/nikhilm55/beyondmeetings/main/install.sh | bash
```

Same command. Your settings, keys and recordings are left alone.

---

### Long meetings

Recording rolls over into fresh segments every 50 minutes, and each closed
segment is transcribed in the background *while the next one records*. By the
time you hit Stop, almost everything is already done — and the transcription
API is never handed hours of audio in one burst. A five-hour meeting works.

---

## What you get

For every meeting, a note at `Meetings/YYYY-MM-DD/[Title].md`:

- **Executive summary**, decisions, action items with owners and due dates,
  open questions, risks, and discussion points
- **Follow-up chains** — if a meeting continues an earlier one, both notes are
  linked, in both directions
- **Task board** entries for every action item, with priorities and back-links
- **Dashboard** kept in sync automatically

The title is derived from what was actually discussed, so you never have to
name a meeting before it starts.

---

## Requirements

**Linux only.** Audio capture uses PipeWire, which has no macOS or Windows
equivalent. The capture layer sits behind a single interface
(`src/beyondmeetings/audio/base.py`) — a port needs one new file and nothing
else. Contributions very welcome.

You also need:

- **ffmpeg** — the installer offers to install it
- **Obsidian** — the installer offers to install it from Flathub
- A **Groq API key** for transcription (free tier is ample), *or* local
  whisper.cpp
- A way to write notes — **your existing Claude/ChatGPT/Gemini subscription
  is enough**, see below

Run `beyondmeetings doctor` at any time to see what is missing.

---

## Choosing your AI

**You do not need an API key.** If you already have a Claude, ChatGPT or
Gemini subscription with its CLI installed, beyondMeetings drives that — your
subscription does the work, and nothing is billed per token.

### No API key needed

| Provider | Needs | Notes |
|---|---|---|
| **Claude Code** | `claude` installed and signed in | **Recommended.** Best summary quality and follow-up detection. |
| **Codex CLI** | `codex` installed and signed in | Uses your ChatGPT subscription. |
| **Gemini CLI** | `gemini` installed and signed in | Uses your Google account. |
| **Ollama** | `ollama serve` + a pulled model | Fully local; nothing leaves your machine. Weaker on code-mixed speech (e.g. Hinglish). |

### API key required

These need a key **with credits**, which is separate from a subscription — a
Claude Pro plan does not come with API credits.

| Provider | Default model |
|---|---|
| Claude API | `claude-opus-5` |
| ChatGPT API | `gpt-4o` |
| Gemini API | `gemini-2.0-flash` |

Pick yours in the setup wizard. To use a different model, set `model` in
`~/.config/beyondmeetings/config.toml` — model names change faster than this
project releases, so the defaults are a starting point, not a constraint. If an
agent CLI needs a different invocation, set `agent_command` rather than
patching the code.

Whichever you choose, the *files* are identical — the notes, task board and
dashboard are written by deterministic Python, not by the model. The model
only decides what the meeting was about. Swapping providers changes summary
quality, never structure or correctness.

### Fully local transcription

Choose **whisper.cpp** in the wizard instead of Groq. You need to build the
binary yourself once (it needs a compiler, so the installer won't do it
silently):

```bash
git clone https://github.com/ggerganov/whisper.cpp
cd whisper.cpp && cmake -B build && cmake --build build -j
```

Then set `whisper_binary` in your config if it isn't on `PATH`. The wizard
downloads the model (~1.5 GB) for you.

---

## Privacy

By default your audio is sent to Groq for transcription, and the transcript is
sent to your chosen model provider. Nothing else leaves your machine, and
nothing is stored by beyondMeetings anywhere but your own disk.

Note that an agent CLI still sends the transcript to that provider — "no API
key" means no billing, not local-only.

For a fully local setup, choose **whisper.cpp** for transcription and
**Ollama** for notes. Then no audio and no transcript ever leaves the machine.

API keys are stored in your OS keyring, falling back to a `0600` file if no
keyring backend is available.

---

## Where things live

| What | Path |
|---|---|
| Config | `~/.config/beyondmeetings/config.toml` |
| Recordings and transcripts | `~/.local/share/beyondmeetings/` |
| The program itself | `~/.local/share/beyondmeetings-app/` |
| Notes | `<your vault>/Meetings/YYYY-MM-DD/` |
| Task board | `<your vault>/Tasks/Task Board.md` |
| Dashboard | `<your vault>/Home.md` |

---

## Using it with a coding agent

The wizard generates `CLAUDE.md`, `AGENTS.md` and `GEMINI.md` in your vault, so
Claude Code, Codex or Gemini CLI can start and stop recordings when you ask
them to. All three files are generated from one template — edit the template,
not the copies.

It also offers to register an MCP server giving your agent read access to the
vault, so you can ask things like "what did we decide about the API last week?"
It uses `@modelcontextprotocol/server-filesystem` scoped to your vault — no
Obsidian plugin and no second API key. Only agents you actually have installed
are touched, and your existing agent config is merged, backed up to `.bak`, and
never overwritten.

---

## Commands

| Command | Does |
|---|---|
| `beyondmeetings open` | Open the app, starting the server only if needed. What the app icon runs. |
| `beyondmeetings serve` | Run the server in the foreground (page + tray icon). |
| `beyondmeetings start ["name"]` | Start recording. The name is optional. |
| `beyondmeetings stop` | Stop, transcribe, and write everything. |
| `beyondmeetings notes <transcript>` | Regenerate notes from an existing transcript. |
| `beyondmeetings doctor` | Check your installation. |
| `beyondmeetings setup` | Reopen the setup wizard. |

The tray icon needs two extra packages, because the GTK/AppIndicator stack is
fiddly across desktops and not everyone wants it:

```bash
pip install 'beyondmeetings[tray]'
```

Without them, `serve` still runs the page — it just says so and skips the icon.

### If note generation fails

The transcript is written to disk **before** the AI is called. If the API is
down or your key expired, the app shows the transcript path and a **Regenerate
notes** button. Your recording is never lost to a failed API call.

---

## Uninstalling

```bash
./uninstall.sh
```

Removes the program, the command, your settings and the start-at-login entry.
**Your recordings, transcripts, API keys, vault and meeting notes are kept.**

```bash
./uninstall.sh --dry-run       # show what would go, change nothing
./uninstall.sh --purge-keys    # also forget your stored API keys
./uninstall.sh --purge-data    # also delete recordings and transcripts
```

The program is deliberately installed to a *different* directory from your
recordings, so removing it can never take your meetings with it.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Adding a model provider is roughly
forty lines — implement `LLMProvider` and add one entry to a table.

## License

MIT — see [LICENSE](LICENSE).
