import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


REGISTRY_DIR = os.path.join(os.path.dirname(__file__), "models", "registry")
REGISTRY_PATH = os.path.join(REGISTRY_DIR, "registry.json")
REGISTRY_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _segment_key(machine_id: Optional[str], part_number: Optional[str]) -> str:
    if machine_id and part_number:
        return f"machine_part:{machine_id}|{part_number}"
    if machine_id:
        return f"machine:{machine_id}"
    return "global"


def _empty_registry() -> Dict[str, Any]:
    return {
        "version": 1,
        "updated_at": _now_iso(),
        "tasks": {
            "scrap_classifier": {
                "active": {},
                "history": {},
            },
            "sensor_forecaster": {
                "active": {},
                "history": {},
            },
        },
        "models": {},
    }


def ensure_registry() -> Dict[str, Any]:
    with REGISTRY_LOCK:
        if os.path.exists(REGISTRY_PATH):
            with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        os.makedirs(REGISTRY_DIR, exist_ok=True)
        reg = _empty_registry()
        with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(reg, f, indent=2)
        return reg


def load_registry() -> Dict[str, Any]:
    return ensure_registry()


def save_registry(registry: Dict[str, Any]) -> None:
    with REGISTRY_LOCK:
        os.makedirs(REGISTRY_DIR, exist_ok=True)
        registry["updated_at"] = _now_iso()
        with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2)


def resolve_active_model_id(
    registry: Dict[str, Any],
    task: str,
    machine_id: Optional[str],
    part_number: Optional[str],
) -> Tuple[Optional[str], str]:
    task_info = (registry.get("tasks") or {}).get(task) or {}
    active = task_info.get("active") or {}
    candidates = [
        (_segment_key(machine_id, part_number), "machine+part"),
        (_segment_key(machine_id, None), "machine"),
        ("global", "global"),
    ]
    for seg, scope in candidates:
        model_id = active.get(seg)
        if model_id:
            return str(model_id), scope
    return None, "none"


def get_model_bundle(registry: Dict[str, Any], model_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not model_id:
        return None
    model_info = (registry.get("models") or {}).get(model_id)
    if isinstance(model_info, dict):
        return model_info
    return None


def register_model_bundle(
    registry: Dict[str, Any],
    task: str,
    model_id: str,
    bundle: Dict[str, Any],
) -> None:
    registry.setdefault("models", {})[model_id] = bundle
    registry.setdefault("tasks", {}).setdefault(task, {"active": {}, "history": {}})


def promote_model(
    registry: Dict[str, Any],
    task: str,
    model_id: str,
    machine_id: Optional[str] = None,
    part_number: Optional[str] = None,
) -> Dict[str, Any]:
    if model_id not in (registry.get("models") or {}):
        raise ValueError(f"Unknown model_id: {model_id}")
    task_info = registry.setdefault("tasks", {}).setdefault(task, {"active": {}, "history": {}})
    segment = _segment_key(machine_id, part_number)
    active = task_info.setdefault("active", {})
    history = task_info.setdefault("history", {})
    prev = active.get(segment)
    if prev:
        history.setdefault(segment, []).append(
            {
                "model_id": prev,
                "switched_at": _now_iso(),
                "reason": "promote",
            }
        )
    active[segment] = model_id
    return {"segment": segment, "previous_model_id": prev, "active_model_id": model_id}


def rollback_model(
    registry: Dict[str, Any],
    task: str,
    machine_id: Optional[str] = None,
    part_number: Optional[str] = None,
) -> Dict[str, Any]:
    task_info = registry.setdefault("tasks", {}).setdefault(task, {"active": {}, "history": {}})
    segment = _segment_key(machine_id, part_number)
    history = task_info.setdefault("history", {})
    segment_history: List[Dict[str, Any]] = history.get(segment) or []
    if not segment_history:
        raise ValueError(f"No rollback history for task={task}, segment={segment}")
    prev = segment_history.pop()
    prev_model = prev.get("model_id")
    if not prev_model:
        raise ValueError(f"Invalid rollback history for task={task}, segment={segment}")
    task_info.setdefault("active", {})[segment] = prev_model
    return {"segment": segment, "active_model_id": prev_model}

