# beyondMeetings

Record a meeting, get structured notes in Obsidian. Locally, on Linux.

beyondMeetings captures every voice on the call, transcribes it, and writes a
meeting note with an executive summary, decisions, action items and open
questions — then adds the action items to a task board, updates a dashboard,
and links follow-up meetings into chains.

```bash
curl -fsSL https://raw.githubusercontent.com/REPLACE_ME/beyondmeetings/main/install.sh | bash
```

The installer checks your system, walks you through the setup wizard in your
browser, and leaves you with one command:

```bash
beyondmeetings start "Client kickoff"
# … have your meeting …
beyondmeetings stop
```

`stop` does everything: transcribes, analyses, and writes the note.

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
- A **Groq API key** for transcription (free tier is ample)
- An API key for whichever model writes your notes

Run `beyondmeetings doctor` at any time to see what is missing.

---

## Choosing your AI

| Provider | Notes |
|---|---|
| **Claude** | Recommended. Best summary quality and follow-up detection. |
| **ChatGPT** | Supported. |
| **Gemini** | Supported. |
| **Ollama** | Fully local, no API key, nothing leaves your machine. Weaker on code-mixed speech (e.g. Hinglish) than the hosted models. |

Whichever you choose, the *files* are identical — the notes, task board and
dashboard are written by deterministic Python, not by the model. The model
only decides what the meeting was about. Swapping providers changes summary
quality, never structure or correctness.

---

## Privacy

By default your audio is sent to Groq for transcription, and the transcript is
sent to your chosen model provider. Nothing else leaves your machine, and
nothing is stored by beyondMeetings anywhere but your own disk.

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
| Notes | `<your vault>/Meetings/YYYY-MM-DD/` |
| Task board | `<your vault>/Tasks/Task Board.md` |
| Dashboard | `<your vault>/Home.md` |

---

## Using it with a coding agent

The wizard generates `CLAUDE.md`, `AGENTS.md` and `GEMINI.md` in your vault, so
Claude Code, Codex or Gemini CLI can start and stop recordings when you ask
them to. All three files are generated from one template — edit the template,
not the copies.

---

## Commands

| Command | Does |
|---|---|
| `beyondmeetings start ["name"]` | Start recording. The name is optional. |
| `beyondmeetings stop` | Stop, transcribe, and write everything. |
| `beyondmeetings notes <transcript>` | Regenerate notes from an existing transcript. |
| `beyondmeetings doctor` | Check your installation. |
| `beyondmeetings setup` | Reopen the setup wizard. |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Adding a model provider is roughly
forty lines — implement `LLMProvider` and add one entry to a table.

## License

MIT — see [LICENSE](LICENSE).
