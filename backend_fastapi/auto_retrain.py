#!/usr/bin/env python3
"""
Optional background retrain trigger based on new-cycle volume and time interval.

This module is intentionally lightweight and can be wired into FastAPI lifespan
or used as a standalone health/trigger helper.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy import func

try:
    from .database import SessionLocal
    from .models import Cycle
except ImportError:
    from database import SessionLocal
    from models import Cycle


LOGGER = logging.getLogger("auto_retrain")


TriggerFn = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


@dataclass
class AutoRetrainConfig:
    enabled: bool = False
    check_interval_minutes: int = 30
    retrain_interval_hours: int = 6
    min_new_cycles: int = 1000


class AutoRetrainPipeline:
    def __init__(self, config: Optional[AutoRetrainConfig] = None) -> None:
        self.config = config or AutoRetrainConfig()
        self.last_retrain: datetime = datetime.now(timezone.utc)
        self.last_checked: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.last_result: Optional[Dict[str, Any]] = None
        self._task: Optional[asyncio.Task] = None

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self.config.enabled),
            "check_interval_minutes": int(self.config.check_interval_minutes),
            "retrain_interval_hours": int(self.config.retrain_interval_hours),
            "min_new_cycles": int(self.config.min_new_cycles),
            "last_retrain": self.last_retrain.isoformat() if self.last_retrain else None,
            "last_checked": self.last_checked.isoformat() if self.last_checked else None,
            "last_error": self.last_error,
            "last_result": self.last_result,
            "running": bool(self._task and not self._task.done()),
        }

    def count_new_cycles_since(self, since: datetime) -> int:
        db = SessionLocal()
        try:
            count = (
                db.query(func.count(Cycle.id))
                .filter(Cycle.timestamp >= since.replace(tzinfo=None))
                .scalar()
            )
            return int(count or 0)
        finally:
            db.close()

    def needs_retrain(self) -> bool:
        if not self.config.enabled:
            return False

        now = datetime.now(timezone.utc)
        self.last_checked = now
        elapsed = now - self.last_retrain
        if elapsed < timedelta(hours=int(self.config.retrain_interval_hours)):
            return False

        new_cycles = self.count_new_cycles_since(self.last_retrain)
        return new_cycles >= int(self.config.min_new_cycles)

    async def trigger_retrain(self, trigger_fn: TriggerFn) -> Dict[str, Any]:
        payload = {
            "machine_ids": None,
            "segment_id": None,
            "auto_promote": False,
            "source": "auto_retrain_pipeline",
        }
        result = await trigger_fn(payload)
        self.last_result = result
        self.last_retrain = datetime.now(timezone.utc)
        self.last_error = None
        LOGGER.info("Auto-retrain triggered: %s", result)
        return result

    async def loop(self, trigger_fn: TriggerFn) -> None:
        interval_seconds = max(60, int(self.config.check_interval_minutes) * 60)
        LOGGER.info(
            "AutoRetrain loop started (enabled=%s, check_interval=%ss, retrain_interval=%sh, min_new_cycles=%s)",
            self.config.enabled,
            interval_seconds,
            self.config.retrain_interval_hours,
            self.config.min_new_cycles,
        )
        while True:
            try:
                if self.needs_retrain():
                    await self.trigger_retrain(trigger_fn)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                LOGGER.exception("AutoRetrain loop error: %s", exc)
            await asyncio.sleep(interval_seconds)

    def start(self, trigger_fn: TriggerFn) -> asyncio.Task:
        if self._task and not self._task.done():
            return self._task
        self._task = asyncio.create_task(self.loop(trigger_fn))
        return self._task

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
