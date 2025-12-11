# Quick helper script to debug statement parsing issues locally.
# Usage:
#   python debug_statement.py path/to/statement.xlsx
#   (run from repo root with the venv activated)

from __future__ import annotations

import argparse
import io
import traceback
from pathlib import Path

import pandas as pd

from backend.services import statement_reader as sr


def preview_raw(ext: str, file_bytes: bytes) -> pd.DataFrame:
    """
    Try to read the raw file without any cleaning so you can inspect headers/rows.
    """
    buffer = io.BytesIO(file_bytes)
    if ext == ".csv":
        return pd.read_csv(buffer)
    if ext in {".xlsx", ".xls"}:
        # Read a small sample with no header inference to catch odd structures
        return pd.read_excel(buffer, header=None, nrows=30)
    return pd.DataFrame()


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug statement parsing.")
    parser.add_argument("file", type=Path, help="Path to statement file (csv/xlsx/xls/pdf)")
    args = parser.parse_args()

    path = args.file
    ext = path.suffix.lower()
    if not path.exists():
        raise SystemExit(f"File not found: {path}")

    file_bytes = path.read_bytes()
    print(f"Loaded file: {path} ({ext}), size={len(file_bytes)} bytes")

    # Show raw data glimpse
    try:
        raw_df = preview_raw(ext, file_bytes)
        if not raw_df.empty:
            print("\nRaw preview (first 5 rows):")
            print(raw_df.head())
            print("\nRaw columns:")
            print(list(raw_df.columns))
    except Exception as e:
        print("\nRaw preview failed:")
        traceback.print_exc()

    # Try full pipeline
    try:
        df = sr.load_statement_from_upload(path.name, file_bytes)
        print("\nParsed dataframe (first 10 rows):")
        print(df.head(10))
        print("\nParsed columns:")
        print(list(df.columns))
    except Exception:
        print("\nFull parser raised an exception:")
        traceback.print_exc()


if __name__ == "__main__":
    main()
