from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения загружаются из переменных среды."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str

    rabbitmq_host: str
    rabbitmq_port: int
    rabbitmq_user: str
    rabbitmq_password: str
    rabbitmq_vhost: str = "/"

    api_key: str

    outbox_poll_interval: float = 0.5
    outbox_batch_size: int = 100


    @property
    def database_url(self) -> str:
        """Возвращает строку подключения к PostgreSQL."""
        return (
            f"postgresql+asyncpg://"
            f"{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}"
            f"/{self.postgres_db}"
        )

    @property
    def alembic_database_url(self) -> str:
        """Возвращает sync URL подключения к PostgreSQL для миграций."""
        return (
            f"postgresql+psycopg://"
            f"{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}"
            f"/{self.postgres_db}"
        )

    @property
    def rabbitmq_url(self) -> str:
        """Возвращает URL подключения к RabbitMQ."""
        return (
            f"amqp://"
            f"{self.rabbitmq_user}:{self.rabbitmq_password}"
            f"@{self.rabbitmq_host}:{self.rabbitmq_port}"
            f"{self.rabbitmq_vhost}"
        )


@lru_cache
def get_settings() -> Settings:
    """Возвращает единственный экземпляр настроек приложения."""
    return Settings()


settings = get_settings()
