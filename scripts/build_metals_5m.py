"""
build_metals_5m.py — silver + gold 1-min parquet -> 5-min bars in harness format.

Source: si_1m_full.parquet / gc_1m_full.parquet (Databento-style, UTC DatetimeIndex,
2020-01 onward, full electronic session).

Output: data/pkl/{si,gc}_5m.pkl with columns d,m,o,h,l,c where `m` = minutes since
midnight EASTERN, restricted to RTH 09:30-15:55 (m 570..955) — the SAME convention as
the existing mgc_5m.pkl, so results are comparable across the metals.

(Note for anyone merging with NQ later: nq_5m_all.pkl uses CENTRAL minutes, not Eastern.
Two conventions live in data/pkl/. Check before you join.)

Building gc_5m alongside the existing mgc_5m is deliberate: it is an INDEPENDENTLY
SOURCED copy of the same market. If a gold result holds on one and not the other, the
result is a data artifact, not an edge. That check is free and worth having.

Sanity: gold/silver intraday returns can explode from roll gaps and bad ticks. A single
bad print fakes a huge PF. Bars implying an absurd 5-min move are dropped and counted.

Run: python3 scripts/build_metals_5m.py
"""
import pandas as pd

SRC = {"si": "data/pkl/si_1m_full.parquet", "gc": "data/pkl/gc_1m_full.parquet"}
MAX_BAR_RET = 0.02          # a >2% move in ONE 5-min bar on metals is a bad tick


def build(name, path):
    df = pd.read_parquet(path)
    df.index = df.index.tz_convert("America/New_York")

    # 5-min bars, right-labelled to the bar's START (o is the first trade in the window)
    b = df.resample("5min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()
    b = b[b["volume"] > 0]

    b["d"] = b.index.strftime("%Y-%m-%d")
    b["m"] = b.index.hour * 60 + b.index.minute
    b = b[(b["m"] >= 570) & (b["m"] <= 955)]          # RTH 09:30-15:55 ET

    b = b.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c"})
    b = b[["d", "m", "o", "h", "l", "c"]].reset_index(drop=True)

    # drop absurd bars (bad ticks / roll gaps) — count them so it's not silent
    rng = (b["h"] - b["l"]) / b["c"]
    bad = rng > MAX_BAR_RET
    if bad.any():
        print(f"  dropped {bad.sum()} bars with >{MAX_BAR_RET:.0%} range (bad ticks/rolls)")
        b = b[~bad].reset_index(drop=True)

    out = f"data/pkl/{name}_5m.pkl"
    b.to_pickle(out)
    bpd = b.groupby("d").size()
    print(f"  {out}: {len(b):,} bars, {b['d'].nunique()} days, "
          f"{b['d'].min()} -> {b['d'].max()}, median {bpd.median():.0f} bars/day")
    return b


if __name__ == "__main__":
    for name, path in SRC.items():
        print(f"=== {name.upper()}")
        build(name, path)
