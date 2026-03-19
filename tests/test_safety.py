from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta

from src.config import settings
from src.refund import safety as safety_module
from src.refund.safety import SafetyGuard


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection
        self._sql = ""

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, sql: str, binds=None) -> None:
        self._sql = " ".join(sql.lower().split())

    def fetchone(self):
        if "select count(*)" in self._sql:
            return (self.connection.daily_count,)
        if "select max(attempted_at)" in self._sql:
            return (self.connection.last_failure_time,)
        raise AssertionError(f"Unexpected fetchone SQL: {self._sql}")

    def fetchall(self):
        if "select status" in self._sql:
            return [(status,) for status in self.connection.statuses]
        raise AssertionError(f"Unexpected fetchall SQL: {self._sql}")


class FakeConnection:
    def __init__(
        self,
        *,
        daily_count: int = 0,
        statuses: list[str] | None = None,
        last_failure_time: datetime | None = None,
    ) -> None:
        self.daily_count = daily_count
        self.statuses = statuses or []
        self.last_failure_time = last_failure_time

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)


class FakeDB:
    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection

    @contextmanager
    def connection(self):
        yield self._connection


def test_allows_first_request(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_daily_refunds", 5)
    monkeypatch.setattr(safety_module, "db", FakeDB(FakeConnection()))

    can_go, reason = SafetyGuard().can_proceed()

    assert can_go
    assert reason == "OK"


def test_blocks_when_daily_limit_reached(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_daily_refunds", 2)
    monkeypatch.setattr(
        safety_module,
        "db",
        FakeDB(FakeConnection(daily_count=2)),
    )

    can_go, reason = SafetyGuard().can_proceed()

    assert not can_go
    assert "Daily limit reached" in reason


def test_blocks_on_consecutive_failures(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_daily_refunds", 5)
    monkeypatch.setattr(
        safety_module,
        "db",
        FakeDB(
            FakeConnection(
                statuses=["failed", "timeout", "safety_stop"],
                last_failure_time=datetime.now() - timedelta(hours=1),
            )
        ),
    )

    can_go, reason = SafetyGuard().can_proceed()

    assert not can_go
    assert "Cooldown" in reason


def test_success_breaks_failure_streak(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_daily_refunds", 5)
    monkeypatch.setattr(
        safety_module,
        "db",
        FakeDB(
            FakeConnection(
                statuses=["failed", "completed", "failed"],
                last_failure_time=datetime.now() - timedelta(hours=25),
            )
        ),
    )

    can_go, reason = SafetyGuard().can_proceed()

    assert can_go
    assert reason == "OK"
