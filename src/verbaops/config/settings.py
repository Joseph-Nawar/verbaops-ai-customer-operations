"""Validated, immutable application configuration."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, ClassVar, Self, cast
from urllib.parse import urlsplit

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    PositiveFloat,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


class Environment(StrEnum):
    """Supported deployment environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Supported application log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class DatabaseSettings(BaseModel):
    """Database connection settings, when the environment requires them."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    url: SecretStr | None = None


class RedisSettings(BaseModel):
    """Redis connection settings, when the environment requires them."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    url: SecretStr | None = None


class LLMSettings(BaseModel):
    """Immutable connection settings for the OpenAI-compatible LLM gateway."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    base_url: str = "http://localhost:4000/v1"
    api_key: SecretStr = SecretStr("local-development-key")
    timeout_seconds: PositiveFloat = 30.0

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """Validate updates instead of allowing credential-bearing URLs to bypass checks."""

        if update is None:
            return super().model_copy(update=None, deep=deep)
        values = self.model_dump()
        values.update(update)
        return type(self).model_validate(values)

    @classmethod
    def model_construct(cls, _fields_set: set[str] | None = None, **values: Any) -> Self:
        """Keep the unsafe Pydantic constructor behind the same validation boundary."""

        return cls.model_validate(values)

    @model_validator(mode="before")
    @classmethod
    def sanitize_url_credentials(cls, data: Any) -> Any:
        """Replace credential-bearing URLs before Pydantic records an error input."""

        if not isinstance(data, Mapping):
            return data
        data = dict(data)
        if "base_url" not in data:
            return data
        value = data.get("base_url")
        if not isinstance(value, str):
            sanitized = dict(data)
            sanitized["base_url"] = "[redacted]"
            return sanitized
        try:
            parsed = urlsplit(value)
            contains_credentials = (
                parsed.username is not None
                or parsed.password is not None
                or bool(parsed.query)
                or bool(parsed.fragment)
            )
        except ValueError:
            contains_credentials = any(marker in value for marker in ("@", "?", "#"))
        if not contains_credentials:
            return data
        sanitized = dict(data)
        sanitized["base_url"] = "[redacted]"
        return sanitized

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        """Require an absolute HTTP(S) gateway URL without exposing credentials."""

        try:
            parsed = urlsplit(value)
        except ValueError:
            raise ValueError("base_url must be an absolute HTTP(S) URL") from None
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("base_url must not contain credentials")
        AnyHttpUrl(value)
        return value

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        """Reject blank credentials while keeping the value secret."""

        if not value.get_secret_value().strip():
            raise ValueError("api_key must not be blank")
        return value


class ObservabilitySettings(BaseModel):
    """Configuration for future observability integrations."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    log_level: LogLevel = LogLevel.INFO


class Settings(BaseSettings):
    """Application settings loaded from VERBAOPS_-prefixed environment variables."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        env_prefix="VERBAOPS_",
        extra="forbid",
        frozen=True,
    )

    environment: Environment = Environment.DEVELOPMENT
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Ignore NovaCommerce entries when both services share `.env`."""

        def filtered_dotenv() -> dict[str, Any]:
            return {
                key: value
                for key, value in dotenv_settings().items()
                if key.lower().startswith("verbaops_")
            }

        return (
            init_settings,
            env_settings,
            cast(PydanticBaseSettingsSource, filtered_dotenv),
            file_secret_settings,
        )

    @model_validator(mode="after")
    def require_deployed_infrastructure(self) -> Self:
        """Require connection URLs in staging and production only."""

        if self.environment in (Environment.STAGING, Environment.PRODUCTION):
            missing = [
                name
                for name, value in (
                    ("database.url", self.database.url),
                    ("redis.url", self.redis.url),
                )
                if value is None or not value.get_secret_value().strip()
            ]
            if missing:
                raise ValueError(
                    "database and redis URLs are required for staging and production: "
                    + ", ".join(missing)
                )
        return self
