from beyondmeetings.doctor.base import (
    Check, CheckResult, completion_percent, run_all, run_fix,
)


class Stub(Check):
    def __init__(self, id, status, required=True, fixable=False):
        self.id = id
        self.label = id.title()
        self.required = required
        self._status = status
        self._fixable = fixable
        self.fixed = False

    def detect(self) -> CheckResult:
        return CheckResult(status=self._status)

    @property
    def fixable(self) -> bool:
        return self._fixable

    def fix(self, **kwargs) -> CheckResult:
        self.fixed = True
        return CheckResult(status="ok")


def test_run_all_reports_each_check():
    rows = run_all([Stub("a", "ok"), Stub("b", "missing")])
    assert [r["id"] for r in rows] == ["a", "b"]
    assert rows[0]["status"] == "ok"
    assert rows[1]["status"] == "missing"


def test_percent_counts_only_required_checks():
    checks = [Stub("a", "ok"), Stub("b", "missing"), Stub("c", "missing", required=False)]
    assert completion_percent(run_all(checks)) == 50


def test_percent_is_100_when_all_required_pass():
    checks = [Stub("a", "ok"), Stub("b", "missing", required=False)]
    assert completion_percent(run_all(checks)) == 100


def test_percent_is_0_with_no_required_checks_passing():
    assert completion_percent(run_all([Stub("a", "missing")])) == 0


def test_percent_is_100_when_there_are_no_required_checks():
    assert completion_percent(run_all([Stub("a", "ok", required=False)])) == 100


def test_row_exposes_fixable_and_required():
    row = run_all([Stub("a", "missing", fixable=True)])[0]
    assert row["fixable"] is True
    assert row["required"] is True


def test_detect_failure_is_reported_as_broken_not_raised():
    class Exploding(Stub):
        def detect(self):
            raise OSError("boom")

    row = run_all([Exploding("a", "ok")])[0]
    assert row["status"] == "broken"
    assert "boom" in row["detail"]


# --- Review finding #12: fix() was unguarded while detect() was guarded ---

def test_run_fix_contains_an_exception(monkeypatch):
    from beyondmeetings.doctor.base import run_fix

    class Exploding(Stub):
        def fix(self, **kwargs):
            raise OSError("read-only file system")

    result = run_fix(Exploding("a", "missing"))
    assert result.status == "broken"
    assert "read-only" in result.detail


def test_run_fix_reports_an_unfixable_check():
    from beyondmeetings.doctor.base import Check, CheckResult, run_fix

    class NotFixable(Check):
        id = "nope"
        label = "Nope"

        def detect(self):
            return CheckResult(status="missing")

    result = run_fix(NotFixable())
    assert result.status == "broken"
    assert "cannot be fixed" in result.detail


def test_run_fix_passes_the_payload_through():
    stub = Stub("a", "missing", fixable=True)
    assert run_fix(stub).status == "ok"
    assert stub.fixed is True
