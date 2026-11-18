"""Environment validation: malformed values fail loudly (naming the variable, never the value)."""

import asyncio

import pytest

from app import config
from app.config import ConfigError
from app.main import app

BAD = ["abc", "nan", "inf", "-1", "0.5e", "1e999"]


@pytest.mark.parametrize("var,loader", [
    ("EMBEDDING_TIMEOUT_SECONDS", config.load_embedding_settings),
    ("EMBEDDING_TOTAL_TIMEOUT_SECONDS", config.load_embedding_settings),
    ("EMBEDDING_MAX_RETRIES", config.load_embedding_settings),
    ("EMBEDDING_MAX_RESPONSE_BYTES", config.load_embedding_settings),
    ("MAX_CONCURRENT_ANALYSES", config.load_analysis_limits),
    ("ANALYSIS_WAIT_TIMEOUT_SECONDS", config.load_analysis_limits),
    ("RATE_LIMIT_PER_CLIENT", config.load_rate_limit_settings),
    ("RATE_LIMIT_WINDOW_SECONDS", config.load_rate_limit_settings),
    ("TRUSTED_PROXY_COUNT", config.load_rate_limit_settings),
])
@pytest.mark.parametrize("value", BAD)
def test_bad_values_raise_config_error_naming_only_the_variable(monkeypatch, var, loader, value):
    monkeypatch.setenv(var, value)
    with pytest.raises(ConfigError) as info:
        loader()
    assert var in str(info.value)
    assert value not in str(info.value) or value in var


def test_blank_and_unset_use_defaults(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MAX_RETRIES", "  ")
    assert config.load_embedding_settings().max_retries == 2
    assert config.load_analysis_limits().max_concurrent == 2


@pytest.mark.parametrize("var,value", [
    ("EMBEDDING_MAX_RETRIES", "6"), ("EMBEDDING_TIMEOUT_SECONDS", "0"), ("MAX_CONCURRENT_ANALYSES", "0"),
    ("MAX_CONCURRENT_ANALYSES", "17"), ("RATE_LIMIT_WINDOW_SECONDS", "5"), ("TRUSTED_PROXY_COUNT", "6"),
])
def test_out_of_range_values_are_rejected(monkeypatch, var, value):
    monkeypatch.setenv(var, value)
    with pytest.raises(ConfigError):
        config.validate_settings()


def test_secret_pasted_into_numeric_field_is_not_echoed(monkeypatch):
    monkeypatch.setenv("EMBEDDING_TIMEOUT_SECONDS", "hf_SUPERSECRETTOKEN")
    with pytest.raises(ConfigError) as info:
        config.validate_settings()
    assert "SUPERSECRET" not in str(info.value)


def test_app_refuses_to_start_with_a_malformed_setting(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "lots")

    async def start():
        async with app.router.lifespan_context(app):
            pass

    with pytest.raises(ConfigError):
        asyncio.run(start())


def test_defaults_validate_cleanly():
    config.validate_settings()
