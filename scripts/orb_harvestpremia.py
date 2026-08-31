"""
HarvestPremia Paper 2, Template 1 — Open Range Breakout. Naked version (no regime filters).

THE CLAIM (Paper 2, Table 1), in plain English:
    Take the high and low of the first 15 minutes after the cash open (09:30-09:45 ET).
    The first 5-min bar that CLOSES above that high is a long; below that low, a short.
    Target 1.5 x ATR(5). Stop 0.5 x ATR(5). Flat at 10:30 ET regardless.

    Mechanism claimed: overnight information reprices at the open, the first 15 minutes
    bound that repricing, and a break means the repricing is INCOMPLETE and continues.

    3:1 reward:risk => breakeven win rate 25%.

FREE PARAMETERS: zero. Every number above is fixed by the paper.

NQ 5-min bar clock (verified): m = minutes since midnight CENTRAL.
    m=510 -> 09:30 ET (cash open, bar index 0)
    m=525 -> 09:45 ET (bar index 3, first decision bar)
    m=570 -> 10:30 ET (bar index 12, the flat-by wall)
"""
import sys
sys.path.insert(0, "toolkit")
import numpy as np
from harness import load_bars, audit, backtest, PF

OPEN_M   = 510   # 09:30 ET  session open
RANGE_M  = 525   # 09:45 ET  opening range ends / first decision bar
LAST_M   = 565   # 10:25 ET  last bar we may trigger on (entry fills at 10:30 open)
EXIT_IDX = 12    # 10:30 ET  absolute flat-by bar


# ---------------------------------------------------------------------------
# The signal
# ---------------------------------------------------------------------------
def orb_signal(day, g):
    """First 5-min CLOSE outside the 09:30-09:45 range. Returns (i, dir, level)."""
    m  = g["m"].to_numpy()
    hi = g["h"].to_numpy()
    lo = g["l"].to_numpy()
    cl = g["c"].to_numpy()

    inrange = m < RANGE_M                     # the 09:30-09:45 opening range bars
    if inrange.sum() < 3:                     # need the full 15 minutes
        return []
    orh = hi[inrange].max()
    orl = lo[inrange].min()

    for i in np.flatnonzero((m >= RANGE_M) & (m <= LAST_M)):
        if cl[i] > orh:
            return [(int(i), +1, float(orh))]  # first break wins, long
        if cl[i] < orl:
            return [(int(i), -1, float(orl))]  # first break wins, short
    return []


# ---------------------------------------------------------------------------
# ATR-anchored exits, sized once per day from data strictly before 09:45
# ---------------------------------------------------------------------------
def atr_tables(bars):
    """
    ATR over the opening-range bars (09:30-09:45), as a FRACTION of the 09:45 price.

    DEVIATION FROM THE PAPER, stated out loud: the paper says ATR(5) on the entry
    timeframe. At 09:45 only three 5-min RTH bars exist, so this is a 3-bar ATR.
    It is the same quantity in spirit -- immediate volatility at entry -- and it is
    strictly causal: every input closes before any entry can fill.
    """
    stop_by_day, targ_by_day = {}, {}
    for d, g in bars.items():
        m  = g["m"].to_numpy()
        hi = g["h"].to_numpy()
        lo = g["l"].to_numpy()
        cl = g["c"].to_numpy()

        idx = np.flatnonzero(m < RANGE_M)
        if len(idx) < 3:
            stop_by_day[d] = targ_by_day[d] = 0.0     # backtest skips a 0 stop
            continue

        tr = []
        for k in idx:
            if k == 0:
                tr.append(hi[k] - lo[k])              # no prior close on bar 0
            else:
                pc = cl[k - 1]
                tr.append(max(hi[k] - lo[k], abs(hi[k] - pc), abs(lo[k] - pc)))
        atr   = float(np.mean(tr))
        price = float(cl[idx[-1]])                    # the 09:45 close
        if atr <= 0 or price <= 0:
            stop_by_day[d] = targ_by_day[d] = 0.0
            continue

        stop_by_day[d] = 0.5 * atr / price            # Table 1: SL 0.5 x ATR
        targ_by_day[d] = 1.5 * atr / price            # Table 1: TP 1.5 x ATR
    return stop_by_day, targ_by_day


def main(path="data/pkl/nq_5m_all.pkl", label="NQ"):
    bars = load_bars(path, min_bars=40)
    stop_d, targ_d = atr_tables(bars)

    print(f"=== {label}: {len(bars)} sessions, {min(bars)} -> {max(bars)}")
    nz = [v for v in stop_d.values() if v > 0]
    print(f"    median stop {np.median(nz)*1e4:.1f} bps, "
          f"target {np.median(nz)*3*1e4:.1f} bps  (3:1, breakeven WR 25%)")

    v = audit(
        orb_signal, bars,
        stop=lambda d: stop_d.get(d, 0.0),
        target=lambda d: targ_d.get(d, 0.0),
        exit_by=EXIT_IDX,
        one_per_day=True,
    )
    v.report()
    return v, bars, stop_d, targ_d


if __name__ == "__main__":
    main()
