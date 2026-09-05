import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_defaults_to_local_model() -> None:
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "local"
    assert settings.max_steps > 0
    assert settings.max_tool_calls > 0


def test_settings_rejects_invalid_max_steps() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_steps=0)
