"""
vol_scan.py — the pre-registered volatility-structure scan on GC / SI / CL.

Executes exactly the search declared in docs/PREREG_VOL_SCAN.md. 104 cells per
instrument x 3 instruments = 312 audits. Do not add cells here; a new idea goes in a
new pre-registration with its own correction.

Everything runs on the 24h session files ({gc,si,cl}_5m_full.pkl), where `m` is minutes
since 18:00 ET and `et` is the wall clock. Family B restricts itself to RTH via `et`.

Usage:
    python3 scripts/vol_scan.py --smoke     # 1 cell per family per instrument, times it
    python3 scripts/vol_scan.py             # the full 312
"""
import sys, argparse, json, time
sys.path.insert(0, "toolkit")

import numpy as np
import pandas as pd
from harness import load_bars, audit, backtest, PF

# ---------------------------------------------------------------- config (frozen)
SCAN_END = {"gc": "2024-12-31", "si": "2024-12-31", "cl": "2024-06-30"}
HOLDOUT_START = {"gc": "2025-01-01", "si": "2025-01-01", "cl": "2024-07-01"}
CATALYST_ET = {"cl": 630, "gc": 510, "si": 510}     # EIA Wed 10:30 / macro 08:30
CATALYST_WED_ONLY = {"cl": True, "gc": False, "si": False}
RTH_LO, RTH_HI = 570, 955
MAX_HOLD = 36
KS = [0.5, 1.0]
KT = [1.0, 2.0]
ATR_N = 14
TRAIL = 60


# ---------------------------------------------------------------- day features
def session_stats(bars):
    """Per-session aggregates, computed from that session only. Used to build
    STRICTLY-PRIOR trailing features below — never read for the current session."""
    rows = []
    for d, g in bars.items():
        et = g["et"].to_numpy()
        rth = (et >= RTH_LO) & (et <= RTH_HI)
        if rth.sum() < 20:
            continue
        gr = g[rth]
        rows.append({
            "d": d,
            "rng": (gr["h"].max() - gr["l"].min()) / gr["c"].iloc[-1],
            "dow": pd.Timestamp(d).dayofweek,
        })
    return pd.DataFrame(rows).sort_values("d").reset_index(drop=True)


def build_atr(bars):
    """ATR(day) = mean session range over the 14 sessions STRICTLY BEFORE `day`.
    shift(1) is the whole ballgame: without it the stop that sizes a session is
    computed from that session's own range."""
    s = session_stats(bars)
    s["atr"] = s["rng"].shift(1).rolling(ATR_N).mean()
    return dict(zip(s["d"], s["atr"]))


def trailing_pct(bars, valuefn, pct_list):
    """day -> {pct: threshold} from the trailing TRAIL sessions strictly before it."""
    vals = []
    for d in sorted(bars):
        vals.append((d, valuefn(bars[d])))
    out, hist = {}, []
    for d, v in vals:
        if len(hist) >= TRAIL:
            w = np.array(hist[-TRAIL:], dtype=float)
            w = w[~np.isnan(w)]
            if len(w) >= 20:
                out[d] = {p: float(np.percentile(w, p)) for p in pct_list}
        if v is not None and not (isinstance(v, float) and np.isnan(v)):
            hist.append(v)
    return out


# ---------------------------------------------------------------- family A
def make_catalyst(inst, prewin, mode, delay):
    T, wed_only = CATALYST_ET[inst], CATALYST_WED_ONLY[inst]

    def signal(day, g):
        if wed_only and pd.Timestamp(day).dayofweek != 2:
            return []
        et = g["et"].to_numpy()
        idx = np.flatnonzero(et == T)
        if len(idx) == 0:
            return []
        t = int(idx[0])
        if t - prewin < 0:
            return []
        i = t + delay
        if i >= len(g):
            return []
        hi = g["h"].to_numpy(); lo = g["l"].to_numpy(); c = g["c"].to_numpy()
        pre_hi = hi[t - prewin:t].max()
        pre_lo = lo[t - prewin:t].min()
        if mode == "breakout":
            if c[i] > pre_hi:
                return [(i, +1)]
            if c[i] < pre_lo:
                return [(i, -1)]
            return []
        else:                                    # fade the first post-event bar
            if t + 1 >= len(g):
                return []
            move = c[t + 1] - c[t]
            if move == 0:
                return []
            return [(i, -1 if move > 0 else +1)]

    return signal


# ---------------------------------------------------------------- family B
def make_compression(inst, L, pctile, thresholds):
    def signal(day, g):
        th = thresholds.get(day)
        if th is None:
            return []
        lim = th[pctile]
        et = g["et"].to_numpy()
        hi = g["h"].to_numpy(); lo = g["l"].to_numpy(); c = g["c"].to_numpy()
        for i in range(1, len(g)):
            if not (RTH_LO <= et[i] <= RTH_HI):
                continue
            j = i - 1                            # window CLOSED before bar i
            if j - L < 0:
                continue
            wh = hi[j - L:j + 1].max()
            wl = lo[j - L:j + 1].min()
            if (wh - wl) / c[j] > lim:           # not compressed
                continue
            if c[i] > wh:
                return [(i, +1)]
            if c[i] < wl:
                return [(i, -1)]
        return []

    return signal


