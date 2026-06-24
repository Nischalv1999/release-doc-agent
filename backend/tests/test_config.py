"""Tests for configuration validation."""
from config import OpenAIConfig, AppConfig


class TestOpenAIConfig:
    def test_valid_config(self):
        cfg = OpenAIConfig(api_key="sk-test123")
        assert cfg.validate() == []

    def test_missing_api_key(self):
        cfg = OpenAIConfig(api_key="")
        errors = cfg.validate()
        assert len(errors) == 1
        assert "OPENAI_API_KEY" in errors[0]

    def test_invalid_retries(self):
        cfg = OpenAIConfig(api_key="sk-test", max_retries=-1)
        errors = cfg.validate()
        assert any("retries" in e.lower() for e in errors)

    def test_invalid_timeout(self):
        cfg = OpenAIConfig(api_key="sk-test", timeout_seconds=2)
        errors = cfg.validate()
        assert any("timeout" in e.lower() for e in errors)


class TestAppConfig:
    def test_defaults(self):
        cfg = AppConfig()
        assert cfg.port == 8000
        assert "http://localhost:3000" in cfg.cors_origins
        assert cfg.max_releases_in_memory == 100
