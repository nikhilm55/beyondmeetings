from beyondmeetings.rules import FILENAMES, render_rules, write_rules


def test_all_three_files_are_written(tmp_path):
    write_rules(tmp_path, vault_path="/v")
    for name in FILENAMES:
        assert (tmp_path / name).is_file()


def test_every_file_has_identical_content(tmp_path):
    write_rules(tmp_path, vault_path="/v")
    bodies = {(tmp_path / n).read_text() for n in FILENAMES}
    assert len(bodies) == 1


def test_content_is_marked_generated(tmp_path):
    write_rules(tmp_path, vault_path="/v")
    assert "do not edit" in (tmp_path / "CLAUDE.md").read_text().lower()


def test_rules_drive_the_cli_rather_than_reimplementing_it():
    text = render_rules(vault_path="/v")
    assert "beyondmeetings start" in text
    assert "beyondmeetings stop" in text


def test_rules_forbid_asking_for_a_meeting_name():
    assert "never ask" in render_rules(vault_path="/v").lower()


def test_vault_path_is_documented():
    assert "/home/x/Vault" in render_rules(vault_path="/home/x/Vault")


def test_link_convention_is_documented():
    assert "[[Meetings/YYYY-MM-DD/Meeting Name]]" in render_rules(vault_path="/v")


def test_existing_files_are_overwritten(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("stale content")
    write_rules(tmp_path, vault_path="/v")
    assert "stale content" not in (tmp_path / "CLAUDE.md").read_text()


def test_rules_do_not_reimplement_the_pipeline(tmp_path):
    """Thin driver, not prose logic — see spec section 7."""
    text = render_rules(vault_path="/v").lower()
    for leaked in ("executive summary", "follow_up_of", "pending —", "priority"):
        assert leaked not in text
