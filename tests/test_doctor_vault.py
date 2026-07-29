from beyondmeetings.config import Config, load_config
from beyondmeetings.doctor.vault import VaultCheck
from beyondmeetings.vault.scaffold import scaffold_vault


def test_missing_when_no_path_configured(tmp_path):
    assert VaultCheck(Config()).detect().status == "missing"


def test_broken_when_path_does_not_exist(tmp_path):
    check = VaultCheck(Config(vault_path=str(tmp_path / "nope")))
    assert check.detect().status == "broken"


def test_missing_when_path_exists_but_is_not_scaffolded(tmp_path):
    assert VaultCheck(Config(vault_path=str(tmp_path))).detect().status == "missing"


def test_ok_once_scaffolded(tmp_path):
    scaffold_vault(tmp_path)
    assert VaultCheck(Config(vault_path=str(tmp_path))).detect().status == "ok"


def test_fix_scaffolds_the_given_path(tmp_path):
    result = VaultCheck(Config(), config_path=tmp_path / "c.toml").fix(
        vault_path=str(tmp_path)
    )
    assert result.status == "ok"
    assert (tmp_path / "Home.md").is_file()
    assert (tmp_path / "Tasks" / "Task Board.md").is_file()


def test_fix_persists_the_path_into_config(tmp_path):
    cfg_path = tmp_path / "config.toml"
    vault = tmp_path / "vault"
    vault.mkdir()
    VaultCheck(Config(), config_path=cfg_path).fix(vault_path=str(vault))
    assert load_config(cfg_path).vault_path == str(vault)


def test_fix_refuses_a_path_that_does_not_exist(tmp_path):
    check = VaultCheck(Config(), config_path=tmp_path / "c.toml")
    assert check.fix(vault_path=str(tmp_path / "absent")).status == "broken"


def test_fix_never_overwrites_an_existing_vault(tmp_path):
    (tmp_path / "Home.md").write_text("MY REAL HOME")
    VaultCheck(Config(), config_path=tmp_path / "c.toml").fix(vault_path=str(tmp_path))
    assert (tmp_path / "Home.md").read_text() == "MY REAL HOME"
