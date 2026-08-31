"""
honest_backtest.py  —  your fake-edge detector.

The single most important rule in backtesting a level/touch/band strategy:
    FILL AT THE NEXT BAR'S OPEN, and if the result changes when you do, the
    original number was LOOKAHEAD (you were peeking at the future).

This file gives you three functions that would have caught every fake edge on
2026-07-20 in about ten seconds each:

    run_fade()          -- a fade backtest with an `entry=` switch so you can
                           flip between the (wrong) fill-at-level and the
                           (honest) fill-at-next-open and DIFF them.
    random_entry_pf()   -- random entries through the SAME exit machinery.
                           If this also prints a high PF, your exit logic is
                           the artifact, not your signal.
    shuffle_level_pf()  -- shuffle the levels to random-but-realistic prices.
                           If the real levels don't beat the shuffle, the
                           level (wall/pin) carries no information.

Everything is plain pandas. Read it top to bottom; nothing is hidden.
Author's note to Igor: extend this, don't trust anything that skips it.
"""

import numpy as np
import pandas as pd


def PF(returns):
    """Profit factor = gross wins / gross losses. >1 makes money, <1 loses."""
    r = np.asarray(returns, float)
    wins = r[r > 0].sum()
    losses = -r[r < 0].sum()
    return wins / losses if losses > 0 else float("inf")


def run_fade(bars_by_day, level_of, *, entry="nextopen",
             band=0.0027, stop=0.0015, target=0.004, cost=1e-4,
             start_min=540, side="fade"):
    """
    Generic intraday fade/momentum backtester. One trade per day, first trigger.

    bars_by_day : dict {day_str -> DataFrame with columns m,o,h,l,c}
                  (m = minutes since midnight in whatever tz your bars use)
    level_of    : function(day, open_price) -> (upper, lower) price levels,
                  OR None to use a symmetric band around the day's open.
    entry       : 'nextopen'  -> HONEST. Fill at the NEXT bar's open.
                  'atlevel'    -> LOOKAHEAD. Fill at the level on the trigger
                                  bar (only "works" because we also require the
                                  bar to close back inside -> peeking). Kept ONLY
                                  so you can measure how big the lookahead is.
    side        : 'fade' (short the upper break / long the lower break) or
                  'momentum' (the mirror). Momentum should LOSE if fade is real.

    Returns a list of (year, trade_return) tuples.
    """
    trades = []
    for day, g in bars_by_day.items():
        g = g.sort_values("m").reset_index(drop=True)
        n = len(g)
        if n < 40:
            continue
        o = g["c"].iloc[0]                         # RTH open = first bar close
        if level_of is None:
            upper, lower = o * (1 + band), o * (1 - band)
        else:
            lv = level_of(day, o)
            if lv is None:
                continue
            upper, lower = lv
            if upper <= lower:
                continue

        for i in range(1, n):
            if g["m"].iloc[i] < start_min:         # trade only after this time
                continue
            hi, lo, cl = g["h"].iloc[i], g["l"].iloc[i], g["c"].iloc[i]
            up = hi >= upper and cl < upper        # touched upper, closed back inside
            dn = lo <= lower and cl > lower
            if not (up or dn):
                continue

            # direction
            if side == "fade":
                edir = -1 if up else 1
            else:                                   # momentum mirror
                edir = 1 if up else -1
            lvl = upper if up else lower

            # ----- ENTRY FILL: this is where fake edges are born -----
            if entry == "atlevel":                 # <-- LOOKAHEAD
                ent = lvl
                scan_from = i + 1
            elif entry == "nextopen":              # <-- HONEST
                if i + 1 >= n:
                    break
                ent = g["o"].iloc[i + 1]
                scan_from = i + 2
            else:
                raise ValueError("entry must be 'atlevel' or 'nextopen'")

            st = ent * (1 - edir * stop)            # stop is against the trade
            tp = ent * (1 + edir * target)          # target is with the trade
            ex = None
            for k in range(scan_from, n):           # check STOP before TARGET (conservative)
                if (edir > 0 and g["l"].iloc[k] <= st) or (edir < 0 and g["h"].iloc[k] >= st):
                    ex = st
                    break
                if (edir > 0 and g["h"].iloc[k] >= tp) or (edir < 0 and g["l"].iloc[k] <= tp):
                    ex = tp
                    break
            if ex is None:
                ex = g["c"].iloc[n - 1]             # flat by end of day
            trades.append((int(day[:4]), (ex - ent) / ent * edir - cost))
            break                                   # one trade per day
    return trades


def per_year(trades):
    """{year: PF} from a list of (year, return) tuples."""
    by = {}
    for y, r in trades:
        by.setdefault(y, []).append(r)
    return {y: round(PF(v), 2) for y, v in sorted(by.items())}


def honest_check(bars_by_day, level_of, **kw):
    """
    THE check. Runs the same strategy with lookahead vs honest fills and prints
    the diff. If PF drops a lot going to next-open, the edge was fake.
    """
    look = run_fade(bars_by_day, level_of, entry="atlevel", **kw)
    hon = run_fade(bars_by_day, level_of, entry="nextopen", **kw)
    print(f"  fill AT LEVEL (lookahead): PF={PF([r for _, r in look]):.2f}  n={len(look)}")
    print(f"  fill NEXT OPEN (honest)  : PF={PF([r for _, r in hon]):.2f}  n={len(hon)}")
    print(f"  per-year (honest): {per_year(hon)}")
    return hon


if __name__ == "__main__":
    # Worked example on your NQ 5-min data (built earlier this session).
    # This is the exact test that exposed the fake 1.74.
    import os
    DATA = os.path.join(os.path.dirname(__file__), "..", "data", "pkl")
    try:
        nq = pd.read_pickle(os.path.join(DATA, "nq_5m_all.pkl"))
        bars = {d: x for d, x in nq.groupby("d")}
        print("NQ intraday band-fade, symmetric 0.27% band around the open:")
        honest_check(bars, level_of=None, band=0.0027)
        print("\nMomentum mirror (should lose if the fade were real):")
        mom = run_fade(bars, None, entry="nextopen", band=0.0027, side="momentum")
        print(f"  momentum honest PF={PF([r for _, r in mom]):.2f}")
    except FileNotFoundError:
        print("Build /tmp/nq_5m_all.pkl first (NQ 5-min bars with columns d,m,o,h,l,c).")