def compression_valuefn(L):
    def f(g):
        et = g["et"].to_numpy()
        hi = g["h"].to_numpy(); lo = g["l"].to_numpy(); c = g["c"].to_numpy()
        vals = []
        for i in range(L, len(g)):
            if RTH_LO <= et[i] <= RTH_HI:
                vals.append((hi[i - L:i + 1].max() - lo[i - L:i + 1].min()) / c[i])
        return float(np.median(vals)) if vals else np.nan
    return f


# ---------------------------------------------------------------- family C
def make_handoff(inst, win, mode, tercile, thresholds):
    m_lo = 0 if win == "overnight" else 540

    def signal(day, g):
        m = g["m"].to_numpy()
        pre = (m >= m_lo) & (m < 930)
        if pre.sum() < 12:
            return []
        idx = np.flatnonzero(m >= 930)
        if len(idx) == 0:
            return []
        i = int(idx[0])                          # first RTH bar
        # NO len(g) guard here. strict=True re-runs this on g.iloc[:i+1], where any
        # length test flips and silently kills the trigger. backtest() already drops
        # triggers with no next bar to fill on.
        gp = g[pre]
        ph, pl = gp["h"].max(), gp["l"].min()
        po, pc = gp["o"].iloc[0], gp["c"].iloc[-1]
        rng = (ph - pl) / pc
        if tercile != "none":
            th = thresholds.get(day)
            if th is None:
                return []
            if tercile == "low" and rng > th[33]:
                return []
            if tercile == "high" and rng < th[67]:
                return []
        if pc == po:
            return []
        up = pc > po
        if mode == "continuation":
            return [(i, +1 if up else -1)]
        return [(i, -1 if up else +1)]

    return signal


def handoff_valuefn(win):
    m_lo = 0 if win == "overnight" else 540

    def f(g):
        m = g["m"].to_numpy()
        pre = (m >= m_lo) & (m < 930)
        if pre.sum() < 12:
            return np.nan
        gp = g[pre]
        return float((gp["h"].max() - gp["l"].min()) / gp["c"].iloc[-1])
    return f


# ---------------------------------------------------------------- cell list
def build_cells(inst, bars):
    cells = []
    comp_th = {L: trailing_pct(bars, compression_valuefn(L), [20, 35]) for L in (12, 24, 48)}
    hand_th = {w: trailing_pct(bars, handoff_valuefn(w), [33, 67]) for w in ("overnight", "london")}

    for prewin in (6, 12):
        for mode in ("breakout", "fade"):
            for delay in (1, 3):
                cells.append(("A", f"cat_pre{prewin}_{mode}_d{delay}",
                              make_catalyst(inst, prewin, mode, delay)))
    for L in (12, 24, 48):
        for p in (20, 35):
            cells.append(("B", f"comp_L{L}_p{p}",
                          make_compression(inst, L, p, comp_th[L])))
    for w in ("overnight", "london"):
        for mode in ("continuation", "fade"):
            for terc in ("low", "high", "none"):
                cells.append(("C", f"hand_{w}_{mode}_{terc}",
                              make_handoff(inst, w, mode, terc, hand_th[w])))
    return cells


# ---------------------------------------------------------------- runner
def run(smoke=False, n_placebo=10):
    results = []
    for inst in ("gc", "si", "cl"):
        allbars = load_bars(f"data/pkl/{inst}_5m_full.pkl", min_bars=100)
        bars = {d: g for d, g in allbars.items() if d <= SCAN_END[inst]}
        atr = build_atr(bars)
        print(f"\n{'='*70}\n{inst.upper()}  {len(bars)} sessions "
              f"(scan window, holdout from {HOLDOUT_START[inst]} withheld)")

        cells = build_cells(inst, bars)
        if smoke:
            seen, keep = set(), []
            for c in cells:
                if c[0] not in seen:
                    seen.add(c[0]); keep.append(c)
            cells = keep

        for fam, name, sig in cells:
            for ks in KS:
                for kt in KT:
                    stop = lambda d, k=ks: (atr.get(d) or 0.0) * k
                    targ = lambda d, k=kt: (atr.get(d) or 0.0) * k
                    t0 = time.time()
                    v = audit(sig, bars, stop=stop, target=targ,
                              max_hold=MAX_HOLD, n_placebo=n_placebo)
                    dt = time.time() - t0
                    row = {
                        "inst": inst, "family": fam, "cell": name,
                        "ks": ks, "kt": kt,
                        "pf": getattr(v, "honest_pf", None),
                        "n": len(getattr(v, "honest_trades", []) or []),
                        "verdict": "PASS" if getattr(v, "passed", False) else "FAIL",
                        "placebos": list(getattr(v, "random_pfs", []) or []),
                        "secs": round(dt, 2),
                    }
                    results.append(row)
                    print(f"  [{fam}] {name:34s} ks{ks} kt{kt}  "
                          f"PF {row['pf'] if row['pf'] is None else round(row['pf'],3)!s:>6} "
                          f"n={row['n']:<5} {row['verdict']}  {dt:.1f}s")
                    if smoke:
                        break
                if smoke:
                    break

    out = "scripts/vol_scan_results.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=1)
    print(f"\nwrote {out}  ({len(results)} cells)")
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--placebo", type=int, default=10)
    a = ap.parse_args()
    run(smoke=a.smoke, n_placebo=a.placebo)
