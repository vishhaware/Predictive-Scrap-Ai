#!/usr/bin/env python3
"""
Create additional database indexes for chart-data and ingestion performance.
"""

from __future__ import annotations

import logging
from typing import List, Tuple

from sqlalchemy import text

try:
    from .database import engine, IS_SQLITE
except ImportError:
    from database import engine, IS_SQLITE


LOGGER = logging.getLogger("create_database_indexes")


def _sqlite_statements() -> List[Tuple[str, str]]:
    return [
        (
            "idx_machine_timestamp",
            "CREATE INDEX IF NOT EXISTS idx_machine_timestamp ON cycles(machine_id, timestamp)",
        ),
        (
            "idx_machine_timestamp_id",
            "CREATE INDEX IF NOT EXISTS idx_machine_timestamp_id ON cycles(machine_id, timestamp, id)",
        ),
        (
            "idx_machine_part_ts_json",
            "CREATE INDEX IF NOT EXISTS idx_machine_part_ts_json "
            "ON cycles(machine_id, json_extract(data, '$.part_number'), timestamp)",
        ),
        (
            "idx_predictions_cycle",
            "CREATE INDEX IF NOT EXISTS idx_predictions_cycle ON predictions(cycle_id)",
        ),
        (
            "idx_stats_machine",
            "CREATE INDEX IF NOT EXISTS idx_stats_machine ON machine_stats(machine_id)",
        ),
    ]


def _postgres_statements() -> List[Tuple[str, str]]:
    return [
        (
            "idx_machine_timestamp",
            "CREATE INDEX IF NOT EXISTS idx_machine_timestamp ON cycles(machine_id, timestamp)",
        ),
        (
            "idx_machine_timestamp_id",
            "CREATE INDEX IF NOT EXISTS idx_machine_timestamp_id ON cycles(machine_id, timestamp, id)",
        ),
        (
            "idx_machine_part_ts_json",
            "CREATE INDEX IF NOT EXISTS idx_machine_part_ts_json "
            "ON cycles(machine_id, ((data ->> 'part_number')), timestamp)",
        ),
        (
            "idx_predictions_cycle",
            "CREATE INDEX IF NOT EXISTS idx_predictions_cycle ON predictions(cycle_id)",
        ),
        (
            "idx_stats_machine",
            "CREATE INDEX IF NOT EXISTS idx_stats_machine ON machine_stats(machine_id)",
        ),
    ]


def create_database_indexes() -> dict:
    statements = _sqlite_statements() if IS_SQLITE else _postgres_statements()
    created = []
    failed = []

    with engine.begin() as conn:
        for name, sql_stmt in statements:
            try:
                conn.execute(text(sql_stmt))
                created.append(name)
                LOGGER.info("Index ensured: %s", name)
            except Exception as exc:
                failed.append({"name": name, "error": str(exc)})
                LOGGER.warning("Index failed: %s (%s)", name, exc)

    return {
        "ok": len(failed) == 0,
        "dialect": "sqlite" if IS_SQLITE else "postgresql",
        "created_or_verified": created,
        "failed": failed,
    }


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    result = create_database_indexes()
    LOGGER.info("Index creation result: %s", result)


if __name__ == "__main__":
    main()
