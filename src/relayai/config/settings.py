"""Validated, immutable application configuration."""

from enum import StrEnum
from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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


class ObservabilitySettings(BaseModel):
    """Configuration for future observability integrations."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    log_level: LogLevel = LogLevel.INFO


class Settings(BaseSettings):
    """Application settings loaded from RELAYAI_-prefixed environment variables."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        env_prefix="RELAYAI_",
        extra="forbid",
        frozen=True,
    )

    environment: Environment = Environment.DEVELOPMENT
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)

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
