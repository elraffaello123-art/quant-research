"""
chains_to_parquet.py — shrink data/chains/ from 22 GB of JSON to ~1 GB of parquet.

WHY: each JSON file repeats every field NAME as text on every contract ("openInterest",
"strikePrice", ... x 31 million contracts). Parquet stores each field once as a column of
numbers. Same data, ~20-40x smaller.

WHAT IT KEEPS: every field, at full float64 precision, so the round-trip is exact.
The ONE exception is `quoteDetail`, a per-contract E*TRADE API URL that is purely derived
from symbol/expiry/type/strike. It is unique per row (so it compresses terribly) and carries
no information. Everything else survives.

OUTPUT (per source tree):
  <tree>_contracts.parquet   one row per contract per snapshot date
  <tree>_quotes.parquet      one row per snapshot date (the underlying's quote block)

This script only WRITES new files. It never deletes the JSON — that is a separate,
explicit step after verify_chains_parquet.py confirms parity.

Run:  python3 scripts/chains_to_parquet.py
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent / "data" / "chains"
OUT = ROOT / "parquet"

# Fields we pull off each contract dict. Order matters only for readability.
CONTRACT_FIELDS = [
    "optionCategory", "optionRootSymbol", "timeStamp", "adjustedFlag",
    "displaySymbol", "optionType", "strikePrice", "symbol",
    "bid", "ask", "bidSize", "askSize", "inTheMoney",
    "volume", "openInterest", "netChange", "lastPrice", "osiKey",
]
GREEK_FIELDS = ["rho", "vega", "theta", "delta", "gamma", "iv", "currentValue"]

# Written as float64 so the parquet round-trips bit-for-bit against the JSON.
FLOAT_COLS = ["strikePrice", "bid", "ask", "netChange", "lastPrice",
              "rho", "vega", "theta", "delta", "gamma", "iv"]
INT_COLS = ["timeStamp", "bidSize", "askSize", "volume", "openInterest"]

# How many JSON files to hold in memory before flushing a parquet row-group.
# Keeps peak RAM to a few hundred MB regardless of how big the tree is.
BATCH_FILES = 100


def parse_one(path: Path, ticker: str):
    """Read one {date}.json -> (contract rows, quote row or None).

    Top-level keys are expiry dates ('2021-01-08', ...) plus, in the historical tree,
    a 'quote' block holding the UNDERLYING's price at snapshot time.
    """
    with open(path) as fh:
        doc = json.load(fh)

    snapshot_date = path.stem  # filename is the snapshot date
    rows = []
    quote_row = None

    for key, val in doc.items():
        if key == "quote":
            # Underlying quote — flatten as-is, plus identifiers.
            if isinstance(val, dict):
                quote_row = {"ticker": ticker, "snapshot_date": snapshot_date, **val}
            continue

        # Everything else is an expiry date mapping to a list of contracts.
        if not isinstance(val, list):
            continue
        for c in val:
            row = {"ticker": ticker, "snapshot_date": snapshot_date, "expiry": key}
            for f in CONTRACT_FIELDS:
                row[f] = c.get(f)
            # NOTE: iv lives INSIDE OptionGreeks, not at the top level. Classic gotcha.
            greeks = c.get("OptionGreeks") or {}
            for f in GREEK_FIELDS:
                row[f] = greeks.get(f)
            rows.append(row)

    return rows, quote_row


def to_table(rows):
    """Rows -> a typed DataFrame. Explicit dtypes so parquet doesn't guess."""
    df = pd.DataFrame(rows)
    for c in FLOAT_COLS:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    for c in INT_COLS:
        if c in df:
            # Int64 (nullable) — a missing openInterest must stay missing, not become 0.
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    return df


def convert_tree(tree: Path):
    """Convert one source tree (e.g. historical_multiexpiry_2021_2024)."""
    OUT.mkdir(parents=True, exist_ok=True)
    contracts_path = OUT / f"{tree.name}_contracts.parquet"
    quotes_path = OUT / f"{tree.name}_quotes.parquet"

    tickers = sorted(d for d in tree.iterdir() if d.is_dir())
    files = [(t.name, f) for t in tickers for f in sorted(t.glob("*.json"))]
    print(f"\n=== {tree.name}: {len(files)} files across {len(tickers)} tickers")

    writer = None
    quote_rows = []
    # Per-file contract counts — the ground truth the verifier checks against.
    counts = {}
    buf = []
    done = 0

    for ticker, path in files:
        rows, qrow = parse_one(path, ticker)
        counts[f"{ticker}/{path.stem}"] = len(rows)
        buf.extend(rows)
        if qrow:
            quote_rows.append(qrow)
        done += 1

        if done % BATCH_FILES == 0 or done == len(files):
            if buf:
                df = to_table(buf)
                table = pa.Table.from_pandas(df, preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(contracts_path, table.schema,
                                              compression="zstd")
                else:
                    # Align to the established schema — later batches can be missing a
                    # column if a ticker never populated it.
                    table = table.select(writer.schema.names)
                writer.write_table(table)
                buf = []
            pct = 100 * done / len(files)
            print(f"  {done}/{len(files)} files ({pct:.0f}%)", end="\r", flush=True)

    if writer:
        writer.close()

    if quote_rows:
        pd.DataFrame(quote_rows).to_parquet(quotes_path, compression="zstd", index=False)

    # Save the per-file counts so verification is independent of this run's memory.
    pd.Series(counts).to_frame("n_contracts").to_parquet(
        OUT / f"{tree.name}_counts.parquet")

    total = sum(counts.values())
    size_mb = contracts_path.stat().st_size / 1e6
    print(f"\n  -> {contracts_path.name}: {total:,} rows, {size_mb:.0f} MB")
    if quote_rows:
        print(f"  -> {quotes_path.name}: {len(quote_rows):,} rows")
    return total


def main():
    trees = [d for d in sorted(ROOT.iterdir())
             if d.is_dir() and d.name != "parquet"]
    if not trees:
        sys.exit(f"no chain trees found under {ROOT}")
    grand = 0
    for tree in trees:
        grand += convert_tree(tree)
    print(f"\nTOTAL {grand:,} contract rows written to {OUT}")
    print("JSON is untouched. Run scripts/verify_chains_parquet.py before deleting anything.")


if __name__ == "__main__":
    main()
