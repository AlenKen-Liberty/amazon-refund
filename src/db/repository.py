from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from src.db.models import Item, LatestPriceSnapshot, Order, PriceRecord, RefundRequest


class OrderRepository:
    def upsert_order(self, connection: Any, order: Order) -> None:
        connection.execute(
            """
            INSERT INTO orders (order_id, order_date, total_amount, status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(order_id) DO UPDATE SET
                order_date = excluded.order_date,
                total_amount = excluded.total_amount,
                status = excluded.status,
                updated_at = datetime('now')
            """,
            (
                order.order_id,
                order.order_date.isoformat() if hasattr(order.order_date, "isoformat") else str(order.order_date),
                order.total_amount,
                order.status,
            ),
        )

    def upsert_items(self, connection: Any, items: Sequence[Item]) -> None:
        if not items:
            return
        for item in items:
            connection.execute(
                """
                INSERT INTO items (order_id, asin, title, purchase_price, product_url, seller, is_eligible)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id, asin) DO UPDATE SET
                    title = excluded.title,
                    purchase_price = excluded.purchase_price,
                    product_url = excluded.product_url,
                    seller = excluded.seller,
                    is_eligible = excluded.is_eligible
                """,
                (
                    item.order_id,
                    item.asin,
                    item.title,
                    item.purchase_price,
                    item.product_url,
                    item.seller,
                    1 if item.is_eligible else 0,
                ),
            )

    def list_items(
        self,
        connection: Any,
        *,
        asin: str | None = None,
        limit: int | None = None,
    ) -> list[Item]:
        sql = """
            SELECT item_id, order_id, asin, title, purchase_price, product_url, seller, is_eligible
            FROM items
        """
        params: list[Any] = []

        if asin:
            sql += " WHERE asin = ?"
            params.append(asin)

        sql += " ORDER BY created_at DESC"

        if limit:
            sql += " LIMIT ?"
            params.append(limit)

        rows = connection.execute(sql, params).fetchall()

        return [
            Item(
                item_id=row[0],
                order_id=row[1],
                asin=row[2],
                title=row[3] or "",
                purchase_price=float(row[4]),
                product_url=row[5] or f"https://www.amazon.com/dp/{row[2]}",
                seller=row[6] or "",
                is_eligible=bool(row[7]),
            )
            for row in rows
        ]


class PriceRepository:
    def record_price(self, connection: Any, record: PriceRecord) -> None:
        connection.execute(
            """
            INSERT INTO price_history (asin, price, extraction_method)
            VALUES (?, ?, ?)
            """,
            (record.asin, record.price, record.extraction_method),
        )

    def list_latest_item_prices(self, connection: Any) -> list[LatestPriceSnapshot]:
        rows = connection.execute(
            """
            SELECT
                i.item_id,
                i.order_id,
                i.asin,
                i.title,
                i.purchase_price,
                i.product_url,
                i.seller,
                i.is_eligible,
                latest.price,
                latest.extraction_method,
                latest.checked_at
            FROM items i
            JOIN (
                SELECT asin, price, extraction_method, checked_at
                FROM (
                    SELECT
                        asin,
                        price,
                        extraction_method,
                        checked_at,
                        ROW_NUMBER() OVER (
                            PARTITION BY asin
                            ORDER BY checked_at DESC, history_id DESC
                        ) AS rn
                    FROM price_history
                )
                WHERE rn = 1
            ) latest ON latest.asin = i.asin
            ORDER BY latest.checked_at DESC
            """
        ).fetchall()

        return [
            LatestPriceSnapshot(
                item=Item(
                    item_id=row[0],
                    order_id=row[1],
                    asin=row[2],
                    title=row[3] or "",
                    purchase_price=float(row[4]),
                    product_url=row[5] or f"https://www.amazon.com/dp/{row[2]}",
                    seller=row[6] or "",
                    is_eligible=bool(row[7]),
                ),
                current_price=float(row[8]),
                extraction_method=row[9] or "",
                checked_at=row[10],
            )
            for row in rows
        ]


