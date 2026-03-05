#!/usr/bin/env python3
"""
Split lstm_sequences.json into plain JSON chunks + manifest.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


LOGGER = logging.getLogger("chunk_sequences")


def _default_paths() -> tuple[Path, Path]:
    cleaned_output = Path(
        os.getenv(
            "CLEANED_DATA_OUTPUT_DIR",
            str(Path(__file__).resolve().parent.parent / "cleaned_data_output"),
        )
    )
    return cleaned_output / "lstm_sequences.json", cleaned_output / "lstm_chunks"


def chunk_lstm_sequences(source: Path, output_dir: Path, chunk_size: int = 10_000) -> Dict[str, Any]:
    if not source.exists():
        raise FileNotFoundError(f"Missing source file: {source}")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")

    output_dir.mkdir(parents=True, exist_ok=True)

    with source.open("r", encoding="utf-8") as f:
        all_sequences = json.load(f)
    if not isinstance(all_sequences, list):
        raise ValueError(f"Expected list in {source}")

    manifest: Dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_file": str(source),
        "total_sequences": len(all_sequences),
        "chunk_size": int(chunk_size),
        "compression": None,
        "chunks": [],
    }

    for start_idx in range(0, len(all_sequences), chunk_size):
        end_idx = min(start_idx + chunk_size, len(all_sequences))
        chunk_data = all_sequences[start_idx:end_idx]
        chunk_id = start_idx // chunk_size
        file_path = output_dir / f"lstm_sequences_chunk_{chunk_id}.json"
        with file_path.open("w", encoding="utf-8") as f:
            json.dump(chunk_data, f)

        manifest["chunks"].append(
            {
                "chunk_id": chunk_id,
                "file": file_path.name,
                "sequence_count": len(chunk_data),
                "size_bytes": file_path.stat().st_size,
                "sequences": {"start": start_idx, "end": end_idx - 1},
            }
        )
        LOGGER.info("Chunk %s written: %s sequences", chunk_id, len(chunk_data))

    manifest_path = output_dir / "lstm_sequences_manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    LOGGER.info("Manifest written: %s", manifest_path)
    return manifest


def parse_args() -> argparse.Namespace:
    default_source, default_output = _default_paths()
    parser = argparse.ArgumentParser(description="Chunk lstm_sequences.json into multiple JSON files.")
    parser.add_argument("--source", default=str(default_source), help="Path to lstm_sequences.json")
    parser.add_argument("--output-dir", default=str(default_output), help="Output chunk directory")
    parser.add_argument("--chunk-size", type=int, default=10_000, help="Sequences per chunk")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    chunk_lstm_sequences(
        source=Path(args.source),
        output_dir=Path(args.output_dir),
        chunk_size=int(args.chunk_size),
    )


if __name__ == "__main__":
    main()
