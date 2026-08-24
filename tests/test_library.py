import pytest

from beyondmeetings.library import list_tasks, open_library_folder, resolve_markdown
from beyondmeetings.models import ActionItem, MeetingRef
from beyondmeetings.vault.scaffold import scaffold_vault
from beyondmeetings.vault.taskboard import add_tasks


def test_resolve_markdown_keeps_reads_inside_the_library(tmp_path):
    expected = tmp_path / "Meetings" / "2026-08-11" / "Review.md"
    assert resolve_markdown(tmp_path, "Meetings/2026-08-11/Review") == expected


def test_resolve_markdown_rejects_traversal(tmp_path):
    with pytest.raises(ValueError, match="outside"):
        resolve_markdown(tmp_path, "../../private-key")


def test_task_board_is_exposed_as_structured_local_data(tmp_path):
    scaffold_vault(tmp_path)
    board_path = tmp_path / "Tasks" / "Task Board.md"
    board = add_tasks(
        board_path.read_text(),
        [ActionItem(task="Ship desktop", owner="Nikhil", project="App",
                    priority="HIGH", due="2026-08-12")],
        MeetingRef(date="2026-08-11", title="Desktop plan"),
        "Finish the cross-platform package.",
    )
    board_path.write_text(board)

    task = list_tasks(tmp_path)[0]
    assert task["title"] == "Ship desktop"
    assert task["owner"] == "Nikhil"
    assert task["meeting"] == "Meetings/2026-08-11/Desktop plan"


@pytest.mark.parametrize(
    ("platform", "executable"),
    [("linux", "xdg-open"), ("darwin", "open"), ("win32", "explorer")],
)
def test_library_opens_in_the_platform_file_manager(tmp_path, platform, executable):
    calls = []
    target = tmp_path / "library"
    open_library_folder(
        target,
        platform=platform,
        spawn=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    assert target.is_dir()
    assert calls[0][0][0] == [executable, str(target)]
