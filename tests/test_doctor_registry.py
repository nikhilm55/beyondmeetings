from beyondmeetings.config import Config
from beyondmeetings.doctor.registry import build_checks
from beyondmeetings.doctor.rules_check import RulesCheck


def test_rules_missing_when_files_absent(tmp_path):
    check = RulesCheck(Config(vault_path=str(tmp_path)), tmp_path)
    assert check.detect().status == "missing"


def test_rules_ok_after_fix(tmp_path):
    check = RulesCheck(Config(vault_path=str(tmp_path)), tmp_path)
    assert check.fix().status == "ok"
    assert (tmp_path / "CLAUDE.md").is_file()


def test_rules_not_required(tmp_path):
    assert RulesCheck(Config(), tmp_path).required is False


def test_registry_returns_checks_in_a_stable_order(tmp_path):
    ids = [c.id for c in build_checks(Config(), config_path=tmp_path / "c.toml")]
    assert ids == [
        "provider_choice", "transcriber_choice",
        "pipewire", "ffmpeg",
        "groq_key", "provider_key", "whisper_model",
        "obsidian", "vault", "rules", "mcp",
    ]


def test_choices_come_first_because_they_change_later_rows(tmp_path):
    ids = [c.id for c in build_checks(Config(), config_path=tmp_path / "c.toml")]
    assert ids[0].endswith("_choice") and ids[1].endswith("_choice")


def test_groq_key_is_dropped_when_transcribing_locally(tmp_path):
    """A Groq key is not a prerequisite if Groq is not being used."""
    cfg = Config(transcriber="whispercpp")
    ids = [c.id for c in build_checks(cfg, config_path=tmp_path / "c.toml")]
    assert "groq_key" not in ids


def test_groq_key_is_present_when_transcribing_with_groq(tmp_path):
    cfg = Config(transcriber="groq")
    ids = [c.id for c in build_checks(cfg, config_path=tmp_path / "c.toml")]
    assert "groq_key" in ids


def test_registry_handles_every_provider(tmp_path):
    for provider in ("anthropic", "openai", "gemini", "ollama"):
        cfg = Config(provider=provider)
        ids = [c.id for c in build_checks(cfg, config_path=tmp_path / "c.toml")]
        assert "provider_key" in ids


def test_registry_uses_the_configured_provider(tmp_path):
    checks = build_checks(Config(provider="anthropic"), config_path=tmp_path / "c.toml")
    provider_check = next(c for c in checks if c.id == "provider_key")
    assert "Claude" in provider_check.label


def test_registry_ids_are_unique(tmp_path):
    ids = [c.id for c in build_checks(Config(), config_path=tmp_path / "c.toml")]
    assert len(ids) == len(set(ids))


def test_rules_land_in_the_vault_when_one_is_configured(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    checks = build_checks(
        Config(vault_path=str(vault)), config_path=tmp_path / "c.toml"
    )
    rules = next(c for c in checks if c.id == "rules")
    assert rules.target_dir == vault
