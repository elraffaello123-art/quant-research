"""
verify_chains_parquet.py — prove the parquet matches the JSON before anything gets deleted.

The chains were expensive to acquire (MEGA/Drive, quota-limited). CLAUDE.md says don't delete
them without reason. So "the script said it worked" is not good enough — this re-reads the
ORIGINAL JSON and checks it against the parquet, on two levels:

  1. COUNT CHECK (complete, every file): re-parse every {date}.json straight from disk and
     count its contracts, independently of the converter's own bookkeeping. Compare to the
     parquet row count for that (ticker, snapshot_date). A single mismatch fails the run.

  2. FIELD CHECK (deep, sampled): pick N random contracts, look each one up by osiKey, and
     compare EVERY field value JSON vs parquet. Catches silent type coercion — a float
     truncated, an openInterest of 0 that was really missing.

Check 1 alone would miss corrupted values; check 2 alone would miss whole missing files.
Both must pass.

Run:  python3 scripts/verify_chains_parquet.py
Exit code 0 = safe to delete the JSON. Anything else = do not delete.
"""
import json
import random
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent / "data" / "chains"
OUT = ROOT / "parquet"

N_SAMPLE_FILES = 100     # files to deep-check field-by-field
SEED = 20260720


def count_contracts_raw(path: Path) -> int:
    """Count contracts in a JSON file WITHOUT using the converter's code.

    Deliberately independent: if parse_one() has a bug that drops an expiry, this
    still counts it and the mismatch surfaces.
    """
    with open(path) as fh:
        doc = json.load(fh)
    return sum(len(v) for k, v in doc.items() if k != "quote" and isinstance(v, list))


def verify_tree(tree: Path) -> bool:
    name = tree.name
    cpath = OUT / f"{name}_contracts.parquet"
    if not cpath.exists():
        print(f"  MISSING {cpath.name} — conversion did not finish")
        return False

    print(f"\n=== {name}")
    # Read ONLY the two key columns. The full frame is ~22M rows x 28 cols and would
    # need several GB of RAM; we don't need the values until the field check, and then
    # only for the sampled files.
    print("  loading key columns...")
    keys = pd.read_parquet(cpath, columns=["ticker", "snapshot_date"])
    got = keys.groupby(["ticker", "snapshot_date"]).size()
    del keys

    files = [(t.name, f) for t in sorted(tree.iterdir()) if t.is_dir()
             for f in sorted(t.glob("*.json"))]

    # ---- check 1: complete count comparison -------------------------------
    print(f"  count-checking all {len(files)} files against parquet...")
    bad = []
    for i, (ticker, path) in enumerate(files, 1):
        want = count_contracts_raw(path)
        have = int(got.get((ticker, path.stem), 0))
        if want != have:
            bad.append((ticker, path.stem, want, have))
        if i % 200 == 0:
            print(f"    {i}/{len(files)}", end="\r", flush=True)

    if bad:
        print(f"\n  COUNT MISMATCH on {len(bad)} file(s):")
        for t, d, want, have in bad[:10]:
            print(f"    {t}/{d}: json={want} parquet={have}")
        return False
    print(f"\n  [OK] all {len(files)} files match on contract count "
          f"({int(got.sum()):,} rows total)")

    # ---- check 2: deep field comparison on a sample ------------------------
    rng = random.Random(SEED)
    sample = rng.sample(files, min(N_SAMPLE_FILES, len(files)))
    print(f"  field-checking {len(sample)} random files, every field...")

    # Pull back only the rows belonging to the sampled snapshot dates, then narrow to the
    # exact (ticker, date) pairs. Keeps this to a few hundred MB instead of the whole tree.
    want_dates = sorted({p.stem for _t, p in sample})
    want_pairs = {(t, p.stem) for t, p in sample}
    df = pd.read_parquet(cpath, filters=[("snapshot_date", "in", want_dates)])
    df = df[[(t, d) in want_pairs
             for t, d in zip(df["ticker"], df["snapshot_date"])]]
    idx = df.set_index(["ticker", "snapshot_date", "osiKey"])
    mismatches = []
    checked = 0

    for ticker, path in sample:
        with open(path) as fh:
            doc = json.load(fh)
        for key, val in doc.items():
            if key == "quote" or not isinstance(val, list):
                continue
            for c in val:
                osi = c.get("osiKey")
                if osi is None:
                    continue
                try:
                    row = idx.loc[(ticker, path.stem, osi)]
                except KeyError:
                    mismatches.append((ticker, path.stem, osi, "osiKey", "present", "MISSING"))
                    continue
                if isinstance(row, pd.DataFrame):   # duplicate osiKey, take first
                    row = row.iloc[0]

                greeks = c.get("OptionGreeks") or {}
                for field, want in list(c.items()) + list(greeks.items()):
                    if field in ("OptionGreeks", "quoteDetail"):
                        continue  # quoteDetail is intentionally dropped (derived URL)
                    if field not in row.index:
                        continue
                    have = row[field]
                    if pd.isna(have) and want is None:
                        continue
                    # numbers compare numerically, everything else as strings
                    if isinstance(want, (int, float)) and not isinstance(want, bool):
                        if pd.isna(have) or float(want) != float(have):
                            mismatches.append((ticker, path.stem, osi, field, want, have))
                    else:
                        if str(want) != str(have):
                            mismatches.append((ticker, path.stem, osi, field, want, have))
                checked += 1

    if mismatches:
        print(f"  FIELD MISMATCH: {len(mismatches)} of {checked:,} contracts")
        for m in mismatches[:15]:
            print(f"    {m[0]}/{m[1]} {m[2]} .{m[3]}: json={m[4]!r} parquet={m[5]!r}")
        return False

    print(f"  [OK] {checked:,} contracts match field-for-field")
    return True


def main():
    trees = [d for d in sorted(ROOT.iterdir())
             if d.is_dir() and d.name != "parquet"]
    ok = all(verify_tree(t) for t in trees)

    print("\n" + "=" * 64)
    if ok:
        json_mb = sum(f.stat().st_size for t in trees for f in t.rglob("*.json")) / 1e6
        pq_mb = sum(f.stat().st_size for f in OUT.glob("*.parquet")) / 1e6
        print(f"  ALL CHECKS PASS")
        print(f"  JSON    {json_mb/1000:6.1f} GB")
        print(f"  parquet {pq_mb/1000:6.1f} GB   ({json_mb/pq_mb:.0f}x smaller)")
        print(f"  deleting the JSON would free ~{json_mb/1000:.1f} GB")
        print("  -> safe to delete, but Igor confirms the delete explicitly.")
    else:
        print("  VERIFICATION FAILED — DO NOT DELETE THE JSON.")
    print("=" * 64)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
