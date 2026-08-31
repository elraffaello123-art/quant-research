"""
vol_scan_analyze.py — apply the pre-registered decision rules to the scan output.

Implements Section 6 of docs/PREREG_VOL_SCAN.md, in order:
  1. audit() verdicts                      (already in the results file)
  2. cross-instrument agreement, >=2 of 3
  3. SEARCH-CORRECTED null: the real best PF must beat the p95 of the distribution of
     the MAXIMUM PF over the whole 312-cell search under random entries
  4. survivors -> the untouched holdout, run once

Rule 3 is the one that matters. With 312 cells, ~15 clear p<0.05 on noise alone, so a
per-cell null is worthless. This is the ORB-metalabel lesson: a selected PF of 1.274
died because the p90 of the properly-constructed null was 1.306.
"""
import sys, json
sys.path.insert(0, "toolkit")
sys.path.insert(0, "scripts")

import numpy as np
import pandas as pd

RESULTS = "scripts/vol_scan_results.json"
N_REP = 20000
SEED = 0


def load():
    df = pd.DataFrame(json.load(open(RESULTS)))
    df["key"] = df.cell + "|ks" + df.ks.astype(str) + "|kt" + df.kt.astype(str)
    return df


def max_null(df, rng):
    """One draw of 'the best cell of a 312-cell search on data with no signal':
    take one random-entry placebo PF from each cell, return the max."""
    pools = [np.asarray(p, dtype=float) for p in df.placebos if p]
    pools = [p[np.isfinite(p)] for p in pools]
    pools = [p for p in pools if len(p)]
    if not pools:
        return None
    draws = np.array([p[rng.integers(len(p))] for p in pools])
    return draws.max()


def main():
    df = load()
    ok = df[np.isfinite(df.pf.astype(float))].copy()
    print(f"cells run: {len(df)}   with a finite PF: {len(ok)}")
    print(f"audit() PASS verdicts: {(df.verdict == 'PASS').sum()}")

    print("\n--- best cells by honest PF (UNCORRECTED — not a result) ---")
    top = ok.sort_values("pf", ascending=False).head(12)
    for _, r in top.iterrows():
        print(f"  {r.inst.upper()} [{r.family}] {r.cell:34s} ks{r.ks} kt{r.kt}  "
              f"PF {r.pf:.3f}  n={r['n']:<5} {r.verdict}")

    # ---- rule 2: cross-instrument agreement -------------------------------
    print("\n--- rule 2: cross-instrument agreement (>=2 of 3, same cell+params) ---")
    agree = []
    for key, grp in ok.groupby("key"):
        good = grp[(grp.pf > 1.05) & (grp["n"] >= 100)]
        if len(good) >= 2:
            agree.append((key, len(good), sorted(good.inst.tolist()),
                          grp.set_index("inst").pf.round(3).to_dict()))
    if not agree:
        print("  NONE. No cell clears PF>1.05 with n>=100 on 2+ instruments.")
    for key, k, insts, pfs in sorted(agree, key=lambda x: -x[1]):
        print(f"  {key:52s} {k}/3 {insts}  {pfs}")

    # ---- rule 3: search-corrected null ------------------------------------
    print(f"\n--- rule 3: search-corrected null ({N_REP} reps) ---")
    rng = np.random.default_rng(SEED)
    nulls = [m for m in (max_null(ok, rng) for _ in range(N_REP)) if m is not None]
    nulls = np.array(nulls)
    best = ok.pf.max()
    p95, p99 = np.percentile(nulls, 95), np.percentile(nulls, 99)
    pval = float((nulls >= best).mean())
    print(f"  observed best PF over the search : {best:.3f}")
    print(f"  null max-PF  median {np.median(nulls):.3f}  p95 {p95:.3f}  p99 {p99:.3f}")
    print(f"  p-value (P[null max >= observed]) : {pval:.4f}")
    print(f"  VERDICT: {'BEATS the search-corrected null' if best > p95 else 'INSIDE the null — not distinguishable from noise'}")

    surv = ok[ok.pf > p95] if best > p95 else ok.iloc[0:0]
    print(f"\n  cells above the null p95: {len(surv)}")
    for _, r in surv.sort_values('pf', ascending=False).iterrows():
        print(f"    {r.inst.upper()} [{r.family}] {r.cell} ks{r.ks} kt{r.kt} PF {r.pf:.3f} n={r['n']}")

    surv.to_json("scripts/vol_scan_survivors.json", orient="records", indent=1)
    print(f"\nwrote scripts/vol_scan_survivors.json ({len(surv)})")
    if len(surv) == 0:
        print("\nNo survivors -> the holdout is NOT touched. It stays clean for the "
              "next study, which is the point of withholding it.")


if __name__ == "__main__":
    main()
