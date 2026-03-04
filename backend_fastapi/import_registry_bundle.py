import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import joblib

try:
    from .model_registry import (
        load_registry,
        promote_model,
        register_model_bundle,
        save_registry,
    )
except ImportError:
    from model_registry import (
        load_registry,
        promote_model,
        register_model_bundle,
        save_registry,
    )


BASE_DIR = Path(__file__).resolve().parent
BUNDLES_DIR = BASE_DIR / "models" / "registry" / "bundles"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _segment_scope(machine_id: Optional[str], part_number: Optional[str]) -> str:
    if machine_id and part_number:
        return "machine+part"
    if machine_id:
        return "machine"
    return "global"


def _build_bundle_metadata(
    *,
    model_id: str,
    task: str,
    family: str,
    artifact_path: str,
    artifact_payload: Dict[str, Any],
    machine_id: Optional[str],
    part_number: Optional[str],
    segment_id: Optional[str],
) -> Dict[str, Any]:
    metrics = artifact_payload.get("metrics")
    feature_cols = artifact_payload.get("feature_cols")
    feature_spec = artifact_payload.get("feature_spec")
    feature_spec_hash = artifact_payload.get("feature_spec_hash")
    decision_threshold = artifact_payload.get("decision_threshold")

    return {
        "model_id": model_id,
        "task": task,
        "family": family,
        "machine_id": machine_id,
        "part_number": part_number,
        "segment_id": segment_id or "global",
        "segment_scope": _segment_scope(machine_id, part_number),
        "feature_cols": feature_cols if isinstance(feature_cols, list) else [],
        "feature_spec": feature_spec if isinstance(feature_spec, dict) else {},
        "feature_spec_hash": feature_spec_hash,
        "decision_threshold": float(decision_threshold) if isinstance(decision_threshold, (int, float)) else 0.5,
        "metrics": metrics if isinstance(metrics, dict) else {},
        "trained_at": artifact_payload.get("trained_at") or _now_iso(),
        "artifact_path": artifact_path,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import a Kaggle-trained registry bundle artifact and optionally promote it."
    )
    parser.add_argument("--bundle-joblib", required=True, help="Path to artifact payload .pkl/.joblib")
    parser.add_argument("--model-id", required=True, help="Model ID to register in registry.json")
    parser.add_argument("--task", default="scrap_classifier", help="Task key (default: scrap_classifier)")
    parser.add_argument("--family", default=None, help="Model family override (e.g. lightgbm)")
    parser.add_argument("--machine-id", default=None, help="Optional machine-specific registration/promotion scope")
    parser.add_argument("--part-number", default=None, help="Optional part-specific registration/promotion scope")
    parser.add_argument("--segment-id", default=None, help="Optional segment ID metadata")
    parser.add_argument(
        "--promote",
        action="store_true",
        help="Promote this model as active for the provided scope (global if no machine/part).",
    )
    args = parser.parse_args()

    bundle_src = Path(args.bundle_joblib).resolve()
    if not bundle_src.exists():
        raise FileNotFoundError(f"Bundle artifact not found: {bundle_src}")

    artifact_payload = joblib.load(bundle_src)
    if not isinstance(artifact_payload, dict):
        raise ValueError("Bundle artifact must be a dict payload.")
    if artifact_payload.get("model") is None:
        raise ValueError("Bundle artifact missing 'model'.")

    task = str(args.task).strip()
    model_id = str(args.model_id).strip()
    family = (
        str(args.family).strip()
        if args.family
        else str(artifact_payload.get("family") or "lightgbm").strip()
    )
    machine_id = str(args.machine_id).strip() if args.machine_id else None
    part_number = str(args.part_number).strip() if args.part_number else None
    segment_id = str(args.segment_id).strip() if args.segment_id else None

    BUNDLES_DIR.mkdir(parents=True, exist_ok=True)
    artifact_dst = (BUNDLES_DIR / f"{model_id}.pkl").resolve()
    if bundle_src != artifact_dst:
        joblib.dump(artifact_payload, artifact_dst)

    registry = load_registry()
    bundle_meta = _build_bundle_metadata(
        model_id=model_id,
        task=task,
        family=family,
        artifact_path=str(artifact_dst),
        artifact_payload=artifact_payload,
        machine_id=machine_id,
        part_number=part_number,
        segment_id=segment_id,
    )
    register_model_bundle(registry, task, model_id, bundle_meta)

    promote_result = None
    if args.promote:
        promote_result = promote_model(
            registry=registry,
            task=task,
            model_id=model_id,
            machine_id=machine_id,
            part_number=part_number,
        )

    save_registry(registry)

    result = {
        "ok": True,
        "registered": {
            "task": task,
            "model_id": model_id,
            "artifact_path": str(artifact_dst),
            "segment_scope": _segment_scope(machine_id, part_number),
            "machine_id": machine_id,
            "part_number": part_number,
        },
        "promoted": bool(args.promote),
        "promote_result": promote_result,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

