"""Centralized configuration with validation and defaults."""
import os
from pathlib import Path
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class OpenAIConfig:
    api_key: str = ""
    model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    max_retries: int = 3
    timeout_seconds: int = 60
    max_tokens: int = 4096

    @classmethod
    def from_env(cls) -> "OpenAIConfig":
        return cls(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
            max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "3")),
            timeout_seconds=int(os.getenv("OPENAI_TIMEOUT", "60")),
            max_tokens=int(os.getenv("OPENAI_MAX_TOKENS", "4096")),
        )

    def validate(self) -> list[str]:
        errors = []
        if not self.api_key:
            errors.append("OPENAI_API_KEY is not set")
        if self.max_retries < 0:
            errors.append("OPENAI_MAX_RETRIES must be >= 0")
        if self.timeout_seconds < 5:
            errors.append("OPENAI_TIMEOUT must be >= 5")
        return errors


@dataclass(frozen=True)
class AppConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:3000"])
    mock_data_dir: Path = field(default_factory=lambda: Path(__file__).parent / "mock_data")
    rag_index_path: Path = field(default_factory=lambda: Path(__file__).parent / "rag_index.json")
    log_level: str = "INFO"
    max_releases_in_memory: int = 100

    @classmethod
    def from_env(cls) -> "AppConfig":
        origins = os.getenv("CORS_ORIGINS", "http://localhost:3000")
        return cls(
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8000")),
            cors_origins=[o.strip() for o in origins.split(",")],
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            max_releases_in_memory=int(os.getenv("MAX_RELEASES", "100")),
        )


def load_config() -> tuple[AppConfig, OpenAIConfig]:
    return AppConfig.from_env(), OpenAIConfig.from_env()
