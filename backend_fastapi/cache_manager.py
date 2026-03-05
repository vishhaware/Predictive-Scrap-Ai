#!/usr/bin/env python3
"""
Optional Redis-backed cache with in-memory fallback.
"""

from __future__ import annotations

import json
import os
import time
from threading import Lock
from typing import Any, Dict, Optional


class _InMemoryTTLCache:
    def __init__(self) -> None:
        self._items: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()

    def get(self, key: str) -> Optional[str]:
        now = time.time()
        with self._lock:
            item = self._items.get(key)
            if not item:
                return None
            expires_at = float(item.get("expires_at", 0.0))
            if expires_at <= now:
                self._items.pop(key, None)
                return None
            return str(item.get("value", ""))

    def setex(self, key: str, ttl_seconds: int, value: str) -> None:
        expires_at = time.time() + max(1, int(ttl_seconds))
        with self._lock:
            self._items[key] = {"value": value, "expires_at": expires_at}

    def keys(self, prefix: str) -> list[str]:
        # prefix may include '*' suffix from existing patterns.
        clean_prefix = str(prefix).rstrip("*")
        now = time.time()
        out = []
        with self._lock:
            stale = [k for k, v in self._items.items() if float(v.get("expires_at", 0.0)) <= now]
            for key in stale:
                self._items.pop(key, None)
            for key in self._items:
                if key.startswith(clean_prefix):
                    out.append(key)
        return out

    def delete(self, *keys: str) -> None:
        if not keys:
            return
        with self._lock:
            for key in keys:
                self._items.pop(key, None)

    def flushdb(self) -> None:
        with self._lock:
            self._items.clear()

    def ping(self) -> bool:
        return True


class _CacheManager:
    def __init__(self) -> None:
        self._backend = None
        self._backend_name = "memory"
        self._init_backend()

    def _init_backend(self) -> None:
        redis_enabled = str(os.getenv("REDIS_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}
        if not redis_enabled:
            self._backend = _InMemoryTTLCache()
            self._backend_name = "memory"
            return

        host = os.getenv("REDIS_HOST", "localhost")
        port = int(os.getenv("REDIS_PORT", "6379"))
        db = int(os.getenv("REDIS_DB", "0"))
        password = os.getenv("REDIS_PASSWORD")
        try:
            import redis  # type: ignore

            client = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password if password else None,
                decode_responses=True,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
            )
            client.ping()
            self._backend = client
            self._backend_name = "redis"
            return
        except Exception:
            self._backend = _InMemoryTTLCache()
            self._backend_name = "memory"

    @property
    def backend_name(self) -> str:
        return self._backend_name

    def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        if not self._backend:
            return None
        raw = self._backend.get(key)
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
            return {"value": parsed}
        except Exception:
            return None

    def set_json(self, key: str, value: Dict[str, Any], ttl_seconds: int) -> None:
        if not self._backend:
            return
        try:
            self._backend.setex(key, max(1, int(ttl_seconds)), json.dumps(value, default=str))
        except Exception:
            return

    def invalidate_machine_cache(self, machine_id: Optional[str] = None) -> None:
        if not self._backend:
            return
        try:
            if machine_id:
                pattern = f"chart_data_v2:{machine_id}:*"
                keys = self._backend.keys(pattern)
                if keys:
                    self._backend.delete(*keys)
            else:
                self._backend.flushdb()
        except Exception:
            return

    def health(self) -> Dict[str, Any]:
        if not self._backend:
            return {"backend": "none", "ok": False}
        try:
            ok = bool(self._backend.ping())
            return {"backend": self._backend_name, "ok": ok}
        except Exception:
            return {"backend": self._backend_name, "ok": False}


_CACHE = _CacheManager()


def get_chart_data_cache(cache_key: str) -> Optional[Dict[str, Any]]:
    return _CACHE.get_json(cache_key)


def set_chart_data_cache(cache_key: str, payload: Dict[str, Any], ttl_seconds: int = 300) -> None:
    _CACHE.set_json(cache_key, payload, ttl_seconds)


def invalidate_machine_cache(machine_id: Optional[str] = None) -> None:
    _CACHE.invalidate_machine_cache(machine_id=machine_id)


def cache_health() -> Dict[str, Any]:
    return _CACHE.health()
