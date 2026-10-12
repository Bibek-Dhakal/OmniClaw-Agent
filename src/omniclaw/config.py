"""Single source of truth for configuration (environment variables and .env)."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class EngineProfile:
    model: str
    api_base: str | None
    api_key: str | None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # General
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 8080
    owner_name: str = "Owner"
    memory_user_id: str = "owner"
    max_agent_steps: int = 8
    history_turns: int = 12
    approval_required: bool = True
    approval_timeout_seconds: int = 300

    # Engine profiles (all routed through LiteLLM)
    agent_engine: Literal["native", "hermes", "openclaw"] = "native"
    llm_model: str = "gemini/gemini-3.8-flash"
    llm_api_base: str = ""
    llm_api_key: SecretStr = SecretStr("")
    hermes_model: str = "openai/hermes"
    hermes_api_base: str = ""
    hermes_api_key: SecretStr = SecretStr("")
    openclaw_model: str = "openai/openclaw"
    openclaw_api_base: str = ""
    openclaw_api_key: SecretStr = SecretStr("")

    # Storage
    database_url: str = "postgresql://omniclaw:omniclaw@localhost:5432/omniclaw"
    mem0_api_key: SecretStr = SecretStr("")
    r2_account_id: str = ""
    r2_access_key_id: SecretStr = SecretStr("")
    r2_secret_access_key: SecretStr = SecretStr("")
    r2_bucket: str = ""

    # Connectors
    composio_api_key: SecretStr = SecretStr("")
    composio_base_url: str = "https://backend.composio.dev"
    composio_user_id: str = "default"
    nango_secret_key: SecretStr = SecretStr("")
    nango_base_url: str = "https://api.nango.dev"
    nango_connection_id: str = ""

    # Telegram
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_allowed_user_ids: str = ""

    # WhatsApp
    whatsapp_token: SecretStr = SecretStr("")
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: SecretStr = SecretStr("")
    whatsapp_app_secret: SecretStr = SecretStr("")
    whatsapp_allowed_numbers: str = ""
    whatsapp_graph_version: str = "v23.0"

    # Voice
    elevenlabs_api_key: SecretStr = SecretStr("")
    elevenlabs_voice_id: str = ""
    elevenlabs_model_id: str = "eleven_multilingual_v2"
    voice_replies_always: bool = False
    stt_model: str = "whisper-1"
    stt_api_key: SecretStr = SecretStr("")

    # Browser
    browser_headless: bool = True
    browser_state_dir: str = "./.browser_state"
    browser_allowed_domains: str = "instagram.com,tinder.com,linkedin.com"

    @property
    def telegram_allowed_ids(self) -> set[str]:
        return set(_csv(self.telegram_allowed_user_ids))

    @property
    def whatsapp_allowed_set(self) -> set[str]:
        return set(_csv(self.whatsapp_allowed_numbers))

    @property
    def browser_allowed_domain_list(self) -> list[str]:
        return [d.lower() for d in _csv(self.browser_allowed_domains)]

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token.get_secret_value() and self.telegram_allowed_ids)

    @property
    def whatsapp_enabled(self) -> bool:
        return all(
            (
                self.whatsapp_token.get_secret_value(),
                self.whatsapp_phone_number_id,
                self.whatsapp_verify_token.get_secret_value(),
                self.whatsapp_app_secret.get_secret_value(),
                self.whatsapp_allowed_set,
            )
        )

    @property
    def r2_enabled(self) -> bool:
        return all(
            (
                self.r2_account_id,
                self.r2_access_key_id.get_secret_value(),
                self.r2_secret_access_key.get_secret_value(),
                self.r2_bucket,
            )
        )

    @property
    def r2_endpoint(self) -> str:
        return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"

    def engine_profile(self) -> EngineProfile:
        if self.agent_engine == "hermes":
            return EngineProfile(
                self.hermes_model,
                self.hermes_api_base or None,
                self.hermes_api_key.get_secret_value() or None,
            )
        if self.agent_engine == "openclaw":
            return EngineProfile(
                self.openclaw_model,
                self.openclaw_api_base or None,
                self.openclaw_api_key.get_secret_value() or None,
            )
        return EngineProfile(
            self.llm_model,
            self.llm_api_base or None,
            self.llm_api_key.get_secret_value() or None,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
