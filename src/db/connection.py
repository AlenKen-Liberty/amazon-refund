from __future__ import annotations

from contextlib import contextmanager
from typing import Any, TYPE_CHECKING

from src.config import settings

if TYPE_CHECKING:
    import oracledb
else:
    oracledb = Any


class Database:
    def __init__(self) -> None:
        self._pool: Any = None

    def init_pool(self, force: bool = False) -> Any:
        if self._pool is not None and not force:
            return self._pool
        if self._pool is not None and force:
            self.close()

        self._validate_backend()
        self._validate_required_settings()

        import oracledb

        pool_kwargs: dict[str, Any] = {
            "user": settings.db_user,
            "password": settings.db_password,
            "dsn": settings.db_dsn,
            "min": 2,
            "max": 5,
            "increment": 1,
        }

        if settings.resolved_db_wallet_dir:
            pool_kwargs["config_dir"] = settings.resolved_db_wallet_dir
            pool_kwargs["wallet_location"] = settings.resolved_db_wallet_dir
        if settings.db_wallet_password:
            pool_kwargs["wallet_password"] = settings.db_wallet_password

        self._pool = oracledb.create_pool(**pool_kwargs)
        return self._pool

    def get_connection(self) -> Any:
        if self._pool is None:
            self.init_pool()
        return self._pool.acquire()

    @contextmanager
    def connection(self) -> Any:
        connection = self.get_connection()
        try:
            yield connection
        finally:
            connection.close()

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    @staticmethod
    def _validate_backend() -> None:
        backend = settings.db_backend.lower().strip()
        if backend != "oracle":
            raise NotImplementedError(
                "Unsupported database backend "
                f"{settings.db_backend!r}. The built-in implementation currently supports "
                "'oracle'. If you want another store, replace the src/db layer and keep "
                "AR_DB_BACKEND in sync."
            )

    @staticmethod
    def _validate_required_settings() -> None:
        required = {
            "AR_DB_USER": settings.db_user,
            "AR_DB_PASSWORD": settings.db_password,
            "AR_DB_DSN": settings.db_dsn,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(
                f"Missing database settings for the oracle backend: {', '.join(missing)}"
            )


db = Database()
