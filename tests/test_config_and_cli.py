from __future__ import annotations

import io
import json
import logging
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from promptlab import cli
from promptlab.config import Settings, get_settings
from promptlab.observability import JsonFormatter, configure_logging, request_id_var


def test_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMPTLAB_DATABASE_URL", "postgresql+asyncpg://u:p@db/x")
    monkeypatch.setenv("PROMPTLAB_CORS_ORIGINS", "https://a.example, https://b.example")
    monkeypatch.setenv("PROMPTLAB_BOOTSTRAP_ADMIN_KEY", "secret")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.database_url == "postgresql+asyncpg://u:p@db/x"
    assert not settings.is_sqlite
    assert settings.cors_origins == ["https://a.example", "https://b.example"]
    assert settings.bootstrap_admin_key is not None
    assert "secret" not in repr(settings)


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_json_formatter_includes_request_id_and_extras() -> None:
    record = logging.makeLogRecord({"msg": "hello", "levelname": "INFO", "name": "t"})
    record.route = "/x"
    token = request_id_var.set("rid-1")
    try:
        payload = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert payload["message"] == "hello"
    assert payload["request_id"] == "rid-1"
    assert payload["route"] == "/x"


def test_configure_logging_plain_and_json() -> None:
    configure_logging("DEBUG", json_logs=False)
    assert logging.getLogger().level == logging.DEBUG
    configure_logging("INFO", json_logs=True)
    assert isinstance(logging.getLogger().handlers[0].formatter, JsonFormatter)


def _sqlite_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'cli.db'}",
        _env_file=None,  # type: ignore[call-arg]
    )


def test_migrate_upgrade_and_downgrade(tmp_path: Path) -> None:
    settings = _sqlite_settings(tmp_path)
    cli.migrate(settings)
    engine = create_engine(f"sqlite:///{tmp_path / 'cli.db'}")
    tables = set(inspect(engine).get_table_names())
    assert {"api_keys", "prompts", "prompt_versions", "experiments", "events"} <= tables
    cli.downgrade(settings, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()


def test_cli_create_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMPTLAB_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'cli.db'}")
    get_settings.cache_clear()
    try:
        assert cli.main(["migrate"]) == 0
        out = io.StringIO()
        with redirect_stdout(out):
            assert cli.main(["create-api-key", "--name", "ops", "--role", "editor"]) == 0
        assert out.getvalue().strip().startswith("pl_")
        assert cli.main(["downgrade", "base"]) == 0
    finally:
        get_settings.cache_clear()


def test_cli_serve_invokes_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(app: str, **kwargs: object) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)
    assert cli.main(["serve", "--port", "9000", "--workers", "3"]) == 0
    assert captured["app"] == "promptlab.main:build_app"
    assert captured["port"] == 9000
    assert captured["workers"] == 3
    assert captured["factory"] is True


def test_cli_requires_command() -> None:
    with pytest.raises(SystemExit):
        cli.main([])


def test_build_app() -> None:
    from promptlab.main import build_app

    app = build_app()
    assert app.title == "PromptLab"
