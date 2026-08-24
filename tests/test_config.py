from beyondmeetings.config import Config, load_config, save_config


def test_load_returns_defaults_when_file_absent(tmp_path):
    cfg = load_config(tmp_path / "config.toml")
    assert cfg.provider == "claude-cli"  # subscription, not an API key
    assert cfg.spoken_language == "auto"
    assert cfg.notes_language == "English"
    assert cfg.projects == []
    assert cfg.segment_minutes == 50
    assert cfg.notes_path.endswith("beyondmeetings/library")


def test_old_vault_setting_is_used_as_the_local_library():
    assert Config(vault_path="/old/notes").notes_path == "/old/notes"


def test_new_library_setting_wins_during_migration():
    cfg = Config(library_path="/new/notes", vault_path="/old/notes")
    assert cfg.notes_path == "/new/notes"


def test_loading_an_old_config_migrates_the_vault_field(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('vault_path = "/old/notes"\n')
    cfg = load_config(path)
    assert cfg.library_path == "/old/notes"
    assert cfg.vault_path == ""


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "config.toml"
    cfg = Config(vault_path="/home/x/Vault", projects=["Acme", "Zenith"])
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.notes_path == "/home/x/Vault"
    assert loaded.projects == ["Acme", "Zenith"]
    assert "vault_path" not in path.read_text()


def test_save_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "deep" / "config.toml"
    save_config(Config(), path)
    assert path.exists()
