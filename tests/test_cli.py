from unittest.mock import patch

from app.cli import main
from app.config import Settings


def test_settings_hide_server_key_and_accept_listen_address():
    settings = Settings(
        host="0.0.0.0", port=9123, server_api_key="top-secret", model_provider="fake"
    )
    assert settings.host == "0.0.0.0"
    assert settings.port == 9123
    assert "top-secret" not in repr(settings)


def test_cli_uses_configured_host_and_port():
    settings = Settings(host="0.0.0.0", port=9123, model_provider="fake")
    with (
        patch("app.cli.Settings", return_value=settings),
        patch("app.cli.uvicorn.run") as run,
    ):
        main()
    run.assert_called_once_with("app.main:app", host="0.0.0.0", port=9123)
