from beyondmeetings.cli import build_parser, format_doctor_report

ROWS = [
    {"id": "a", "label": "PipeWire", "status": "ok", "detail": "found",
     "required": True, "fixable": False, "description": "", "inputs": []},
    {"id": "b", "label": "ffmpeg", "status": "missing", "detail": "run apt",
     "required": True, "fixable": True, "description": "", "inputs": []},
    {"id": "c", "label": "Rules", "status": "missing", "detail": "",
     "required": False, "fixable": True, "description": "", "inputs": []},
]


def test_doctor_subcommand_parses():
    assert build_parser().parse_args(["doctor"]).command == "doctor"


def test_setup_subcommand_parses():
    args = build_parser().parse_args(["setup"])
    assert args.command == "setup"
    assert args.port == 7788


def test_setup_accepts_a_custom_port():
    assert build_parser().parse_args(["setup", "--port", "9000"]).port == 9000


def test_report_shows_percent():
    assert "50%" in format_doctor_report(ROWS)


def test_report_marks_each_status():
    text = format_doctor_report(ROWS)
    assert "✓ PipeWire" in text
    assert "✗ ffmpeg" in text


def test_report_labels_optional_rows():
    assert "optional" in format_doctor_report(ROWS)


def test_report_includes_detail_text():
    assert "run apt" in format_doctor_report(ROWS)


def test_report_handles_an_empty_check_list():
    assert "100%" in format_doctor_report([])
