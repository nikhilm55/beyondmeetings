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
    # Pinned to linux: without it this asserts the host's platform, so it
    # expected "pipewire" and got "windows_audio" on the Windows CI runner.
    ids = [c.id for c in build_checks(
        Config(), config_path=tmp_path / "c.toml", platform="linux"
    )]
    assert ids == [
        "provider_choice", "transcriber_choice",
        "pipewire", "ffmpeg",
        "groq_key", "provider_key", "whisper_model",
        "storage", "rules", "mcp", "launcher", "autostart",
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


def test_windows_uses_wasapi_and_shortcut_checks_not_freedesktop_ones(tmp_path):
    checks = build_checks(
        Config(), config_path=tmp_path / "c.toml", platform="win32"
    )
    by_id = {c.id: type(c).__name__ for c in checks}

    assert "windows_audio" in by_id
    assert "pipewire" not in by_id
    # Same ids as Linux so the wizard renders identical rows, but backed by
    # Start Menu and Startup shortcuts rather than freedesktop files.
    assert by_id["launcher"] == "StartMenuShortcutCheck"
    assert by_id["autostart"] == "WindowsAutostartCheck"


def test_linux_keeps_the_freedesktop_launcher_and_autostart_checks(tmp_path):
    checks = build_checks(
        Config(), config_path=tmp_path / "c.toml", platform="linux"
    )
    by_id = {c.id: type(c).__name__ for c in checks}

    assert by_id["launcher"] == "DesktopLauncherCheck"
    assert by_id["autostart"] == "AutostartCheck"
    assert "pipewire" in by_id
    assert "windows_audio" not in by_id


def test_windows_check_ids_stay_unique(tmp_path):
    ids = [c.id for c in build_checks(
        Config(), config_path=tmp_path / "c.toml", platform="win32"
    )]
    assert len(ids) == len(set(ids))


def test_rules_land_in_the_vault_when_one_is_configured(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    checks = build_checks(
        Config(vault_path=str(vault)), config_path=tmp_path / "c.toml"
    )
    rules = next(c for c in checks if c.id == "rules")
    assert rules.target_dir == vault
