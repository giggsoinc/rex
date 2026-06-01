"""PreFlight check data models — status enum + result/report dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CheckStatus(str, Enum):
    """Outcome of a single check."""

    OK = "ok"
    SOFT_WARN = "soft_warn"
    HARD_FAIL = "hard_fail"


@dataclass
class CheckResult:
    """Result of one PreFlight check."""

    name: str
    status: CheckStatus
    message: str
    detail: dict = field(default_factory=dict)


@dataclass
class PreFlightReport:
    """Aggregate PreFlight result."""

    results: list[CheckResult]
    overall: CheckStatus = CheckStatus.OK

    @property
    def hard_fails(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == CheckStatus.HARD_FAIL]

    @property
    def soft_warns(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == CheckStatus.SOFT_WARN]

    @property
    def passed(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == CheckStatus.OK]

    def compute_overall(self) -> None:
        if any(r.status == CheckStatus.HARD_FAIL for r in self.results):
            self.overall = CheckStatus.HARD_FAIL
        elif any(r.status == CheckStatus.SOFT_WARN for r in self.results):
            self.overall = CheckStatus.SOFT_WARN
        else:
            self.overall = CheckStatus.OK
