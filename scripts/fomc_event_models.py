"""
HarvestPremia Paper 2, Templates 2 (Event Continuation) and 3 (Event Fade), on FOMC.

FOMC is the only Tier 1 event testable on RTH-only NQ bars: the statement is 14:00 ET (m=780
Central), inside the session. NFP and CPI print at 08:30 ET, before the RTH open, and need a
full-session rebuild from the 1-min raw.

Validated before use: NQ 5-min |return| at m=780 is 30.81 bps on these dates vs 7.09 bps
otherwise (4.34x). The dates and the ET->CT conversion are both correct.

ATR(5) = the five 5-min bars ending at 13:55 ET (m 755..775), strictly before the release.

TEMPLATE 2 -- Event Continuation (Table 2)
    Initial move (the 14:00 bar) must exceed 1.0 x ATR(5). Direction = sign of that move.
    Enter on the first CONSOLIDATION bar after it (body < 50% of the prior bar's body).
    TP 1.0 x ATR(5), SL 0.5 x ATR(5)  -> 2:1, min WR 33%. Max hold 20 min (4 bars).

TEMPLATE 3 -- Event Fade (Table 3)
    Initial spike must exceed 2.0 x ATR(5). Enter COUNTER-trend once price has retraced 30%
    of the spike, on a bar CLOSE (the paper's "entry when price retraces 30%" is a resting
    limit at a level -- filling there intrabar is the lookahead this project exists to catch).
    TP 0.5 x ATR(5), SL 1.0 x ATR(5) -> min WR 67%. Max hold 15 min (3 bars).

    AMBIGUITY, stated: Table 3 says the stop is "1.0 x ATR(5) above the spike high", which is
    NOT 1.0 ATR from entry and does not produce the 0.5:1 / 67% WR the same table claims. The
    harness sizes stops from the entry price, so this uses SL = 1.0 x ATR from entry, which is
    the version consistent with the table's own stated RR and win rate.

SAMPLE SIZE WARNING: 88 FOMC sessions in range, fewer after filters. Below the harness's
100-trade gate. A negative here is informative; a positive would not be evidence.
"""
import sys
sys.path.insert(0, "toolkit")
import numpy as np
import pandas as pd
from harness import load_bars, backtest, PF

REL_M = 780          # 14:00 ET statement
ATR_LO, ATR_HI = 755, 775


def atr_at_release(g):
    """ATR(5) from the five bars ending 13:55 ET. Returns (atr, price) or (0,0)."""
    m = g["m"].to_numpy(); hi = g["h"].to_numpy()
    lo = g["l"].to_numpy(); cl = g["c"].to_numpy()
    idx = np.flatnonzero((m >= ATR_LO) & (m <= ATR_HI))
    if len(idx) < 5 or idx[0] == 0:
        return 0.0, 0.0
    tr = [max(hi[k] - lo[k], abs(hi[k] - cl[k-1]), abs(lo[k] - cl[k-1])) for k in idx]
    return float(np.mean(tr)), float(cl[idx[-1]])


def rel_bar(g):
    """Index of the 14:00 bar, or None."""
    idx = np.flatnonzero(g["m"].to_numpy() == REL_M)
    return int(idx[0]) if len(idx) else None


def continuation_signal(fomc, min_move=1.0):
    def sig(day, g):
        if str(day) not in fomc:
            return []
        r = rel_bar(g)
        if r is None:
            return []
        atr, _ = atr_at_release(g)
        if atr <= 0:
            return []
        op = g["o"].to_numpy(); cl = g["c"].to_numpy()
        move = cl[r] - op[r]
        if abs(move) < min_move * atr:          # muted reaction -> stand down
            return []
        edir = 1 if move > 0 else -1
        prev_body = abs(move)
        for i in range(r + 1, len(g)):
            body = abs(cl[i] - op[i])
            if body < 0.5 * prev_body:          # consolidation bar
                return [(i, edir)]
            prev_body = body
            if i > r + 6:                       # event window has passed
                break
        return []
    return sig


def fade_signal(fomc, min_spike=2.0, retrace=0.30):
    def sig(day, g):
        if str(day) not in fomc:
            return []
        r = rel_bar(g)
        if r is None:
            return []
        atr, _ = atr_at_release(g)
        if atr <= 0:
            return []
        op = g["o"].to_numpy(); cl = g["c"].to_numpy()
        hi = g["h"].to_numpy(); lo = g["l"].to_numpy()
        move = cl[r] - op[r]
        if abs(move) < min_spike * atr:
            return []
        up = move > 0
        base = op[r]
        peak = hi[r] if up else lo[r]
        span = abs(peak - base)
        if span <= 0:
            return []
        # fade level = 30% back from the spike extreme toward the pre-event price
        lvl = peak - retrace * span if up else peak + retrace * span
        for i in range(r + 1, min(r + 4, len(g))):     # 5-15 min after release
            if abs(cl[i] - op[i]) >= abs(move):        # "second candle body < first"
                return []
            if (up and cl[i] <= lvl) or (not up and cl[i] >= lvl):
                return [(i, -1 if up else +1, float(lvl))]
        return []
    return sig


def run(name, sigfac, stop_mult, targ_mult, max_hold, bars, fomc, breakeven):
    sd, td = {}, {}
    for d, g in bars.items():
        atr, price = atr_at_release(g)
        if atr > 0 and price > 0:
            sd[d], td[d] = stop_mult * atr / price, targ_mult * atr / price
        else:
            sd[d] = td[d] = 0.0
    kw = dict(stop=lambda d: sd.get(d, 0.0), target=lambda d: td.get(d, 0.0),
              max_hold=max_hold, one_per_day=True)
    s = sigfac(fomc)
    tr = backtest(s, bars, fill="nextopen", **kw)
    if len(tr) < 10:
        print(f"{name}: only {len(tr)} trades -- nothing to say"); return
    pf = PF(tr); wr = np.mean([t.ret > 0 for t in tr])

    def flip(seed):
        def f(day, g):
            t = s(day, g)
            if not t:
                return []
            rng = np.random.default_rng([seed, int(str(day).replace("-", ""))])
            return [(t[0][0], 1 if rng.random() < 0.5 else -1)]
        return f
    nulls = np.array([PF(backtest(flip(x), bars, fill="nextopen", **kw)) for x in range(400)])
    print(f"{name}")
    print(f"    n={len(tr)}  PF={pf:.3f}  WR={wr:.3f} (breakeven {breakeven:.3f})")
    print(f"    direction-flip null: median={np.median(nulls):.3f} "
          f"p90={np.percentile(nulls,90):.3f}  ->  p={(nulls>=pf).mean():.3f}")


def main():
    bars = load_bars("data/pkl/nq_5m_all.pkl", min_bars=40)
    cal = pd.read_pickle("data/pkl/fomc_calendar.pkl")
    fomc = set(cal[cal.scheduled].index)
    n = len([d for d in bars if d in fomc])
    print(f"=== FOMC event models: {n} scheduled FOMC sessions in the NQ sample\n")
    run("TEMPLATE 2 -- Event Continuation (TP 1.0 / SL 0.5 ATR, 20min)",
        continuation_signal, 0.5, 1.0, 4, bars, fomc, 1/3)
    print()
    run("TEMPLATE 3 -- Event Fade (TP 0.5 / SL 1.0 ATR, 15min)",
        fade_signal, 1.0, 0.5, 3, bars, fomc, 2/3)


if __name__ == "__main__":
    main()
