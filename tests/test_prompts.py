from beyondmeetings.models import MeetingRef
from beyondmeetings.prompts import build_analysis_prompt
from beyondmeetings.vault.followup import Candidate

CANDIDATES = [
    Candidate(ref=MeetingRef(date="2026-07-29", title="Design QA Review"),
              tags=["Acme"], executive_summary="We reviewed the designs.")
]


def test_transcript_is_included():
    prompt = build_analysis_prompt("We discussed the roadmap.", "2026-07-30", [], [])
    assert "We discussed the roadmap." in prompt


def test_candidate_ids_are_listed_verbatim():
    prompt = build_analysis_prompt("t", "2026-07-30", CANDIDATES, [])
    assert "2026-07-29/Design QA Review" in prompt
    assert "We reviewed the designs." in prompt


def test_states_the_strong_evidence_bar_for_follow_ups():
    prompt = build_analysis_prompt("t", "2026-07-30", CANDIDATES, [])
    assert "same specific work-thread" in prompt
    assert "most recent" in prompt


def test_instructs_standalone_when_unsure():
    prompt = build_analysis_prompt("t", "2026-07-30", CANDIDATES, [])
    assert "null" in prompt


def test_no_candidates_states_it_must_be_standalone():
    prompt = build_analysis_prompt("t", "2026-07-30", [], [])
    assert "no candidate meetings" in prompt.lower()


def test_informal_rule_is_present():
    prompt = build_analysis_prompt("t", "2026-07-30", [], [])
    assert "is_informal" in prompt
    assert "show-and-tell" in prompt


def test_implied_work_rule_is_present():
    prompt = build_analysis_prompt("t", "2026-07-30", [], [])
    assert "not just explicitly stated action items" in prompt


def test_configured_projects_are_offered_as_tags():
    prompt = build_analysis_prompt("t", "2026-07-30", [], ["Acme", "Zenith"])
    assert "Acme" in prompt and "Zenith" in prompt


def test_notes_language_is_honoured():
    prompt = build_analysis_prompt("t", "2026-07-30", [], [], notes_language="English")
    assert "in English" in prompt
