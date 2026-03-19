from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from src.config import settings
from src.db.connection import db


class SafetyGuard:
    """Protect the account by limiting refund volume and repeated failures."""

    ABSOLUTE_MAX_DAILY = 10
    CONSECUTIVE_FAIL_LIMIT = 3
    COOLDOWN_HOURS = 24
    ATTEMPT_STATUSES = (
        "completed",
        "success",
        "failed",
        "timeout",
        "safety_stop",
        "in_progress",
    )
    FAILURE_STATUSES = ("failed", "timeout", "safety_stop")

    def can_proceed(self) -> tuple[bool, str]:
        with db.connection() as connection:
            daily_count = self._get_today_count(connection)
            limit = min(settings.max_daily_refunds, self.ABSOLUTE_MAX_DAILY)
            if daily_count >= limit:
                return False, f"Daily limit reached ({daily_count}/{limit})"

            consecutive_failures = self._get_consecutive_failures(connection)
            if consecutive_failures >= self.CONSECUTIVE_FAIL_LIMIT:
                last_failure_time = self._get_last_failure_time(connection)
                if last_failure_time is not None:
                    cooldown_until = last_failure_time + timedelta(
                        hours=self.COOLDOWN_HOURS
                    )
                    now = datetime.now()
                    if now < cooldown_until:
                        remaining = cooldown_until - now
                        remaining_hours = max(1, int(remaining.total_seconds() // 3600))
                        return False, (
                            f"{consecutive_failures} consecutive failures. "
                            f"Cooldown: {remaining_hours}h remaining"
                        )

        return True, "OK"

    def _get_today_count(self, connection: Any) -> int:
        placeholders = ", ".join(
            f":status_{idx}" for idx, _ in enumerate(self.ATTEMPT_STATUSES)
        )
        binds = {
            f"status_{idx}": status for idx, status in enumerate(self.ATTEMPT_STATUSES)
        }

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM refund_requests
                WHERE attempted_at >= TRUNC(SYSDATE)
                  AND status IN ({placeholders})
                """,
                binds,
            )
            row = cursor.fetchone()
        return int(row[0]) if row else 0

    def _get_consecutive_failures(self, connection: Any) -> int:
        terminal_statuses = ("completed", "success", *self.FAILURE_STATUSES)
        placeholders = ", ".join(
            f":status_{idx}" for idx, _ in enumerate(terminal_statuses)
        )
        binds = {
            f"status_{idx}": status for idx, status in enumerate(terminal_statuses)
        }

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT status
                FROM (
                    SELECT status, attempted_at, refund_id
                    FROM refund_requests
                    WHERE attempted_at IS NOT NULL
                      AND status IN ({placeholders})
                    ORDER BY attempted_at DESC, refund_id DESC
                )
                WHERE ROWNUM <= {self.CONSECUTIVE_FAIL_LIMIT}
                """,
                binds,
            )
            rows = cursor.fetchall()

        count = 0
        for row in rows:
            status = row[0]
            if status not in self.FAILURE_STATUSES:
                break
            count += 1
        return count

    def _get_last_failure_time(self, connection: Any) -> datetime | None:
        placeholders = ", ".join(
            f":status_{idx}" for idx, _ in enumerate(self.FAILURE_STATUSES)
        )
        binds = {
            f"status_{idx}": status for idx, status in enumerate(self.FAILURE_STATUSES)
        }

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT MAX(attempted_at)
                FROM refund_requests
                WHERE status IN ({placeholders})
                """,
                binds,
            )
            row = cursor.fetchone()
        return row[0] if row and row[0] else None
