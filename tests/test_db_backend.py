from __future__ import annotations

import pytest

from src.config import settings
from src.db.connection import Database


def test_init_pool_rejects_unsupported_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "db_backend", "sqlite")

    with pytest.raises(NotImplementedError, match="Unsupported database backend"):
        Database().init_pool()
