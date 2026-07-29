from beyondmeetings.doctor.base import (
    Check, CheckResult, completion_percent, run_all,
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