class RefundRepository:
    def upsert_pending_requests(
        self, connection: Any, requests: Sequence[RefundRequest]
    ) -> None:
        if not requests:
            return
        for req in requests:
            # Check if an active request already exists
            existing = connection.execute(
                """
                SELECT refund_id FROM refund_requests
                WHERE item_id = ? AND status IN ('pending', 'in_progress')
                """,
                (req.item_id,),
            ).fetchone()

            if existing:
                connection.execute(
                    """
                    UPDATE refund_requests
                    SET purchase_price = ?, current_price = ?, price_diff = ?, status = ?
                    WHERE refund_id = ?
                    """,
                    (req.purchase_price, req.current_price, req.price_diff, req.status, existing[0]),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO refund_requests (item_id, purchase_price, current_price, price_diff, status)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (req.item_id, req.purchase_price, req.current_price, req.price_diff, req.status),
                )

    def list_pending(
        self,
        connection: Any,
        *,
        limit: int | None = None,
        order_id: str | None = None,
    ) -> list[RefundRequest]:
        sql = """
            SELECT
                r.refund_id,
                r.item_id,
                r.purchase_price,
                r.current_price,
                r.price_diff,
                r.status,
                r.refund_amount,
                r.refund_type,
                r.conversation_log,
                r.failure_reason,
                r.attempted_at
            FROM refund_requests r
            JOIN items i ON i.item_id = r.item_id
            WHERE r.status = 'pending'
        """
        params: list[Any] = []
        if order_id:
            sql += " AND i.order_id = ?"
            params.append(order_id)
        sql += " ORDER BY r.price_diff DESC, r.created_at ASC"

        if limit:
            sql += " LIMIT ?"
            params.append(limit)

        rows = connection.execute(sql, params).fetchall()
        return [self._row_to_request(row) for row in rows]

    def update_result(
        self,
        connection: Any,
        refund_id: int,
        *,
        status: str,
        refund_amount: float | None = None,
        refund_type: str | None = None,
        conversation_log: str | None = None,
        failure_reason: str | None = None,
    ) -> None:
        connection.execute(
            """
            UPDATE refund_requests
            SET status = ?,
                refund_amount = ?,
                refund_type = ?,
                conversation_log = ?,
                failure_reason = ?,
                attempted_at = datetime('now')
            WHERE refund_id = ?
            """,
            (status, refund_amount, refund_type, conversation_log, failure_reason, refund_id),
        )

    def get_item_details(self, connection: Any, item_id: int) -> dict[str, Any] | None:
        row = connection.execute(
            """
            SELECT
                i.order_id,
                i.asin,
                i.title,
                i.purchase_price,
                i.product_url,
                i.seller,
                o.order_date
            FROM items i
            JOIN orders o ON o.order_id = i.order_id
            WHERE i.item_id = ?
            """,
            (item_id,),
        ).fetchone()

        if not row:
            return None

        order_date = row[6]
        return {
            "order_id": row[0],
            "asin": row[1],
            "title": row[2] or "",
            "purchase_price": float(row[3]),
            "product_url": row[4] or f"https://www.amazon.com/dp/{row[1]}",
            "seller": row[5] or "",
            "purchase_date": order_date or "",
        }

    @staticmethod
    def _row_to_request(row: Sequence[Any]) -> RefundRequest:
        return RefundRequest(
            refund_id=int(row[0]),
            item_id=int(row[1]),
            purchase_price=float(row[2]),
            current_price=float(row[3]),
            price_diff=float(row[4]),
            status=row[5] or "pending",
            refund_amount=float(row[6]) if row[6] is not None else None,
            refund_type=row[7],
            conversation_log=row[8],
            failure_reason=row[9],
            attempted_at=row[10],
        )


class SystemRepository:
    def get_stats(self, connection: Any) -> dict[str, int]:
        stats: dict[str, int] = {}
        for label, sql in {
            "orders": "SELECT COUNT(*) FROM orders",
            "items": "SELECT COUNT(*) FROM items",
            "price_checks": "SELECT COUNT(*) FROM price_history",
            "refund_requests": "SELECT COUNT(*) FROM refund_requests",
        }.items():
            row = connection.execute(sql).fetchone()
            stats[label] = int(row[0])
        return stats
