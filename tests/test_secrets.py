import os
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


# --- Review finding #11: world-readable window; silent keyring fallback ---

def test_fallback_file_is_never_world_readable_even_briefly(monkeypatch, tmp_path):
    """chmod after write left the key readable for the duration of the write."""
    monkeypatch.setattr(secrets_mod, "keyring", FakeKeyring(working=False))
    seen = []
    real_fdopen = os.fdopen

    def watching_fdopen(fd, *a, **k):
        handle = real_fdopen(fd, *a, **k)
        seen.append(stat.S_IMODE(os.fstat(fd).st_mode))
        return handle

    monkeypatch.setattr(os, "fdopen", watching_fdopen)
    secrets_mod.set_secret("groq_api_key", "gsk_SECRET", fallback_dir=tmp_path)
    assert seen and all(mode == 0o600 for mode in seen), seen


def test_an_existing_loose_file_is_tightened(monkeypatch, tmp_path):
    monkeypatch.setattr(secrets_mod, "keyring", FakeKeyring(working=False))
    path = tmp_path / "secrets.toml"
    path.write_text("")
    os.chmod(path, 0o644)
    secrets_mod.set_secret("groq_api_key", "gsk", fallback_dir=tmp_path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_keyring_failure_is_logged_not_swallowed(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(secrets_mod, "keyring", FakeKeyring(working=False))
    with caplog.at_level("WARNING"):
        secrets_mod.set_secret("groq_api_key", "gsk", fallback_dir=tmp_path)
    assert "keyring unavailable" in caplog.text


def test_last_store_reports_where_the_key_went(monkeypatch, tmp_path):
    monkeypatch.setattr(secrets_mod, "keyring", FakeKeyring(working=False))
    secrets_mod.set_secret("groq_api_key", "gsk", fallback_dir=tmp_path)
    assert secrets_mod.last_store() == "file"

    monkeypatch.setattr(secrets_mod, "keyring", FakeKeyring())
    secrets_mod.set_secret("groq_api_key", "gsk", fallback_dir=tmp_path)
    assert secrets_mod.last_store() == "keyring"


def test_secret_location_reports_the_file_fallback(monkeypatch, tmp_path):
    """doctor runs in a fresh process, so the last-write global is useless."""
    monkeypatch.setattr(secrets_mod, "keyring", FakeKeyring(working=False))
    secrets_mod.set_secret("groq_api_key", "gsk", fallback_dir=tmp_path)
    assert secrets_mod.secret_location("groq_api_key", fallback_dir=tmp_path) == "file"


def test_secret_location_reports_the_keyring(monkeypatch, tmp_path):
    fake = FakeKeyring()
    monkeypatch.setattr(secrets_mod, "keyring", fake)
    secrets_mod.set_secret("groq_api_key", "gsk", fallback_dir=tmp_path)
    assert secrets_mod.secret_location("groq_api_key", fallback_dir=tmp_path) == "keyring"


def test_secret_location_is_none_when_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(secrets_mod, "keyring", FakeKeyring())
    assert secrets_mod.secret_location("absent", fallback_dir=tmp_path) is None
