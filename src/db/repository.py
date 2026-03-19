from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.db.models import Item, LatestPriceSnapshot, Order, PriceRecord, RefundRequest


class OrderRepository:
    def upsert_order(self, connection: Any, order: Order) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                MERGE INTO orders dst
                USING (
                    SELECT
                        :order_id AS order_id,
                        :order_date AS order_date,
                        :total_amount AS total_amount,
                        :status AS status
                    FROM dual
                ) src
                ON (dst.order_id = src.order_id)
                WHEN MATCHED THEN
                    UPDATE SET
                        dst.order_date = src.order_date,
                        dst.total_amount = src.total_amount,
                        dst.status = src.status,
                        dst.updated_at = CURRENT_TIMESTAMP
                WHEN NOT MATCHED THEN
                    INSERT (order_id, order_date, total_amount, status)
                    VALUES (src.order_id, src.order_date, src.total_amount, src.status)
                """,
                {
                    "order_id": order.order_id,
                    "order_date": order.order_date,
                    "total_amount": order.total_amount,
                    "status": order.status,
                },
            )

    def upsert_items(self, connection: Any, items: Sequence[Item]) -> None:
        if not items:
            return

        with connection.cursor() as cursor:
            cursor.executemany(
                """
                MERGE INTO items dst
                USING (
                    SELECT
                        :order_id AS order_id,
                        :asin AS asin,
                        :title AS title,
                        :purchase_price AS purchase_price,
                        :product_url AS product_url,
                        :seller AS seller,
                        :is_eligible AS is_eligible
                    FROM dual
                ) src
                ON (dst.order_id = src.order_id AND dst.asin = src.asin)
                WHEN MATCHED THEN
                    UPDATE SET
                        dst.title = src.title,
                        dst.purchase_price = src.purchase_price,
                        dst.product_url = src.product_url,
                        dst.seller = src.seller,
                        dst.is_eligible = src.is_eligible
                WHEN NOT MATCHED THEN
                    INSERT (
                        order_id,
                        asin,
                        title,
                        purchase_price,
                        product_url,
                        seller,
                        is_eligible
                    )
                    VALUES (
                        src.order_id,
                        src.asin,
                        src.title,
                        src.purchase_price,
                        src.product_url,
                        src.seller,
                        src.is_eligible
                    )
                """,
                [
                    {
                        "order_id": item.order_id,
                        "asin": item.asin,
                        "title": item.title,
                        "purchase_price": item.purchase_price,
                        "product_url": item.product_url,
                        "seller": item.seller,
                        "is_eligible": 1 if item.is_eligible else 0,
                    }
                    for item in items
                ],
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
        binds: dict[str, Any] = {}
        clauses: list[str] = []

        if asin:
            clauses.append("asin = :asin")
            binds["asin"] = asin

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        sql += " ORDER BY created_at DESC"

        if limit:
            sql = f"SELECT * FROM ({sql}) WHERE ROWNUM <= :limit"
            binds["limit"] = limit

        with connection.cursor() as cursor:
            cursor.execute(sql, binds)
            rows = cursor.fetchall()

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
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO price_history (asin, price, extraction_method)
                VALUES (:asin, :price, :extraction_method)
                """,
                {
                    "asin": record.asin,
                    "price": record.price,
                    "extraction_method": record.extraction_method,
                },
            )

    def list_latest_item_prices(self, connection: Any) -> list[LatestPriceSnapshot]:
        with connection.cursor() as cursor:
            cursor.execute(
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
            )
            rows = cursor.fetchall()

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

        with connection.cursor() as cursor:
            cursor.executemany(
                """
                MERGE INTO refund_requests dst
                USING (
                    SELECT
                        :item_id AS item_id,
                        :purchase_price AS purchase_price,
                        :current_price AS current_price,
                        :price_diff AS price_diff,
                        :status AS status
                    FROM dual
                ) src
                ON (
                    dst.item_id = src.item_id
                    AND dst.status IN ('pending', 'in_progress')
                )
                WHEN MATCHED THEN
                    UPDATE SET
                        dst.purchase_price = src.purchase_price,
                        dst.current_price = src.current_price,
                        dst.price_diff = src.price_diff,
                        dst.status = src.status
                WHEN NOT MATCHED THEN
                    INSERT (item_id, purchase_price, current_price, price_diff, status)
                    VALUES (
                        src.item_id,
                        src.purchase_price,
                        src.current_price,
                        src.price_diff,
                        src.status
                    )
                """,
                [
                    {
                        "item_id": request.item_id,
                        "purchase_price": request.purchase_price,
                        "current_price": request.current_price,
                        "price_diff": request.price_diff,
                        "status": request.status,
                    }
                    for request in requests
                ],
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
        binds: dict[str, Any] = {}
        if order_id:
            sql += " AND i.order_id = :order_id"
            binds["order_id"] = order_id
        sql += " ORDER BY r.price_diff DESC, r.created_at ASC"

        if limit:
            sql = f"SELECT * FROM ({sql}) WHERE ROWNUM <= :limit"
            binds["limit"] = limit

        with connection.cursor() as cursor:
            cursor.execute(sql, binds)
            rows = cursor.fetchall()

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
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE refund_requests
                SET status = :status,
                    refund_amount = :refund_amount,
                    refund_type = :refund_type,
                    conversation_log = :conversation_log,
                    failure_reason = :failure_reason,
                    attempted_at = CURRENT_TIMESTAMP
                WHERE refund_id = :refund_id
                """,
                {
                    "status": status,
                    "refund_amount": refund_amount,
                    "refund_type": refund_type,
                    "conversation_log": conversation_log,
                    "failure_reason": failure_reason,
                    "refund_id": refund_id,
                },
            )

    def get_item_details(self, connection: Any, item_id: int) -> dict[str, Any] | None:
        with connection.cursor() as cursor:
            cursor.execute(
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
                WHERE i.item_id = :item_id
                """,
                {"item_id": item_id},
            )
            row = cursor.fetchone()

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
            "purchase_date": order_date.strftime("%Y-%m-%d") if order_date else "",
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
        with connection.cursor() as cursor:
            for label, sql in {
                "orders": "SELECT COUNT(*) FROM orders",
                "items": "SELECT COUNT(*) FROM items",
                "price_checks": "SELECT COUNT(*) FROM price_history",
                "refund_requests": "SELECT COUNT(*) FROM refund_requests",
            }.items():
                cursor.execute(sql)
                stats[label] = int(cursor.fetchone()[0])
        return stats
