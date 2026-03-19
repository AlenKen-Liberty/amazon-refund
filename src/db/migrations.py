from __future__ import annotations

from src.db.connection import Database

ORA_OBJECT_EXISTS = 955

TABLE_DDLS = [
    """
    CREATE TABLE orders (
        order_id        VARCHAR2(50) PRIMARY KEY,
        order_date      DATE NOT NULL,
        total_amount    NUMBER(10,2),
        status          VARCHAR2(50),
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE items (
        item_id         NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        order_id        VARCHAR2(50) NOT NULL REFERENCES orders(order_id),
        asin            VARCHAR2(20) NOT NULL,
        title           VARCHAR2(500),
        purchase_price  NUMBER(10,2) NOT NULL,
        product_url     VARCHAR2(2000),
        seller          VARCHAR2(200),
        is_eligible     NUMBER(1) DEFAULT 1,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_items_order_asin UNIQUE (order_id, asin)
    )
    """,
    """
    CREATE TABLE price_history (
        history_id      NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        asin            VARCHAR2(20) NOT NULL,
        price           NUMBER(10,2) NOT NULL,
        extraction_method VARCHAR2(20),
        checked_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE refund_requests (
        refund_id       NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        item_id         NUMBER NOT NULL REFERENCES items(item_id),
        purchase_price  NUMBER(10,2) NOT NULL,
        current_price   NUMBER(10,2) NOT NULL,
        price_diff      NUMBER(10,2) NOT NULL,
        status          VARCHAR2(20) DEFAULT 'pending',
        refund_amount   NUMBER(10,2),
        refund_type     VARCHAR2(50),
        conversation_log CLOB,
        failure_reason  VARCHAR2(500),
        attempted_at    TIMESTAMP,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE system_state (
        key             VARCHAR2(100) PRIMARY KEY,
        value           VARCHAR2(4000),
        updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
]

INDEX_DDLS = [
    "CREATE INDEX idx_items_asin ON items(asin)",
    "CREATE INDEX idx_items_order ON items(order_id)",
    "CREATE INDEX idx_price_history_asin ON price_history(asin)",
    "CREATE INDEX idx_price_history_time ON price_history(checked_at)",
    "CREATE INDEX idx_refund_status ON refund_requests(status)",
]


def create_tables(database: Database) -> None:
    with database.connection() as connection:
        with connection.cursor() as cursor:
            for ddl in (*TABLE_DDLS, *INDEX_DDLS):
                _execute_ddl(cursor, ddl)
        connection.commit()


def _execute_ddl(cursor: object, ddl: str) -> None:
    try:
        cursor.execute(ddl)
    except Exception as exc:
        error_obj = getattr(exc, "args", [None])[0]
        code = getattr(error_obj, "code", None)
        if code != ORA_OBJECT_EXISTS:
            raise
