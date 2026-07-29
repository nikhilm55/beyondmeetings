from beyondmeetings.doctor.obsidian import ObsidianCheck


def test_ok_when_binary_on_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/obsidian")
    assert ObsidianCheck().detect().status == "ok"


def test_ok_when_installed_as_a_flatpak(monkeypatch):
    monkeypatch.setattr(
        "shutil.which", lambda n: "/usr/bin/flatpak" if n == "flatpak" else None
    )
    monkeypatch.setattr(
        "beyondmeetings.doctor.obsidian._flatpak_list",
        lambda: "md.obsidian.Obsidian\n",
    )
    assert ObsidianCheck().detect().status == "ok"


def test_missing_when_neither_present(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: None)
    monkeypatch.setattr("beyondmeetings.doctor.obsidian._flatpak_list", lambda: "")
    assert ObsidianCheck().detect().status == "missing"


def test_detail_explains_how_to_install_without_flatpak(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: None)
    monkeypatch.setattr("beyondmeetings.doctor.obsidian._flatpak_list", lambda: "")
    assert "obsidian.md" in ObsidianCheck().detect().detail


def test_is_fixable_only_when_flatpak_is_available(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: None)
    assert ObsidianCheck().fixable is False
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/flatpak")
    assert ObsidianCheck().fixable is True
