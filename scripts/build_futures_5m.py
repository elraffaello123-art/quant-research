"""
build_futures_5m.py — gold + silver + oil 1-min parquet -> 5-min bars in harness format.

Supersedes build_metals_5m.py. Two changes:
  1. adds CL (crude oil), downloaded 2026-07-21 from Drive as a Databento DBN (`CL.v.0`,
     volume-rolled continuous) and converted to cl_1m_full.parquet.
  2. RETAINS volume as column `v`. The old script dropped it. A volatility study wants it,
     and harness.load_bars only *requires* d,m,o,h,l,c — extra columns pass straight through
     into the per-day frame your signal receives, so `v` is free to carry.

Output: data/pkl/{gc,si,cl}_5m.pkl with columns d,m,o,h,l,c,v where `m` = minutes since
midnight EASTERN, restricted to 09:30-15:55 ET (m 570..955).

Session-window note: 570..955 is the metals RTH convention inherited from mgc_5m.pkl, and
it is applied to CL as well. Oil's pit session is really 09:00-14:30 ET and its European
morning is active, so this window clips some genuine CL activity. It is kept uniform on
purpose: cross-instrument agreement is the primary filter in this study, and that argument
is only clean if all three instruments see the same clock. The EIA release (Wed 10:30 ET)
sits inside the window, which is what matters most for the catalyst family.

COVERAGE IS NOT EQUAL — do not compare across instruments without slicing to a common window:
    GC  2020-01 -> 2026-02
    SI  2020-01 -> 2026-02
    CL  2020-01 -> 2024-12   <-- 14 months shorter

Sanity: metals and oil intraday returns can explode from roll gaps and bad ticks. A single
bad print fakes a huge PF. Bars implying an absurd 5-min move are dropped and counted.

Run: python3 scripts/build_futures_5m.py
"""
import pandas as pd

SRC = {
    "si": "data/pkl/si_1m_full.parquet",
    "gc": "data/pkl/gc_1m_full.parquet",
    "cl": "data/pkl/cl_1m_full.parquet",
}

# Bad-tick threshold: a 5-min range this large is a print error, not a market.
# CL gets a much looser one. At 0.02 the filter deleted 433 bars in 2020 -- almost all
# of them 2020-04-21, the day after WTI settled negative, carrying 5.5x median volume.
# Those are the single most violent real vol event in oil's history, and silently
# dropping them from a VOLATILITY study is exactly backwards. 0.10 catches only genuine
# ticks; the 2020 regime is handled by START below, as a declared exclusion instead.
MAX_BAR_RET = {"si": 0.02, "gc": 0.02, "cl": 0.10}

# Declared sample starts. CL begins 2021-01-01 for two independent reasons:
#   1. it excludes the April-2020 negative-price structural break, where percentage
#      returns at $6 oil are not commensurable with those at $80 and the continuous
#      contract's arithmetic genuinely breaks;
#   2. 2021-01-04 is exactly where the GLD/SLV/USO options data starts, so the Phase 2
#      futures sample and the Phase 3 options-conditioned sample are the same window
#      with no additional choice made.
# Reason 2 is why this is a design decision and not a threshold tuned to help a number.
START = {"cl": "2021-01-01"}


def build(name, path, rth=True):
    df = pd.read_parquet(path)
    df.index = df.index.tz_convert("America/New_York")

    # 5-min bars, labelled to the bar's START (o is the first trade in the window)
    b = df.resample("5min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()
    b = b[b["volume"] > 0]

    b["d"] = b.index.strftime("%Y-%m-%d")
    b["m"] = b.index.hour * 60 + b.index.minute
    if rth:
        b = b[(b["m"] >= 570) & (b["m"] <= 955)]      # 09:30-15:55 ET

    b = b.rename(columns={"open": "o", "high": "h", "low": "l",
                          "close": "c", "volume": "v"})

    if rth:
        b = b[["d", "m", "o", "h", "l", "c", "v"]].reset_index(drop=True)
    else:
        # 24h build. Two things break if you just widen the filter and stop thinking:
        #
        # 1. SESSION vs CALENDAR DAY. The futures session runs 18:00 ET -> 17:00 ET, so
        #    the overnight that PRECEDES Tuesday's RTH is stamped with Monday's calendar
        #    date. Grouping by calendar date would hand a signal the overnight that comes
        #    AFTER the RTH it is supposed to predict. That is lookahead, and because it
        #    lives in the data build rather than the signal, strict=True would never see
        #    it. Bars at/after 18:00 ET are therefore rolled forward to the next day.
        #
        # 2. SORT ORDER. harness.load_bars sorts each day by `m`. With raw ET minutes,
        #    18:00 (=1080) sorts AFTER 09:30 (=570), which silently reverses the session.
        #    So `m` becomes minutes-since-18:00-ET (monotonic within a session: 18:00->0,
        #    09:30->930, 15:55->1075) and the original ET clock is preserved as `et` for
        #    any time-of-day rule that needs it.
        roll = b["m"] >= 1080
        b["d"] = pd.to_datetime(b["d"])
        b.loc[roll, "d"] += pd.Timedelta(days=1)
        b["d"] = b["d"].dt.strftime("%Y-%m-%d")
        b["et"] = b["m"]
        b["m"] = (b["m"] - 1080) % 1440
        b = b[["d", "m", "et", "o", "h", "l", "c", "v"]].reset_index(drop=True)
        b = b.sort_values(["d", "m"]).reset_index(drop=True)

    start = START.get(name)
    if start:
        n0 = len(b)
        b = b[b["d"] >= start].reset_index(drop=True)
        print(f"  declared sample start {start}: dropped {n0 - len(b):,} bars before it")

    thresh = MAX_BAR_RET[name]
    rng = (b["h"] - b["l"]) / b["c"]
    bad = rng > thresh
    if bad.any():
        print(f"  dropped {bad.sum()} bars with >{thresh:.0%} range (bad ticks/rolls)")
        b = b[~bad].reset_index(drop=True)

    bpd = b.groupby("d").size()
    print(f"  {len(b):,} bars, {b['d'].nunique()} days, "
          f"{b['d'].min()} -> {b['d'].max()}, median {bpd.median():.0f} bars/day")
    return b


if __name__ == "__main__":
    for name, path in SRC.items():
        print(f"=== {name.upper()} (24h session file)")
        full = build(name, path, rth=False)
        full.to_pickle(f"data/pkl/{name}_5m_full.pkl")
        print(f"  wrote data/pkl/{name}_5m_full.pkl")

    for name, path in SRC.items():
        print(f"=== {name.upper()} (RTH)")
        new = build(name, path)
        out = f"data/pkl/{name}_5m.pkl"

        # If a previous build exists, prove the OHLC is bar-for-bar identical before
        # overwriting. Silently shifting the bars under results that already exist is
        # how a study becomes unreproducible.
        try:
            old = pd.read_pickle(out)
        except FileNotFoundError:
            print(f"  no existing {out} — writing fresh")
        else:
            key = ["d", "m"]
            m = old.merge(new, on=key, suffixes=("_old", "_new"))
            cols = ["o", "h", "l", "c"]
            same = all((m[f"{c}_old"] == m[f"{c}_new"]).all() for c in cols)
            print(f"  vs existing: {len(old):,} old / {len(new):,} new rows, "
                  f"{len(m):,} matched on (d,m); OHLC identical: {same}")
            if not same or len(m) != len(old):
                raise SystemExit(
                    f"  REFUSING to overwrite {out}: rebuild does not reproduce the "
                    f"existing bars. Investigate before continuing."
                )

        new.to_pickle(out)
        print(f"  wrote {out}")
