from beyondmeetings.config import Config, load_config, save_config


def test_load_returns_defaults_when_file_absent(tmp_path):
    cfg = load_config(tmp_path / "config.toml")
    assert cfg.provider == "claude-cli"  # subscription, not an API key
    assert cfg.spoken_language == "auto"
    assert cfg.notes_language == "English"
    assert cfg.projects == []
    assert cfg.segment_minutes == 50


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "config.toml"
    cfg = Config(vault_path="/home/x/Vault", projects=["Acme", "Zenith"])
    save_config(cfg, path)
    assert load_config(path) == cfg


def test_save_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "deep" / "config.toml"
    save_config(Config(), path)
    assert path.exists()
