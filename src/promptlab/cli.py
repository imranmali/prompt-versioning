"""Operator command line: ``promptlab serve | migrate | downgrade | create-api-key``."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from alembic import command
from alembic.config import Config

from promptlab.config import Settings, get_settings
from promptlab.models import Role

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config(database_url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def migrate(settings: Settings, revision: str = "head") -> None:
    command.upgrade(alembic_config(settings.database_url), revision)


def downgrade(settings: Settings, revision: str) -> None:
    command.downgrade(alembic_config(settings.database_url), revision)


async def _create_api_key(settings: Settings, name: str, role: Role) -> str:
    from promptlab.db import create_engine, create_session_factory
    from promptlab.services.api_keys import create_api_key

    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            _, plaintext = await create_api_key(session, name, role)
    finally:
        await engine.dispose()
    return plaintext


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "promptlab.main:build_app",
        factory=True,
        host=args.host,
        port=args.port,
        workers=None if args.reload else args.workers,
        reload=args.reload,
        log_config=None,
        log_level=settings.log_level.lower(),
        proxy_headers=True,
        forwarded_allow_ips=args.forwarded_allow_ips,
        access_log=False,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="promptlab", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run the HTTP API server")
    serve.add_argument("--host", default="0.0.0.0")  # noqa: S104 - container default
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--workers", type=int, default=1)
    serve.add_argument("--reload", action="store_true", help="Auto-reload (development only)")
    serve.add_argument("--forwarded-allow-ips", default="127.0.0.1")

    up = sub.add_parser("migrate", help="Apply database migrations")
    up.add_argument("--revision", default="head")

    down = sub.add_parser("downgrade", help="Revert database migrations")
    down.add_argument("revision", help="Target revision, e.g. -1 or base")

    key = sub.add_parser("create-api-key", help="Create an API key and print it once")
    key.add_argument("--name", required=True)
    key.add_argument("--role", choices=[r.value for r in Role], default=Role.ADMIN.value)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    if args.command == "serve":
        _serve(args)
    elif args.command == "migrate":
        migrate(settings, args.revision)
    elif args.command == "downgrade":
        downgrade(settings, args.revision)
    elif args.command == "create-api-key":
        key = asyncio.run(_create_api_key(settings, args.name, Role(args.role)))
        sys.stdout.write(key + "\n")
    return 0
