#!/usr/bin/env python3
"""
Populate prediction_accuracy table from historical cycles + predictions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import joinedload

try:
    from .database import SessionLocal, init_db
    from .models import Cycle, PredictionAccuracy
except ImportError:
    from database import SessionLocal, init_db
    from models import Cycle, PredictionAccuracy


MODEL_ID = "lightgbm_v1"
BATCH_SIZE = 1000


def _safe_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except Exception:
        return None
    return out


def _extract_counter(data: Dict[str, Any], *keys: str) -> Optional[float]:
    if not isinstance(data, dict):
        return None
    for key in keys:
        if key in data:
            value = _safe_float(data.get(key))
            if value is not None:
                return value
    return None


def populate_prediction_accuracy(model_id: str = MODEL_ID) -> Dict[str, int]:
    init_db()
    db = SessionLocal()
    inserted = 0
    skipped = 0
    processed = 0

    try:
        machine_rows = db.query(Cycle.machine_id).distinct().all()
        machine_ids = [str(row[0]) for row in machine_rows if row and row[0]]

        for machine_id in machine_ids:
            existing_cycle_ids = {
                int(cid)
                for (cid,) in (
                    db.query(PredictionAccuracy.cycle_id)
                    .filter(
                        PredictionAccuracy.machine_id == machine_id,
                        PredictionAccuracy.model_id == model_id,
                    )
                    .all()
                )
            }

            cycles = (
                db.query(Cycle)
                .options(joinedload(Cycle.prediction))
                .filter(Cycle.machine_id == machine_id)
                .order_by(Cycle.timestamp.asc(), Cycle.id.asc())
                .all()
            )

            pending = []
            prev_scrap_counter: Optional[float] = None
            prev_shot_counter: Optional[float] = None

            for cycle in cycles:
                if not cycle.prediction:
                    continue
                processed += 1

                if int(cycle.id) in existing_cycle_ids:
                    skipped += 1
                    continue

                data = cycle.data or {}
                # Prefer explicit per-cycle increments if present.
                scrap_inc = _extract_counter(data, "scrap_inc")
                shot_inc = _extract_counter(data, "shot_inc")

                if scrap_inc is None:
                    scrap_counter = _extract_counter(data, "scrap_counter", "Scrap_counter")
                    if scrap_counter is not None and prev_scrap_counter is not None:
                        scrap_inc = scrap_counter - prev_scrap_counter
                        if scrap_inc < 0:
                            scrap_inc = scrap_counter
                    elif scrap_counter is not None:
                        scrap_inc = scrap_counter
                    else:
                        scrap_inc = 0.0
                if shot_inc is None:
                    shot_counter = _extract_counter(data, "shot_counter", "Shot_counter")
                    if shot_counter is not None and prev_shot_counter is not None:
                        shot_inc = shot_counter - prev_shot_counter
                        if shot_inc < 0:
                            shot_inc = shot_counter
                    elif shot_counter is not None:
                        shot_inc = shot_counter
                    else:
                        shot_inc = 1.0

                scrap_inc = max(0.0, float(scrap_inc or 0.0))
                shot_inc = max(0.0, float(shot_inc or 0.0))
                actual_scrap_event = 1 if scrap_inc > 0 else 0

                predicted_prob = _safe_float(cycle.prediction.scrap_probability)
                if predicted_prob is None:
                    predicted_prob = 0.0

                pending.append(
                    PredictionAccuracy(
                        cycle_id=int(cycle.id),
                        machine_id=machine_id,
                        model_id=model_id,
                        predicted_scrap_probability=max(0.0, min(float(predicted_prob), 1.0)),
                        actual_scrap_event=actual_scrap_event,
                        evaluation_window="cycle",
                        evaluated_at=datetime.now(timezone.utc),
                    )
                )

                # update running cumulative references
                latest_scrap_counter = _extract_counter(data, "scrap_counter", "Scrap_counter")
                latest_shot_counter = _extract_counter(data, "shot_counter", "Shot_counter")
                if latest_scrap_counter is not None:
                    prev_scrap_counter = latest_scrap_counter
                if latest_shot_counter is not None:
                    prev_shot_counter = latest_shot_counter

                if len(pending) >= BATCH_SIZE:
                    db.bulk_save_objects(pending)
                    db.commit()
                    inserted += len(pending)
                    pending.clear()

            if pending:
                db.bulk_save_objects(pending)
                db.commit()
                inserted += len(pending)

        return {"processed": processed, "inserted": inserted, "skipped": skipped}
    finally:
        db.close()


def main() -> None:
    result = populate_prediction_accuracy()
    print("populate_prediction_accuracy complete")
    print(f"  processed: {result['processed']}")
    print(f"  inserted: {result['inserted']}")
    print(f"  skipped: {result['skipped']}")


if __name__ == "__main__":
    main()
