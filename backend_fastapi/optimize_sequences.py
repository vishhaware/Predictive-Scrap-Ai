#!/usr/bin/env python3
"""
Optimize large LSTM sequence artifacts for production usage.

Default behavior:
1) Read cleaned_data_output/lstm_sequences.json
2) Split into chunks (10k sequences each)
3) Gzip each chunk
4) Write manifest.json for API pagination/streaming
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


LOGGER = logging.getLogger("optimize_sequences")


def _default_cleaned_output_dir() -> Path:
    return Path(
        os.getenv(
            "CLEANED_DATA_OUTPUT_DIR",
            str(Path(__file__).resolve().parent.parent / "cleaned_data_output"),
        )
    )


def optimize_sequences_hybrid(
    source_path: Path,
    output_dir: Path,
    chunk_size: int = 10_000,
    compresslevel: int = 9,
) -> Dict[str, Any]:
    if not source_path.exists():
        raise FileNotFoundError(f"Missing source file: {source_path}")

    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if compresslevel < 1 or compresslevel > 9:
        raise ValueError("compresslevel must be between 1 and 9")

    output_dir.mkdir(parents=True, exist_ok=True)

    with source_path.open("r", encoding="utf-8") as f:
        all_sequences = json.load(f)

    if not isinstance(all_sequences, list):
        raise ValueError(f"Expected a JSON array of sequences in {source_path}")

    manifest: Dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_file": str(source_path),
        "total_sequences": len(all_sequences),
        "chunk_size": int(chunk_size),
        "compression": "gzip",
        "chunks": [],
    }

    total_compressed_size = 0
    for start_idx in range(0, len(all_sequences), chunk_size):
        end_idx = min(start_idx + chunk_size, len(all_sequences))
        chunk_data = all_sequences[start_idx:end_idx]
        chunk_id = start_idx // chunk_size
        chunk_file = output_dir / f"lstm_sequences_chunk_{chunk_id}.json.gz"

        with gzip.open(chunk_file, "wt", encoding="utf-8", compresslevel=compresslevel) as gz:
            json.dump(chunk_data, gz, separators=(",", ":"), ensure_ascii=False)

        size_bytes = chunk_file.stat().st_size
        total_compressed_size += size_bytes

        manifest["chunks"].append(
            {
                "chunk_id": chunk_id,
                "file": chunk_file.name,
                "sequence_count": len(chunk_data),
                "size_bytes": size_bytes,
                "size_mb": round(size_bytes / (1024 * 1024), 3),
                "sequences": {"start": start_idx, "end": end_idx - 1},
            }
        )
        LOGGER.info(
            "Chunk %s written: %s sequences, %.2f MB",
            chunk_id,
            len(chunk_data),
            size_bytes / (1024 * 1024),
        )

    source_bytes = source_path.stat().st_size
    compression_ratio = 0.0
    if source_bytes > 0:
        compression_ratio = (1.0 - (float(total_compressed_size) / float(source_bytes))) * 100.0

    manifest["summary"] = {
        "source_size_bytes": source_bytes,
        "source_size_mb": round(source_bytes / (1024 * 1024), 3),
        "compressed_total_bytes": total_compressed_size,
        "compressed_total_mb": round(total_compressed_size / (1024 * 1024), 3),
        "compression_ratio_pct": round(compression_ratio, 2),
        "chunk_count": len(manifest["chunks"]),
    }

    manifest_path = output_dir / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    LOGGER.info(
        "Optimization complete: source=%.2f MB -> compressed=%.2f MB (%.2f%% reduction), chunks=%s",
        source_bytes / (1024 * 1024),
        total_compressed_size / (1024 * 1024),
        compression_ratio,
        len(manifest["chunks"]),
    )
    LOGGER.info("Manifest: %s", manifest_path)
    return manifest


def parse_args() -> argparse.Namespace:
    cleaned_output = _default_cleaned_output_dir()
    parser = argparse.ArgumentParser(description="Optimize lstm_sequences.json into compressed chunks.")
    parser.add_argument(
        "--source",
        default=str(cleaned_output / "lstm_sequences.json"),
        help="Path to lstm_sequences.json",
    )
    parser.add_argument(
        "--output-dir",
        default=str(cleaned_output / "lstm_chunks_compressed"),
        help="Output directory for compressed chunks + manifest",
    )
    parser.add_argument("--chunk-size", type=int, default=10_000, help="Sequences per chunk.")
    parser.add_argument("--compresslevel", type=int, default=9, help="gzip level (1-9).")
    parser.add_argument("--log-level", default="INFO", help="DEBUG/INFO/WARNING/ERROR")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    optimize_sequences_hybrid(
        source_path=Path(args.source),
        output_dir=Path(args.output_dir),
        chunk_size=int(args.chunk_size),
        compresslevel=int(args.compresslevel),
    )


if __name__ == "__main__":
    main()
