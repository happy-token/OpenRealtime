"""Apply pending PostgreSQL migrations as an explicit deployment step."""

import asyncio
import hashlib
import os
from pathlib import Path

import asyncpg

from server.persistence.postgres.schema import validate_schema_name


MIGRATIONS = Path(__file__).resolve().parents[1] / "server/persistence/postgres/migrations"


async def main() -> None:
    dsn = os.environ["VOICEAGENT_POSTGRES_DSN"]
    schema = validate_schema_name(os.environ.get("VOICEAGENT_POSTGRES_SCHEMA", "voiceagent"))
    connection = await asyncpg.connect(dsn)
    try:
        async with connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"openrealtime:{schema}:migrations")
            await connection.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            await connection.execute(
                f'CREATE TABLE IF NOT EXISTS "{schema}".schema_migrations '
                '(name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())'
            )
            applied = {
                row["name"]: row["sha256"]
                for row in await connection.fetch(f'SELECT name, sha256 FROM "{schema}".schema_migrations')
            }
            for path in sorted(MIGRATIONS.glob("*.sql")):
                source = path.read_text(encoding="utf-8")
                digest = hashlib.sha256(source.encode()).hexdigest()
                if path.name in applied:
                    if applied[path.name] != digest:
                        raise RuntimeError(f"migration changed after application: {path.name}")
                    continue
                await connection.execute(source.replace("__VOICEAGENT_SCHEMA__", schema))
                await connection.execute(
                    f'INSERT INTO "{schema}".schema_migrations (name, sha256) VALUES ($1, $2)',
                    path.name,
                    digest,
                )
                print(f"applied {path.name}")
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
