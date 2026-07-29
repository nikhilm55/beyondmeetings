from beyondmeetings.vault.scaffold import scaffold_vault


def test_creates_expected_structure(tmp_path):
    scaffold_vault(tmp_path)
    assert (tmp_path / "Meetings").is_dir()
    assert (tmp_path / "Tasks" / "Task Board.md").is_file()
    assert (tmp_path / "Home.md").is_file()


def test_new_task_board_has_zeroed_counters(tmp_path):
    scaffold_vault(tmp_path)
    text = (tmp_path / "Tasks" / "Task Board.md").read_text()
    assert "> [!todo]+ Pending — 0" in text
    assert "`0 pending`" in text


def test_new_home_has_recent_callout(tmp_path):
    scaffold_vault(tmp_path)
    assert "> [!example]+ Recent" in (tmp_path / "Home.md").read_text()


def test_never_overwrites_existing_files(tmp_path):
    (tmp_path / "Tasks").mkdir()
    (tmp_path / "Tasks" / "Task Board.md").write_text("MY 205 REAL TASKS")
    (tmp_path / "Home.md").write_text("MY REAL HOME")
    scaffold_vault(tmp_path)
    assert (tmp_path / "Tasks" / "Task Board.md").read_text() == "MY 205 REAL TASKS"
    assert (tmp_path / "Home.md").read_text() == "MY REAL HOME"


def test_is_safely_repeatable(tmp_path):
    scaffold_vault(tmp_path)
    first = (tmp_path / "Home.md").read_text()
    scaffold_vault(tmp_path)
    assert (tmp_path / "Home.md").read_text() == first
