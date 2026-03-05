#!/usr/bin/env python3
"""
Compress lstm_sequences.json into lstm_sequences.json.gz.
"""

from __future__ import annotations

import argparse
import gzip
import logging
import os
from pathlib import Path


LOGGER = logging.getLogger("compress_sequences")


def _default_source() -> Path:
    cleaned_output = Path(
        os.getenv(
            "CLEANED_DATA_OUTPUT_DIR",
            str(Path(__file__).resolve().parent.parent / "cleaned_data_output"),
        )
    )
    return cleaned_output / "lstm_sequences.json"


def compress_lstm_sequences(source: Path, destination: Path, compresslevel: int = 9) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Missing source file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    with source.open("rb") as src, gzip.open(destination, "wb", compresslevel=compresslevel) as dst:
        dst.writelines(src)

    original_size = source.stat().st_size
    compressed_size = destination.stat().st_size
    ratio = 0.0
    if original_size > 0:
        ratio = (1.0 - (float(compressed_size) / float(original_size))) * 100.0

    LOGGER.info("Original: %.2f MB", original_size / (1024 * 1024))
    LOGGER.info("Compressed: %.2f MB", compressed_size / (1024 * 1024))
    LOGGER.info("Reduction: %.2f%%", ratio)
    LOGGER.info("Output: %s", destination)


def parse_args() -> argparse.Namespace:
    source = _default_source()
    parser = argparse.ArgumentParser(description="Compress lstm_sequences.json into gzip.")
    parser.add_argument("--source", default=str(source), help="Path to lstm_sequences.json")
    parser.add_argument(
        "--destination",
        default=str(source.with_suffix(source.suffix + ".gz")),
        help="Output .json.gz path",
    )
    parser.add_argument("--compresslevel", type=int, default=9, help="gzip level (1-9)")
    parser.add_argument("--log-level", default="INFO", help="DEBUG/INFO/WARNING/ERROR")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    compress_lstm_sequences(
        source=Path(args.source),
        destination=Path(args.destination),
        compresslevel=max(1, min(int(args.compresslevel), 9)),
    )


if __name__ == "__main__":
    main()
