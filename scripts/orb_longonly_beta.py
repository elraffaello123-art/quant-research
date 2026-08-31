"""
Igor's variant: LONG-ONLY NQ, first-30-min opening range, 1:2 risk-reward.

    Range  = 09:30-10:00 ET (bars 0-5). Long on the first 5-min CLOSE above the high.
    Stop   = 1.0 x ATR(5)      Target = 2.0 x ATR(5)      (1:2, breakeven WR 33.3%)
    Exit   = stop / target / the day's close.

WHY THIS NEEDS A DIFFERENT NULL THAN THE TWO-SIDED ORB.
NQ ran ~4,000 -> ~22,000 across this sample. A long-only rule inherits that drift, so
PF > 1 is the DEFAULT, not evidence. "Smart beta" is the honest name for it. The only
question that matters: does the breakout condition beat simply being long?

Three benchmarks, all through the same exit engine:
    1. LONG-ONLY RANDOM  - same days, random entry bar, always long. Isolates the drift.
    2. ALWAYS-LONG 10:00 - buy the 10:00 open every day, no breakout condition at all.
                           If the ORB doesn't beat this, the breakout is decoration.
    3. The real signal.

A 30-min range also fixes the ATR(5) compromise in orb_harvestpremia.py: six bars give
five true ranges, so this is a genuine ATR(5) and still strictly pre-entry.
"""
import sys
sys.path.insert(0, "toolkit")
import numpy as np
from harness import load_bars, backtest, PF

RANGE_M = 540    # 10:00 ET -- opening range is every bar before this


def atr5_tables(bars, stop_mult=1.0, targ_mult=2.0):
    """ATR(5) over the 09:30-10:00 bars, as a fraction of the 10:00 price."""
    stop_d, targ_d = {}, {}
    for d, g in bars.items():
        m  = g["m"].to_numpy(); hi = g["h"].to_numpy()
        lo = g["l"].to_numpy(); cl = g["c"].to_numpy()
        idx = np.flatnonzero(m < RANGE_M)
        if len(idx) < 6:
            stop_d[d] = targ_d[d] = 0.0
            continue
        tr = [max(hi[k] - lo[k], abs(hi[k] - cl[k-1]), abs(lo[k] - cl[k-1]))
              for k in idx[1:]]                      # 5 true ranges = ATR(5)
        atr, price = float(np.mean(tr)), float(cl[idx[-1]])
        if atr <= 0 or price <= 0:
            stop_d[d] = targ_d[d] = 0.0
            continue
        stop_d[d] = stop_mult * atr / price
        targ_d[d] = targ_mult * atr / price
    return stop_d, targ_d


def long_orb(day, g):
    """First close above the 09:30-10:00 high. Long only."""
    m = g["m"].to_numpy(); hi = g["h"].to_numpy(); cl = g["c"].to_numpy()
    inr = m < RANGE_M
    if inr.sum() < 6:
        return []
    orh = hi[inr].max()
    for i in np.flatnonzero(m >= RANGE_M):
        if cl[i] > orh:
            return [(int(i), +1)]
    return []


def always_long(day, g):
    """Benchmark 2: buy the 10:00 bar every session, no condition. Pure beta."""
    m = g["m"].to_numpy()
    idx = np.flatnonzero(m >= RANGE_M)
    return [(int(idx[0]), +1)] if len(idx) else []


def long_random(seed, fired):
    """Benchmark 1: same days, random bar at/after 10:00, always long."""
    def sig(day, g):
        if str(day) not in fired:
            return []
        m = g["m"].to_numpy()
        cand = np.flatnonzero(m >= RANGE_M)
        if len(cand) < 2:
            return []
        rng = np.random.default_rng([seed, int(str(day).replace("-", ""))])
        return [(int(rng.choice(cand[:-1])), +1)]
    return sig


def main():
    bars = load_bars("data/pkl/nq_5m_all.pkl", min_bars=40)
    sd, td = atr5_tables(bars)
    kw = dict(stop=lambda d: sd.get(d, 0.0), target=lambda d: td.get(d, 0.0),
              one_per_day=True)

    real = backtest(long_orb, bars, fill="nextopen", **kw)
    fired = {t.day for t in real}
    alw = backtest(always_long, bars, fill="nextopen", **kw)

    def line(nm, tr):
        print(f"{nm:26s} n={len(tr):5d}  PF={PF(tr):6.3f}  "
              f"WR={np.mean([t.ret>0 for t in tr]):.3f}  (breakeven 0.333)")

    print(f"=== NQ long-only, 30-min range, 1:2 RR   {min(bars)} -> {max(bars)}")
    line("REAL long ORB", real)
    line("BENCH always-long 10:00", alw)

    nulls = np.array([PF(backtest(long_random(s, fired), bars, fill="nextopen", **kw))
                      for s in range(200)])
    pf = PF(real)
    print(f"\nBENCH long-only RANDOM entry (200 seeds, same days):")
    print(f"   median={np.median(nulls):.3f}  p75={np.percentile(nulls,75):.3f}  "
          f"p95={np.percentile(nulls,95):.3f}")
    print(f"   REAL {pf:.3f} -> p = {(nulls>=pf).mean():.3f}")
    return real, alw, nulls


if __name__ == "__main__":
    main()
