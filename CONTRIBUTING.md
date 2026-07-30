# Contributing

Thanks for looking. This is a small, focused project and contributions are
welcome — particularly macOS and Windows audio capture.

## Getting set up

```bash
git clone https://github.com/REPLACE_ME/beyondmeetings
cd beyondmeetings
./install.sh          # same script users run; safe to run from a clone
```

Or, for a development environment without installing to `~/.local/bin`:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

## Running the tests

```bash
.venv/bin/python -m pytest
```

Everything is unit-tested except audio capture, which needs a live sound
server. `audio/pipewire.py` injects its subprocess runner, so its logic is
tested with a fake — but the real thing has to be exercised by hand:

```bash
.venv/bin/beyondmeetings start "Test"
.venv/bin/beyondmeetings stop
```

## How it fits together

The single organising idea: **the model does judgment, Python does every file
write.** The LLM returns one JSON object (`models.py`); everything in `vault/`
turns that into markdown deterministically. Task board counters are arithmetic,
not a model's guess. This is what lets any provider produce identical files.

| Area | Where |
|---|---|
| Data contract | `models.py` |
| Audio capture | `audio/` — `base.py` is the interface |
| Transcription | `transcribe/` |
| Model providers | `llm/` |
| File writing | `vault/` |
| Prerequisite checks | `doctor/` |
| Setup wizard | `server.py` + `web/` |

## Adding a model provider

1. Add `llm/<name>.py` implementing `LLMProvider.analyse()`. Route the response
   through `parse_meeting_note()` — it handles fenced JSON, surrounding prose,
   and validating `follow_up_of` against the supplied candidates. Request JSON
   natively if the API supports it.
2. Add a display name to `labels.py`.
3. Register the class in `llm/factory.py` (`KEYED`).
4. Add a key validator to `doctor/keys.py` and register it in `VALIDATORS`.
5. Add an entry to `PROVIDERS` in `doctor/choices.py` so it appears in the
   wizard.
6. Test with `pytest-httpx`, asserting request shape and that malformed output
   is repaired. See `tests/test_llm_gemini.py`.

Roughly forty lines of implementation, five small registrations.

Model defaults live at the top of each adapter. They will go stale — treat a
PR bumping them as welcome housekeeping.

## Porting audio capture to another OS

Implement `Recorder` from `audio/base.py` in a new file beside
`pipewire.py`. It needs `start()`, `stop()`, `status()` and `roll_segment()`.
Nothing outside `audio/` should need changing. macOS will need something like
BlackHole for a loopback device; Windows has WASAPI loopback via ffmpeg.

## Style

Match the surrounding code. Comments explain *why*, not *what* — if a line
needs a comment saying what it does, the line probably wants rewriting instead.
Tests assert behaviour, not implementation details.

## Before opening a PR

- `.venv/bin/python -m pytest` passes
- New behaviour has a test that fails without your change
- If you touched the vault writers, generate a note and **read it** — several
  formatting bugs in this project's history passed their unit tests and were
  only caught by looking at real output
