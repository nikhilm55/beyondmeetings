from beyondmeetings.doctor.system import FfmpegCheck, PipeWireCheck, install_hint


def test_pipewire_ok_when_both_binaries_present(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: f"/usr/bin/{n}")
    assert PipeWireCheck().detect().status == "ok"


def test_pipewire_missing_when_pw_record_absent(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: None if n == "pw-record" else "/usr/bin/x")
    result = PipeWireCheck().detect()
    assert result.status == "missing"
    assert "pw-record" in result.detail


def test_pipewire_is_not_auto_fixable():
    assert PipeWireCheck().fixable is False


def test_ffmpeg_ok_when_present(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/ffmpeg")
    assert FfmpegCheck().detect().status == "ok"


def test_ffmpeg_missing_when_absent(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: None)
    assert FfmpegCheck().detect().status == "missing"


def test_ffmpeg_is_fixable():
    assert FfmpegCheck().fixable is True


def test_install_hint_matches_the_available_package_manager(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/dnf" if n == "dnf" else None)
    assert install_hint("ffmpeg") == "sudo dnf install -y ffmpeg"


def test_install_hint_falls_back_when_no_manager_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: None)
    assert "package manager" in install_hint("ffmpeg")
