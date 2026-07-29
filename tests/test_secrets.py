import stat

from beyondmeetings import secrets as secrets_mod


class FakeKeyring:
    """Stands in for the OS keyring; records calls."""

    def __init__(self, working=True):
        self.working = working
        self.store: dict[tuple[str, str], str] = {}

    def set_password(self, service, name, value):
        if not self.working:
            raise RuntimeError("no keyring backend")
        self.store[(service, name)] = value

    def get_password(self, service, name):
        if not self.working:
            raise RuntimeError("no keyring backend")
        return self.store.get((service, name))


def test_uses_keyring_when_available(monkeypatch, tmp_path):
    fake = FakeKeyring()
    monkeypatch.setattr(secrets_mod, "keyring", fake)
    secrets_mod.set_secret("groq_api_key", "gsk_live", fallback_dir=tmp_path)
    assert secrets_mod.get_secret("groq_api_key", fallback_dir=tmp_path) == "gsk_live"
    assert not (tmp_path / "secrets.toml").exists()


def test_falls_back_to_file_when_keyring_broken(monkeypatch, tmp_path):
    monkeypatch.setattr(secrets_mod, "keyring", FakeKeyring(working=False))
    secrets_mod.set_secret("groq_api_key", "gsk_fallback", fallback_dir=tmp_path)
    assert secrets_mod.get_secret("groq_api_key", fallback_dir=tmp_path) == "gsk_fallback"


def test_fallback_file_is_owner_only(monkeypatch, tmp_path):
    monkeypatch.setattr(secrets_mod, "keyring", FakeKeyring(working=False))
    secrets_mod.set_secret("groq_api_key", "gsk_fallback", fallback_dir=tmp_path)
    mode = (tmp_path / "secrets.toml").stat().st_mode
    assert stat.S_IMODE(mode) == 0o600


def test_missing_secret_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(secrets_mod, "keyring", FakeKeyring())
    assert secrets_mod.get_secret("absent", fallback_dir=tmp_path) is None
