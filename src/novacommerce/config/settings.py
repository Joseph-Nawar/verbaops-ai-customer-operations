"""Independent, immutable NovaCommerce configuration."""

from enum import StrEnum
from typing import Any, ClassVar, Self, cast

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


class Environment(StrEnum):
    """Supported NovaCommerce deployment environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Supported service log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class DatabaseSettings(BaseModel):
    """NovaCommerce PostgreSQL connection settings."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    url: SecretStr | None = None


class ObservabilitySettings(BaseModel):
    """Operational logging settings."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    log_level: LogLevel = LogLevel.INFO


class Settings(BaseSettings):
    """Load only `NOVACOMMERCE_`-prefixed environment variables."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        env_prefix="NOVACOMMERCE_",
        extra="forbid",
        frozen=True,
    )

    environment: Environment = Environment.DEVELOPMENT
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
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
        """Allow the shared dotenv file to contain VerbaOps settings as well."""

        def filtered_dotenv() -> dict[str, Any]:
            return {
                key: value
                for key, value in dotenv_settings().items()
                if key.lower().startswith("novacommerce_")
            }

        return (
            init_settings,
            env_settings,
            cast(PydanticBaseSettingsSource, filtered_dotenv),
            file_secret_settings,
        )

    @model_validator(mode="after")
    def require_deployed_database(self) -> Self:
        """Require a non-blank database URL outside local environments."""

        if self.environment in (Environment.STAGING, Environment.PRODUCTION) and (
            self.database.url is None or not self.database.url.get_secret_value().strip()
        ):
            raise ValueError("database.url is required in staging and production")
        return self
