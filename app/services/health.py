"""Readiness: can this instance serve requests right now?

``GET /health`` stays a cheap liveness probe (the process is up).
``GET /health/ready`` runs these checks. A failed **critical** check (OCR
engine, vector store) makes the instance unavailable (503); a failed
non-critical one (the LLM, needed only by ``/api/ask``) makes it degraded but
still ready (200), because extract and ingest keep working.

Each probe returns a short detail string or raises. Any exception counts as a
failure here on purpose: a health check must report every way a dependency
can be broken, and the failure is logged and returned, never swallowed.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    probe: Callable[[], str]
    critical: bool = True


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    ok: bool
    critical: bool
    detail: str
    duration_ms: float


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    status: str  # "ready" | "degraded" | "unavailable"
    checks: list[CheckResult]

    @property
    def serving(self) -> bool:
        return self.status != "unavailable"


class ReadinessService:
    def __init__(self, checks: Sequence[Check]) -> None:
        self._checks = tuple(checks)

    def check(self) -> ReadinessReport:
        results = [self._run(check) for check in self._checks]
        if any(not r.ok and r.critical for r in results):
            status = "unavailable"
        elif any(not r.ok for r in results):
            status = "degraded"
        else:
            status = "ready"
        if status != "ready":
            failed = [r.name for r in results if not r.ok]
            logger.warning("readiness_failed", status=status, failed=failed)
        return ReadinessReport(status=status, checks=results)

    @staticmethod
    def _run(check: Check) -> CheckResult:
        started = time.perf_counter()
        try:
            detail, ok = check.probe(), True
        except Exception as exc:  # a probe reports every failure; see module docstring
            detail, ok = f"{type(exc).__name__}: {exc}", False
        return CheckResult(
            name=check.name,
            ok=ok,
            critical=check.critical,
            detail=detail,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
