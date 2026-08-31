"""
build_gld_option_features.py — GLD EOD chains -> daily options features for gold.

WHY GLD FOR A GOLD FUTURES STRATEGY: GLD is the liquid options market on gold. There is no
retail-accessible options chain on GC. Dealer positioning in GLD is the best available read
on who has to hedge what in the metal.

*** THE CAUSALITY RULE (do not weaken this) ***
The E*TRADE snapshots are inconsistently timed. Checked 2026-07-20: of 795 GLD files, 737
carry a quote timestamp from the PRIOR evening but 58 (7.3%) are stamped AFTER THEIR OWN
DAY'S CLOSE (e.g. file 2021-01-05 holds a quote from 01-05 16:10 EST).

So a file dated D is NOT safely usable on day D. Every feature here is joined to trading
day T using the latest snapshot STRICTLY BEFORE T. That guarantees the information existed
before T's open, on every day, without having to trust the timestamp.

7% contamination is far more than enough to manufacture an edge, and those days are not
randomly distributed. This is LEAK_CHECKLIST #6 — check the timestamp of every input.

Output: data/pkl/gld_opt_daily.pkl, indexed by snapshot_date, to be joined causally.

Run: python3 scripts/build_gld_option_features.py
"""
import numpy as np
import pandas as pd

TREES = [
    "data/chains/parquet/historical_multiexpiry_2021_2024_contracts.parquet",
    "data/chains/parquet/recent_frontexpiry_2025_2026_contracts.parquet",
]
TICKER = "GLD"
MIN_DTE, MAX_DTE = 7, 45      # skip 0DTE noise; front-ish expiry where dealer gamma lives
FAR_DTE = 90                  # for the term-structure slope


def load_chains():
    parts = []
    for p in TREES:
        df = pd.read_parquet(
            p,
            columns=["ticker", "snapshot_date", "expiry", "optionType", "strikePrice",
                     "openInterest", "volume", "gamma", "delta", "iv", "bid", "ask"],
            filters=[("ticker", "=", TICKER)],
        )
        parts.append(df)
    df = pd.concat(parts, ignore_index=True)
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
    df["expiry"] = pd.to_datetime(df["expiry"])
    df["dte"] = (df["expiry"] - df["snapshot_date"]).dt.days
    # a contract with no bid is not a real price; its iv is noise
    df = df[(df["iv"] > 0.01) & (df["iv"] < 3.0) & (df["ask"] > 0)]
    return df


def spot_from_quotes():
    """Underlying price per snapshot, from the quote block."""
    qs = []
    for p in ["data/chains/parquet/historical_multiexpiry_2021_2024_quotes.parquet",
              "data/chains/parquet/recent_frontexpiry_2025_2026_quotes.parquet"]:
        q = pd.read_parquet(p)
        q = q[q["ticker"] == TICKER][["snapshot_date", "lastTrade"]]
        qs.append(q)
    q = pd.concat(qs, ignore_index=True)
    q["snapshot_date"] = pd.to_datetime(q["snapshot_date"])
    return q.rename(columns={"lastTrade": "spot"}).drop_duplicates("snapshot_date")


def features_for_day(g, spot):
    """One snapshot -> one row of features. All of it is same-snapshot data; the
    CAUSAL part is handled by the join, not here."""
    front = g[(g["dte"] >= MIN_DTE) & (g["dte"] <= MAX_DTE)]
    if len(front) < 20 or not np.isfinite(spot):
        return None

    calls, puts = front[front["optionType"] == "CALL"], front[front["optionType"] == "PUT"]
    if len(calls) < 5 or len(puts) < 5:
        return None

    out = {"spot": spot}

    # --- ATM implied vol: contracts nearest the money -------------------
    front = front.assign(moneyness=(front["strikePrice"] / spot - 1).abs())
    atm = front.nsmallest(6, "moneyness")
    out["atm_iv"] = atm["iv"].mean()

    # --- 25-delta risk reversal = the skew ------------------------------
    # put delta is negative; find the contracts closest to +/-0.25
    p25 = puts.iloc[(puts["delta"] + 0.25).abs().argsort()[:3]]
    c25 = calls.iloc[(calls["delta"] - 0.25).abs().argsort()[:3]]
    out["skew25"] = p25["iv"].mean() - c25["iv"].mean()

    # --- positioning ----------------------------------------------------
    coi, poi = calls["openInterest"].sum(), puts["openInterest"].sum()
    out["pc_oi"] = poi / coi if coi > 0 else np.nan
    out["total_oi"] = coi + poi
    cvol, pvol = calls["volume"].sum(), puts["volume"].sum()
    out["pc_vol"] = pvol / cvol if cvol > 0 else np.nan

    # --- dealer gamma proxy: dealers long calls / short puts ------------
    # scale-free (tilt), so it's comparable across time and price levels
    cg = (calls["gamma"] * calls["openInterest"]).sum()
    pg = (puts["gamma"] * puts["openInterest"]).sum()
    out["gamma_tilt"] = (cg - pg) / (cg + pg) if (cg + pg) > 0 else np.nan

    # --- term structure: far IV minus front IV --------------------------
    far = g[(g["dte"] > MAX_DTE) & (g["dte"] <= FAR_DTE * 2)]
    if len(far) > 10:
        far = far.assign(moneyness=(far["strikePrice"] / spot - 1).abs())
        out["term_slope"] = far.nsmallest(6, "moneyness")["iv"].mean() - out["atm_iv"]
    else:
        out["term_slope"] = np.nan

    return out


def main():
    df = load_chains()
    spots = spot_from_quotes().set_index("snapshot_date")["spot"]
    print(f"{TICKER}: {df['snapshot_date'].nunique()} snapshots, {len(df):,} contracts")

    rows = {}
    for d, g in df.groupby("snapshot_date"):
        f = features_for_day(g, spots.get(d, np.nan))
        if f:
            rows[d] = f

    out = pd.DataFrame(rows).T.sort_index()
    out.index.name = "snapshot_date"

    # changes — the LEVEL of skew and its CHANGE are different signals
    for c in ["atm_iv", "skew25", "pc_oi", "gamma_tilt", "term_slope"]:
        out[f"d1_{c}"] = out[c].diff()
        out[f"d5_{c}"] = out[c].diff(5)
    # where does today's level sit in its own recent history? (scale-free regime read)
    for c in ["atm_iv", "skew25", "gamma_tilt"]:
        out[f"z60_{c}"] = ((out[c] - out[c].rolling(60).mean())
                           / out[c].rolling(60).std())

    out.to_pickle("data/pkl/gld_opt_daily.pkl")
    print(f"-> data/pkl/gld_opt_daily.pkl: {len(out)} days, {out.shape[1]} features")
    print(f"   {out.index.min().date()} -> {out.index.max().date()}")
    print(out[["atm_iv", "skew25", "pc_oi", "gamma_tilt", "term_slope"]].describe().to_string())


if __name__ == "__main__":
    main()
