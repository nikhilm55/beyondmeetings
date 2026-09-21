"""The offline Windows installer: what goes into it, and what it promises.

The promise is narrow and worth stating plainly, because every test here
defends one half of it: a 64-bit Windows machine with *nothing* on it — no
Python, no git, no curl, no package manager, and no reachable network — must
end up with a working beyondMeetings after double-clicking one file.

The half that can be tested here is the build: which interpreter is chosen,
how it is unpacked, and whether the Inno Setup script is aimed at the right
directories. The other half — that the compiled installer actually installs —
is asserted by .github/workflows/windows-installer.yml, which runs it
unattended with every proxy pointed at a closed port.

One invariant deserves special mention. On Windows,
%LOCALAPPDATA%\\beyondMeetings (the program) and %LOCALAPPDATA%\\beyondmeetings
(the recordings) differ only in case, which is to say they are the same
directory. An uninstaller aimed one level too high therefore deletes every
meeting the user has ever recorded. Several tests below exist only to keep
that from being reintroduced.
"""
import importlib.util
import io
import re
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "installer" / "windows"
ISS = INSTALLER / "beyondmeetings.iss"
FINISH = INSTALLER / "setup-finish.ps1"


def _load_build_payload():
    """Imported by path: installer/ is not a package, and must not become one.

    A top-level `packaging`-style directory on sys.path is how projects end up
    shadowing a real distribution by accident.
    """
    spec = importlib.util.spec_from_file_location(
        "bm_build_payload", INSTALLER / "build_payload.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_payload = _load_build_payload()


# --- picking an interpreter ---------------------------------------------------

STRIPPED = "cpython-3.12.11+20250818-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
NEWEST = "cpython-3.12.11+20250818-x86_64-pc-windows-msvc-install_only.tar.gz"
OLDER = "cpython-3.12.4+20240814-x86_64-pc-windows-msvc-install_only.tar.gz"
LINUX = "cpython-3.12.11+20250818-x86_64-unknown-linux-gnu-install_only.tar.gz"
OTHER_SERIES = "cpython-3.13.1+20250818-x86_64-pc-windows-msvc-install_only.tar.gz"
THIRTY_TWO = "cpython-3.12.11+20250818-i686-pc-windows-msvc-install_only.tar.gz"


def test_it_takes_the_newest_patch_release():
    chosen = build_payload.select_python_asset([OLDER, NEWEST, LINUX])
    assert chosen == NEWEST


def test_a_newer_build_of_the_same_patch_wins():
    rebuild = NEWEST.replace("+20250818", "+20251201")
    assert build_payload.select_python_asset([NEWEST, rebuild]) == rebuild


def test_the_stripped_build_is_not_mistaken_for_the_real_one():
    """`install_only_stripped` contains an interpreter with its symbols gone.

    A substring test for "install_only" matches it, and the mistake would
    survive every build and show up as an unimportable extension module.
    """
    with pytest.raises(LookupError):
        build_payload.select_python_asset([STRIPPED])


def test_another_platform_is_never_chosen():
    for wrong in (LINUX, THIRTY_TWO):
        with pytest.raises(LookupError):
            build_payload.select_python_asset([wrong])


def test_another_series_is_never_chosen():
    with pytest.raises(LookupError):
        build_payload.select_python_asset([OTHER_SERIES])


def test_the_series_it_defaults_to_is_one_with_wheels_for_everything():
    """Not the newest Python: a series without wheels needs a compiler."""
    assert build_payload.PYTHON_SERIES == "3.12"


def test_the_url_comes_from_the_matching_asset():
    release = {
        "assets": [
            {"name": LINUX, "browser_download_url": "https://example/linux"},
            {"name": NEWEST, "browser_download_url": "https://example/windows"},
        ]
    }

    assert build_payload.resolve_python_url(release) == "https://example/windows"


def test_a_release_with_nothing_usable_is_an_error_not_a_guess():
    with pytest.raises(LookupError):
        build_payload.resolve_python_url({"assets": [{"name": LINUX, "u": "x"}]})


# --- unpacking ----------------------------------------------------------------


def _tarball(path: Path, roots=("python",)) -> Path:
    with tarfile.open(path, "w:gz") as bundle:
        for root in roots:
            for name, body in ((f"{root}/python.exe", b"MZ"),
                               (f"{root}/Lib/os.py", b"# os")):
                info = tarfile.TarInfo(name)
                info.size = len(body)
                bundle.addfile(info, io.BytesIO(body))
    return path


def test_the_wrapper_directory_is_flattened_away(tmp_path):
    """install_only builds wrap everything in `python/`.

    Flattening here rather than in the .iss keeps the installed layout
    described in one place.
    """
    archive = _tarball(tmp_path / "cpython.tar.gz")

    runtime = build_payload.unpack_python(archive, tmp_path / "runtime")

    assert (runtime / "python.exe").read_bytes() == b"MZ"
    assert not (runtime / "python").exists()


def test_unpacking_twice_does_not_nest(tmp_path):
    archive = _tarball(tmp_path / "cpython.tar.gz")
    build_payload.unpack_python(archive, tmp_path / "runtime")

    runtime = build_payload.unpack_python(archive, tmp_path / "runtime")

    assert (runtime / "python.exe").is_file()
    assert not (runtime / "runtime").exists()


def test_an_unexpected_archive_shape_is_refused(tmp_path):
    """Better a failed build than a payload with no python.exe in it."""
    archive = _tarball(tmp_path / "two.tar.gz", roots=("python", "extra"))

    with pytest.raises(RuntimeError, match="one top-level directory"):
        build_payload.unpack_python(archive, tmp_path / "runtime")


def test_the_interpreter_is_where_the_iss_expects_it(tmp_path):
    assert build_payload.python_executable(tmp_path).name == "python.exe"
    assert build_payload.python_executable(tmp_path).parent == tmp_path


# --- ffmpeg -------------------------------------------------------------------


def test_ffmpeg_comes_from_the_same_url_the_application_uses():
    """One source of truth: doctor fetches ffmpeg from here too."""
    from beyondmeetings.provision_windows import FFMPEG_URL

    assert build_payload.FFMPEG_URL == FFMPEG_URL


def test_an_ffmpeg_archive_with_no_binaries_fails_the_build(tmp_path):
    with pytest.raises(RuntimeError, match="no ffmpeg"):
        build_payload.fetch_ffmpeg(
            tmp_path, fetch=lambda url, dest: dest.write_bytes(b""),
            extract=lambda archive, dest: [],
        )


def test_ffmpeg_is_fetched_into_the_bin_directory(tmp_path):
    seen = {}

    def extract(archive, dest):
        seen["dest"] = dest
        return [dest / "ffmpeg.exe"]

    build_payload.fetch_ffmpeg(
        tmp_path,
        fetch=lambda url, dest: seen.__setitem__("url", url),
        extract=extract,
    )

    assert seen["dest"] == tmp_path
    assert seen["url"] == build_payload.FFMPEG_URL


# --- wheels -------------------------------------------------------------------


def test_wheels_are_built_with_the_interpreter_that_will_import_them(tmp_path):
    """A wheel built by the build agent's Python can be the wrong ABI."""
    calls = []

    build_payload.collect_wheels(
        tmp_path / "runtime" / "python.exe",
        tmp_path / "wheels",
        runner=lambda args, **kw: calls.append(args)
        or subprocess.CompletedProcess(args, 0),
    )

    assert calls[0][0] == str(tmp_path / "runtime" / "python.exe")
    assert calls[0][1:4] == ["-m", "pip", "wheel"]


def test_a_failed_pip_stops_the_build(tmp_path):
    with pytest.raises(RuntimeError, match="pip wheel exited 1"):
        build_payload.collect_wheels(
            tmp_path / "python.exe", tmp_path / "wheels",
            runner=lambda args, **kw: subprocess.CompletedProcess(args, 1),
        )


def test_the_desktop_extra_is_left_out():
    """The setup.exe app runs in a browser, so pywebview — and the WebView2
    runtime it would then need fetching — is weight with no payoff."""
    assert "desktop" not in build_payload.EXTRAS
    assert build_payload.EXTRAS == "tray"


# --- the Inno Setup script ------------------------------------------------------


def _expand_defines(text: str) -> str:
    """Substitute the script's own #define values.

    Every path in the .iss is written through {#AppName}, so a test that
    matched the raw text would be asserting on the spelling rather than on
    the directory the installer actually uses.
    """
    values = dict(re.findall(r'^\s*#define\s+(\w+)\s+"([^"]*)"', text, re.MULTILINE))
    for _ in range(3):  # a define may be written in terms of another
        for name, value in values.items():
            text = text.replace("{#" + name + "}", value)
    return text


@pytest.fixture(scope="module")
def iss() -> str:
    return _expand_defines(ISS.read_text(encoding="utf-8"))


def _directive(text: str, name: str) -> str:
    found = re.search(rf"^{name}=(.+)$", text, re.MULTILINE)
    assert found, f"no {name}= in the .iss"
    return found.group(1).strip()


def test_it_never_asks_for_administrator(iss):
    assert _directive(iss, "PrivilegesRequired") == "lowest"


def test_it_is_sixty_four_bit_only(iss):
    assert _directive(iss, "ArchitecturesAllowed") == "x64compatible"
    assert _directive(iss, "ArchitecturesInstallIn64BitMode") == "x64compatible"


def test_it_installs_into_a_subdirectory_of_the_data_directory(iss):
    r"""%LOCALAPPDATA%\beyondMeetings is also where the recordings live.

    Windows paths are case-insensitive, so the program directory and the data
    directory are the same directory under two spellings. Installing the
    program *into* it, rather than beside the meetings, is the only reason
    the uninstaller can safely delete what it installed.
    """
    assert _directive(iss, "DefaultDirName") == r"{localappdata}\beyondMeetings\app"


def test_the_uninstaller_never_removes_the_directory_that_holds_meetings(iss):
    removals = re.findall(r"^Type:\s*(\S+);\s*Name:\s*\"([^\"]+)\"", iss, re.MULTILINE)
    assert removals, "the .iss removes nothing"
    for kind, target in removals:
        if target.rstrip("\\").lower() == r"{localappdata}\beyondmeetings":
            # dirifempty is harmless; anything else is a data-loss bug.
            assert kind == "dirifempty", f"{kind} on the data directory"


def test_the_uninstaller_removes_the_shim_it_was_never_told_about(iss):
    """setup-finish.ps1 writes it after Inno has finished recording files."""
    assert r"{localappdata}\beyondMeetings\bin\beyondmeetings.cmd" in iss


def test_ffmpeg_lands_where_the_application_looks_for_it(iss):
    """Not on PATH — in the directory tools.which_tool searches."""
    from beyondmeetings.tools import APP_DIR_NAME

    expected = f'DestDir: "{{localappdata}}\\{APP_DIR_NAME}\\bin"'
    assert iss.count(expected) == 2, "ffmpeg.exe and ffprobe.exe both go there"


def test_the_app_icon_opens_the_browser_app_without_a_console(iss):
    block = _section(iss, "Icons")
    assert "userprograms" in block, "no Start Menu entry"
    assert "pythonw.exe" in block, "a console script flashes a black window"
    assert "-m beyondmeetings open" in block, (
        "`open` is the idempotent one — `serve` fails to bind on a second click"
    )
    assert " app\"" not in block, "this build ships no pywebview to draw a window"


def _section(iss: str, name: str) -> str:
    """One section of the .iss, from its header line to the next one.

    Anchored at the start of a line, because a section *name* also appears in
    ordinary prose — "handled in [Code]" is a comment near the top of the
    file, and splitting on the bare string landed in the middle of [Setup].
    """
    found = re.search(
        rf"^\[{name}\]$(.*?)(?=^\[[A-Za-z]+\]$|\Z)",
        iss, re.MULTILINE | re.DOTALL,
    )
    assert found, f"no [{name}] section"
    return found.group(1)


def _code_outside_strings(iss: str) -> str:
    """The [Code] section with its Pascal string literals blanked out.

    Braces are legal and common inside a literal — `ExpandConstant('{app}')`
    and a PowerShell script block both contain them — so any check for stray
    braces has to look at the code around the strings, not at the text.
    """
    return re.sub(r"'(?:[^']|'')*'", "''", _section(iss, "Code"))


def test_the_code_section_uses_only_line_comments(iss):
    """Pascal has three comment forms here and two of them are block comments
    that do not nest — in either spelling. Writing an Inno constant in one
    ends it early and the rest of the sentence is compiled as code.

    This is not hypothetical. The first version of this installer carried a
    `(* ... *)` comment whose text mentioned `(* *)`, which closed itself and
    failed the build with "'BEGIN' expected". Allowing only `//` removes the
    whole class of mistake, so that is what is asserted.
    """
    bare = _code_outside_strings(iss)

    assert "(*" not in bare, "a (* *) comment — use // instead"
    assert "{" not in bare, "a { } comment or a stray constant — use // instead"


@pytest.mark.parametrize(
    "comment",
    [
        "{ executables inside {app} are stopped }",
        "(* it ends at the first *) not the last *)",
    ],
)
def test_the_comment_guard_actually_detects_the_bug(comment):
    """A static guard nobody has seen fail is a guard nobody can trust.

    Both of these compile to something other than a comment. The second is
    the one that actually broke a build.
    """
    bare = _code_outside_strings(f"[Code]\n{comment}\n")

    assert "(*" in bare or "{" in bare


def test_the_guard_does_not_trip_on_braces_inside_a_string():
    sample = "[Code]\nX := ExpandConstant('{app}') + 'a || b { c }';\n"

    bare = _code_outside_strings(sample)

    assert "{" not in bare


def test_the_minimum_windows_is_stated(iss):
    assert _directive(iss, "MinVersion") == "10.0"


def test_the_installer_is_named_for_the_architecture_it_is(iss):
    assert _directive(iss, "OutputBaseFilename") == "beyondMeetings-Setup-x64"


# --- what happens after the files are copied ------------------------------------


@pytest.fixture(scope="module")
def finish() -> str:
    return FINISH.read_text(encoding="utf-8")


def test_nothing_is_downloaded_while_installing(finish):
    """The whole point of a setup.exe: it works with no network at all."""
    for verb in ("Invoke-WebRequest", "Invoke-RestMethod", "Start-BitsTransfer",
                 "DownloadFile", "curl ", "wget "):
        assert verb not in finish, f"{verb} would need a working network"


def test_pip_is_forbidden_from_reaching_an_index(finish):
    """Without --no-index a machine that *can* see pypi.org resolves against
    it, so the offline path is never the one that gets tested."""
    assert "--no-index" in finish
    assert "--find-links" in finish


def test_it_builds_a_venv_rather_than_shipping_one(finish):
    """pip writes the interpreter's absolute path into every console script,
    so a venv built on a build agent points at a directory the user has not
    got. Building it on the machine is what makes the payload relocatable."""
    assert "-m\", \"venv\"" in finish or '"-m", "venv"' in finish or \
        '@("-m", "venv", $Venv)' in finish


def test_a_failure_before_the_application_is_installed_is_reported(finish):
    codes = re.findall(r"^\s*exit (\d+)\s*$", finish, re.MULTILINE)
    assert set(codes) - {"0"}, "every failure path exits 0 — nothing is reported"


def test_nothing_after_the_point_of_no_return_can_fail_the_install(finish):
    """Same rule install.ps1 follows: once the application is installed and
    working, a missing convenience is a warning, not a failed installation."""
    marker = "Past this line the application is installed and working"
    assert marker in finish, "the point of no return is not marked"
    after = finish.split(marker, 1)[1]
    assert re.findall(r"^\s*exit (\d+)\s*$", after, re.MULTILINE) == ["0"]


def test_the_log_is_somewhere_the_user_can_find(finish, iss):
    assert "beyondmeetings-setup.log" in finish
    assert "beyondmeetings-setup.log" in iss, (
        "a failed install must name the log in the message box"
    )


def test_the_bundled_wheels_do_not_stay_on_disk(finish):
    assert "Reclaimed the bundled wheels" in finish


def test_the_shim_matches_the_one_the_other_installer_writes(finish):
    """Both Windows installers must leave the same command in the same place,
    or uninstall.ps1 and doctor each only half work."""
    install_ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    for script in (finish, install_ps1):
        assert 'Set-Content -Path' in script
        assert "beyondmeetings.cmd" in script
        assert "-Encoding Oem" in script


def test_the_shipped_pip_is_refreshed_before_anything_is_built(tmp_path):
    """`python -m venv` seeds the user's environment with the interpreter's
    own pip, so a stale one in the payload becomes a stale one on every
    machine that installs it."""
    calls = []
    build_payload.upgrade_pip(
        tmp_path / "python.exe",
        runner=lambda args, **kw: calls.append(args)
        or subprocess.CompletedProcess(args, 0),
    )

    assert calls[0][:5] == [
        str(tmp_path / "python.exe"), "-m", "pip", "install", "--upgrade",
    ]
    assert "pip" in calls[0]


def test_a_stale_pip_that_cannot_be_replaced_does_not_stop_the_build():
    """The bundled one usually works, and `pip wheel` reports it plainly if
    it does not — failing here would trade a warning for a broken build."""
    build_payload.upgrade_pip(
        Path("python.exe"),
        runner=lambda args, **kw: subprocess.CompletedProcess(args, 1),
    )


# --- the two installers have to coexist ------------------------------------


def test_the_script_uninstaller_defers_to_the_registered_one():
    """A setup.exe install is registered with Windows. Deleting its files
    from underneath it leaves an entry in Settings > Apps that can never be
    removed, so uninstall.ps1 has to hand over rather than race it."""
    script = (ROOT / "uninstall.ps1").read_text(encoding="utf-8")

    assert "unins*.exe" in script
    handover = script.split("unins*.exe", 1)[1].split("# Resolve the real paths")[0]
    assert "Settings > Apps" in handover
    assert re.search(r"^\s*exit 0\s*$", handover, re.MULTILINE), (
        "it detects the registered uninstaller and then removes the files anyway"
    )


def test_both_installers_build_the_same_layout():
    """`doctor`, the Start Menu shortcut and uninstall.ps1 all resolve these
    paths themselves. If the two installers disagree, each of those works for
    one kind of install and silently half-works for the other."""
    install_ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    iss = _expand_defines(ISS.read_text(encoding="utf-8"))

    assert r'Join-Path $LocalAppData "beyondMeetings\app"' in install_ps1
    assert r"DefaultDirName={localappdata}\beyondMeetings\app" in iss
    assert r'Join-Path $LocalAppData "beyondMeetings\bin"' in install_ps1
    assert r"{localappdata}\beyondMeetings\bin" in iss
    assert "venv\\Scripts\\beyondmeetings.exe" in install_ps1.replace(
        'Join-Path $Venv "Scripts\\beyondmeetings.exe"',
        "venv\\Scripts\\beyondmeetings.exe",
    )
    assert r"{app}\venv\Scripts" in iss


# --- the release lookup ------------------------------------------------------


def test_the_release_lookup_authenticates_when_it_can():
    """60 anonymous API calls an hour, per IP, shared between runners: two
    builds of one push were enough for `403: rate limit exceeded`."""
    headers = build_payload.api_headers({"GITHUB_TOKEN": "ghs_secret"})

    assert headers["Authorization"] == "Bearer ghs_secret"


def test_either_token_variable_is_honoured():
    """Actions sets GITHUB_TOKEN; the gh CLI sets GH_TOKEN."""
    assert "Authorization" in build_payload.api_headers({"GH_TOKEN": "x"})


def test_it_still_works_with_no_token_at_all():
    """A developer running this by hand has neither."""
    headers = build_payload.api_headers({})

    assert "Authorization" not in headers
    assert headers["User-Agent"]


def test_the_workflow_passes_a_token_to_the_payload_step():
    workflow = (
        ROOT / ".github" / "workflows" / "windows-installer.yml"
    ).read_text(encoding="utf-8")
    step = workflow.split("Assemble the payload", 1)[1].split("- name:", 1)[0]

    assert "GITHUB_TOKEN" in step


def test_the_workflow_does_not_race_itself():
    """Push and pull_request both fire it, and the job is expensive."""
    workflow = (
        ROOT / ".github" / "workflows" / "windows-installer.yml"
    ).read_text(encoding="utf-8")

    assert "cancel-in-progress: true" in workflow


def test_no_native_command_is_piped_into_a_short_circuiting_filter():
    """`ffmpeg -version | Select-Object -First 1` stops the pipeline early,
    PowerShell kills the command, and $LASTEXITCODE then reports a failure
    for output it simply stopped reading. It failed a passing install."""
    workflow = (
        ROOT / ".github" / "workflows" / "windows-installer.yml"
    ).read_text(encoding="utf-8")

    for line in workflow.splitlines():
        if "Select-Object -First" not in line or line.lstrip().startswith("#"):
            continue
        assert not line.lstrip().startswith("&"), line
