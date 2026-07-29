"""Analysis prompt assembly.

Every behavioural rule from the original CLAUDE.md pipeline lives here, so
it runs on every provider rather than depending on an agent reading a file.
"""
from __future__ import annotations

from .vault.followup import Candidate

SCHEMA = """{
  "title": string,
  "date": "YYYY-MM-DD",
  "tags": [string],
  "attendees": [string],
  "executive_summary": string,
  "one_line_summary": string,
  "sections": [{"heading": string, "bullets": [string]}],
  "decisions": [string],
  "open_questions": [string],
  "risks": [string],
  "follow_ups": [string],
  "action_items": [{"task": string, "owner": string|null, "due": string|null,
                    "project": string|null, "priority": "HIGH"|"MEDIUM"|"LOW"}],
  "transcription_note": string|null,
  "is_informal": boolean,
  "follow_up_of": string|null
}"""

RULES = """
Rules:

1. TASKS — Extract every task, not just explicitly stated action items. Anything
   discussed that implies work counts: decisions requiring follow-up, things
   flagged for review, confirmations needed, work assigned to anyone. If it was
   discussed as a next step, it is a task. Infer `priority` from the urgency in
   the discussion.

2. INFORMAL CALLS — Set `is_informal` to true when this is a peer show-and-tell
   or demo, a casual catch-up or social chat, or a conversation dominated by
   personal projects, tooling, hobbies or home setup rather than client/project
   work with assigned deliverables. Signals: no clear ownership or deadlines,
   content is mostly demonstrating already-built things, or it is a 1:1 catch-up
   with no project agenda. When genuinely ambiguous, prefer true. When
   `is_informal` is true, still fill in `action_items` if any were stated — the
   caller decides what to do with them.

3. TITLE — Derive a specific, descriptive title from the content. Never use a
   placeholder such as "recording-14-30".

4. TRANSCRIPTION_NOTE — If the transcript is visibly garbled, machine-translated
   or has systematically mangled names or numbers, describe the problem and list
   the substitutions you inferred. Otherwise null.

5. SECTIONS — `sections` is for free-form narrative only. Never duplicate
   decisions, open questions, risks, follow-ups or action items there.

6. ONE_LINE_SUMMARY — One sentence, no trailing full stop, for the dashboard.
"""


def _followup_rules(candidates: list[Candidate]) -> str:
    if not candidates:
        return (
            "\n7. FOLLOW-UP — There are no candidate meetings. "
            "Set `follow_up_of` to null.\n"
        )

    listing = "\n".join(
        f'  - id: "{c.ref.id}"\n'
        f"    tags: {', '.join(c.tags) or 'none'}\n"
        f"    summary: {c.executive_summary}"
        for c in candidates
    )
    return f"""
7. FOLLOW-UP — Decide whether this meeting continues one of the meetings below.
   Judge from the transcript content only, never from the meeting's name.

   Declare a follow-up only on strong evidence. BOTH must hold:
     (a) the same project AND the same specific work-thread — not merely the
         same project or the same client; and
     (b) at least one strong continuity signal: an explicit back-reference in
         the transcript ("yesterday", "last time", "continue", "as we
         discussed"), the same screens / tickets / documents / artifacts named
         again, OR the same people actively working the very task the prior
         meeting was about.

   If several qualify, pick the most recent, so a chain links to its latest
   link rather than the original. If nothing clears the bar, or you are
   genuinely unsure, set `follow_up_of` to null.

   Set `follow_up_of` to exactly one of these ids, or null:
{listing}
"""


def build_analysis_prompt(
    transcript: str,
    meeting_date: str,
    candidates: list[Candidate],
    projects: list[str],
    notes_language: str = "English",
) -> str:
    project_rule = (
        f"\n8. PROJECT TAGS — Use one of these when it clearly applies, else omit: "
        f"{', '.join(projects)}.\n"
        if projects
        else "\n8. PROJECT TAGS — No configured projects; omit `project`.\n"
    )

    return f"""You are analysing a meeting transcript recorded on {meeting_date}.

Return ONLY a single JSON object matching this schema. No prose, no markdown
fence, no commentary before or after.

{SCHEMA}

Write all output in {notes_language}, regardless of the language spoken in the
transcript.
{RULES}{_followup_rules(candidates)}{project_rule}
--- TRANSCRIPT ---
{transcript}
--- END TRANSCRIPT ---
"""
