from __future__ import annotations

import os
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ModuleNotFoundError:

    class SettingsConfigDict(dict):
        pass

    class BaseSettings:
        model_config: dict[str, Any] = {}

        def __init__(self, **overrides: Any) -> None:
            env_prefix = str(self.model_config.get("env_prefix", ""))
            env_file = self.model_config.get("env_file")
            file_values = _read_env_file(env_file) if env_file else {}

            annotations = get_type_hints(self.__class__)
            for field_name, annotation in annotations.items():
                default = getattr(self.__class__, field_name, None)
                raw_value = overrides.get(
                    field_name, _lookup_env_value(field_name, env_prefix, file_values)
                )
                value = (
                    default
                    if raw_value is None
                    else _coerce_env_value(raw_value, annotation, default)
                )
                setattr(self, field_name, value)


def _read_env_file(path: str | os.PathLike[str] | None) -> dict[str, str]:
    if not path:
        return {}

    env_path = Path(path)
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _lookup_env_value(
    field_name: str, env_prefix: str, file_values: dict[str, str]
) -> str | None:
    env_name = f"{env_prefix}{field_name.upper()}"
    if env_name in os.environ:
        return os.environ[env_name]
    return file_values.get(env_name)


def _coerce_env_value(raw_value: Any, annotation: Any, default: Any) -> Any:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        return raw_value

    target_type = _resolve_annotation(annotation, default)
    lowered = raw_value.lower()

    if target_type is bool:
        return lowered in {"1", "true", "yes", "on"}
    if target_type is int:
        return int(raw_value)
    if target_type is float:
        return float(raw_value)
    return raw_value


def _resolve_annotation(annotation: Any, default: Any) -> Any:
    origin = get_origin(annotation)
    if origin is None:
        if annotation is Any and default is not None:
            return type(default)
        return annotation

    if origin in {list, dict, tuple, set}:
        return origin

    args = [arg for arg in get_args(annotation) if arg is not type(None)]
    if args:
        return args[0]

    if default is not None:
        return type(default)
    return str


class Settings(BaseSettings):
    cdp_port: int = 9222

    db_user: str = ""
    db_password: str = ""
    db_dsn: str = ""
    db_wallet_dir: str | None = None
    db_wallet_password: str | None = None

    llm_provider: str = "ollama"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    chat2api_url: str = "http://127.0.0.1:7860"
    chat2api_model: str = "codex"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    # ── Model tiers ──
    # Callers pick a tier; the tier resolves to a concrete Chat2API model.
    #   thinking : deep reasoning (complex decisions, fallback analysis)
    #   balanced : good quality + reasonable speed (general use)
    #   fast     : low-latency replies (live customer service chat)
    llm_tier_thinking: str = "codex"
    llm_tier_balanced: str = "gemini-2.5-pro"
    llm_tier_fast: str = "gemini-2.5-flash"

    min_refund_amount: float = 2.0
    min_refund_pct: float = 5.0
    amazon_only: bool = True
    max_daily_refunds: int = 5
    max_chat_rounds: int = 10

    check_interval_hours: float = 6.0
    interval_jitter_pct: float = 0.3

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    ntfy_topic: str | None = None
    ntfy_server: str = "https://ntfy.sh"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="AR_")

    @property
    def resolved_db_wallet_dir(self) -> str | None:
        if not self.db_wallet_dir:
            return None
        return str(Path(self.db_wallet_dir).expanduser())


settings = Settings()
